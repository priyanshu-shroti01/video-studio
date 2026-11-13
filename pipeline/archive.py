"""Archive productions and render jobs: hide them from every list and the dashboard, and move their files to
output/_archive/ (reversible: nothing is deleted, the audit history and approvals stay in the registry).

  video-pipeline archive --production P...   [--actor NAME] [--note ...]
  video-pipeline archive --job J...
  video-pipeline archive --all-except P... [--all-except P...]     everything else (productions + loose jobs)

Refuses anything that is running or publishing. Deleting the archive for good is a separate, manual step
(`rm -rf output/_archive`), never done by the pipeline."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .errors import PipelineError
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
    reg.audit(actor, "archive.production", pid, {"state": p["state"], "to": rel(new), "jobs": jobs, "note": note})
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


__all__ = ["archive_job", "archive_production", "archive_all_except", "archive_size_mb", "ARCHIVE_DIR", "ROOT"]
