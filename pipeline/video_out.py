"""video-out/: the finished videos, by brand, with readable names (copies; the originals stay in output/).

  video-out/<brand>/for-review/   rendered + QA done, waiting for a person's final approval
  video-out/<brand>/approved/     approved (or published) productions
  video-out/README.md

Kept in sync automatically on every production state change (render finished, approve, reject, archive) and on
demand with `video-pipeline video-out`. Copies, never links: trimming or re-saving a file here can't touch the
approved original (whose hash the approval is bound to). Only files this module wrote (listed in
video-out/.index.json) are ever removed; anything you add yourself is left alone."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from .paths import ROOT, atomic_write_json, atomic_write_text

OUT = ROOT / "video-out"
INDEX = OUT / ".index.json"
FOLDER = {"AWAITING_APPROVAL": "for-review", "APPROVED": "approved", "PUBLISHING": "approved", "PUBLISHED": "approved"}
README = """# video-out

Finished videos, one folder per brand. These are **copies**; the originals stay in `output/`.

- `for-review/`: rendered and QA-checked, waiting for your final approval (Studio → Publishing).
- `approved/`: approved by a named reviewer. Only these may be exported or published.

File name: `<date> <production name> (<id>) <format>.mp4`. This folder updates itself when a render finishes or
a production is approved, rejected or archived. Rejected and archived videos disappear from here (their
originals are in `output/` or `output/_archive/`). Refresh by hand with `uv run video-pipeline video-out`.
"""


def _safe(s: str) -> str:
    return re.sub(r"[^\w .,()&+-]", "", s).strip()[:60] or "video"


def _index() -> dict:
    try:
        return json.loads(INDEX.read_text())
    except (OSError, ValueError):
        return {"files": {}}


def wanted(reg) -> dict[str, dict]:
    """{relative path under video-out: {src, production, state}} for every non-archived finished production."""
    from .productions import Productions
    out = {}
    for p in Productions(reg).list(10_000):
        folder = FOLDER.get(p["state"])
        if not folder or not p["job_id"]:
            continue
        job = reg.get(p["job_id"])
        vids = sorted((Path(job["output_dir"]) / "video").glob("final-*.mp4"))
        date = time.strftime("%Y-%m-%d", time.localtime(p["created_at"]))
        for v in vids:
            fmt = v.stem.removeprefix("final-")
            name = f"{date} {_safe(p['name'])} ({p['id'][-5:]}) {fmt}.mp4"
            out[f"{p['brand']}/{folder}/{name}"] = {"src": str(v), "production": p["id"], "state": p["state"]}
    return out


def sync(reg=None) -> dict:
    from .jobs import Registry
    reg = reg or Registry()
    OUT.mkdir(exist_ok=True)
    if not (OUT / "README.md").exists():
        atomic_write_text(OUT / "README.md", README)
    want = wanted(reg)
    idx = _index()
    added, removed = [], []
    for relp, info in want.items():
        dst, src = OUT / relp, Path(info["src"])
        if not src.exists():
            continue
        if not dst.exists() or dst.stat().st_size != src.stat().st_size or dst.stat().st_mtime < src.stat().st_mtime:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part")
            shutil.copy2(src, tmp)
            tmp.replace(dst)
            added.append(relp)
    for relp in list(idx.get("files", {})):
        if relp not in want:                       # only files we created
            f = OUT / relp
            if f.exists():
                f.unlink()
                removed.append(relp)
            for d in (f.parent, f.parent.parent):
                try:
                    d.rmdir()                       # drop empty folders only
                except OSError:
                    pass
    atomic_write_json(INDEX, {"updated_at": time.time(), "files": want})
    return {"dir": "video-out", "videos": sorted(want), "added": added, "removed": removed}


def sync_quietly(reg=None) -> None:
    """Never let the convenience copy break a workflow step."""
    try:
        sync(reg)
    except Exception:  # noqa: BLE001
        pass
