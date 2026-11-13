"""Plain functions for the main CLI and a GUI.

    generate_concepts(brief, request=None, provider="ollama", out_dir=None) -> dict
    build_storyboard(brief, concept, provider="ollama", out_dir=None) -> (storyboard, project_config, reports)

`provider` may be "ollama", "mock", None (deterministic planner only) or a Provider instance. Output files are
written only when `out_dir` is given (it is created; nothing outside it is touched)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..errors import ConfigError
from ..paths import ROOT
from .brief import parse_brief
from .claims import verify_brief
from .concepts import comparison_markdown, generate_concepts as _gen_concepts
from .facts import FactBase, empty_facts, load_facts
from .preview import creative_plan, preview_markdown
from .providers import Provider, get_provider
from .storyboard_gen import build_storyboard as _build


def _provider(p) -> Provider | None:
    if p is None or isinstance(p, Provider):
        return p
    return get_provider(p)


def _brief(brief, request=None) -> tuple[dict, list[str]]:
    if isinstance(brief, dict) and "price_parsed" in brief and "brand_id" in brief:
        return brief, []
    return parse_brief(brief, request)


def _facts(brief: dict, facts: FactBase | str | Path | None) -> FactBase:
    if isinstance(facts, FactBase):
        return facts
    try:
        return load_facts(brief["brand_id"], facts)
    except ConfigError:
        return empty_facts(brief["brand_id"], brief["brand"])


def _write(out: Path, name: str, obj) -> str:
    out.mkdir(parents=True, exist_ok=True)
    p = out / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return str(p)


def generate_concepts(brief: dict, request: str | None = None, *, provider="ollama", out_dir: str | Path | None = None,
                      facts: FactBase | str | Path | None = None, n: int = 3) -> dict:
    t0 = time.time()
    b, warnings = _brief(brief, request)
    fb = _facts(b, facts)
    prov = _provider(provider)
    res = _gen_concepts(b, fb, prov, n=n)
    res["brief"] = b
    res["brief_warnings"] = warnings
    res["brief_claims"] = verify_brief(b, fb)
    res["provider"] = prov.info() if prov else {"provider": "none"}
    res["elapsed_s"] = round(time.time() - t0, 2)
    if out_dir:
        out = Path(out_dir)
        res["files"] = {"concepts.json": _write(out, "concepts.json", res),
                        "concepts.md": _write(out, "concepts.md", comparison_markdown(b, res) + _brief_flags_md(res["brief_claims"]))}
    return res


def _brief_flags_md(bc: dict) -> str:
    if not bc["needs_review"]:
        return ""
    return "\n## Brief claims needing owner review\n" + "\n".join(f"- **{c['text']}** — {c.get('reason', '')}" for c in bc["needs_review"]) + "\n"


def _theme_preset(brief: dict) -> tuple[dict | None, dict | None, str]:
    preset_name = "shorts" if brief.get("format") == "short" else "landscape"
    th = pr = None
    try:
        th = json.loads((ROOT / "brands" / brief["brand_id"] / "theme.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        pr = json.loads((ROOT / "presets" / f"{preset_name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return th, pr, preset_name


def build_storyboard(brief: dict, concept: dict, *, request: str | None = None, provider="ollama",
                     out_dir: str | Path | None = None, facts: FactBase | str | Path | None = None,
                     name: str | None = None, max_repairs: int = 2) -> tuple[dict, dict, dict]:
    """-> (storyboard, project_config, reports). reports["review"]["blocking"] is True when any claim needs review."""
    t0 = time.time()
    b, warnings = _brief(brief, request)
    fb = _facts(b, facts)
    prov = _provider(provider)
    r = _build(b, concept, fb, prov, max_repairs=max_repairs)
    sb, chk = r["storyboard"], r["check"]
    theme, preset, preset_name = _theme_preset(b)
    plan = creative_plan(b, concept, sb, r["publishing"], theme, preset, fb)
    brief_claims = verify_brief(b, fb)
    nr = chk["claims"]["needs_review"] + [c for c in brief_claims["needs_review"]
                                         if not any(x["text"] == c["text"] for x in chk["claims"]["needs_review"])]
    reasons = []
    if not fb.facts:
        reasons.append(f"no verified fact base for brand {b['brand_id']!r}: every claim is unverified")
    groups: dict[tuple, list[dict]] = {}
    for c in nr:
        groups.setdefault((c["origin"], c.get("reason", "unverified")), []).append(c)
    for (origin, why), cs in groups.items():
        texts = sorted({c["text"] for c in cs})
        reasons.append(f"{' / '.join(repr(t) for t in texts)} ({origin}, {len(cs)} place{'s' if len(cs) > 1 else ''}): {why}")
    if chk["errors"]:
        reasons.append(f"storyboard has {len(chk['errors'])} validation errors")
    review = {"status": "BLOCKED" if nr or chk["errors"] or not fb.facts else "READY_FOR_HUMAN_REVIEW",
              "blocking": bool(nr or chk["errors"] or not fb.facts), "reasons": reasons, "needs_review": nr,
              "facts_file": str(fb.path) if fb.path else None, "facts_fetched_at": fb.fetched_at,
              "known_mismatches": [m for m in fb.not_found if b.get("price") and str(b["price_parsed"]["amount"]) in m["claim"]],
              "produced_by": r["path"], "note": "The video may be rendered for review, but must not be published while blocking is true."}
    pname = name or f"{b['brand_id']}-" + re.sub(r"[^a-z0-9]+", "-", concept.get("name", "concept").lower()).strip("-")[:40]
    pname = re.sub(r"[^A-Za-z0-9._-]", "-", pname)[:100]
    project = {"$comment": f"generated by pipeline.intelligence ({r['path']}); review status: {review['status']}",
               "name": pname, "preset": preset_name, "formats": [b.get("format", "short")], "brand": b["brand_id"],
               "storyboard": sb, "audio": {"music": None}, "publishing": plan["publishing"]}
    if b.get("voice") and re.match(r"^[A-Za-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z]+Neural$", b["voice"]):
        project["voice"] = {"voice": b["voice"]}
    reports = {"path": r["path"], "check": {k: v for k, v in chk.items() if k != "claims"}, "claims": chk["claims"],
               "brief_claims": brief_claims, "review": review, "creative_plan": plan, "fixes": r["fixes"], "log": r["log"],
               "brief": b, "brief_warnings": warnings, "concept": concept, "provider": prov.info() if prov else {"provider": "none"},
               "elapsed_s": round(time.time() - t0, 2)}
    if out_dir:
        out = Path(out_dir)
        sb_path = out / f"{pname}.storyboard.json"
        files = {"storyboard": _write(out, sb_path.name, sb)}
        try:
            project["storyboard"] = str(sb_path.resolve().relative_to(ROOT))
        except ValueError:
            pass  # outside the workspace: keep it inline
        files["project"] = _write(out, f"{pname}.json", project)
        files["claims"] = _write(out, "claims.json", {"storyboard": chk["claims"], "brief": brief_claims})
        files["review"] = _write(out, "review.json", review)
        files["creative_plan"] = _write(out, "creative-plan.json", plan)
        files["preview"] = _write(out, "storyboard-preview.md", preview_markdown(b, concept, sb, chk, plan, r["path"], review))
        files["log"] = _write(out, "generation-log.json", {k: reports[k] for k in ("path", "check", "fixes", "log", "provider", "elapsed_s")})
        reports["files"] = files
    return sb, project, reports
