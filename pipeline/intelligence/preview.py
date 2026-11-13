"""Low-cost outputs that need no rendering: creative plan (music mood, caption plan, SFX cue notes, CTA,
publishing) and storyboard-preview.md (scene table with estimated timings, narration, blocks, claim flags)."""
from __future__ import annotations

import re

from .planner import word_count
from .storyboard_gen import PAD, SCENE_GAP, WPS

SFX_NOTES = {  # mirrors pipeline.storyboard.auto_sfx conventions (theme `sfx` kinds)
    "pill": "appear pop (impact thud if stamp)", "logo": "impact thud + success ding", "price": "5 ratchet ticks while counting, pop at countEnd",
    "checklist": "pop per item", "bars": "whoosh per bar, impact on badge", "compare-rows": "glass ding per row + badge",
    "plans": "pop per card, click on select", "domain-input": "key clicks per character, ding on available, click + ding on button",
    "browser": "pop on tag", "hook-tag": "whoosh", "flat-line": "ding at drawEnd", "cta": "whoosh, shimmer on URL, click",
    "headline": "whoosh on strike-through", "text": "—",
}


def scene_timings(sb: dict, wps: float = WPS) -> list[dict]:
    t, out = PAD / 2, []
    for s in sb["scenes"]:
        d = word_count(s["narration"]) / wps
        out.append({"id": s["id"], "start": round(t, 1), "end": round(t + d, 1), "words": word_count(s["narration"])})
        t += d + SCENE_GAP
    return out


def emphasis_words(sb: dict, brief: dict, facts) -> list[str]:
    words = {brief["brand"].split()[0]}
    for s in sb["scenes"]:
        words |= set(re.findall(r"\b\d[\d,]*\b", s["narration"]))
        for p in facts.plan_names():
            if p.lower() in s["narration"].lower():
                words.add(p)
    return sorted(words)


def creative_plan(brief: dict, concept: dict, sb: dict, publishing: dict, theme: dict | None, preset: dict | None, facts) -> dict:
    cap = (preset or {}).get("captions", {})
    sfx = (theme or {}).get("sfx", {})
    scenes = []
    for s, tm in zip(sb["scenes"], scene_timings(sb)):
        scenes.append({"scene": s["id"], "est": f"{tm['start']}–{tm['end']}s",
                       "sfx": [f"{b['type']}: {SFX_NOTES.get(b['type'], '—')}" for b in s["blocks"]] +
                              (["transition swoosh at scene start"] if s is not sb["scenes"][0] else [])})
    cta = next((b for s in sb["scenes"] for b in s["blocks"] if b["type"] == "cta"), None)
    return {
        "concept": {"id": concept.get("id"), "name": concept.get("name"), "pattern": concept.get("pattern")},
        "music": {"mood": concept.get("music_mood", "technology"), "vocabulary": ["cinematic", "corporate", "technology", "energetic",
                                                                                   "minimal", "educational", "calm", "promotional"],
                  "level_db": (preset or {}).get("audio", {}).get("musicDb", -16), "ducking": "side-chain under voice (preset)",
                  "file": None, "note": "pick a licensed track with this mood; record it in audio/music/licenses.json"},
        "captions": {"style": cap.get("style", "word"), "max_words": cap.get("maxWords", 4), "position_bottom_frac": cap.get("bottomFrac"),
                     "highlight_colour": (theme or {}).get("caption", {}).get("highlight"),
                     "emphasis_words": emphasis_words(sb, brief, facts),
                     "note": "engine highlights the current word; emphasis_words are advisory (brand name, prices, plan names)"},
        "sfx": {"auto": True, "family": sfx.get("$comment", "brand theme sfx kit"), "per_scene": scenes},
        "cta": {"text": cta.get("text") if cta else brief.get("cta"), "url": cta.get("url") if cta else None,
                "treatment": concept.get("cta_treatment", {}).get("style")},
        "publishing": publishing,
        "voice": brief.get("voice") or (preset or {}).get("voice", {}).get("voice"),
    }


def _blocks_summary(b: dict) -> str:
    ty = b["type"]
    if ty == "headline":
        return f"headline “{b['words'] if isinstance(b.get('words'), str) else ' '.join(w['text'] for w in b.get('words', []))}”"
    if ty in ("text", "pill"):
        return f"{ty} “{b.get('text')}”"
    if ty == "price":
        return f"price ₹{b.get('amount')}{b.get('period', '')}"
    if ty == "checklist":
        return "checklist: " + ", ".join(i["text"] for i in b.get("items", []))
    if ty == "compare-rows":
        return "compare: " + "; ".join(f"{r['label']} {r['value']}" for r in b.get("rows", [])) + (f" [{b['badge']['text']}]" if b.get("badge") else "")
    if ty == "plans":
        return "plans: " + ", ".join(f"{p['name']} {p['price']}" for p in b.get("plans", []))
    if ty == "domain-input":
        return f"domain-input {b.get('domain')} → “{b.get('button', {}).get('done')}”"
    if ty == "browser":
        return f"browser {b.get('url')}"
    if ty == "hook-tag":
        return f"hook-tag {b.get('label')}: {b.get('text')}"
    if ty == "flat-line":
        return "flat-line " + " / ".join(p["value"] for p in b.get("points", []))
    if ty == "cta":
        return f"cta “{b.get('text')}” → {b.get('url')}"
    return ty


def preview_markdown(brief: dict, concept: dict, sb: dict, chk: dict, plan: dict, path: str, review: dict) -> str:
    tm = scene_timings(sb)
    by_scene: dict[str, list[dict]] = {}
    for c in chk["claims"]["needs_review"]:
        m = re.match(r"scenes\[\d+\]\(([^)]+)\)", c["scope"])
        by_scene.setdefault(m.group(1) if m else "other", []).append(c)
    lines = [f"# Storyboard preview — {sb.get('title')}", "",
             f"**Concept:** {concept.get('name')} ({concept.get('pattern_name') or concept.get('pattern')}) · **produced by:** `{path}`",
             f"**Estimated length:** {chk['estimate_s']} s (target {chk['target_s']} s, {WPS} words/s) · **music:** {plan['music']['mood']} · "
             f"**captions:** {plan['captions']['style']}, {plan['captions']['max_words']} words/page",
             f"**Validation:** {'PASS' if not chk['errors'] else 'FAIL'} ({len(chk['errors'])} errors, {len(chk['warnings'])} warnings) · "
             f"**Fact check:** {chk['claims']['summary']['verified']} verified, {chk['claims']['summary']['needs_review']} NEEDS_REVIEW",
             ""]
    if review["blocking"]:
        lines += [f"> **BLOCKED — needs owner review before publishing.** " + " ".join(review["reasons"][:3]), ""]
    lines += ["| # | scene | purpose | est. time | words | narration | blocks | review |", "|---|---|---|---|---|---|---|---|"]
    for k, (s, t) in enumerate(zip(sb["scenes"], tm), 1):
        flags = by_scene.get(s["id"], [])
        fl = "; ".join(f"⚠ {c['text']}" for c in flags[:3]) or "✓"
        lines.append(f"| {k} | `{s['id']}` | {s['purpose']}{' · ' + s['mood'] if s.get('mood') and s['mood'] != 'neutral' else ''} | "
                     f"{t['start']}–{t['end']}s | {t['words']} | {s['narration']} | {'<br>'.join(_blocks_summary(b) for b in s['blocks'])} | {fl} |")
    lines += ["", "## CTA", f"{plan['cta']['text']} → {plan['cta']['url']} ({plan['cta']['treatment']})", "",
              "## Publishing", f"- **Title:** {plan['publishing'].get('title')}",
              f"- **Description:** {(plan['publishing'].get('description') or '').replace(chr(10), ' / ')}",
              f"- **Hashtags:** {' '.join(plan['publishing'].get('hashtags', []))}", "",
              "## SFX cue notes (auto from brand theme)"]
    for s in plan["sfx"]["per_scene"]:
        lines.append(f"- `{s['scene']}` ({s['est']}): " + "; ".join(s["sfx"]))
    if chk["claims"]["needs_review"]:
        lines += ["", "## Claims needing review"]
        for c in chk["claims"]["needs_review"]:
            lines.append(f"- **{c['text']}** ({c['kind']}, from {c['origin']}) in `{c['scope']}` — {c.get('reason', '')}")
    if chk["warnings"]:
        lines += ["", "## Warnings"] + [f"- {w}" for w in chk["warnings"]]
    return "\n".join(lines) + "\n"
