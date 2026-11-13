import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pipeline import paths, procs
from pipeline.assets import check_svg
from pipeline.errors import (AssetError, Cancelled, DuplicateJob, PathError, PipelineError, ProcessStalled,
                             ProcessTimeout, ResourceError, StateError, TTSError)


# ---- state machine / registry -------------------------------------------------------------------
def test_legal_and_illegal_transitions(registry, tmp_path):
    j = registry.create("x", "h1", {}, None, tmp_path)
    with pytest.raises(StateError):
        registry.transition(j["id"], "RENDERING")          # can't skip stages
    for s in ["PREPARING", "GENERATING_AUDIO", "BUILDING_TIMELINE", "RENDERING", "POST_PROCESSING", "QA", "COMPLETED"]:
        registry.transition(j["id"], s)
    with pytest.raises(StateError):
        registry.transition(j["id"], "RETRYING")           # completed jobs are final


def test_failed_job_can_be_retried(registry, tmp_path):
    j = registry.create("x", "h1", {}, None, tmp_path)
    registry.transition(j["id"], "PREPARING")
    registry.transition(j["id"], "FAILED", error={"code": "X"})
    registry.transition(j["id"], "RETRYING")
    registry.transition(j["id"], "PREPARING")
    assert registry.get(j["id"])["attempts"] == 1


def test_duplicate_job_prevention(registry, tmp_path):
    registry.create("x", "same", {}, None, tmp_path)
    with pytest.raises(DuplicateJob):
        registry.create("x", "same", {}, None, tmp_path)
    assert registry.create("x", "same", {}, None, tmp_path, force=True)["id"]


def test_failed_duplicates_do_not_block_new_jobs(registry, tmp_path):
    j = registry.create("x", "k", {}, None, tmp_path)
    registry.transition(j["id"], "CANCELLED")
    assert registry.create("x", "k", {}, None, tmp_path)["state"] == "QUEUED"


def test_cancellation(registry, tmp_path):
    q = registry.create("q", "a", {}, None, tmp_path)
    assert registry.request_cancel(q["id"]) == "CANCELLED"
    r = registry.create("r", "b", {}, None, tmp_path)
    registry.transition(r["id"], "PREPARING")
    assert registry.request_cancel(r["id"]) == "CANCEL_REQUESTED" and registry.cancel_requested(r["id"])


def test_stale_job_recovery(registry, tmp_path):
    j = registry.create("x", "h", {}, None, tmp_path)
    registry.transition(j["id"], "PREPARING")
    dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
    with registry.conn() as c:
        c.execute("UPDATE jobs SET pid=?, heartbeat=? WHERE id=?", (dead.pid, time.time() - 999, j["id"]))
    assert registry.recover_stale() == [j["id"]]
    assert registry.get(j["id"])["state"] == "FAILED" and registry.get(j["id"])["error"]["code"] == "STALE_JOB"


def test_render_slots_limit_and_reclaim(registry):
    assert registry.acquire_slot("a", 1) == 0
    assert registry.acquire_slot("b", 1) is None
    with registry.conn() as c:  # holder died
        c.execute("UPDATE render_slots SET pid=999999, heartbeat=0")
    assert registry.acquire_slot("b", 1) == 0


# ---- subprocess hardening -----------------------------------------------------------------------
def _alive(pid):
    try:
        os.kill(pid, 0); return True
    except ProcessLookupError:
        return False


def test_timeout_kills_whole_process_group(tmp_path):
    marker = tmp_path / "child.pid"
    script = f"sleep 30 & echo $! > {marker}; wait"
    with pytest.raises(ProcessTimeout):
        procs.run(["sh", "-c", script], timeout=1.0)
    child = int(marker.read_text())
    time.sleep(0.3)
    assert not _alive(child), "orphaned child survived the timeout"


def test_stall_detection():
    with pytest.raises(ProcessStalled):
        procs.run([sys.executable, "-c", "print('start', flush=True); import time; time.sleep(30)"], timeout=60,
                  stall_timeout=1.0)


def test_cancel_kills_process():
    flag = {"n": 0}

    def cancel():
        flag["n"] += 1
        return flag["n"] > 3
    with pytest.raises(Cancelled):
        procs.run(["sleep", "30"], timeout=60, should_cancel=cancel)


def test_shell_strings_rejected():
    with pytest.raises(TypeError):
        procs.run("ls -la", timeout=5)  # type: ignore[arg-type]


def test_nonzero_exit_has_tail_detail():
    with pytest.raises(PipelineError) as e:
        procs.run([sys.executable, "-c", "print('boom'); raise SystemExit(3)"], timeout=10)
    assert "boom" in e.value.detail


def test_retry_only_transient(no_sleep):
    n = {"c": 0}

    def flaky():
        n["c"] += 1
        if n["c"] < 3:
            raise TTSError("blip", transient=True)
        return "ok"
    assert procs.retry(flaky, attempts=4) == "ok" and n["c"] == 3 and len(no_sleep) == 2
    m = {"c": 0}

    def permanent():
        m["c"] += 1
        raise TTSError("bad voice")
    with pytest.raises(TTSError):
        procs.retry(permanent, attempts=4)
    assert m["c"] == 1


def test_backoff_grows_exponentially(no_sleep, monkeypatch):
    monkeypatch.setattr(procs.random, "uniform", lambda a, b: b)
    with pytest.raises(TTSError):
        procs.retry(lambda: (_ for _ in ()).throw(TTSError("x", transient=True)), attempts=4, base=1, cap=30)
    assert no_sleep == [1, 2, 4]


# ---- paths / security ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "public/../../x", "a\x00b", ""])
def test_path_traversal_rejected(bad):
    with pytest.raises(PathError):
        paths.safe_path(bad)


def test_symlink_escape_rejected(tmp_path):
    link = paths.ROOT / ".pipeline" / "tmp" / "escape-link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.unlink(missing_ok=True)
    link.symlink_to("/etc")
    try:
        with pytest.raises(PathError):
            paths.safe_path(link / "hosts")
    finally:
        link.unlink()


@pytest.mark.parametrize("name,ok", [("shrotihost-short", True), ("a/b", False), ("..", False), ("x;rm -rf", False)])
def test_safe_names(name, ok):
    if ok:
        assert paths.safe_name(name) == name
    else:
        with pytest.raises(PathError):
            paths.safe_name(name)


def test_publish_refuses_overwrite(tmp_path):
    dst = tmp_path / "final.mp4"; dst.write_text("old")
    src = tmp_path / "new.mp4"; src.write_text("new")
    with pytest.raises(PathError):
        paths.publish_file(src, dst)
    assert dst.read_text() == "old"


def test_atomic_write_leaves_no_partial_file(tmp_path, monkeypatch):
    dst = tmp_path / "out.json"
    dst.write_text("previous")
    monkeypatch.setattr(paths.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        paths.atomic_write_text(dst, "new")
    assert dst.read_text() == "previous" and not [p for p in tmp_path.iterdir() if p.name.startswith(".out.json")]


def test_disk_exhaustion_preflight(monkeypatch):
    class U: free = 1_000_000_000
    monkeypatch.setattr(paths.shutil, "disk_usage", lambda p: U)
    with pytest.raises(ResourceError):
        paths.require_free_space(5)


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil/x.png"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>'])
def test_unsafe_svg_rejected(tmp_path, svg):
    p = tmp_path / "x.svg"; p.write_text(svg)
    with pytest.raises(AssetError):
        check_svg(p)


def test_brand_svgs_are_safe():
    for f in ("logo-on-dark.svg", "logo-on-light.svg", "icon.svg"):
        check_svg(paths.ROOT / "public/brand" / f)


def test_timeout_kills_detached_grandchildren(tmp_path):
    """Remotion launches Chromium detached (own process group); a timeout must still kill it."""
    marker = tmp_path / "gc.pid"
    code = ("import subprocess,sys,time;"
            "p=subprocess.Popen(['sleep','60'],start_new_session=True);"
            f"open({str(marker)!r},'w').write(str(p.pid));print('started',flush=True);time.sleep(60)")
    with pytest.raises(ProcessTimeout):
        procs.run([sys.executable, "-c", code], timeout=2.5)
    gc = int(marker.read_text())
    time.sleep(0.3)
    assert not _alive(gc), "detached grandchild survived"


def test_rss_includes_detached_descendants():
    code = ("import subprocess,time;"
            "subprocess.Popen(['python3','-c','x=bytearray(150_000_000);import time;time.sleep(4)'],start_new_session=True);"
            "print('ok',flush=True);time.sleep(3)")
    r = procs.run([sys.executable, "-c", code], timeout=20, sample_rss=True)
    assert r.peak_rss_mb > 140, r.peak_rss_mb
