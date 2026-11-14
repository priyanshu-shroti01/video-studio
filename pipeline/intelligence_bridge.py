"""Adapter between the service layer (pipeline/api.py) and the creative engines:

  engine "llm"     pipeline/intelligence: the local LLM designs the storyboard block by block (v0.3.0)
  engine "hybrid"  pipeline/creative: deterministic scene templates own composition, animation and labels;
                   the local LLM only proposes hooks and drafts copy inside validated slots (docs/CREATIVE_SYSTEM.md)

The engine is chosen per brief (`"engine": "llm"` to opt out). Default "hybrid" since 2026-11-13: the reviewer
chose the hybrid production (B3) after the same-brief comparison (docs/reports/CREATIVE_COMPARISON.md).
Kept thin so the creative engine can evolve without touching the workflow/approval code.
LLM work runs under the cross-process scheduler (priority "llm") so it never overlaps a render, and the
local runtime is asked to unload its model afterwards. The runtime itself is managed automatically
(`providers.ManagedRuntime`): started for the work if it isn't running, stopped again only if this call started
it. Missing Ollama/model is not an error: the engine falls back, and the concepts report says so plainly."""
from __future__ import annotations

import json
from pathlib import Path

from .errors import NotFound
from .intelligence.providers import ManagedRuntime
from .jobs import Registry
from .paths import atomic_write_json
from .scheduler import HeavyWork


PIPELINE_KEYS = ("provider", "request", "engine")   # workflow options, not part of the creative brief schema
ENGINES = ("llm", "hybrid")
DEFAULT_ENGINE = "hybrid"


def _brief(brief: dict, brand: str | None = None) -> dict:
    b = {k: v for k, v in brief.items() if k not in PIPELINE_KEYS}
    if brand:
        b["brand_id"] = brand                           # the production's brand, not a guess from the display name
    return b


def _engine(brief: dict):
    name = brief.get("engine", DEFAULT_ENGINE)
    if name not in ENGINES:
        raise NotFound(f"unknown creative engine {name!r}; use one of {ENGINES}")
    if name == "hybrid":
        from . import creative as eng
    else:
        from .intelligence import api as eng
    return name, eng


def concepts(brief: dict, out_dir: Path, brand: str, provider: str = "ollama") -> dict:
    _, intel = _engine(brief)
    out_dir.mkdir(parents=True, exist_ok=True)
    with HeavyWork(Registry(), "llm", ref=f"concepts:{out_dir.parent.name}"), ManagedRuntime(provider) as rt:
        res = intel.generate_concepts(_brief(brief, brand), brief.get("request"), provider=provider, out_dir=out_dir)
    _record_runtime(res, rt, out_dir)
    if any(c.get("components") for c in res.get("concepts", [])):       # "components": "generate"
        from .creative.components import save_generated
        res["component_files"] = save_generated(out_dir.parent, brand, res["concepts"])
    return res


def _runtime_record(rt: dict) -> dict:
    return {k: rt[k] for k in ("started", "stopped", "ready", "warning", "reason")}


def _record_runtime(res: dict, rt: dict, out_dir: Path) -> None:
    """Put the runtime outcome in the concepts result, concepts.json and (if there is a warning) concepts.md."""
    if not rt.get("managed"):
        return
    res["llm_runtime"] = _runtime_record(rt)
    if rt.get("warning"):
        res.setdefault("warnings", []).append(rt["warning"])
    cj = out_dir / "concepts.json"
    if cj.exists():
        doc = json.loads(cj.read_text(encoding="utf-8"))
        doc["llm_runtime"] = res["llm_runtime"]
        if rt.get("warning"):
            doc["warnings"] = [*doc.get("warnings", []), rt["warning"]]
        atomic_write_json(cj, doc)
    md = out_dir / "concepts.md"
    if rt.get("warning") and md.exists():
        lines = md.read_text(encoding="utf-8").split("\n")
        at = 1 if lines and lines[0].startswith("#") else 0
        lines[at:at] = ["", f"> **Note:** {rt['warning']}"]
        md.write_text("\n".join(lines), encoding="utf-8")


def claims_report(reports: dict) -> dict:
    """Normalise the engine's claim check into the shape productions.flags_from_job consumes."""
    out = []
    for c in reports.get("claims", {}).get("verified", []) or []:
        out.append({**c, "status": "VERIFIED"})
    for c in reports.get("claims", {}).get("needs_review", []) or []:
        out.append({**c, "status": c.get("status", "NEEDS_REVIEW")})
    for c in reports.get("brief_claims", {}).get("needs_review", []) or []:
        if not any(x["text"] == c["text"] for x in out):
            out.append({**c, "status": "NEEDS_REVIEW"})
    rv = reports.get("review", {})
    return {"status": rv.get("status"), "blocking": rv.get("blocking"), "reasons": rv.get("reasons", []),
            "produced_by": rv.get("produced_by"), "claims": out}


def storyboard(brief: dict, prod_dir: Path, concept_id: str, brand: str,
               provider: str = "ollama") -> tuple[dict, dict, dict]:
    engine, intel = _engine(brief)
    cdir = prod_dir / "concepts"
    doc = json.loads((cdir / "concepts.json").read_text())
    concept = next((c for c in doc["concepts"] if c.get("id") == concept_id), None)
    if concept is None:
        raise NotFound(f"no concept {concept_id!r}; available: {[c.get('id') for c in doc['concepts']]}")
    with HeavyWork(Registry(), "llm", ref=f"storyboard:{prod_dir.name}"), ManagedRuntime(provider) as rt:
        sb, project, reports = intel.build_storyboard(_brief(brief, brand), concept, request=brief.get("request"),
                                                      provider=provider, out_dir=cdir)
    if rt.get("managed"):
        reports["llm_runtime"] = _runtime_record(rt)
        if rt.get("warning"):
            reports.setdefault("warnings", []).append(rt["warning"])
            atomic_write_json(cdir / "llm-runtime.json", reports["llm_runtime"])
    mood = (reports.get("creative_plan", {}).get("music") or {}).get("mood")
    if mood:
        project.setdefault("audio", {})["music"] = f"mood:{mood}"
    project.pop("$comment", None)
    cr = claims_report(reports)
    atomic_write_json(cdir / "claims-report.json", cr)
    atomic_write_json(cdir / "review.json", reports.get("review", {}))
    atomic_write_json(cdir / "creative-plan.json", {**reports.get("creative_plan", {}), "engine": engine})
    for k in ("rules", "sync", "copy_sources"):
        if k in reports:
            atomic_write_json(cdir / f"{k.replace('_', '-')}.json", reports[k])
    if concept.get("components"):
        from .creative.components import save_selected
        save_selected(prod_dir, concept)
    return sb, project, reports
