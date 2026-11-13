"""Concept generation: 3 concepts per brief that differ in hook, narrative pattern, visual approach (block
types), pacing, animation style and CTA treatment. Near-duplicates are rejected by a distinctness check and
regenerated (then replaced by a deterministic template concept)."""
from __future__ import annotations

import json
import re

from .claims import verify_concept
from .facts import FactBase
from .patterns import (ANIMATION_STYLES, BLOCK_TYPES, CTA_STYLES, HOOK_STYLES, MUSIC_MOODS, PATTERNS, coverage,
                       rank_patterns)
from .planner import STYLE, template_concept
from .providers import LLMError, Provider
from ..storyboard import PURPOSES

DUP_HOOK_SIM = 0.55       # hook similarity above this = near-duplicate
DUP_BLOCK_JACCARD = 0.8   # hero-block overlap above this = near-duplicate
MIN_DISTINCT = 0.45       # overall distinctness score below this = near-duplicate


CONCEPT_BLOCKS = [b for b in BLOCK_TYPES if b != "bars"]   # bars is never offered to the storyboard writer


def _unused(options: list[str], used: set[str]) -> list[str]:
    left = [o for o in options if o not in used]
    return left or options


def concept_schema(allowed_patterns: list[str], avoid: list[dict] | None = None) -> dict:
    """Pattern, animation, music and CTA enums exclude what earlier concepts used: the grammar guarantees they differ."""
    avoid = avoid or []
    return {
        "type": "object", "additionalProperties": False,
        "required": ["name", "pattern", "hook", "hook_style", "logline", "beats", "hero_blocks", "words_per_second",
                     "scene_count", "animation_style", "music_mood", "cta_style", "cta_text"],
        "properties": {
            "name": {"type": "string", "minLength": 3, "maxLength": 48},
            "pattern": {"type": "string", "enum": allowed_patterns},
            "hook": {"type": "string", "minLength": 8, "maxLength": 110},
            "hook_style": {"type": "string", "enum": HOOK_STYLES},
            "logline": {"type": "string", "minLength": 10, "maxLength": 220},
            "beats": {"type": "array", "minItems": 4, "maxItems": 8, "items": {
                "type": "object", "additionalProperties": False, "required": ["purpose", "idea"],
                "properties": {"purpose": {"type": "string", "enum": [p for p in PURPOSES if p != "custom"]},
                               "idea": {"type": "string", "minLength": 4, "maxLength": 160}}}},
            "hero_blocks": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "string", "enum": CONCEPT_BLOCKS}},
            "words_per_second": {"type": "number", "minimum": 2.0, "maximum": 3.2},
            "scene_count": {"type": "integer", "minimum": 4, "maximum": 9},
            "animation_style": {"type": "string", "enum": _unused(ANIMATION_STYLES, {c["animation_style"] for c in avoid})},
            "music_mood": {"type": "string", "enum": _unused(MUSIC_MOODS, {c["music_mood"] for c in avoid})},
            "cta_style": {"type": "string", "enum": _unused(CTA_STYLES, {c["cta_treatment"]["style"] for c in avoid})},
            "cta_text": {"type": "string", "minLength": 2, "maxLength": 60},
        },
    }


# ---- distinctness ----------------------------------------------------------------------------------------
_STOP = set("a an the and or to of in on for with your you is are it at this that be by from as our we my".split())


def _content_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", s.lower()) if w not in _STOP}


def _trigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", " ", s.lower())
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))}


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def hook_similarity(a: str, b: str) -> float:
    return round(max(_jac(_content_words(a), _content_words(b)), _jac(_trigrams(a), _trigrams(b))), 3)


def pair_distinctness(a: dict, b: dict) -> dict:
    hs = hook_similarity(a["hook"], b["hook"])
    bj = round(_jac(set(a["visual_approach"]["hero_blocks"]), set(b["visual_approach"]["hero_blocks"])), 3)
    pa, pb = a["pacing"], b["pacing"]
    pacing_diff = abs(pa["words_per_second"] - pb["words_per_second"]) >= 0.15 or pa["scene_count"] != pb["scene_count"]
    axes = {"pattern": a["pattern"] != b["pattern"], "animation": a["animation_style"] != b["animation_style"],
            "cta": a["cta_treatment"]["style"] != b["cta_treatment"]["style"], "music": a["music_mood"] != b["music_mood"],
            "pacing": pacing_diff, "hook_style": a["hook_style"] != b["hook_style"]}
    score = round(0.25 * axes["pattern"] + 0.25 * (1 - bj) + 0.25 * (1 - hs) +
                  0.25 * sum(axes[k] for k in ("animation", "cta", "music", "pacing")) / 4, 3)
    reasons = []
    if not axes["pattern"]:
        reasons.append("same narrative pattern")
    if hs > DUP_HOOK_SIM:
        reasons.append(f"hooks too similar ({hs})")
    if bj > DUP_BLOCK_JACCARD:
        reasons.append(f"same visual blocks (jaccard {bj})")
    if score < MIN_DISTINCT:
        reasons.append(f"distinctness {score} < {MIN_DISTINCT}")
    return {"a": a["id"], "b": b["id"], "hook_similarity": hs, "block_jaccard": bj, "axes_differ": axes, "score": score,
            "near_duplicate": bool(reasons), "reasons": reasons}


def distinctness(concepts: list[dict]) -> dict:
    pairs = [pair_distinctness(a, b) for i, a in enumerate(concepts) for b in concepts[i + 1:]]
    return {"pairs": pairs, "min_score": min((p["score"] for p in pairs), default=1.0),
            "all_distinct": not any(p["near_duplicate"] for p in pairs)}


# ---- LLM path --------------------------------------------------------------------------------------------
SYSTEM = (
    "You are a senior short-form video creative director. You write concepts for vertical product videos that a "
    "deterministic engine will animate. HARD RULES: (1) Use ONLY facts from the FACT SHEET or the BRIEF. Never invent "
    "prices, discounts, uptime, speed numbers, certifications, customer counts, reviews, awards or integrations. If a "
    "fact is not listed, do not state it. (2) No competitor names, no multipliers like '3x' or 'triple'. (3) Hooks are "
    "spoken aloud in under 3 seconds: 5-12 words, concrete, second person. (4) Reply with JSON only.")


def _concept_prompt(brief: dict, fb: FactBase, allowed: list[str], avoid: list[dict], extra: str = "") -> str:
    pats = "\n".join(f"- {pid}: {PATTERNS[pid]['name']} (beats: {', '.join(b['beat'] + '=' + b['purpose'] for b in PATTERNS[pid]['beats'])})"
                     for pid in allowed)
    av = "\n".join(f"- hook: {c['hook']!r}; pattern {c['pattern']}; blocks {c['visual_approach']['hero_blocks']}; "
                   f"animation {c['animation_style']}; music {c['music_mood']}; cta {c['cta_treatment']['style']}" for c in avoid) or "- (none yet)"
    b = {k: brief.get(k) for k in ("brand", "product", "price", "audience", "format", "duration_seconds", "goal", "cta", "tone",
                                    "requirements", "request")}
    return (f"BRIEF:\n{json.dumps(b, ensure_ascii=False)}\n\nFACT SHEET (verified on {fb.site}, {fb.fetched_at[:10]}):\n"
            f"{fb.for_prompt(brief.get('product', ''), 40)}\n\n"
            f"NOTE: the brief's price is the owner's claim; you may use it exactly as written, but never any other price.\n\n"
            f"Choose ONE narrative pattern from:\n{pats}\n\n"
            "HOOK STYLES: question = ask the viewer about THEIR situation; myth = state a belief, then break it; pain-point = "
            "name the frustration in their words; before-after = one sharp contrast; bold-claim = a promise taken from the "
            "fact sheet; promise = a result in N steps; contrast = two things side by side. The hook must be specific to "
            f"{brief.get('audience') or 'the audience'} and {brief.get('product')}; generic lines like 'You can't run a site "
            "without hosting' are weak.\n"
            f"Engine block types: {', '.join(BLOCK_TYPES)}.\n"
            f"Every concept must cover these brief requirements: {', '.join(brief.get('requirements', []))}.\n"
            f"The video is {brief.get('duration_seconds')} s (~{round(brief.get('duration_seconds', 35) * 2.4)} spoken words).\n\n"
            f"ALREADY CHOSEN CONCEPTS (yours must differ in hook wording, hook_style, hero_blocks, animation_style, "
            f"music_mood, cta_style and pacing):\n{av}\n"
            + (f"Hero blocks already used: {sorted({b for c in avoid for b in c['visual_approach']['hero_blocks']})}; pick 3-5 hero "
               "blocks with at most 2 of those.\n" if avoid else "Pick 3-5 hero blocks.\n")
            + f"{extra}\nReturn one new concept as JSON.")


def _normalize_llm_concept(d: dict, idx: int, brief: dict) -> dict:
    have, missing = coverage(d["pattern"], brief.get("requirements", []))
    return {
        "id": f"concept-{idx}", "name": d["name"].strip(), "pattern": d["pattern"], "pattern_name": PATTERNS[d["pattern"]]["name"],
        "hook": d["hook"].strip(), "hook_style": d["hook_style"], "logline": d["logline"].strip(), "beats": d["beats"],
        "visual_approach": {"hero_blocks": list(dict.fromkeys(d["hero_blocks"])),
                            "description": f"{d['animation_style']} built from {', '.join(d['hero_blocks'][:5])}"},
        "pacing": {"words_per_second": round(float(d["words_per_second"]), 2), "scene_count": int(d["scene_count"]),
                   "target_words": round(brief.get("duration_seconds", 35) * float(d["words_per_second"]) * 0.88)},
        "animation_style": d["animation_style"], "music_mood": d["music_mood"],
        "cta_treatment": {"style": d["cta_style"], "text": d["cta_text"].strip()},
        "requirements_covered": have, "requirements_missing": missing, "source": "llm",
    }


def generate_concepts(brief: dict, fb: FactBase, provider: Provider | None = None, *, n: int = 3, seed: int = 7,
                      log: list | None = None) -> dict:
    """-> {"concepts": [...], "distinctness": {...}, "path": "llm"|"template"|"mixed", "log": [...]}"""
    log = log if log is not None else []
    ranked = rank_patterns(brief)
    concepts: list[dict] = []
    llm_ok = provider is not None
    if provider is not None:
        ok, why = provider.available()
        if not ok:
            log.append({"event": "llm_unavailable", "reason": why}); llm_ok = False
    for i in range(1, n + 1):
        used = {c["pattern"] for c in concepts}
        allowed = [p for p in ranked if p not in used][:4]
        concept = None
        if llm_ok:
            extra = ""
            for attempt in range(1, 4):
                try:
                    r = provider.generate_json(system=SYSTEM, messages=[{"role": "user", "content": _concept_prompt(brief, fb, allowed, concepts, extra)}],
                                               schema=concept_schema(allowed, concepts), task="concept",
                                               context={"brief": brief, "allowed": allowed, "slot": i, "avoid": concepts},
                                               temperature=0.8 + 0.1 * (attempt - 1), seed=seed + 31 * i + attempt, max_tokens=700)
                except LLMError as e:
                    log.append({"event": "llm_error", "slot": i, "attempt": attempt, "error": e.message})
                    if e.code == "LLM_UNAVAILABLE":
                        llm_ok = False
                        break
                    continue
                entry = {"event": "concept_generated", "slot": i, "attempt": attempt, "stats": r.stats.as_dict(),
                         "schema_errors": r.schema_errors}
                log.append(entry)
                if r.schema_errors:
                    extra = "\nYOUR LAST REPLY WAS INVALID: " + "; ".join(r.schema_errors[:6])
                    continue
                cand = _normalize_llm_concept(r.data, i, brief)
                cl = verify_concept(cand, fb, brief)
                invented = [c for c in cl["needs_review"] if c["origin"] == "generated"]
                dups = [pair_distinctness(cand, c) for c in concepts]
                dups = [d for d in dups if d["near_duplicate"]]
                entry.update({"invented_claims": [c["text"] for c in invented], "near_duplicate_of": [d["b"] for d in dups],
                              "dup_reasons": [r for d in dups for r in d["reasons"]]})
                if invented:
                    extra = ("\nYOUR LAST CONCEPT STATED UNVERIFIED CLAIMS: " + ", ".join(repr(c["text"]) for c in invented) +
                             ". Remove them; use only FACT SHEET items.")
                    continue
                if dups:
                    extra = ("\nYOUR LAST CONCEPT WAS A NEAR-DUPLICATE (" + "; ".join(entry["dup_reasons"]) +
                             "). Use a completely different hook, other blocks and other styles.")
                    log.append({"event": "rejected_near_duplicate", "slot": i, "reasons": entry["dup_reasons"]})
                    continue
                cand["claims"] = cl["summary"]
                concept = cand
                break
        if concept is None:
            for pid in allowed + ranked:
                if pid in used:
                    continue
                cand = template_concept(brief, fb, pid, i)
                if not any(pair_distinctness(cand, c)["near_duplicate"] for c in concepts):
                    break
            for key, opts in (("animation_style", ANIMATION_STYLES), ("music_mood", MUSIC_MOODS)):
                used_v = {c[key] for c in concepts}
                if cand[key] in used_v:
                    cand[key] = _unused(opts, used_v)[0]
            used_cta = {c["cta_treatment"]["style"] for c in concepts}
            if cand["cta_treatment"]["style"] in used_cta:
                cand["cta_treatment"]["style"] = _unused(CTA_STYLES, used_cta)[0]
            cand["visual_approach"]["description"] = f"{cand['animation_style']} built from {', '.join(cand['visual_approach']['hero_blocks'][:5])}"
            cand["claims"] = verify_concept(cand, fb, brief)["summary"]
            concept = cand
            log.append({"event": "template_concept", "slot": i, "pattern": cand["pattern"]})
        concepts.append(concept)
    if provider is not None:
        provider.unload()
    srcs = {c["source"] for c in concepts}
    return {"concepts": concepts, "distinctness": distinctness(concepts),
            "path": srcs.pop() if len(srcs) == 1 else "mixed", "log": log}


def comparison_markdown(brief: dict, result: dict) -> str:
    cs = result["concepts"]
    lines = [f"# Concepts — {brief['brand']} · {brief['product']}", "",
             f"Brief: {brief.get('duration_seconds')} s {brief.get('format')} · audience: {brief.get('audience') or '—'} · "
             f"goal: {brief.get('goal')} · CTA: {brief.get('cta')} · requirements: {', '.join(brief.get('requirements', []))}",
             f"Generated by: **{result['path']}** (llm = local model; template = deterministic planner)", "",
             "| | " + " | ".join(f"**{c['id']}** {c['name']}" for c in cs) + " |",
             "|---|" + "---|" * len(cs)]
    rows = [("Pattern", lambda c: c["pattern_name"]), ("Hook", lambda c: f"“{c['hook']}”"), ("Hook style", lambda c: c["hook_style"]),
            ("Hero blocks", lambda c: ", ".join(c["visual_approach"]["hero_blocks"])),
            ("Pacing", lambda c: f"{c['pacing']['words_per_second']} w/s · {c['pacing']['scene_count']} scenes"),
            ("Animation", lambda c: c["animation_style"]), ("Music mood", lambda c: c["music_mood"]),
            ("CTA", lambda c: f"{c['cta_treatment']['style']}: {c['cta_treatment']['text']}"),
            ("Covers", lambda c: ", ".join(c["requirements_covered"]) + (f" (missing: {', '.join(c['requirements_missing'])})" if c["requirements_missing"] else "")),
            ("Claims", lambda c: f"{c['claims']['verified']} verified / {c['claims']['needs_review']} need review"),
            ("Source", lambda c: c["source"])]
    for name, f in rows:
        lines.append(f"| {name} | " + " | ".join(str(f(c)).replace("|", "/") for c in cs) + " |")
    d = result["distinctness"]
    lines += ["", f"## Distinctness (min score {d['min_score']}, all distinct: {d['all_distinct']})", "",
              "| pair | score | hook sim | block jaccard | near-dup |", "|---|---|---|---|---|"]
    for p in d["pairs"]:
        lines.append(f"| {p['a']} ↔ {p['b']} | {p['score']} | {p['hook_similarity']} | {p['block_jaccard']} | "
                     f"{'YES: ' + '; '.join(p['reasons']) if p['near_duplicate'] else 'no'} |")
    lines += ["", "## Beats", ""]
    for c in cs:
        lines.append(f"**{c['id']} · {c['name']}** — {c['logline']}")
        lines += [f"{k + 1}. *{b['purpose']}* — {b['idea']}" for k, b in enumerate(c["beats"])]
        lines.append("")
    return "\n".join(lines)
