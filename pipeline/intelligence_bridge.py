"""Adapter between the service layer (pipeline/api.py) and the creative engines:

  engine "llm"     pipeline/intelligence: the local LLM designs the storyboard block by block (v0.3.0)
  engine "hybrid"  pipeline/creative: deterministic scene templates own composition, animation and labels;
                   the local LLM only proposes hooks and drafts copy inside validated slots (docs/CREATIVE_SYSTEM.md)

The engine is chosen per brief (`"engine": "llm"` to opt out). Default "hybrid" since 2026-11-13: the reviewer
chose the hybrid production (B3) after the same-brief comparison (docs/reports/CREATIVE_COMPARISON.md).
Kept thin so the creative engine can evolve without touching the workflow/approval code.
LLM work runs under the cross-process scheduler (priority "llm") so it never overlaps a render, and the
local runtime is asked to unload its model afterwards."""
from __future__ import annotations

import json
from pathlib import Path

from .errors import NotFound
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
    with HeavyWork(Registry(), "llm", ref=f"concepts:{out_dir.parent.name}"):
        res = intel.generate_concepts(_brief(brief, brand), brief.get("request"), provider=provider, out_dir=out_dir)
    if any(c.get("components") for c in res.get("concepts", [])):       # "components": "generate"
        from .creative.components import save_generated
        res["component_files"] = save_generated(out_dir.parent, brand, res["concepts"])
    return res


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
    with HeavyWork(Registry(), "llm", ref=f"storyboard:{prod_dir.name}"):
        sb, project, reports = intel.build_storyboard(_brief(brief, brand), concept, request=brief.get("request"),
                                                      provider=provider, out_dir=cdir)
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
