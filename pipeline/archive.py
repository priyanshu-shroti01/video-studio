"""Archive productions and render jobs: hide them from every list and the dashboard, and move their files to
output/_archive/ (reversible: nothing is deleted, the audit history and approvals stay in the registry).

  video-pipeline archive --production P...   [--actor NAME] [--note ...]
  video-pipeline archive --job J...
  video-pipeline archive --all-except P... [--all-except P...]     everything else (productions + loose jobs)
  video-pipeline archive --list                                      what is in output/_archive
  video-pipeline archive --restore P... [--restore-job J...] --actor NAME   move it back (never overwrites)

Refuses anything that is running or publishing. Deleting the archive for good is a separate, manual step
(`rm -rf output/_archive`), never done by the pipeline."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .errors import ConfigError, PipelineError, StateError
from .jobs import Registry
from .paths import OUTPUT_DIR, ROOT, rel

ARCHIVE_DIR = OUTPUT_DIR / "_archive"
BUSY_PRODUCTION = {"RENDERING", "PUBLISHING"}
BUSY_JOB = {"QUEUED", "RETRYING", "PREPARING", "GENERATING_AUDIO", "BUILDING_TIMELINE", "RENDERING", "POST_PROCESSING", "QA"}


def _move(src: Path, dst: Path) -> Path | None:
    if not src.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst = dst.with_name(f"{dst.name}-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.move(str(src), str(dst))
    return dst


def _swap(value: str | None, old: Path, new: Path) -> str | None:
    """Rewrite a stored path (absolute or repo-relative) that lives under `old` to live under `new`."""
    if not value:
        return value
    for o, n in ((str(old), str(new)), (rel(old), rel(new))):
        if value == o or value.startswith(o + "/"):
            return n + value[len(o):]
    return value


def archive_job(reg: Registry, jid: str, actor: str, note: str = "") -> dict:
    j = reg.get(jid)
    if j["state"] in BUSY_JOB:
        raise PipelineError(f"job {jid} is {j['state']}: cancel it or wait before archiving")
    old = Path(j["output_dir"])
    new = _move(old, ARCHIVE_DIR / "jobs" / old.name)
    with reg.conn() as c:
        c.execute("UPDATE jobs SET archived_at=?, output_dir=? WHERE id=?",
                  (time.time(), str(new) if new else j["output_dir"], jid))
    reg.audit(actor, "archive.job", jid, {"from": rel(old), "to": rel(new) if new else None, "note": note})
    return {"job": jid, "moved_to": rel(new) if new else None}


def archive_production(reg: Registry, pid: str, actor: str, note: str = "") -> dict:
    from .productions import Productions
    prod = Productions(reg)
    p = prod.get(pid)
    if p["state"] in BUSY_PRODUCTION:
        raise PipelineError(f"production {pid} is {p['state']}: wait for it to finish before archiving")
    old = Path(p["dir"])
    # every render job this production ran (retries included), found through its project file
    with reg.conn() as c:
        jobs = [r[0] for r in c.execute("SELECT id FROM jobs WHERE archived_at IS NULL AND (config_path LIKE ? OR id=?)",
                                        (rel(old) + "/%", p["job_id"] or ""))]
    moved_jobs = [archive_job(reg, j, actor, f"with production {pid}") for j in jobs]
    new = _move(old, ARCHIVE_DIR / "productions" / old.name) or old
    with reg.conn() as c:
        c.execute("UPDATE productions SET archived_at=?, dir=?, project_path=?, storyboard_path=?, concepts_path=? WHERE id=?",
                  (time.time(), str(new), _swap(p["project_path"], old, new), _swap(p["storyboard_path"], old, new),
                   _swap(p["concepts_path"], old, new), pid))
        c.execute("UPDATE jobs SET config_path=? WHERE config_path LIKE ?",
                  (_swap(rel(old) + "/project.json", old, new), rel(old) + "/project.json"))
    reg.audit(actor, "archive.production", pid, {"state": p["state"], "from": rel(old), "to": rel(new), "jobs": jobs, "note": note})
    return {"production": pid, "state": p["state"], "moved_to": rel(new), "jobs": moved_jobs}


def archive_all_except(reg: Registry, keep: list[str], actor: str, note: str = "") -> dict:
    from .productions import Productions
    prod = Productions(reg)
    keep_set = set(keep)
    for pid in keep:
        prod.get(pid)                                   # unknown id -> NotFound before anything moves
    kept_jobs = {prod.get(pid)["job_id"] for pid in keep} - {None}
    with reg.conn() as c:
        kept_jobs |= {r[0] for pid in keep for r in c.execute("SELECT id FROM jobs WHERE config_path LIKE ?",
                                                              (rel(Path(prod.get(pid)["dir"])) + "/%",))}
    out = {"productions": [], "jobs": [], "kept": sorted(keep_set), "skipped": []}
    for p in prod.list(10_000):
        if p["id"] in keep_set:
            continue
        try:
            out["productions"].append(archive_production(reg, p["id"], actor, note))
        except PipelineError as e:
            out["skipped"].append(f"{p['id']}: {e.message}")
    for j in reg.list(10_000):
        if j["id"] in kept_jobs:
            continue
        try:
            out["jobs"].append(archive_job(reg, j["id"], actor, note))
        except PipelineError as e:
            out["skipped"].append(f"{j['id']}: {e.message}")
    return out


def archive_size_mb() -> float:
    if not ARCHIVE_DIR.exists():
        return 0.0
    return round(sum(f.stat().st_size for f in ARCHIVE_DIR.rglob("*") if f.is_file()) / 1e6, 1)


# ---- restore (the exact reverse of archiving; refuses rather than overwrites) ------------------------------
def _abs(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else ROOT / p


def _last_audit(reg: Registry, action: str, subject: str) -> dict:
    with reg.conn() as c:
        r = c.execute("SELECT detail_json FROM audit_log WHERE action=? AND subject=? ORDER BY id DESC LIMIT 1",
                      (action, subject)).fetchone()
    try:
        return json.loads(r[0]) if r and r[0] else {}
    except ValueError:
        return {}


def _size_mb(p: Path) -> float:
    if not p.exists():
        return 0.0
    if p.is_file():
        return round(p.stat().st_size / 1e6, 1)
    return round(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6, 1)


def _job_origin(reg: Registry, j: dict) -> Path | None:
    """Where an archived job's folder lived before archiving (from its archive.job audit entry)."""
    src = _last_audit(reg, "archive.job", j["id"]).get("from")
    return _abs(src) if src else None


def _production_origin(reg: Registry, p: dict) -> Path:
    src = _last_audit(reg, "archive.production", p["id"]).get("from")
    if src:
        return _abs(src)
    from . import productions as PR                    # archives made before "from" was recorded
    return PR.PRODUCTIONS_DIR / p["id"]


def _production_jobs(reg: Registry, p: dict) -> list[str]:
    """The render jobs archived together with this production."""
    jobs = list(_last_audit(reg, "archive.production", p["id"]).get("jobs") or [])
    if p.get("job_id") and p["job_id"] not in jobs:
        jobs.append(p["job_id"])
    return jobs


def list_archived(reg: Registry | None = None) -> dict:
    """Everything in output/_archive: productions (with their jobs) and loose jobs archived on their own."""
    reg = reg or Registry()
    with reg.conn() as c:
        prows = [dict(r) for r in c.execute("SELECT id,brand,name,state,job_id,dir,archived_at FROM productions "
                                             "WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")]
        jrows = [dict(r) for r in c.execute("SELECT id,name,state,output_dir,archived_at FROM jobs "
                                             "WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")]
    archived_jobs = {j["id"] for j in jrows}
    owned: set[str] = set()
    prods = []
    for p in prows:
        detail = _last_audit(reg, "archive.production", p["id"])
        jobs = [j for j in _production_jobs(reg, p) if j in archived_jobs]
        owned |= set(jobs)
        origin = _production_origin(reg, p)
        prods.append({"id": p["id"], "name": p["name"], "brand": p["brand"], "state": detail.get("state") or p["state"],
                      "archived_at": p["archived_at"], "size_mb": round(_size_mb(Path(p["dir"])) + sum(
                          _size_mb(Path(j["output_dir"])) for j in jrows if j["id"] in jobs), 1),
                      "dir": rel(Path(p["dir"])), "restore_to": rel(origin), "jobs": jobs,
                      "blocked": f"{rel(origin)} already exists" if origin.exists() else None})
    loose = []
    for j in jrows:
        if j["id"] in owned:
            continue
        origin = _job_origin(reg, j)
        loose.append({"id": j["id"], "name": j["name"], "state": j["state"], "archived_at": j["archived_at"],
                      "size_mb": _size_mb(Path(j["output_dir"])), "dir": rel(Path(j["output_dir"])),
                      "restore_to": rel(origin) if origin else None,
                      "blocked": f"{rel(origin)} already exists" if origin and origin.exists() else None})
    return {"productions": prods, "jobs": loose, "size_mb": archive_size_mb()}


def _need_actor(actor: str) -> str:
    actor = (actor or "").strip()
    if not actor:
        raise ConfigError("restoring needs the name of the person asking for it (--actor)")
    return actor


def _restore_job_files(reg: Registry, j: dict) -> tuple[Path, Path]:
    """(current archived folder, where it goes back to). Refuses before anything moves."""
    if not j.get("archived_at"):
        raise StateError(f"job {j['id']} is not archived")
    cur = Path(j["output_dir"])
    origin = _job_origin(reg, j)
    if origin is None:
        raise StateError(f"job {j['id']}: no record of where it lived before archiving; move it back by hand")
    if cur.exists() and origin.exists():
        raise StateError(f"{rel(origin)} already exists: move or rename it first (restore never overwrites)")
    return cur, origin


def _do_restore_job(reg: Registry, j: dict, cur: Path, origin: Path, actor: str, note: str) -> dict:
    moved = False
    if cur.exists():
        origin.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cur), str(origin))
        moved = True
    with reg.conn() as c:
        c.execute("UPDATE jobs SET archived_at=NULL, output_dir=? WHERE id=?", (str(origin), j["id"]))
    reg.audit(actor, "restore.job", j["id"], {"from": rel(cur), "to": rel(origin), "moved": moved, "note": note})
    return {"job": j["id"], "restored_to": rel(origin), "moved": moved}


def restore_job(jid: str, actor: str, note: str = "", *, reg: Registry | None = None) -> dict:
    """Restore a loose job archived on its own. A job archived with its production comes back with it."""
    actor = _need_actor(actor)
    reg = reg or Registry()
    j = reg.get(jid)
    if not j.get("archived_at"):
        raise StateError(f"job {jid} is not archived")
    with reg.conn() as c:
        owners = [dict(r) for r in c.execute("SELECT id,job_id FROM productions WHERE archived_at IS NOT NULL")]
    for p in owners:
        if jid in _production_jobs(reg, p):
            raise StateError(f"job {jid} was archived with production {p['id']}: restore the production instead")
    cur, origin = _restore_job_files(reg, j)
    return _do_restore_job(reg, j, cur, origin, actor, note)


def restore_production(pid: str, actor: str, note: str = "", *, reg: Registry | None = None) -> dict:
    """Move an archived production (and the render jobs archived with it) back to where it was and show it in
    lists and the dashboard again. Refuses, before moving anything, if any original path is taken."""
    from .productions import Productions
    actor = _need_actor(actor)
    reg = reg or Registry()
    p = Productions(reg).get(pid)
    if not p.get("archived_at"):
        raise StateError(f"production {pid} is not archived")
    cur = Path(p["dir"])
    origin = _production_origin(reg, p)
    if cur.exists() and origin.exists() and cur.resolve() != origin.resolve():
        raise StateError(f"{rel(origin)} already exists: move or rename it first (restore never overwrites)")
    jobs = []
    for jid in _production_jobs(reg, p):
        try:
            j = reg.get(jid)
        except PipelineError:
            continue
        if j.get("archived_at"):
            jobs.append((j, *_restore_job_files(reg, j)))          # every check passes before any file moves
    if cur.exists() and cur.resolve() != origin.resolve():
        origin.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cur), str(origin))
    with reg.conn() as c:
        c.execute("UPDATE productions SET archived_at=NULL, dir=?, project_path=?, storyboard_path=?, concepts_path=? WHERE id=?",
                  (str(origin), _swap(p["project_path"], cur, origin), _swap(p["storyboard_path"], cur, origin),
                   _swap(p["concepts_path"], cur, origin), pid))
        c.execute("UPDATE jobs SET config_path=? WHERE config_path=?", (rel(origin) + "/project.json", rel(cur) + "/project.json"))
    restored = [_do_restore_job(reg, j, jc, jo, actor, f"with production {pid}") for j, jc, jo in jobs]
    reg.audit(actor, "restore.production", pid, {"from": rel(cur), "to": rel(origin), "jobs": [r["job"] for r in restored],
                                                 "note": note})
    return {"production": pid, "state": p["state"], "restored_to": rel(origin), "jobs": restored}


__all__ = ["archive_job", "archive_production", "archive_all_except", "archive_size_mb", "list_archived",
           "restore_production", "restore_job", "ARCHIVE_DIR", "ROOT"]
