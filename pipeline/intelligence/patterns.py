"""Narrative pattern library. Each pattern is a beat sequence; every beat maps onto a storyboard scene
`purpose` (pipeline.storyboard.PURPOSES), suggests block types for the engine's 14 blocks, and says which
brief requirements it can satisfy (problem / demonstration / pricing-comparison / cta ...)."""
from __future__ import annotations

MUSIC_MOODS = ["cinematic", "corporate", "technology", "energetic", "minimal", "educational", "calm", "promotional"]
ANIMATION_STYLES = ["kinetic-type", "ui-walkthrough", "data-viz", "stamp-and-strike", "minimal-reveal"]
CTA_STYLES = ["url-click", "logo-lockup", "offer-stamp", "callback-question", "button-press"]
HOOK_STYLES = ["question", "bold-claim", "myth", "pain-point", "before-after", "promise", "contrast"]
BLOCK_TYPES = ["headline", "text", "pill", "price", "checklist", "bars", "compare-rows", "plans", "domain-input",
               "browser", "hook-tag", "flat-line", "logo", "cta"]

PATTERNS: dict[str, dict] = {
    "hook-problem-solution-demo-cta": {
        "name": "Hook → Problem → Solution → Demonstration → CTA",
        "best_for": ["conversions", "launch"],
        "hook_styles": ["question", "pain-point"],
        "beats": [
            {"beat": "hook", "purpose": "hook", "role": "stop the scroll with the viewer's own situation",
             "blocks": ["headline", "pill"], "satisfies": []},
            {"beat": "problem", "purpose": "problem", "role": "make the pain concrete", "mood": "danger",
             "blocks": ["browser", "hook-tag", "compare-rows", "text"], "satisfies": ["problem"]},
            {"beat": "solution", "purpose": "turn", "role": "introduce the brand as the answer", "mood": "brand",
             "blocks": ["logo", "pill"], "satisfies": []},
            {"beat": "demonstration", "purpose": "journey", "role": "show the product doing the job",
             "blocks": ["domain-input", "checklist", "browser"], "satisfies": ["demonstration"]},
            {"beat": "pricing", "purpose": "resolution", "role": "price + renewal promise",
             "blocks": ["price", "compare-rows", "plans"], "satisfies": ["pricing", "pricing-comparison"]},
            {"beat": "cta", "purpose": "cta", "role": "one clear action", "mood": "brand",
             "blocks": ["logo", "cta"], "satisfies": ["cta"]},
        ],
    },
    "myth-reality-explanation": {
        "name": "Myth → Reality → Explanation",
        "best_for": ["education", "awareness", "conversions"],
        "hook_styles": ["myth", "contrast"],
        "beats": [
            {"beat": "myth", "purpose": "hook", "role": "state a belief the audience holds",
             "blocks": ["hook-tag", "headline"], "satisfies": []},
            {"beat": "reality", "purpose": "problem", "role": "break the myth with the real cost", "mood": "danger",
             "blocks": ["headline", "compare-rows", "text"], "satisfies": ["problem"]},
            {"beat": "explanation", "purpose": "point", "role": "explain what actually matters",
             "blocks": ["checklist", "pill", "text"], "satisfies": ["demonstration"]},
            {"beat": "proof", "purpose": "resolution", "role": "show it with numbers",
             "blocks": ["plans", "price", "flat-line"], "satisfies": ["pricing", "pricing-comparison"]},
            {"beat": "cta", "purpose": "cta", "role": "invite the switch", "mood": "brand",
             "blocks": ["logo", "cta"], "satisfies": ["cta"]},
        ],
    },
    "before-after": {
        "name": "Before → After",
        "best_for": ["conversions", "awareness"],
        "hook_styles": ["before-after", "contrast"],
        "beats": [
            {"beat": "before", "purpose": "hook", "role": "the messy 'before' state", "mood": "danger",
             "blocks": ["browser", "headline"], "satisfies": ["problem"]},
            {"beat": "before-cost", "purpose": "problem", "role": "what the 'before' costs you", "mood": "danger",
             "blocks": ["hook-tag", "compare-rows", "text"], "satisfies": ["problem"]},
            {"beat": "switch", "purpose": "turn", "role": "the switch moment", "mood": "brand",
             "blocks": ["logo", "pill"], "satisfies": []},
            {"beat": "after", "purpose": "journey", "role": "the clean 'after' state, shown working",
             "blocks": ["domain-input", "checklist"], "satisfies": ["demonstration"]},
            {"beat": "after-price", "purpose": "resolution", "role": "side-by-side price, before vs after",
             "blocks": ["compare-rows", "price", "flat-line"], "satisfies": ["pricing", "pricing-comparison"]},
            {"beat": "cta", "purpose": "cta", "role": "make the switch", "mood": "brand",
             "blocks": ["logo", "cta"], "satisfies": ["cta"]},
        ],
    },
    "feature-benefit-proof": {
        "name": "Feature → Benefit → Proof",
        "best_for": ["conversions", "education"],
        "hook_styles": ["bold-claim", "promise"],
        "beats": [
            {"beat": "hook", "purpose": "hook", "role": "a bold, verifiable promise", "blocks": ["headline", "pill"], "satisfies": []},
            {"beat": "feature", "purpose": "point", "role": "the feature, named plainly", "blocks": ["pill", "checklist"],
             "satisfies": ["demonstration"]},
            {"beat": "benefit", "purpose": "example", "role": "what it means for the viewer", "blocks": ["browser", "text", "checklist"],
             "satisfies": ["demonstration", "problem"]},
            {"beat": "proof", "purpose": "resolution", "role": "proof with real, sourced numbers",
             "blocks": ["plans", "compare-rows", "price"], "satisfies": ["pricing", "pricing-comparison"]},
            {"beat": "cta", "purpose": "cta", "role": "act now", "mood": "brand", "blocks": ["logo", "cta"], "satisfies": ["cta"]},
        ],
    },
    "problem-discovery-transformation": {
        "name": "Problem → Discovery → Transformation",
        "best_for": ["awareness", "conversions"],
        "hook_styles": ["pain-point", "question"],
        "beats": [
            {"beat": "problem", "purpose": "hook", "role": "open on the problem itself", "mood": "danger",
             "blocks": ["headline", "browser"], "satisfies": ["problem"]},
            {"beat": "struggle", "purpose": "problem", "role": "the struggle escalates", "mood": "danger",
             "blocks": ["compare-rows", "hook-tag"], "satisfies": ["problem"]},
            {"beat": "discovery", "purpose": "turn", "role": "discovering the brand", "mood": "brand",
             "blocks": ["logo", "pill"], "satisfies": []},
            {"beat": "transformation", "purpose": "journey", "role": "life after: shown working",
             "blocks": ["domain-input", "checklist", "plans"], "satisfies": ["demonstration"]},
            {"beat": "result", "purpose": "resolution", "role": "the lasting result (price that stays)",
             "blocks": ["flat-line", "price", "compare-rows"], "satisfies": ["pricing", "pricing-comparison"]},
            {"beat": "cta", "purpose": "cta", "role": "start your own transformation", "mood": "brand",
             "blocks": ["logo", "cta"], "satisfies": ["cta"]},
        ],
    },
    "tutorial-demo-result": {
        "name": "Tutorial → Demonstration → Result",
        "best_for": ["education", "conversions"],
        "hook_styles": ["promise", "question"],
        "beats": [
            {"beat": "promise", "purpose": "hook", "role": "promise a result in N steps", "blocks": ["headline", "pill"], "satisfies": []},
            {"beat": "step-1", "purpose": "journey", "role": "step one, on screen", "blocks": ["plans", "text"],
             "satisfies": ["demonstration", "pricing"]},
            {"beat": "step-2", "purpose": "journey", "role": "step two, on screen", "blocks": ["domain-input"], "satisfies": ["demonstration"]},
            {"beat": "step-3", "purpose": "example", "role": "step three: it's live", "blocks": ["checklist", "browser"],
             "satisfies": ["demonstration"]},
            {"beat": "result", "purpose": "resolution", "role": "the result and what it costs", "blocks": ["price", "compare-rows"],
             "satisfies": ["pricing", "pricing-comparison"]},
            {"beat": "cta", "purpose": "cta", "role": "your turn", "mood": "brand", "blocks": ["logo", "cta"], "satisfies": ["cta"]},
        ],
    },
}


def structure_for(pattern_id: str) -> list[str]:
    """Ordered unique purposes (used as the storyboard's `structure`)."""
    out: list[str] = []
    for b in PATTERNS[pattern_id]["beats"]:
        if b["purpose"] not in out:
            out.append(b["purpose"])
    return out


def coverage(pattern_id: str, requirements: list[str]) -> tuple[list[str], list[str]]:
    sat = {s for b in PATTERNS[pattern_id]["beats"] for s in b["satisfies"]}
    have = [r for r in requirements if r in sat or (r == "pricing" and "pricing-comparison" in sat)]
    return have, [r for r in requirements if r not in have]


def rank_patterns(brief: dict) -> list[str]:
    """Patterns ordered by fit to the brief (goal + requirement coverage); stable for determinism."""
    goal = (brief.get("goal") or "").lower()
    reqs = brief.get("requirements", [])

    def score(pid):
        p = PATTERNS[pid]
        have, missing = coverage(pid, reqs)
        return (len(missing) * -3) + (2 if goal in p["best_for"] else 0) + (1 if "problem" in reqs and p["beats"][1]["purpose"] == "problem" else 0)

    return sorted(PATTERNS, key=lambda pid: (-score(pid), list(PATTERNS).index(pid)))
