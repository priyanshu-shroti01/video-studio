"""Subprocess execution: argument arrays only (never a shell), own process group per child,
hard timeout, stall detection on output, cancellation, and peak-RSS sampling of the whole tree.

Killing the process *group* matters for Remotion: `npx remotion render` spawns node + several
Chromium processes; killing only the parent leaves orphaned Chromium workers eating RAM."""
from __future__ import annotations

import os
import random
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .errors import Cancelled, PipelineError, ProcessStalled, ProcessTimeout


@dataclass
class ProcResult:
    args: list[str]
    returncode: int
    output: str
    seconds: float
    peak_rss_mb: float = 0.0
    tail: list[str] = field(default_factory=list)


def _ps() -> list[tuple[int, int, int, int, str]]:
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pgid=,rss=,comm="], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), parts[4]))
    return rows


def _tree(root: int, known: dict[int, tuple[int, str]]) -> float:
    """Walk the ppid tree from `root`, remember every descendant (pid -> (pgid, comm)) and return the
    tree's total RSS in MB. Needed because Remotion launches Chromium *detached* (its own process
    group): a process-group kill or RSS sum on our group alone misses ~1 GB of Chromium."""
    rows = _ps()
    kids: dict[int, list] = {}
    for r in rows:
        kids.setdefault(r[1], []).append(r)
    total, stack = 0, [root]
    by_pid = {r[0]: r for r in rows}
    if root in by_pid:
        total += by_pid[root][3]
    while stack:
        for r in kids.get(stack.pop(), []):
            known[r[0]] = (r[2], r[4])
            total += r[3]
            stack.append(r[0])
    for pid, (pgid, comm) in list(known.items()):  # re-parented orphans still count while alive
        if pid in by_pid and by_pid[pid][4] == comm and not _is_desc(pid, root, by_pid):
            total += by_pid[pid][3]
    return total / 1024.0


def _is_desc(pid: int, root: int, by_pid: dict) -> bool:
    seen = 0
    while pid in by_pid and seen < 64:
        pid = by_pid[pid][1]
        if pid == root:
            return True
        seen += 1
    return False


def kill_tree(root_pgid: int, known: dict[int, tuple[int, str]], grace: float = 3.0) -> None:
    """Kill our process group and every process group a remembered descendant lives in (only if that pid
    still runs the same executable, so a recycled pid is never touched)."""
    alive = {r[0]: r for r in _ps()}
    groups = {root_pgid}
    for pid, (pgid, comm) in known.items():
        if pid in alive and alive[pid][4] == comm and pgid > 1:
            groups.add(pgid)
    for g in groups:
        kill_group(g, grace)


def kill_group(pgid: int, grace: float = 3.0) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, PermissionError):  # macOS: EPERM once only zombies remain
                return
            time.sleep(0.1)


def run(
    args: list[str],
    *,
    timeout: float = 600,
    stall_timeout: float | None = None,
    cwd: str | os.PathLike | None = None,
    env: dict | None = None,
    on_line: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    sample_rss: bool = False,
    check: bool = True,
) -> ProcResult:
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise TypeError("args must be a list of str (no shell strings)")
    start = time.time()
    proc = subprocess.Popen(
        args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, errors="replace", start_new_session=True, bufsize=1,
    )
    pgid = proc.pid
    known: dict[int, tuple[int, str]] = {}
    lines: list[str] = []
    last_output = [time.time()]
    peak = [0.0]

    def reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            last_output[0] = time.time()
            if on_line:
                try:
                    on_line(line)
                except Exception:  # a progress callback must never kill the job
                    pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    reason: PipelineError | None = None
    next_sample = 0.0
    try:
        while proc.poll() is None:
            now = time.time()
            if now >= next_sample:  # always track descendants (for kill), RSS as a by-product
                rss = _tree(proc.pid, known)
                if sample_rss:
                    peak[0] = max(peak[0], rss)
                next_sample = now + 1.0
            if now - start > timeout:
                reason = ProcessTimeout(f"{os.path.basename(args[0])} exceeded {timeout:.0f}s timeout")
            elif stall_timeout and now - last_output[0] > stall_timeout:
                reason = ProcessStalled(f"{os.path.basename(args[0])} produced no output for {stall_timeout:.0f}s")
            elif should_cancel and should_cancel():
                reason = Cancelled("cancelled by user")
            if reason:
                kill_tree(pgid, known)
                break
            time.sleep(0.2)
    finally:
        if proc.poll() is None:
            kill_tree(pgid, known)
        proc.wait(timeout=10)
        t.join(timeout=5)
        # reap stragglers (our group + detached descendants) even after a clean exit
        kill_tree(pgid, known, grace=1.0)
    res = ProcResult(args, proc.returncode, "\n".join(lines), time.time() - start, peak[0], lines[-25:])
    if reason:
        reason.detail = "\n".join(res.tail)
        raise reason
    if check and proc.returncode != 0:
        raise PipelineError(f"{os.path.basename(args[0])} exited with {proc.returncode}", detail="\n".join(res.tail))
    return res


def _backoff_sleep(seconds: float) -> None:  # separate seam so tests can skip backoff waits
    time.sleep(seconds)


def retry(fn: Callable[[], object], *, attempts: int = 3, base: float = 1.0, cap: float = 30.0,
          is_transient: Callable[[BaseException], bool] | None = None,
          on_retry: Callable[[int, BaseException, float], None] | None = None, sleep=None):
    """Exponential backoff with full jitter; only retries errors classified as transient."""
    is_transient = is_transient or (lambda e: isinstance(e, PipelineError) and e.transient)
    for n in range(1, attempts + 1):
        try:
            return fn()
        except Cancelled:
            raise
        except BaseException as e:  # noqa: BLE001 - re-raised below unless transient
            if n == attempts or not is_transient(e):
                raise
            delay = random.uniform(0, min(cap, base * 2 ** (n - 1)))
            if on_retry:
                on_retry(n, e, delay)
            (sleep or _backoff_sleep)(delay)
    raise AssertionError("unreachable")
