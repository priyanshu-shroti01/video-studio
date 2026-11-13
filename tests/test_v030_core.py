"""v0.3.0 core: migrations, production lifecycle, approval gate, publishing safety, scheduler."""
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pipeline import migrations, publishing, scheduler
from pipeline.errors import StateError
from pipeline.productions import BLOCKING, ApprovalError, Productions, flags_from_job


# ---- migrations ---------------------------------------------------------------------------------
def test_v020_database_migrates_without_losing_jobs(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    from pipeline.jobs import SCHEMA
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO jobs (id,name,key_hash,state,config_json,output_dir,created_at,updated_at) "
              "VALUES ('J1','old','k','COMPLETED','{}','output/J1',1,1)")
    c.commit(); c.close()
    monkeypatch.setattr(migrations, "BACKUP_DIR", tmp_path / "bk")
    res = migrations.migrate(db)
    assert res["from"] == 1 and res["to"] == migrations.LATEST and Path(res["backup"]).exists()
    c = sqlite3.connect(db)
    assert c.execute("SELECT state FROM jobs WHERE id='J1'").fetchone()[0] == "COMPLETED"
    assert c.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST
    assert c.execute("SELECT count(*) FROM sqlite_master WHERE name='productions'").fetchone()[0] == 1
    assert migrations.migrate(db)["from"] == migrations.LATEST      # idempotent


# ---- fixtures: a completed render job with real files -------------------------------------------
@pytest.fixture
def prod(registry, tmp_path, monkeypatch):
    import pipeline.productions as P
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", tmp_path / "productions")
    return Productions(registry)


def _completed_job(reg, tmp_path, qa="PASS", music_license="CC0"):
    job = reg.create("demo", f"k{time.time()}", {}, None, tmp_path / "out")
    out = Path(job["output_dir"])
    for d in ("video", "publishing", "captions", "reports", "assets"):
        (out / d).mkdir(parents=True, exist_ok=True)
    (out / "video/final-short.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + os.urandom(2048))
    (out / "publishing/thumbnail.png").write_bytes(b"\x89PNG" + os.urandom(64))
    (out / "publishing/title.txt").write_text("Title\n")
    (out / "publishing/description.md").write_text("Desc\n")
    (out / "publishing/hashtags.txt").write_text("#a #b\n")
    (out / "captions/captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    (out / "reports/qa-report.json").write_text(json.dumps({"status": qa, "formats": [
        {"format": "short", "counts": {"PASS": 1, "WARN": 1, "FAIL": 0},
         "checks": [{"id": "audio.loudness", "status": "WARN", "detail": "-15.2 LUFS"}]}]}))
    (out / "reports/QA_REPORT.md").write_text("ok")
    (out / "reports/audio-report.json").write_text("{}")
    (out / "assets/manifest.json").write_text(json.dumps({"assets": [
        {"path": "audio/music/x.mp3", "license": music_license}]}))
    for s in ["PREPARING", "GENERATING_AUDIO", "BUILDING_TIMELINE", "RENDERING", "POST_PROCESSING", "QA", "COMPLETED"]:
        reg.transition(job["id"], s)
    reg.update(job["id"], qa_status=qa)
    return job, out


def _ready(prod, registry, tmp_path, **kw):
    job, out = _completed_job(registry, tmp_path, **kw)
    p = prod.create("shrotihost", "demo", {"product": "x"})
    for s in ("STORYBOARD_READY", "RENDERING"):
        prod.transition(p["id"], s)
    prod.update(p["id"], job_id=job["id"])
    prod.transition(p["id"], "QA_COMPLETE")
    flags_from_job(prod, p["id"], out)
    prod.build_package(p["id"])
    return p["id"], out


def _resolve_all(prod, pid):
    for f in prod.flags(pid, "open"):
        if f["severity"] == BLOCKING:
            prod.resolve_flag(pid, f["id"], "Priyanshu", "checked")


# ---- lifecycle / approval -----------------------------------------------------------------------
def test_qa_success_stops_at_awaiting_approval(prod, registry, tmp_path):
    pid, _ = _ready(prod, registry, tmp_path)
    assert prod.get(pid)["state"] == "AWAITING_APPROVAL"
    with pytest.raises(StateError):
        prod.transition(pid, "PUBLISHED")


def test_mandatory_human_flags_block_approval(prod, registry, tmp_path):
    pid, _ = _ready(prod, registry, tmp_path)
    kinds = {f["kind"] for f in prod.flags(pid, "open")}
    assert {"human:pronunciation", "human:final-watch", "qa:audio.loudness"} <= kinds
    with pytest.raises(ApprovalError):
        prod.approve(pid, "Priyanshu")
    _resolve_all(prod, pid)
    a = prod.approve(pid, "Priyanshu", "looks good")
    assert prod.get(pid)["state"] == "APPROVED" and len(a["package_hash"]) == 64


def test_test_tone_music_is_blocking(prod, registry, tmp_path):
    pid, _ = _ready(prod, registry, tmp_path, music_license="PUBLIC-DOMAIN (self-generated test tone)")
    assert any(f["kind"] == "music:test-tone" and f["severity"] == BLOCKING for f in prod.flags(pid))


def test_resolving_a_flag_needs_reviewer_and_note(prod, registry, tmp_path):
    pid, _ = _ready(prod, registry, tmp_path)
    f = prod.flags(pid, "open")[0]
    with pytest.raises(ApprovalError):
        prod.resolve_flag(pid, f["id"], "", "")


def test_any_change_after_approval_invalidates_it(prod, registry, tmp_path):
    pid, out = _ready(prod, registry, tmp_path)
    _resolve_all(prod, pid)
    prod.approve(pid, "Priyanshu")
    (out / "publishing/title.txt").write_text("Edited title\n")        # metadata change
    assert prod.check_approval(pid) is None
    assert prod.get(pid)["state"] == "AWAITING_APPROVAL"
    with pytest.raises(ApprovalError):
        publishing.export(prod, pid)


def test_approval_against_stale_package_rejected(prod, registry, tmp_path):
    pid, out = _ready(prod, registry, tmp_path)
    _resolve_all(prod, pid)
    (out / "video/final-short.mp4").write_bytes(b"different")         # changed after the package was built
    with pytest.raises(ApprovalError):
        prod.approve(pid, "Priyanshu")


def test_failed_qa_cannot_be_approved(prod, registry, tmp_path):
    pid, _ = _ready(prod, registry, tmp_path, qa="FAIL")
    _resolve_all(prod, pid)
    with pytest.raises(ApprovalError):
        prod.approve(pid, "Priyanshu")


# ---- publishing gate ----------------------------------------------------------------------------
def test_publish_requires_confirmation_and_approval(prod, registry, tmp_path):
    pid, _ = _ready(prod, registry, tmp_path)
    with pytest.raises(ApprovalError):
        publishing.publish(prod, pid, "youtube", "short", confirm=False, actor="me")
    with pytest.raises(ApprovalError):                                 # not approved yet
        publishing.publish(prod, pid, "export", "short", confirm=True, actor="me")


def test_export_package_has_checksums_and_does_not_publish(prod, registry, tmp_path):
    pid, _ = _ready(prod, registry, tmp_path)
    _resolve_all(prod, pid)
    prod.approve(pid, "Priyanshu")
    res = publishing.export(prod, pid)
    d = Path(prod.get(pid)["dir"]) / "export"
    pkg = next(p for p in d.glob("short-*") if p.is_dir())
    sums = json.loads((pkg / "SHA256SUMS.json").read_text())
    assert {"video.mp4", "thumbnail.png", "title.txt", "credits.json"} <= set(sums)
    meta = json.loads((pkg / "platform-metadata.json").read_text())
    assert meta["youtube"]["status"]["privacyStatus"] == "private" and meta["youtube"]["status"]["containsSyntheticMedia"]
    assert prod.get(pid)["state"] == "APPROVED"                        # export is not publishing
    assert Path(res["zip"]).name.endswith(".zip")


class FakeYouTube:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append((method, url))
        if "oauth2" in url:
            return 200, {}, json.dumps({"access_token": "t"}).encode()
        if "/channels" in url:                     # brand-bound account check (pipeline/publishing._verify_account)
            return 200, {}, json.dumps({"items": [{"id": "UC_TEST", "snippet": {"title": "t"}}]}).encode()
        if method == "POST":
            return 200, {"Location": "https://upload.example/session"}, b""
        return 201, {}, json.dumps({"id": "VID123"}).encode()


def test_youtube_adapter_needs_private_credentials(tmp_path):
    with pytest.raises(publishing.NotConfigured):
        publishing.YouTubeAdapter(tmp_path / "none.json")
    cfg = tmp_path / "yt.json"
    cfg.write_text(json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c"}))
    os.chmod(cfg, 0o644)
    with pytest.raises(publishing.NotConfigured):
        publishing.YouTubeAdapter(cfg)


def test_youtube_publish_mocked_end_to_end(prod, registry, tmp_path, monkeypatch):
    monkeypatch.setattr(publishing, "expected_account", lambda brand, platform: "UC_TEST")
    pid, _ = _ready(prod, registry, tmp_path)
    _resolve_all(prod, pid)
    prod.approve(pid, "Priyanshu")
    cfg = tmp_path / "yt.json"
    cfg.write_text(json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c"}))
    os.chmod(cfg, 0o600)
    fake = FakeYouTube()
    res = publishing.publish(prod, pid, "youtube", "short", confirm=True, actor="Priyanshu",
                             adapter=publishing.YouTubeAdapter(cfg, http=fake))
    assert res["remote_id"] == "VID123" and prod.get(pid)["state"] == "PUBLISHED"
    assert [m for m, _ in fake.calls] == ["POST", "GET", "POST", "PUT"]   # token, channel check, session, bytes


def test_failed_publish_returns_to_approved(prod, registry, tmp_path, monkeypatch):
    monkeypatch.setattr(publishing, "expected_account", lambda brand, platform: "UC_TEST")
    pid, _ = _ready(prod, registry, tmp_path)
    _resolve_all(prod, pid)
    prod.approve(pid, "Priyanshu")

    class Boom:
        def account(self):
            return {"id": "UC_TEST"}

        def upload(self, *a):
            raise RuntimeError("network down")
    with pytest.raises(RuntimeError):
        publishing.publish(prod, pid, "youtube", "short", confirm=True, actor="me", adapter=Boom())
    assert prod.get(pid)["state"] == "APPROVED"


# ---- scheduler -----------------------------------------------------------------------------------
class Mem:
    def __init__(self, mb):
        self.available_mb = mb


def test_scheduler_runs_one_heavy_workload_at_a_time_by_priority(registry):
    order, started = [], threading.Event()

    def holder():
        with scheduler.HeavyWork(registry, "render", poll=0.05, mem=lambda: Mem(9999)):
            started.set()
            time.sleep(0.6)
            order.append("render-done")

    def waiter(kind):
        with scheduler.HeavyWork(registry, kind, poll=0.05, mem=lambda: Mem(9999)):
            order.append(kind)
    t = threading.Thread(target=holder); t.start(); started.wait(2)
    a = threading.Thread(target=waiter, args=("llm",)); a.start(); time.sleep(0.15)
    b = threading.Thread(target=waiter, args=("tts",)); b.start()
    for x in (t, a, b):
        x.join(5)
    assert order == ["render-done", "tts", "llm"]          # tts (2) beats llm (3) although it queued later


def test_scheduler_waits_for_memory(registry, monkeypatch):
    monkeypatch.setattr(scheduler, "load_config", lambda: {"priorities": scheduler.DEFAULT_PRIORITY,
                                                            "min_available_mb": {**scheduler.DEFAULT_MEM_MB, "llm": 2000},
                                                            "max_mem_wait_s": 0.4})
    seen = []
    mem = lambda: (seen.append(1), Mem(500))[1]
    t0 = time.time()
    with scheduler.HeavyWork(registry, "llm", poll=0.05, mem=mem) as g:
        pass
    assert time.time() - t0 >= 0.4 and len(seen) > 3        # waited, then proceeded after max_mem_wait


def test_scheduler_reaps_dead_holders(registry):
    dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
    with registry.conn() as c:
        c.execute("INSERT INTO sched_queue (kind,priority,pid,state,enqueued_at) VALUES ('render',1,?,'granted',0)",
                  (dead.pid,))
    with scheduler.HeavyWork(registry, "llm", poll=0.05, timeout=3, mem=lambda: Mem(9999)):
        assert True
    assert scheduler.queue(registry) == []


def test_fresh_registry_is_stamped_and_never_backed_up(tmp_path, monkeypatch):
    """Regression: fresh (test) databases were mistaken for v0.2.0 ones and backed up into the real
    .pipeline/backups on every Registry() call."""
    monkeypatch.setattr(migrations, "BACKUP_DIR", tmp_path / "real-backups")
    monkeypatch.setenv("VIDEO_PIPELINE_DB", str(tmp_path / "fresh.db"))
    from pipeline.jobs import Registry
    Registry(); Registry()
    assert not (tmp_path / "real-backups").exists() and not (tmp_path / "backups").exists()
    c = sqlite3.connect(tmp_path / "fresh.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST
