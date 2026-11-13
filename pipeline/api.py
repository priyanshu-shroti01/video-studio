"""Service layer shared by the CLI and the Studio UI. Every workflow rule lives here (or below), so the
GUI cannot bypass validation, the scheduler or the approval gate.

Production directory: output/productions/<id>/
  brief.json · concepts/ (concepts.json, comparison.md) · storyboard.json · project.json ·
  preview/ (contact sheet of storyboard stills) · approval/ · export/
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .config import config_hash, load_project
from .errors import NotFound, PipelineError
from .jobs import Registry
from .paths import OUTPUT_DIR, ROOT, atomic_write_json, free_gb, rel, safe_path
from .productions import Productions, flags_from_job
from .storyboard import validate_storyboard

FORMAT_PRESET = {"short": "shorts", "landscape": "landscape"}


def _reg() -> Registry:
    return Registry()


def _dir_mb(p: Path) -> float:
    if not p.exists():
        return 0.0
    return round(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6, 1)


# ---- dashboard -----------------------------------------------------------------------------------
def _gate(p: dict) -> dict | None:
    g = Path(p["dir"]) / "preview/gate.json" if p.get("dir") else None
    if not g or not g.exists():
        return None
    try:
        d = json.loads(g.read_text())
    except ValueError:
        return None
    return {"status": d.get("status"), "failed": [c["id"] for c in d.get("checks", []) if c["status"] == "FAIL"],
            "warned": [c["id"] for c in d.get("checks", []) if c["status"] == "WARN"]}


def brand_overview(include_hidden: bool = False) -> list[dict]:
    """Every brand with its setup status: draft/ready, verified facts, logo licence, publishing accounts.
    Hidden (test) brands are left out unless include_hidden."""
    from .brands import list_brands, load_profile, visible_brands
    from .paths import STATE_DIR
    out = []
    for b in (list_brands() if include_hidden else visible_brands()):
        row = {"id": b, "name": b, "status": "ready", "industry": None, "colour": None, "website": None,
               "facts": 0, "facts_checked": None, "unverified_claims": 0, "review": [], "accounts": {}}
        try:
            prof = load_profile(b)
            row.update(name=prof.get("name", b), status=prof.get("status", "ready"), industry=(prof.get("creative") or {}).get("industry") or prof.get("industry"),
                       website=prof.get("website"))
            th = json.loads((ROOT / "brands" / b / "theme.json").read_text())
            row["colour"] = th.get("colors", {}).get("brand")
        except (PipelineError, OSError, ValueError) as e:
            row["review"].append(f"profile unreadable: {e}")
        ff = ROOT / "knowledge" / b / "facts.json"
        if ff.exists():
            try:
                fd = json.loads(ff.read_text())
                row.update(facts=len(fd.get("facts", [])), facts_checked=fd.get("fetched_at") or None,
                           unverified_claims=sum(1 for x in fd.get("not_found", []) if x.get("status") == "NEEDS_REVIEW"))
            except ValueError:
                row["review"].append("facts.json unreadable")
        else:
            row["review"].append("no verified facts")
        af = ROOT / "brands" / b / "assets.json"
        if af.exists() and "NEEDS_REVIEW" in af.read_text():
            row["review"].append("asset licence needs review")
        if row["status"] == "draft":
            row["review"].append("brand profile is a draft")
        if row["facts"] == 0 and ff.exists():
            row["review"].append("no verified facts yet: prices and features can't be shown")
        # publishing accounts: presence only, never contents
        for plat in ("youtube", "instagram"):
            row["accounts"][plat] = (STATE_DIR / "secrets" / b / f"{plat}.json").exists()
        out.append(row)
    return out


def attention(prods: list[dict], reg) -> list[dict]:
    """What needs a person, most urgent first: decisions only humans can make."""
    prod = Productions(reg)
    items = []
    for p in prods:
        full = prod.get(p["id"])
        base = {"production": p["id"], "name": p["name"], "brand": p["brand"], "state": p["state"]}
        if p["state"] == "PREVIEW_READY":
            g = _gate(full)
            if g and g["status"] == "FAIL":
                items.append({**base, "kind": "fix-storyboard", "priority": 2, "title": "Storyboard failed the preview gate",
                              "detail": ", ".join(g["failed"]), "action": "storyboard"})
            elif not _preview_approved(reg, full):
                items.append({**base, "kind": "review-preview", "priority": 1, "title": "Review the preview before rendering",
                              "detail": f"gate {g['status'] if g else 'not run'}" + (f" ({', '.join(g['warned'])})" if g and g["warned"] else ""),
                              "action": "qa"})
        elif p["state"] == "AWAITING_APPROVAL":
            blocking = [f for f in prod.flags(p["id"], "open") if f["severity"] == "blocking"]
            items.append({**base, "kind": "approve", "priority": 1, "title": "Watch, review flags and decide",
                          "detail": f"{len(blocking)} blocking review flag(s) open", "action": "publish"})
        elif p["state"] == "CHANGES_REQUESTED":
            items.append({**base, "kind": "revise", "priority": 3, "title": "Changes requested", "detail": "", "action": "storyboard"})
        elif p["state"] == "FAILED":
            items.append({**base, "kind": "failed", "priority": 2, "title": "Production failed", "detail": "see the render monitor",
                          "action": "monitor"})
        elif p["state"] == "APPROVED":
            items.append({**base, "kind": "ready", "priority": 4, "title": "Approved: ready to export or publish",
                          "detail": "publishing needs your explicit confirmation", "action": "publish"})
    return sorted(items, key=lambda x: x["priority"])


def dashboard(brand: str | None = None) -> dict:
    reg = _reg()
    prod = Productions(reg)
    from .scheduler import queue
    from .system import mem_snapshot
    m = mem_snapshot()
    bench = {}
    bf = ROOT / ".pipeline/benchmark.json"
    if bf.exists():
        bench = json.loads(bf.read_text()).get("recommended", {})
    prods_all = prod.list(500)
    prods = [p for p in prods_all if not brand or p["brand"] == brand]
    with reg.conn() as c:   # every render job a production ran (not only its latest), mapped to the brand
        job_brand = {r[0]: r[1] for r in c.execute("SELECT job_id, brand FROM productions WHERE job_id IS NOT NULL")}
    jobs = reg.list(200)
    if brand:
        jobs = [j for j in jobs if job_brand.get(j["id"]) == brand]
    by_state: dict[str, int] = {}
    for p in prods:
        by_state[p["state"]] = by_state.get(p["state"], 0) + 1
    recent = []
    for p in prods[:12]:
        full = prod.get(p["id"])
        qa = None
        if full.get("job_id"):
            try:
                qa = reg.get(full["job_id"]).get("qa_status")
            except Exception:  # noqa: BLE001
                qa = None
        recent.append({**p, "gate": (_gate(full) or {}).get("status"), "preview_approved": _preview_approved(reg, full),
                       "qa_status": qa})
    brands = brand_overview()
    for b in brands:
        b["productions"] = sum(1 for p in prods_all if p["brand"] == b["id"])
    att = attention(prods, reg)
    for b in brands:
        if (not brand or b["id"] == brand) and b["review"] and b["status"] == "draft":
            att.append({"production": None, "name": b["name"], "brand": b["id"], "state": None, "kind": "brand-setup",
                        "priority": 5, "title": "Finish brand setup", "detail": "; ".join(b["review"][:3]), "action": "assets"})
    return {
        "version": __version__, "brand": brand,
        "jobs": {"total": len(jobs), "active": [j for j in jobs if j["state"] not in ("COMPLETED", "FAILED", "CANCELLED")],
                 "completed": sum(j["state"] == "COMPLETED" for j in jobs), "failed": sum(j["state"] == "FAILED" for j in jobs),
                 "recent": [{**j, "brand": job_brand.get(j["id"])} for j in jobs[:10]]},
        "productions": {"by_state": by_state, "recent": recent},
        "attention": att, "brands": brands,
        "storage": {"free_gb": round(free_gb(), 1), "output_mb": round(_dir_mb(OUTPUT_DIR) - _dir_mb(OUTPUT_DIR / "_archive"), 1),
                    "archive_mb": _dir_mb(OUTPUT_DIR / "_archive"), "video_out_mb": _dir_mb(ROOT / "video-out"),
                    "models_mb": _dir_mb(ROOT / "models"),
                    "cache_mb": _dir_mb(ROOT / ".pipeline/cache")},
        "memory": {"available_mb": round(m.available_mb), "swap_used_mb": round(m.swap_used_mb)},
        "render_defaults": bench, "scheduler": queue(reg),
    }


# ---- productions -----------------------------------------------------------------------------------
def create_production(brand: str, brief: dict, name: str | None = None) -> dict:
    from .brands import list_brands
    if brand not in list_brands():
        raise NotFound(f"unknown brand {brand!r}")
    from .intelligence.brief import parse_brief
    parse_brief(brief)          # reject an invalid brief now, not after a production directory exists (raises ConfigError)
    prod = Productions(_reg())
    p = prod.create(brand, name or brief.get("product", "production"), brief)
    atomic_write_json(Path(p["dir"]) / "brief.json", brief)
    return p


def production(pid: str) -> dict:
    reg = _reg()
    prod = Productions(reg)
    p = prod.get(pid)
    d = Path(p["dir"])
    out = {**p, "flags": prod.flags(pid), "files": {}}
    for name in ("brief.json", "storyboard.json", "project.json", "concepts/concepts.json", "concepts/comparison.md",
                 "approval/approval-manifest.json", "approval/APPROVAL_PACKAGE.md", "preview/contact-sheet.jpg"):
        if (d / name).exists():
            out["files"][name] = rel(d / name)
    if p["job_id"]:
        j = reg.get(p["job_id"])
        j.pop("config", None)
        out["job"] = {**j, "stages": reg.stages(p["job_id"]), "events": reg.events(p["job_id"], 30)}
    with reg.conn() as c:
        out["approvals"] = [dict(r) for r in c.execute("SELECT * FROM approvals WHERE production_id=? ORDER BY id", (pid,))]
        out["publications"] = [dict(r) for r in c.execute("SELECT * FROM publications WHERE production_id=? ORDER BY id", (pid,))]
    a = prod.current_approval(pid) if p["job_id"] and p["state"] in ("APPROVED", "PUBLISHING", "PUBLISHED") else None
    out["approval_valid"] = bool(a and a["valid"])
    gf = d / "preview/gate.json"
    if gf.exists():
        try:
            g = json.loads(gf.read_text())
            out["gate"] = {"status": g.get("status"), "checks": g.get("checks", []),
                           "current": g.get("storyboard_hash") == storyboard_hash(p) if (d / "storyboard.json").exists() else False}
        except (ValueError, OSError):
            out["gate"] = None
    out["preview_approved"] = _preview_approved(reg, p)
    return out


def generate_concepts(pid: str) -> dict:
    """Creative engine: 3 distinct concepts for the production's brief (local LLM, see pipeline/intelligence)."""
    from . import intelligence_bridge as ib
    prod = Productions(_reg())
    p = prod.get(pid)
    res = ib.concepts(p["brief"], Path(p["dir"]) / "concepts", brand=p["brand"],
                      provider=p["brief"].get("provider", "ollama"))
    prod.update(pid, concepts_path=rel(Path(p["dir"]) / "concepts/concepts.json"))
    return res


def select_concept(pid: str, concept_id: str) -> dict:
    from . import intelligence_bridge as ib
    prod = Productions(_reg())
    p = prod.get(pid)
    sb, project, reports = ib.storyboard(p["brief"], Path(p["dir"]), concept_id, brand=p["brand"],
                                         provider=p["brief"].get("provider", "ollama"))
    res = save_storyboard(pid, sb, project=project)
    # generated copy: fix text overflow before any voice/render is spent (recorded for the reviewer)
    from .layout_fit import fit_storyboard
    cfg, _ = load_project(prod.get(pid)["project_path"])
    fitted, fixes, unresolved = fit_storyboard(cfg)
    atomic_write_json(Path(p["dir"]) / "concepts" / "layout-fit.json", {"fixes": fixes, "unresolved": unresolved})
    if fixes:
        save_storyboard(pid, fitted)
    reports["layout_fit"] = {"fixes": fixes, "unresolved": unresolved}
    prod.update(pid, concept_id=concept_id)
    return {"storyboard": sb, "reports": reports}


def save_storyboard(pid: str, storyboard: dict, project: dict | None = None) -> dict:
    """Validate, then store the storyboard (manual edits from the Studio go through here too)."""
    prod = Productions(_reg())
    p = prod.get(pid)
    if p["state"] not in ("DRAFT", "STORYBOARD_READY", "PREVIEW_READY", "CHANGES_REQUESTED", "FAILED"):
        raise PipelineError(f"storyboard is locked while the production is {p['state']}")
    errs, warns = validate_storyboard(storyboard)
    if errs:
        raise PipelineError("storyboard is invalid", detail="\n".join(errs))
    d = Path(p["dir"])
    if (d / "storyboard.json").exists():                  # keep every previous version
        hist = d / "storyboard.history"
        hist.mkdir(exist_ok=True)
        shutil.copy2(d / "storyboard.json", hist / f"storyboard-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.json")
    atomic_write_json(d / "storyboard.json", storyboard)
    if project is None and (d / "project.json").exists():
        project = json.loads((d / "project.json").read_text())
    project = project or default_project(p)
    project["storyboard"] = rel(d / "storyboard.json")
    atomic_write_json(d / "project.json", project)
    cfg, cwarn = load_project(rel(d / "project.json"))       # full validation incl. brand isolation
    try:                                                         # report (never auto-change) manual overflows
        from .layout_fit import _overflows
        cwarn += [f"layout: {o['scene']}/{o['type']} {o['text'][:40]!r} needs {o['estWidth']}px of {o['maxWidth']}px"
                  for o in _overflows(cfg)]
    except Exception as e:  # noqa: BLE001
        cwarn.append(f"layout check unavailable: {e}")
    prod.update(pid, storyboard_path=rel(d / "storyboard.json"), project_path=rel(d / "project.json"))
    if p["state"] != "STORYBOARD_READY":
        prod.transition(pid, "STORYBOARD_READY", note="storyboard saved")
    return {"warnings": warns + cwarn, "hash": config_hash(cfg)}


def default_project(p: dict) -> dict:
    fmt = p["brief"].get("format", "short")
    return {"name": f"{p['brand']}-{p['id']}".lower(), "brand": p["brand"], "preset": FORMAT_PRESET.get(fmt, "shorts"),
            "formats": [fmt], "storyboard": "", "audio": {"music": f"mood:{p['brief'].get('musicMood', 'corporate')}"}}


def preview(pid: str) -> dict:
    """Low-cost preview: one still per scene (no TTS, no full render) at the scene's estimated midpoint."""
    from .preview import storyboard_stills
    prod = Productions(_reg())
    p = prod.get(pid)
    res = storyboard_stills(Path(p["dir"]))
    from .preview_gate import evaluate
    cfg, _ = load_project(p["project_path"])
    res["gate"] = evaluate(Path(p["dir"]), cfg)
    if p["state"] == "STORYBOARD_READY":
        prod.transition(pid, "PREVIEW_READY")
    return res


def storyboard_hash(p: dict) -> str:
    from .preview_gate import saved_storyboard_hash
    return saved_storyboard_hash(Path(p["dir"]))


def approve_preview(pid: str, reviewer: str, note: str = "") -> dict:
    """A named person reviewed the preview contact sheet for THIS storyboard and allows the full render."""
    reg = _reg()
    prod = Productions(reg)
    p = prod.get(pid)
    if not reviewer.strip():
        raise PipelineError("preview approval needs a reviewer name")
    gate_f = Path(p["dir"]) / "preview/gate.json"
    if not gate_f.exists():
        raise PipelineError("no preview yet: run `production preview` first")
    gate = json.loads(gate_f.read_text())
    h = storyboard_hash(p)
    if gate["storyboard_hash"] != h:
        raise PipelineError("the storyboard changed after the preview; re-run the preview before approving it")
    if gate["status"] == "FAIL":
        raise PipelineError("the preview quality gate FAILED; fix the storyboard first",
                            detail="\n".join(f"{c['id']}: {c['detail']}" for c in gate["checks"] if c["status"] == "FAIL"))
    with reg.conn() as c:
        c.execute("INSERT INTO approvals (production_id,package_hash,decision,reviewer,note,created_at) VALUES (?,?,?,?,?,?)",
                  (pid, h, "PREVIEW_APPROVED", reviewer, note, time.time()))
    reg.audit(reviewer, "preview.approve", pid, {"storyboard_hash": h, "gate": gate["status"]})
    return {"storyboard_hash": h, "gate": gate["status"]}


def _preview_approved(reg, p: dict) -> bool:
    d = Path(p["dir"])
    if not (d / "storyboard.json").exists() or not (d / "project.json").exists():
        return False
    h = storyboard_hash(p)
    with reg.conn() as c:
        return bool(c.execute("SELECT 1 FROM approvals WHERE production_id=? AND decision='PREVIEW_APPROVED' AND package_hash=?",
                              (p["id"], h)).fetchone())


def start_render(pid: str, *, wait: bool = False, skip_preview_review: str | None = None, actor: str = "operator") -> dict:
    reg = _reg()
    prod = Productions(reg)
    p = prod.get(pid)
    if p["state"] not in ("STORYBOARD_READY", "PREVIEW_READY", "FAILED"):
        raise PipelineError(f"cannot render a production in state {p['state']}")
    if not _preview_approved(reg, p):
        if not skip_preview_review:
            raise PipelineError("the storyboard preview has not been approved by a person for this storyboard",
                                detail="run `production preview`, look at preview/contact-sheet.jpg and preview/GATE.md, then "
                                       "`production approve-preview --id ... --reviewer \"Name\"`")
        reg.audit(actor, "preview.review_skipped", pid, {"reason": skip_preview_review, "storyboard_hash": storyboard_hash(p)})
        from .productions import BLOCKING
        prod.flag(pid, "human:preview-not-reviewed", f"Full render started without a human storyboard-preview review "
                  f"(reason: {skip_preview_review}). Review preview/contact-sheet.jpg and the final video.", BLOCKING, "policy")
    cfg, _ = load_project(p["project_path"])
    job = reg.create(cfg["name"], config_hash(cfg), cfg, p["project_path"], OUTPUT_DIR, force=True)
    prod.update(pid, job_id=job["id"])
    prod.transition(pid, "RENDERING", note=job["id"])
    args = [sys.executable, "-m", "pipeline.cli", "--quiet", "production", "run-job", "--id", pid]
    if wait:
        r = subprocess.run(args, cwd=ROOT)
        return {"job_id": job["id"], "returncode": r.returncode}
    log = open(Path(p["dir"]) / "render.log", "ab")
    subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return {"job_id": job["id"], "started": True}


def run_production_job(pid: str) -> dict:
    """Runs in the background process started by start_render: job -> QA -> approval package."""
    from .runner import JobRunner
    reg = _reg()
    prod = Productions(reg)
    p = prod.get(pid)
    try:
        JobRunner(reg, p["job_id"], echo=lambda m: None).run()
    except Exception as e:  # noqa: BLE001 - the job record has the details
        prod.transition(pid, "FAILED", note=str(e)[:300])
        raise
    job = reg.get(p["job_id"])
    out = Path(job["output_dir"])
    for name in ("claims-report.json", "review.json", "creative-plan.json", "layout-fit.json"):   # creative reports join the package
        src = Path(p["dir"]) / "concepts" / name
        if src.exists():
            shutil.copy2(src, out / "reports" / name)
    prod.transition(pid, "QA_COMPLETE", note=f"QA {job['qa_status']}")
    flags_from_job(prod, pid, out)
    return prod.build_package(pid)


def assets(brand: str | None = None) -> dict:
    from .assets import AssetRegistry
    from .brands import load_profile, list_brands
    from .music import tracks
    reg = _reg()
    AssetRegistry(reg)
    with reg.conn() as c:
        rows = [dict(r) for r in c.execute("SELECT sha256,path,type,bytes,source,license,attribution,refs_json "
                                           "FROM assets ORDER BY path").fetchall()]
    if brand:
        roots = tuple(r.replace("public/", "", 1) for r in load_profile(brand)["assetRoots"])
        rows = [r for r in rows if not r["path"].startswith("public/brands/") or
                r["path"].replace("public/", "", 1).startswith(roots)]
    from .brands import visible_brands
    return {"brands": visible_brands(), "assets": rows, "music": tracks()}


def job_monitor(job_id: str) -> dict:
    reg = _reg()
    j = reg.get(job_id)
    j.pop("config", None)
    out = Path(j["output_dir"])
    rr = out / "reports/render-report.json"
    from .scheduler import queue
    from .system import mem_snapshot
    m = mem_snapshot()
    log_tail = []
    lf = out / "logs/pipeline.jsonl"
    if lf.exists():
        log_tail = [json.loads(l) for l in lf.read_text().splitlines()[-40:]]
    chunks = sorted(p.name for p in (out / "work/chunks").glob("*.mp4")) if (out / "work/chunks").exists() else []
    return {**j, "stages": reg.stages(job_id), "events": reg.events(job_id, 50), "log": log_tail,
            "render_report": json.loads(rr.read_text()) if rr.exists() else None, "chunks_on_disk": chunks,
            "memory": {"available_mb": round(m.available_mb), "swap_used_mb": round(m.swap_used_mb)},
            "scheduler": queue(reg)}


AUDIO_ROOTS = ("audio/kit", "audio/music")
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def safe_output_file(path: str) -> Path:
    """Studio file serving: files under output/ or public/, plus *audio* files from the licensed sound kit
    and music library (for previews). Never source, secrets or state."""
    p = safe_path(path, must_exist=True)
    in_out = str(p).startswith(str(OUTPUT_DIR) + os.sep) or str(p).startswith(str(ROOT / "public") + os.sep)
    in_audio = p.suffix.lower() in AUDIO_EXT and any(str(p).startswith(str(ROOT / r) + os.sep) for r in AUDIO_ROOTS)
    if not (in_out or in_audio):
        raise PipelineError("file is outside output/, public/ and the audio libraries")
    if ".pipeline" in p.parts or "secrets" in p.parts:
        raise PipelineError("refused")
    return p
