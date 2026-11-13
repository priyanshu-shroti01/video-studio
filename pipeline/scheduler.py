"""Cross-process scheduler for memory-heavy work on a 16 GB machine.

Only ONE heavy workload runs at a time (rendering, local TTS, LLM inference, OCR...). Waiters are
served by priority, then FIFO. A grant also waits for enough reclaimable memory. Default priorities
(lower = first): render 1, tts 2, llm 3, background 4. Override in .pipeline/scheduler.json, e.g.
{"priorities": {"llm": 1, "render": 2}, "min_available_mb": {"llm": 2500, "render": 2900}}.

State lives in the registry (table sched_queue), so the CLI, the Studio server and tests all see the
same queue. Dead holders (pid gone) are reclaimed automatically."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass

from .errors import Cancelled, ResourceError
from .paths import STATE_DIR
from .system import mem_snapshot

CONFIG = STATE_DIR / "scheduler.json"
DEFAULT_PRIORITY = {"render": 1, "tts": 2, "alignment": 2, "llm": 3, "ocr": 4, "background": 4}
DEFAULT_MEM_MB = {"render": 1500, "tts": 900, "alignment": 700, "llm": 2600, "ocr": 400, "background": 300}


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        cfg = {}
    return {"priorities": {**DEFAULT_PRIORITY, **cfg.get("priorities", {})},
            "min_available_mb": {**DEFAULT_MEM_MB, **cfg.get("min_available_mb", {})},
            "max_mem_wait_s": cfg.get("max_mem_wait_s", 300)}


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


@dataclass
class Grant:
    id: int
    kind: str
    waited_s: float
    available_mb: float


class HeavyWork:
    """with HeavyWork(reg, "llm", ref="P123"): ...   — blocks until it is this workload's turn."""

    def __init__(self, reg, kind: str, ref: str = "", *, poll: float = 0.5, timeout: float = 3600,
                 should_cancel=None, log=None, mem=mem_snapshot):
        cfg = load_config()
        if kind not in cfg["priorities"]:
            raise ValueError(f"unknown workload kind {kind!r}")
        self.reg, self.kind, self.ref = reg, kind, ref
        self.priority = int(cfg["priorities"][kind])
        self.need_mb = float(cfg["min_available_mb"][kind])
        self.max_mem_wait = float(cfg["max_mem_wait_s"])
        self.poll, self.timeout = poll, timeout
        self.should_cancel = should_cancel or (lambda: False)
        self.log = log or (lambda m: None)
        self.mem = mem
        self.id: int | None = None
        self._stop = threading.Event()
        self.grant: Grant | None = None

    def _reap(self, c) -> None:
        for r in c.execute("SELECT id, pid FROM sched_queue").fetchall():
            if not _alive(r["pid"]):
                c.execute("DELETE FROM sched_queue WHERE id=?", (r["id"],))

    def __enter__(self) -> Grant:
        t0 = time.time()
        with self.reg.conn() as c:
            self.id = c.execute("INSERT INTO sched_queue (kind,priority,pid,job_ref,state,enqueued_at,heartbeat) "
                                "VALUES (?,?,?,?,?,?,?)", (self.kind, self.priority, os.getpid(), self.ref, "waiting",
                                                           t0, t0)).lastrowid
        announced = mem_wait_start = None
        try:
            while True:
                if self.should_cancel():
                    raise Cancelled(f"cancelled while waiting to run {self.kind}")
                if time.time() - t0 > self.timeout:
                    raise ResourceError(f"{self.kind} waited {self.timeout:.0f}s for its turn")
                with self.reg.conn() as c:
                    c.execute("BEGIN IMMEDIATE")
                    self._reap(c)
                    busy = c.execute("SELECT kind, job_ref FROM sched_queue WHERE state='granted'").fetchone()
                    head = c.execute("SELECT id FROM sched_queue WHERE state='waiting' "
                                     "ORDER BY priority, enqueued_at, id LIMIT 1").fetchone()
                    mine = (not busy) and head and head["id"] == self.id
                    snap = self.mem() if mine else None
                    enough = snap is not None and (snap.available_mb >= self.need_mb or
                                                   (mem_wait_start and time.time() - mem_wait_start > self.max_mem_wait))
                    if mine and enough:
                        c.execute("UPDATE sched_queue SET state='granted', granted_at=?, heartbeat=? WHERE id=?",
                                  (time.time(), time.time(), self.id))
                        c.execute("COMMIT")
                        self.grant = Grant(self.id, self.kind, round(time.time() - t0, 2), round(snap.available_mb))
                        threading.Thread(target=self._beat, daemon=True).start()
                        return self.grant
                    c.execute("COMMIT")
                if mine and not enough:
                    if mem_wait_start is None:
                        mem_wait_start = time.time()
                        self.log(f"{self.kind}: waiting for memory ({snap.available_mb:.0f} MB available, "
                                 f"want {self.need_mb:.0f} MB)")
                elif busy and announced != busy["kind"]:
                    announced = busy["kind"]
                    self.log(f"{self.kind}: waiting for running {busy['kind']} ({busy['job_ref']})")
                time.sleep(self.poll)
        except BaseException:
            self._release()
            raise

    def _beat(self):
        while not self._stop.wait(5):
            try:
                with self.reg.conn() as c:
                    c.execute("UPDATE sched_queue SET heartbeat=? WHERE id=?", (time.time(), self.id))
            except Exception:  # noqa: BLE001 - heartbeat must not crash the workload
                pass

    def _release(self):
        self._stop.set()
        if self.id is not None:
            with self.reg.conn() as c:
                c.execute("DELETE FROM sched_queue WHERE id=?", (self.id,))
            self.id = None

    def __exit__(self, *exc):
        self._release()
        return False


def queue(reg) -> list[dict]:
    with reg.conn() as c:
        return [dict(r) for r in c.execute("SELECT id,kind,priority,pid,job_ref,state,enqueued_at,granted_at "
                                           "FROM sched_queue ORDER BY state DESC, priority, enqueued_at").fetchall()]
