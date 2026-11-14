"""Restoring from output/_archive/: the exact reverse of archiving (files, registry state, lists, video-out),
named actor, never overwrites. Everything runs in a temp workspace; the real archive is never touched."""
import json
import shutil
import time
import uuid
from pathlib import Path

import pytest

from pipeline import archive as AR
from pipeline import video_out as VO
from pipeline.errors import ConfigError, StateError
from pipeline.paths import TMP_DIR, rel


@pytest.fixture
def ws(monkeypatch):
    import pipeline.productions as P
    d = TMP_DIR / f"test-restore-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", d / "productions")
    monkeypatch.setattr(AR, "ARCHIVE_DIR", d / "_archive")
    monkeypatch.setattr(VO, "OUT", d / "video-out")
    monkeypatch.setattr(VO, "INDEX", d / "video-out" / ".index.json")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _job(registry, ws, config_path=None, name="job"):
    jdir = ws / "jobs" / f"job-{uuid.uuid4().hex[:6]}"
    (jdir / "video").mkdir(parents=True)
    (jdir / "video" / "final-short.mp4").write_bytes(b"\x00" * 4096)
    jid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    with registry.conn() as c:
        c.execute("INSERT INTO jobs (id,name,key_hash,state,config_json,config_path,output_dir,created_at,updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (jid, name, uuid.uuid4().hex, "COMPLETED", "{}", config_path, str(jdir),
                                                 time.time(), time.time()))
    return jid, jdir


def _finished(registry, ws, state="AWAITING_APPROVAL", name="WP Promo"):
    from pipeline.productions import Productions
    prod = Productions(registry)
    p = prod.create("shrotihost", name, {"brand": "Shroti Host", "product": "x"})
    d = Path(p["dir"])
    (d / "project.json").write_text("{}")
    (d / "storyboard.json").write_text("{}")
    jid, jdir = _job(registry, ws, rel(d) + "/project.json", name)
    with registry.conn() as c:
        c.execute("UPDATE productions SET state=?, job_id=?, project_path=?, storyboard_path=? WHERE id=?",
                  (state, jid, str(d / "project.json"), str(d / "storyboard.json"), p["id"]))
    return prod.get(p["id"]), jid, jdir


def test_archive_then_restore_is_a_round_trip(registry, ws):
    from pipeline.productions import Productions
    prod = Productions(registry)
    p, jid, jdir = _finished(registry, ws)
    before = {"prod": prod.get(p["id"]), "job": registry.get(jid)}
    assert len(VO.sync(registry)["videos"]) == 1
    AR.archive_production(registry, p["id"], "Reviewer", "clean up")
    assert VO.sync(registry)["videos"] == [] and not Path(p["dir"]).exists() and not jdir.exists()

    listed = AR.list_archived(registry)
    assert [x["id"] for x in listed["productions"]] == [p["id"]] and listed["jobs"] == []   # its job is not "loose"
    row = listed["productions"][0]
    assert row["state"] == "AWAITING_APPROVAL" and row["brand"] == "shrotihost" and row["name"] == "WP Promo"
    assert row["jobs"] == [jid] and row["archived_at"] and row["blocked"] is None and row["restore_to"] == rel(Path(p["dir"]))
    assert row["size_mb"] >= 0 and "_archive" in row["dir"]

    r = AR.restore_production(p["id"], "Priyanshu", "needed again", reg=registry)
    assert r["restored_to"] == rel(Path(p["dir"])) and [j["job"] for j in r["jobs"]] == [jid]
    after = {"prod": prod.get(p["id"]), "job": registry.get(jid)}
    for k in ("dir", "project_path", "storyboard_path", "concepts_path", "state", "job_id"):
        assert after["prod"][k] == before["prod"][k], k
    for k in ("output_dir", "config_path", "state"):
        assert after["job"][k] == before["job"][k], k
    assert after["prod"]["archived_at"] is None and after["job"]["archived_at"] is None
    assert (Path(p["dir"]) / "project.json").exists() and (jdir / "video" / "final-short.mp4").exists()
    assert p["id"] in [x["id"] for x in prod.list()] and jid in [j["id"] for j in registry.list()]
    assert AR.list_archived(registry) == {"productions": [], "jobs": [], "size_mb": AR.archive_size_mb()}
    vo = VO.sync(registry)
    assert len(vo["videos"]) == 1 and "/for-review/" in vo["videos"][0]
    with registry.conn() as c:
        audit = [tuple(x) for x in c.execute("SELECT actor, action, subject FROM audit_log WHERE action LIKE 'restore.%' ORDER BY id")]
    assert audit == [("Priyanshu", "restore.job", jid), ("Priyanshu", "restore.production", p["id"])]
    # and it can be archived again afterwards
    AR.archive_production(registry, p["id"], "Reviewer")
    assert p["id"] not in [x["id"] for x in prod.list()]


def test_restore_never_overwrites_and_moves_nothing_when_refused(registry, ws):
    from pipeline.productions import Productions
    p, jid, jdir = _finished(registry, ws)
    AR.archive_production(registry, p["id"], "Reviewer")
    archived_dir = Path(Productions(registry).get(p["id"])["dir"])
    Path(p["dir"]).mkdir(parents=True)                               # something new took the original place
    (Path(p["dir"]) / "mine.txt").write_text("keep me")
    assert AR.list_archived(registry)["productions"][0]["blocked"]
    with pytest.raises(StateError, match="already exists"):
        AR.restore_production(p["id"], "Priyanshu", reg=registry)
    assert (Path(p["dir"]) / "mine.txt").read_text() == "keep me" and archived_dir.exists()
    assert Productions(registry).get(p["id"])["archived_at"] and registry.get(jid)["archived_at"]

    shutil.rmtree(p["dir"])
    jdir.mkdir(parents=True)                                         # now only the job's original folder is taken
    with pytest.raises(StateError, match="already exists"):
        AR.restore_production(p["id"], "Priyanshu", reg=registry)
    assert archived_dir.exists() and not Path(p["dir"]).exists()     # checked before the production moved
    assert Productions(registry).get(p["id"])["archived_at"]


def test_restore_needs_a_named_actor(registry, ws):
    from pipeline.productions import Productions
    p, jid, _ = _finished(registry, ws)
    AR.archive_production(registry, p["id"], "Reviewer")
    for who in ("", "   ", None):
        with pytest.raises(ConfigError):
            AR.restore_production(p["id"], who, reg=registry)
        with pytest.raises(ConfigError):
            AR.restore_job(jid, who, reg=registry)
    assert Productions(registry).get(p["id"])["archived_at"]


def test_restore_refuses_what_is_not_archived(registry, ws):
    p, jid, _ = _finished(registry, ws)
    with pytest.raises(StateError, match="not archived"):
        AR.restore_production(p["id"], "Priyanshu", reg=registry)
    with pytest.raises(StateError, match="not archived"):
        AR.restore_job(jid, "Priyanshu", reg=registry)


def test_loose_archived_job_restores_on_its_own_but_a_production_s_job_does_not(registry, ws):
    jid, jdir = _job(registry, ws, None, "loose")
    AR.archive_job(registry, jid, "Reviewer", "old test")
    assert jid not in [j["id"] for j in registry.list()] and not jdir.exists()
    loose = AR.list_archived(registry)["jobs"]
    assert [j["id"] for j in loose] == [jid] and loose[0]["restore_to"] == rel(jdir)
    r = AR.restore_job(jid, "Priyanshu", reg=registry)
    assert r["restored_to"] == rel(jdir) and (jdir / "video" / "final-short.mp4").exists()
    assert registry.get(jid)["output_dir"] == str(jdir) and jid in [j["id"] for j in registry.list()]

    p, pjob, _ = _finished(registry, ws)
    AR.archive_production(registry, p["id"], "Reviewer")
    with pytest.raises(StateError, match="restore the production"):
        AR.restore_job(pjob, "Priyanshu", reg=registry)

    jid2, jdir2 = _job(registry, ws, None, "loose 2")
    AR.archive_job(registry, jid2, "Reviewer")
    jdir2.mkdir(parents=True)
    with pytest.raises(StateError, match="already exists"):
        AR.restore_job(jid2, "Priyanshu", reg=registry)
    assert registry.get(jid2)["archived_at"]


def test_restore_of_an_archive_made_before_from_was_recorded(registry, ws):
    """Older archive.production audit entries have no "from": the production goes back to output/productions/<id>."""
    p, _, _ = _finished(registry, ws)
    AR.archive_production(registry, p["id"], "Reviewer")
    with registry.conn() as c:
        row = c.execute("SELECT id, detail_json FROM audit_log WHERE action='archive.production' AND subject=?", (p["id"],)).fetchone()
        d = json.loads(row[1]); d.pop("from")
        c.execute("UPDATE audit_log SET detail_json=? WHERE id=?", (json.dumps(d), row[0]))
    AR.restore_production(p["id"], "Priyanshu", reg=registry)
    assert Path(p["dir"]).exists()


def test_cli_list_and_restore(registry, ws, capsys):
    from pipeline.cli import main
    p, _, _ = _finished(registry, ws)
    assert main(["archive", "--production", p["id"], "--actor", "Reviewer"]) == 0
    capsys.readouterr()
    assert main(["--json", "archive", "--list"]) == 0
    assert [x["id"] for x in json.loads(capsys.readouterr().out)["productions"]] == [p["id"]]
    with pytest.raises(SystemExit):
        main(["archive", "--restore", p["id"]])                       # no actor
    assert main(["archive", "--restore", p["id"], "--actor", "Priyanshu"]) == 0
    assert "restored " + p["id"] in capsys.readouterr().out and Path(p["dir"]).exists()
