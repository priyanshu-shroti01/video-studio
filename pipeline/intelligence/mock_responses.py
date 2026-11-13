"""Default answers of the mock provider: the deterministic planner's output, shaped like the LLM schemas, so
tests exercise parsing, compilation, checks and reports without a model."""
from __future__ import annotations

from .facts import load_facts
from .planner import template_concept, template_draft, template_publishing, template_scenes


def default_response(task: str, context: dict, messages: list[dict]) -> dict:
    brief = context["brief"]
    fb = context.get("facts") or load_facts(brief["brand_id"])
    if task == "concept":
        pid = context["allowed"][0]
        c = template_concept(brief, fb, pid, context.get("slot", 1))
        return {"name": c["name"], "pattern": pid, "hook": c["hook"], "hook_style": c["hook_style"], "logline": c["logline"],
                "beats": c["beats"], "hero_blocks": [b for b in c["visual_approach"]["hero_blocks"] if b != "bars"][:5],
                "words_per_second": c["pacing"]["words_per_second"], "scene_count": c["pacing"]["scene_count"],
                "animation_style": c["animation_style"], "music_mood": c["music_mood"], "cta_style": c["cta_treatment"]["style"],
                "cta_text": c["cta_treatment"]["text"]}
    if task == "storyboard":
        d = template_draft(brief, fb, context["concept"])
        d.pop("structure", None)
        return d
    if task == "scene":
        c = context["concept"]
        sc = template_scenes(brief, fb, c["pattern"], (c.get("cta_treatment") or {}).get("style"))[context["index"]]
        return {k: sc[k] for k in ("narration", "blocks", "mood") if k in sc}
    if task == "publishing":
        return template_publishing(brief, fb)
    raise ValueError(f"mock provider has no default for task {task!r}")
