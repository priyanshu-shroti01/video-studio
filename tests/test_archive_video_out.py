"""Archiving (reversible clean-up of the dashboard) and video-out/ (finished videos by brand)."""
import json
import shutil
import time
import uuid

import pytest

from pipeline import archive as AR
from pipeline import video_out as VO
from pipeline.paths import TMP_DIR, rel


@pytest.fixture
def ws(monkeypatch):
    d = TMP_DIR / f"test-archive-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    monkeypatch.setattr(AR, "ARCHIVE_DIR", d / "_archive")
    monkeypatch.setattr(VO, "OUT", d / "video-out")
    monkeypatch.setattr(VO, "INDEX", d / "video-out" / ".index.json")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _finished(registry, ws, state="AWAITING_APPROVAL", name="WP Promo", brand="shrotihost"):
    """A production in `state` whose render job has a final video (states set directly: lifecycle is tested elsewhere)."""
    from pipeline.productions import Productions
    prod = Productions(registry)
    p = prod.create(brand, name, {"brand": "Shroti Host", "product": "x"})
    jdir = ws / f"job-{uuid.uuid4().hex[:6]}"
    (jdir / "video").mkdir(parents=True)
    (jdir / "video" / "final-short.mp4").write_bytes(b"\x00" * 2048)
    jid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    with registry.conn() as c:
        c.execute("INSERT INTO jobs (id,name,key_hash,state,config_json,config_path,output_dir,created_at,updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (jid, name, uuid.uuid4().hex, "COMPLETED", "{}",
                                                 rel(__import__('pathlib').Path(p["dir"])) + "/project.json", str(jdir), time.time(), time.time()))
        c.execute("UPDATE productions SET state=?, job_id=? WHERE id=?", (state, jid, p["id"]))
    return prod.get(p["id"]), jid


def test_archive_hides_moves_and_keeps_history(registry, ws):
    from pipeline.productions import Productions
    p, jid = _finished(registry, ws, "REJECTED")
    registry.audit("Reviewer", "production.rejected", p["id"])
    r = AR.archive_production(registry, p["id"], "Reviewer", "clean dashboard")
    assert p["id"] not in [x["id"] for x in Productions(registry).list()]
    assert jid not in [j["id"] for j in registry.list()]
    assert p["id"] in [x["id"] for x in Productions(registry).list(include_archived=True)]   # not deleted
    moved = Productions(registry).get(p["id"])
    assert "_archive" in moved["dir"] and (AR.ARCHIVE_DIR / "jobs").exists() and r["jobs"]
    with registry.conn() as c:
        actions = [x[0] for x in c.execute("SELECT action FROM audit_log WHERE subject IN (?,?)", (p["id"], jid))]
    assert {"production.rejected", "archive.production", "archive.job"} <= set(actions)


def test_archive_all_except_keeps_the_chosen_production(registry, ws):
    from pipeline.productions import Productions
    keep, kjob = _finished(registry, ws, "APPROVED", "Keep me")
    other, _ = _finished(registry, ws, "REJECTED", "Old")
    AR.archive_all_except(registry, [keep["id"]], "Reviewer")
    assert [x["id"] for x in Productions(registry).list()] == [keep["id"]]
    assert [j["id"] for j in registry.list()] == [kjob]
    shutil.rmtree(keep["dir"], ignore_errors=True)


def test_running_work_is_never_archived(registry, ws):
    p, jid = _finished(registry, ws, "RENDERING")
    with pytest.raises(Exception, match="RENDERING"):
        AR.archive_production(registry, p["id"], "Reviewer")
    shutil.rmtree(p["dir"], ignore_errors=True)


def test_video_out_folders_follow_the_approval_state(registry, ws):
    p, _ = _finished(registry, ws, "AWAITING_APPROVAL", "WordPress Hosting")
    r = VO.sync(registry)
    assert len(r["videos"]) == 1 and "/for-review/" in r["videos"][0] and r["videos"][0].startswith("shrotihost/")
    mine = VO.OUT / "shrotihost" / "my-notes.txt"
    mine.write_text("keep me")                                   # a file the user added
    with registry.conn() as c:
        c.execute("UPDATE productions SET state='APPROVED' WHERE id=?", (p["id"],))
    r = VO.sync(registry)
    assert "/approved/" in r["videos"][0] and r["removed"] and "(" + p["id"][-5:] + ")" in r["videos"][0]
    AR.archive_production(registry, p["id"], "Reviewer")
    r = VO.sync(registry)
    assert r["videos"] == [] and mine.read_text() == "keep me"   # only our own copies are removed
    assert json.loads(VO.INDEX.read_text())["files"] == {}
