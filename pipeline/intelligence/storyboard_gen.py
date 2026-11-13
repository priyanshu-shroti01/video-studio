"""Storyboard generation for a selected concept -> the EXISTING storyboard format (pipeline/storyboard.py).

  draft (LLM JSON or template)  ->  compile_draft (sanitise, engine defaults, brand conventions)
                                ->  check (validate_storyboard, block fields, duration fit, requirements, claims)
  LLM path: errors are fed back to the model (repair loop, N rounds) -> deterministic autofix ->
  template planner fallback. The path that produced the output is recorded."""
from __future__ import annotations

import copy
import difflib
import json
import re

from ..contract import ICONS, TONES
from ..storyboard import EXPR, PURPOSES, _word_in, validate_storyboard
from ..timing import tokenize
from .claims import block_texts_all, verify_storyboard
from .facts import FactBase
from .patterns import BLOCK_TYPES, PATTERNS, structure_for
from .planner import template_draft, word_count
from .providers import LLMError, Provider

WPS = 2.33          # spoken words per second, measured on local Kokoro am_michael +5% (was 2.6, 10% optimistic)
SCENE_GAP = 0.2     # preset voice.sceneGap
PAD = 0.5           # lead-in + tail pad
DURATION_TOL = (0.85, 1.12)
MAX_BLOCKS = 3

T = {"type": "string"}          # time expression ("@word:X+0.2")
TONE = {"type": "string", "enum": sorted(TONES)}
ICON = {"type": "string", "enum": sorted(ICONS)}


def _obj(req: list[str], props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": req, "properties": props}


BLOCK_SCHEMAS = {
    "headline": _obj(["type", "size", "words"], {"type": {"const": "headline"}, "size": {"type": "string", "enum": ["xl", "l", "m"]},
                                                 "words": {"type": "string", "maxLength": 48}, "at": T}),
    "text": _obj(["type", "text", "size"], {"type": {"const": "text"}, "text": {"type": "string", "maxLength": 60},
                                            "size": {"type": "string", "enum": ["l", "m", "s"]}, "tone": TONE, "at": T}),
    "pill": _obj(["type", "text", "tone"], {"type": {"const": "pill"}, "text": {"type": "string", "maxLength": 32}, "tone": TONE,
                                            "icon": ICON, "stamp": {"type": "boolean"}, "at": T}),
    "price": _obj(["type", "amount", "period", "label", "at", "countEnd"],
                  {"type": {"const": "price"}, "amount": {"type": "number"}, "period": {"type": "string", "enum": ["/mo", "/yr"]},
                   "label": {"type": "string", "maxLength": 48}, "note": {"type": "string", "maxLength": 24}, "at": T, "countEnd": T}),
    "checklist": _obj(["type", "items"], {"type": {"const": "checklist"}, "items": {"type": "array", "minItems": 2, "maxItems": 4, "items":
                      _obj(["text", "icon", "at"], {"text": {"type": "string", "maxLength": 32}, "icon": ICON, "at": T})}}),
    "compare-rows": _obj(["type", "rows"], {"type": {"const": "compare-rows"}, "rows": {"type": "array", "minItems": 2, "maxItems": 3, "items":
                         _obj(["label", "value", "at"], {"label": {"type": "string", "maxLength": 28}, "value": {"type": "string", "maxLength": 28}, "at": T})},
                         "badge": _obj(["text", "tone", "at"], {"text": {"type": "string", "maxLength": 20}, "tone": TONE, "at": T})}),
    "plans": _obj(["type", "plans"], {"type": {"const": "plans"}, "plans": {"type": "array", "minItems": 2, "maxItems": 3, "items":
                  _obj(["name", "price"], {"name": {"type": "string", "maxLength": 20}, "price": {"type": "string", "maxLength": 10},
                                           "period": {"type": "string", "enum": ["/mo", "/yr"]}, "detail": {"type": "string", "maxLength": 24},
                                           "badge": {"type": "string", "maxLength": 16}})}, "emphasizeAt": T}),
    "domain-input": _obj(["type", "title", "domain", "typeAt", "availableText", "button"],
                         {"type": {"const": "domain-input"}, "title": {"type": "string", "maxLength": 28}, "domain": {"type": "string", "maxLength": 24},
                          "typeAt": T, "availableText": {"type": "string", "maxLength": 20},
                          "button": _obj(["idle", "busy", "done", "clickAt", "doneAt"], {"idle": {"type": "string", "maxLength": 20},
                                         "busy": {"type": "string", "maxLength": 20}, "done": {"type": "string", "maxLength": 22},
                                         "clickAt": T, "doneAt": T})}),
    "browser": _obj(["type", "url", "loadUntil"], {"type": {"const": "browser"}, "url": {"type": "string", "maxLength": 32}, "at": T,
                                                   "loadUntil": T, "stallAt": T,
                                                   "tag": _obj(["text", "at"], {"text": {"type": "string", "maxLength": 20}, "at": T})}),
    "hook-tag": _obj(["type", "label", "text"], {"type": {"const": "hook-tag"}, "label": {"type": "string", "maxLength": 16},
                                                 "text": {"type": "string", "maxLength": 24}, "sub": {"type": "string", "maxLength": 28}, "at": T}),
    "flat-line": _obj(["type", "title", "points", "drawEnd"], {"type": {"const": "flat-line"}, "title": {"type": "string", "maxLength": 32},
                      "points": {"type": "array", "minItems": 2, "maxItems": 4, "items": _obj(["label", "value"], {
                          "label": {"type": "string", "maxLength": 12}, "value": {"type": "string", "maxLength": 12}})}, "drawEnd": T, "at": T}),
    "logo": _obj(["type"], {"type": {"const": "logo"}, "at": T}),
    "cta": _obj(["type", "text", "url", "urlAt"], {"type": {"const": "cta"}, "text": {"type": "string", "maxLength": 32},
                                                   "url": {"type": "string", "maxLength": 32}, "urlAt": T, "clickAt": T,
                                                   "sub": {"type": "string", "maxLength": 60}, "at": T}),
}
# bars is deliberately not offered to the model: relative bar heights imply numbers nobody sourced.
LLM_BLOCKS = [b for b in BLOCK_TYPES if b != "bars"]


def draft_schema(n_scenes: int | None = None) -> dict:
    scene = _obj(["id", "purpose", "narration", "blocks"], {
        "id": {"type": "string", "minLength": 1, "maxLength": 31},
        "purpose": {"type": "string", "enum": [p for p in PURPOSES if p != "custom"]},
        "narration": {"type": "string", "minLength": 3, "maxLength": 200},
        "mood": {"type": "string", "enum": ["neutral", "danger", "brand"]},
        "blocks": {"type": "array", "minItems": 1, "maxItems": MAX_BLOCKS, "items": {"anyOf": [BLOCK_SCHEMAS[b] for b in LLM_BLOCKS]}},
    })
    return _obj(["title", "scenes", "publishing"], {
        "title": {"type": "string", "maxLength": 80},
        "scenes": {"type": "array", "minItems": max(3, (n_scenes or 6) - 2), "maxItems": min(10, (n_scenes or 6) + 2), "items": scene},
        "publishing": _obj(["title", "description", "hashtags"], {
            "title": {"type": "string", "maxLength": 100}, "description": {"type": "string", "maxLength": 400},
            "hashtags": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "string", "minLength": 3, "maxLength": 32}}}),
    })


# ---- compile -----------------------------------------------------------------------------------------
ALLOWED = {
    "logo": {"variant", "width"}, "headline": {"size", "words", "tones", "strike", "align"}, "text": {"text", "size", "tone"},
    "pill": {"text", "tone", "icon", "stamp"}, "price": {"currency", "amount", "period", "label", "note", "countFrom", "countEnd"},
    "checklist": {"items"}, "bars": {"title", "bars", "badge"}, "compare-rows": {"rows", "badge"},
    "plans": {"plans", "select", "emphasizeAt"},
    "domain-input": {"title", "domain", "typeAt", "keyTimes", "availableAt", "availableText", "button"},
    "browser": {"url", "loadUntil", "stallAt", "tag"}, "hook-tag": {"label", "text", "sub"},
    "flat-line": {"title", "points", "drawEnd"}, "cta": {"text", "url", "urlAt", "clickAt", "sub"},
}
REQUIRED = {"headline": ["size", "words"], "text": ["text", "size"], "pill": ["text", "tone"], "price": ["amount"],
            "checklist": ["items"], "bars": ["title", "bars"], "compare-rows": ["rows"], "plans": ["plans"],
            "domain-input": ["title", "domain", "typeAt", "availableText", "button"], "browser": ["url", "loadUntil"],
            "hook-tag": ["label", "text"], "flat-line": ["title", "points", "drawEnd"], "cta": ["text", "url", "urlAt"], "logo": []}


_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def clean_text(v):
    """ASCII quotes; drop mojibake/partial UTF-8 left when a grammar maxLength cuts a multi-byte char."""
    if isinstance(v, str):
        v = v.translate(_QUOTES)
        v = re.sub(r"[\u00c2\u00e2\ufffd][\u0080-\u00bf]*$", "", v)
        return re.sub(r"\s+", " ", v).strip()
    if isinstance(v, list):
        return [clean_text(x) for x in v]
    if isinstance(v, dict):
        return {k: (x if k == "type" else clean_text(x)) for k, x in v.items()}
    return v


def _sid(s: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", str(s).lower()).strip("-_")[:40]
    return s if s and s[0].isalnum() else f"s-{s}"[:40]


def compile_draft(draft: dict, brief: dict, fb: FactBase, *, pattern: str | None = None) -> tuple[dict, list[str]]:
    """Draft (LLM or template JSON) -> storyboard in the project format + list of deterministic fixes applied."""
    fixes: list[str] = []
    d = clean_text(copy.deepcopy(draft))
    scenes, seen = [], set()
    domain = fb.domain()
    for i, sc in enumerate(d.get("scenes", [])):
        sid = _sid(sc.get("id") or f"scene-{i + 1}")
        while sid in seen:
            sid = _sid(f"{sid}-{i + 1}")
        seen.add(sid)
        purpose = sc.get("purpose") if sc.get("purpose") in PURPOSES else "custom"
        if purpose != sc.get("purpose"):
            fixes.append(f"{sid}: purpose {sc.get('purpose')!r} -> custom")
        narr = re.sub(r"\s+", " ", str(sc.get("narration", ""))).strip()
        n2 = re.sub(r"₹\s?(\d[\d,]*)\s*/\s*(mo|month)\b", r"\1 rupees a month", narr)
        n2 = re.sub(r"₹\s?(\d[\d,]*)", r"\1 rupees", n2)
        if n2 != narr:
            fixes.append(f"{sid}: narration currency symbol spelled out for TTS"); narr = n2
        out = {"id": sid, "purpose": purpose, "narration": narr}
        for k in ("mood", "transition", "layout", "splitAt", "brandBar", "cues", "sfx", "autoSfx"):
            if k in sc:
                out[k] = sc[k]
        if out.get("mood") not in (None, "neutral", "danger", "brand"):
            out.pop("mood"); fixes.append(f"{sid}: bad mood dropped")
        blocks = []
        for j, b in enumerate(sc.get("blocks", [])):
            if not isinstance(b, dict) or b.get("type") not in ALLOWED:
                fixes.append(f"{sid}: dropped unknown block {b.get('type') if isinstance(b, dict) else b!r}"); continue
            ty = b["type"]
            nb = {"type": ty, **{k: v for k, v in b.items() if k in ALLOWED[ty] | {"at", "exitAt", "id", "tones"}}}
            dropped = set(b) - set(nb)
            if dropped:
                fixes.append(f"{sid}.blocks[{j}]: dropped fields {sorted(dropped)}")
            if ty == "price":
                nb.setdefault("currency", "₹")
                if isinstance(nb.get("amount"), str):
                    m = re.search(r"\d+(?:\.\d+)?", nb["amount"])
                    nb["amount"] = float(m.group(0)) if m else 0
                if isinstance(nb.get("amount"), float) and nb["amount"].is_integer():
                    nb["amount"] = int(nb["amount"])
                nb.setdefault("note", "excl. taxes")
            if ty == "logo":
                nb["variant"] = "onDark"; nb.setdefault("width", 780)
            if ty == "cta" and domain and nb.get("url") != domain:
                if nb.get("url"):
                    fixes.append(f"{sid}: cta url {nb.get('url')!r} -> {domain!r} (brand site)")
                nb["url"] = domain
            for key in ("tone", "icon"):
                for holder in _holders(nb, key):
                    if holder[key] not in (TONES if key == "tone" else ICONS):
                        fixes.append(f"{sid}.blocks[{j}]: invalid {key} {holder[key]!r} dropped")
                        holder.pop(key)
                        if ty == "pill" and key == "tone" and holder is nb:
                            nb["tone"] = "brand"
            blocks.append(nb)
        if sum(b["type"] == "logo" for b in blocks) > 1:
            first = next(i for i, b in enumerate(blocks) if b["type"] == "logo")
            blocks = [b for i, b in enumerate(blocks) if b["type"] != "logo" or i == first]
            fixes.append(f"{sid}: duplicate logo blocks removed")
        if len(blocks) > MAX_BLOCKS:
            keep = [b for b in blocks if b["type"] in ("logo", "cta")] if purpose == "cta" else []
            blocks = (keep + [b for b in blocks if b not in keep])[:MAX_BLOCKS]
            fixes.append(f"{sid}: trimmed to {MAX_BLOCKS} blocks")
        out["blocks"] = blocks or [{"type": "text", "text": narr[:48], "size": "m"}]
        scenes.append(out)
    # brand conventions: danger mood on problem scenes, brand bar after the reveal (not on logo / cta scenes)
    revealed = False
    for k, sc in enumerate(scenes):
        has_logo = any(b["type"] == "logo" for b in sc["blocks"])
        if sc["purpose"] == "problem":
            sc.setdefault("mood", "danger")
        if sc["purpose"] == "cta":
            sc.setdefault("mood", "brand")
        if "brandBar" not in sc:
            sc["brandBar"] = revealed and not has_logo and sc["purpose"] != "cta"
        revealed = revealed or has_logo or sc["purpose"] in ("turn",)
        sc.setdefault("transition", "fade" if k == 0 or sc["purpose"] in ("hook", "problem", "cta") else "slide-up")
        if sc.get("layout") == "split" and "splitAt" not in sc:
            sc["splitAt"] = 1
    sb = {"version": 1, "title": str(d.get("title") or f"{brief['brand']} — {brief['product']}")[:120],
          "structure": d.get("structure") or (structure_for(pattern) if pattern in PATTERNS else None), "scenes": scenes}
    if not sb["structure"]:
        sb.pop("structure")
    else:
        sb["structure"] = [p for p in sb["structure"] if p in PURPOSES]
    return sb, fixes


def _holders(obj, key):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], str):
            yield obj
        for v in list(obj.values()):
            if isinstance(v, (dict, list)):
                yield from _holders(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _holders(v, key)


# ---- checks ------------------------------------------------------------------------------------------
def estimate_seconds(sb: dict, wps: float = WPS) -> float:
    words = sum(word_count(s["narration"]) for s in sb["scenes"])
    return round(words / wps + SCENE_GAP * len(sb["scenes"]) + PAD, 1)


def requirement_coverage(sb: dict, brief: dict) -> dict:
    sc = sb["scenes"]
    types = lambda pred: {b["type"] for s in sc if pred(s) for b in s["blocks"]}
    allt = types(lambda s: True)
    have = {
        "problem": any(s["purpose"] == "problem" or s.get("mood") == "danger" for s in sc),
        "demonstration": bool(allt & {"domain-input", "browser", "checklist", "plans"}) and
        any(s["purpose"] in ("journey", "point", "example") for s in sc),
        "pricing-comparison": any(b["type"] in ("compare-rows", "plans", "flat-line", "bars") and "₹" in json.dumps(b, ensure_ascii=False)
                                  for s in sc for b in s["blocks"]),
        "pricing": any("₹" in json.dumps(b, ensure_ascii=False) or b["type"] == "price" for s in sc for b in s["blocks"]),
        "cta": sc[-1]["purpose"] == "cta" and any(b["type"] == "cta" for b in sc[-1]["blocks"]),
    }
    reqs = brief.get("requirements", [])
    return {"covered": [r for r in reqs if have.get(r, True)], "missing": [r for r in reqs if not have.get(r, True)]}


def check(sb: dict, brief: dict, fb: FactBase, publishing: dict | None) -> dict:
    errors, warnings = validate_storyboard(sb)
    if not errors:
        for i, s in enumerate(sb["scenes"]):
            for j, b in enumerate(s["blocks"]):
                miss = [k for k in REQUIRED.get(b["type"], []) if k not in b]
                if b["type"] == "domain-input" and "button" in b:
                    miss += [f"button.{k}" for k in ("idle", "busy", "done", "clickAt", "doneAt") if k not in b["button"]]
                for it in (b.get("items") or []) if b["type"] == "checklist" else []:
                    if "at" not in it or "text" not in it:
                        miss.append("items[].text/at")
                for r in (b.get("rows") or []) if b["type"] == "compare-rows" else []:
                    if not {"label", "value", "at"} <= set(r):
                        miss.append("rows[].label/value/at")
                if miss:
                    errors.append(f"$storyboard.scenes[{i}]({s['id']}).blocks[{j}] {b['type']}: missing {sorted(set(miss))}")
    target = brief.get("duration_seconds", 35)
    est = estimate_seconds(sb)
    lo, hi = target * DURATION_TOL[0], target * DURATION_TOL[1]
    dur_err = None
    if not lo <= est <= hi:
        words = sum(word_count(s["narration"]) for s in sb["scenes"])
        want = round((target - SCENE_GAP * len(sb["scenes"]) - PAD) * WPS)
        dur_err = (f"estimated length {est}s is outside {lo:.0f}–{hi:.0f}s for a {target}s target: narration has {words} words, "
                   f"needs about {want} (±10%) at {WPS} words/s")
    cov = requirement_coverage(sb, brief)
    if sb["scenes"][-1]["purpose"] != "cta":
        warnings.append("last scene is not a cta scene")
    claims = verify_storyboard(sb, fb, brief, publishing)
    invented = [c for c in claims["needs_review"] if c["origin"] == "generated"]
    return {"errors": errors, "duration_error": dur_err, "estimate_s": est, "target_s": target, "warnings": warnings,
            "coverage": cov, "claims": claims, "invented": invented}


def _problems(chk: dict) -> list[str]:
    p = list(chk["errors"])
    if chk["duration_error"]:
        p.append(chk["duration_error"])
    if chk["coverage"]["missing"]:
        p.append(f"the brief requires these beats, which are missing: {chk['coverage']['missing']}")
    for c in chk["invented"][:8]:
        p.append(f"unverified claim {c['text']!r} in {c['scope']}: {c.get('reason', '')[:140]}. Remove it or use a FACT SHEET item")
    return p


# ---- deterministic autofix ---------------------------------------------------------------------------
def autofix(sb: dict) -> tuple[dict, list[str]]:
    """Repair time expressions whose word is not spoken in the scene (nearest spoken word, else scene-relative)."""
    sb = copy.deepcopy(sb)
    fixes = []
    for s in sb["scenes"]:
        toks = [re.sub(r"[^\w']", "", t) for t in tokenize(s["narration"])]
        toks = [t for t in toks if t]
        cues = s.get("cues", {})

        def fix(v, key):
            if not isinstance(v, str):
                return v
            m = EXPR.match(v)
            if m and (not m.group(1).startswith("word:") or _word_in(s["narration"], m.group(1)[5:].split("#")[0])) and \
                    (m.group(1) in ("start", "end", "speech_end") or m.group(1).startswith("word:") or m.group(1) in cues):
                return v
            w = re.sub(r"^@word:|[+\-].*$|#\d+$", "", v.split("+")[0]) if v.startswith("@") else v
            near = difflib.get_close_matches(w, toks, n=1, cutoff=0.6)
            new = f"@word:{near[0]}" if near else ("@start+0.3" if key in ("at", "typeAt", "cursorStart") else "@speech_end-0.2")
            fixes.append(f"{s['id']}: time {v!r} -> {new!r}")
            return new

        def rec(o):
            if isinstance(o, dict):
                for k, v in list(o.items()):
                    if isinstance(v, (dict, list)):
                        rec(v)
                    elif k in ("at", "exitAt", "countEnd", "growEnd", "clickAt", "doneAt", "availableAt", "cursorStart", "urlAt",
                               "loadUntil", "stallAt", "drawEnd", "emphasizeAt", "typeAt"):
                        o[k] = fix(v, k)
            elif isinstance(o, list):
                for v in o:
                    rec(v)
        rec(s["blocks"])
    return sb, fixes


# ---- generation (scene by scene) ---------------------------------------------------------------------
# A 4B model writes one coherent scene far more reliably than a whole storyboard (measured: one-shot drafts
# came back 4 scenes / 24-40 s with missing beats). So the pattern's beats fix the structure; the model
# writes each scene against a scene-specific schema (allowed block types, word budget) and each scene has
# its own validate -> repair -> autofix -> template-scene loop.
SYSTEM = (
    "You write ONE scene at a time for a deterministic vertical-video engine. Output JSON only, matching the schema.\n"
    "FACT DISCIPLINE: every price, plan name, spec, feature, guarantee or number must come from the FACT SHEET or the BRIEF. "
    "Never invent discounts, uptime, speed numbers, customer counts, reviews, awards, certifications or integrations. "
    "No competitor names, no multipliers (3x, triple), no 'hidden fees', no 'guaranteed'.\n"
    "TIMING: block times are expressions resolved against the spoken narration of THIS scene: '@word:Grow' (when that "
    "word is spoken), '@word:Grow+0.4', '@start', '@end-0.3', '@speech_end'. Every @word MUST be a word from this scene's "
    "narration. Write prices as the narrator says them ('39 rupees a month') and anchor on the digits ('@word:39').\n"
    "STYLE: confident, second person, concrete, short sentences, no filler, no exclamation marks.")

BEAT_WEIGHT = {"hook": 0.11, "problem": 0.19, "turn": 0.10, "journey": 0.22, "point": 0.2, "example": 0.19,
               "resolution": 0.2, "cta": 0.1, "intro": 0.1, "conclusion": 0.12}
EXAMPLES = {
    "price": {"type": "price", "amount": 49, "period": "/mo", "label": "Launch plan · starting at", "note": "excl. taxes",
              "at": "@word:start-0.1", "countEnd": "@word:49+0.5"},
    "compare-rows": {"type": "compare-rows", "rows": [{"label": "Today", "value": "₹49/mo", "at": "@word:start"},
                                                      {"label": "On renewal", "value": "₹49/mo", "at": "@word:renewal"}],
                     "badge": {"text": "Same price", "tone": "success", "at": "@word:renewal+0.4"}},
    "domain-input": {"type": "domain-input", "title": "Find your domain", "domain": "yourbrand.in", "typeAt": "@word:type+0.1",
                     "availableText": "is available", "button": {"idle": "Launch site", "busy": "Launching…", "done": "Your site is live",
                                                                 "clickAt": "@word:launch", "doneAt": "@word:minutes+0.2"}},
    "checklist": {"type": "checklist", "items": [{"text": "Free SSL", "icon": "lock", "at": "@word:SSL"},
                                                 {"text": "Daily backups", "icon": "cloud", "at": "@word:backups"}]},
    "cta": {"type": "cta", "text": "Launch your site today", "url": "{DOMAIN}", "at": "@word:Launch-0.05",
            "urlAt": "@word:{DOMAIN_WORD}", "clickAt": "@word:{DOMAIN_WORD}+0.55", "sub": "Same price on renewal"},
    "browser": {"type": "browser", "url": "your-website.in", "at": "@word:slow-0.1", "loadUntil": "@word:slow+0.8", "stallAt": "@word:slow"},
    "flat-line": {"type": "flat-line", "title": "Your bill", "at": "@word:same", "drawEnd": "@word:renew+0.3",
                  "points": [{"label": "Year 1", "value": "₹49/mo"}, {"label": "Year 2", "value": "₹49/mo"}]},
    "hook-tag": {"type": "hook-tag", "label": "MYTH", "text": "Cheap stays cheap", "sub": "…right?", "at": "@word:cheap"},
}


def word_budgets(n_or_beats, target: float) -> list[int]:
    beats = n_or_beats
    total = (target - SCENE_GAP * len(beats) - PAD) * WPS
    w = [BEAT_WEIGHT.get(b["purpose"], 0.15) for b in beats]
    return [max(4, round(total * x / sum(w))) for x in w]


REQ_BLOCKS = {"demonstration": ["domain-input", "checklist", "browser"], "pricing-comparison": ["compare-rows", "flat-line", "plans"]}


def assign_requirements(beats: list[dict], brief: dict) -> dict[int, list[str]]:
    """Each brief requirement is demanded of ONE beat: the first that satisfies it and suggests a fitting block."""
    reqs = set(brief.get("requirements", []))
    if "pricing" in reqs:
        reqs.add("pricing-comparison") if "pricing-comparison" in reqs else None
    out: dict[int, list[str]] = {}
    for r in ("demonstration", "pricing-comparison"):
        if r not in reqs and not (r == "pricing-comparison" and "pricing" in reqs):
            continue
        cands = [k for k, b in enumerate(beats) if r in b["satisfies"]]
        best = next((k for k in cands if set(beats[k]["blocks"]) & set(REQ_BLOCKS[r])), cands[0] if cands else None)
        if best is not None:
            out.setdefault(best, []).append(r)
    return out


def _scene_spec(beat: dict, assigned: list[str], price_ok: bool) -> tuple[list[str], list[list[str]]]:
    """(allowed block types, required groups: each group needs >=1 block of those types; '₹' = any block showing a price)."""
    if beat["purpose"] == "cta":
        return ["logo", "cta"], [["logo"], ["cta"]]
    allowed = [b for b in beat["blocks"] if b in LLM_BLOCKS and b != "logo"] + ["headline", "text", "pill"]
    if beat["purpose"] == "turn" or "logo" in beat["blocks"]:
        allowed.append("logo")
    if not price_ok:
        allowed = [b for b in allowed if b != "plans"]
    req: list[list[str]] = []
    if "pricing-comparison" in assigned:
        allowed += [b for b in ("price", "compare-rows") if b not in allowed]
        req += [[b for b in REQ_BLOCKS["pricing-comparison"] if b in allowed], ["price", "₹"]]
    if "demonstration" in assigned:
        allowed += [b for b in ("checklist",) if b not in allowed]
        req.append([b for b in REQ_BLOCKS["demonstration"] if b in allowed])
    if beat["purpose"] == "turn":
        req.append(["logo"])
    return list(dict.fromkeys(allowed)), req


def _groups(req: list[list[str]]) -> list[list[str]]:
    return [[t for t in g if t != "₹"] for g in req if "₹" not in g]


def scene_schema(allowed: list[str], budget: int, req: list[list[str]]) -> dict:
    """Required block groups are separate required properties (block_1, block_2 ...), so the grammar itself
    guarantees them; `more_blocks` holds up to the remaining 3-N optional blocks."""
    groups = _groups(req)
    props = {"narration": {"type": "string", "minLength": 3, "maxLength": max(60, budget * 9)},
             "mood": {"type": "string", "enum": ["neutral", "danger", "brand"]}}
    for i, g in enumerate(groups, 1):
        props[f"block_{i}"] = {"anyOf": [BLOCK_SCHEMAS[t] for t in g]}
    rest = MAX_BLOCKS - len(groups)
    if rest > 0:
        props["more_blocks"] = {"type": "array", "minItems": 0 if groups else 1, "maxItems": rest,
                                "items": {"anyOf": [BLOCK_SCHEMAS[b] for b in allowed]}}
    return _obj(["narration", *[f"block_{i}" for i in range(1, len(groups) + 1)], *(["more_blocks"] if not groups else [])], props)


def scene_blocks(data: dict) -> list:
    if isinstance(data.get("blocks"), list):
        return data["blocks"]
    keys = sorted((k for k in data if re.fullmatch(r"block_\d+", k)), key=lambda k: int(k[6:]))
    return [data[k] for k in keys] + list(data.get("more_blocks") or [])


PUBLISHING_SCHEMA = _obj(["title", "description", "hashtags"], {
    "title": {"type": "string", "minLength": 10, "maxLength": 100}, "description": {"type": "string", "minLength": 20, "maxLength": 400},
    "hashtags": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "string", "minLength": 3, "maxLength": 32}}})


def _prefix(brief: dict, concept: dict, fb: FactBase) -> str:
    b = {k: brief.get(k) for k in ("brand", "product", "price", "audience", "duration_seconds", "goal", "cta", "tone", "request")}
    c = {k: concept.get(k) for k in ("name", "pattern_name", "hook", "logline", "animation_style", "music_mood")}
    return (f"BRIEF:\n{json.dumps(b, ensure_ascii=False)}\n\nCONCEPT:\n{json.dumps(c, ensure_ascii=False)}\n\n"
            f"FACT SHEET (verified on {fb.site}):\n{fb.for_prompt(brief.get('product', ''), 40)}\n\n"
            f"PRICE RULE: the only price you may state for {brief.get('product')} is the brief's ({brief.get('price')}); do not "
            f"mention any other {brief.get('product')} price.\nBRAND SITE: {fb.domain()} · CTA: {brief.get('cta')} · "
            f"placeholder domains for UI mock-ups: yourbrand.in, your-website.in\n")


def _concept_idea(concept: dict, beat: dict, k: int) -> str:
    beats = concept.get("beats") or []
    same = [b for b in beats if b.get("purpose") == beat["purpose"]]
    if same:
        return same[0].get("idea", "")
    return beats[k].get("idea", "") if k < len(beats) else ""


def _scene_prompt(prefix: str, so_far: list[dict], beat: dict, k: int, n: int, idea: str, budget: int,
                  allowed: list[str], req: list[list[str]], fb: FactBase | None = None) -> str:
    prev = "\n".join(f"{i + 1}. [{s['purpose']}] {s['narration']}" for i, s in enumerate(so_far)) or "(this is the first scene)"
    groups = _groups(req)
    must = "; ".join(f"block_{i} = a {' or '.join(g)} block" for i, g in enumerate(groups, 1)) or "more_blocks: 1-3 blocks"
    if any("₹" in g for g in req):
        must += "; the price must be shown in a block (price block or ₹ value)"
    ex = {t: EXAMPLES[t] for g in req for t in g if t in EXAMPLES}
    if "cta" in ex:                                   # the brand's own domain, never another brand's
        dom = (fb.domain() if fb else "") or "example.com"
        ex["cta"] = json.loads(json.dumps(ex["cta"]).replace("{DOMAIN_WORD}", dom.split(".")[0]).replace("{DOMAIN}", dom))
    return (f"{prefix}\nSTORYBOARD SO FAR:\n{prev}\n\n"
            f"WRITE SCENE {k + 1} of {n}: purpose '{beat['purpose']}' ({beat['beat']}: {beat['role']}).\n"
            f"Concept idea for this scene: {idea or beat['role']}\n"
            f"Narration: {max(3, -(-budget * 4 // 5))}-{budget + 3} words (count them), continuing from the scenes above without repeating them.\n"
            + (f"This is the closing scene: the narration must say '{prefix_cta(prefix)}' and the site name.\n" if beat["purpose"] == "cta" else "")
            + "On-screen text is a SHORT label (pill <=4 words, headline <=7, text <=9), never the narration itself. Use plain ASCII apostrophes.\n"
            f"Blocks (max 3 in total): {must}. Optional more_blocks types: {', '.join(allowed)}.\n"
            + (f"Block format examples (prices/words are placeholders):\n{json.dumps(ex, ensure_ascii=False)}\n" if ex else ""))


ALLOWED_SYMBOLS = set("₹…·–—‘’“”×✓→←↑↓•€")
MAX_WORDS = {"pill": 4, "headline": 7, "text": 9, "hook-tag": 6}


def prefix_cta(prefix: str) -> str:
    m = re.search(r"CTA: ([^\n]+)", prefix)
    return m.group(1).strip() if m else "the call to action"


def check_scene(scene: dict, brief: dict, fb: FactBase, budget: int, req: list[list[str]],
                previous: list[dict] | None = None) -> tuple[dict, list[str], list[str]]:
    sb, fixes = compile_draft({"scenes": [scene]}, brief, fb)
    errors, _ = validate_storyboard(sb)
    s = sb["scenes"][0]
    probs = list(errors)
    for j, b in enumerate(s["blocks"]):
        miss = [k for k in REQUIRED.get(b["type"], []) if k not in b]
        if miss:
            probs.append(f"block {j} ({b['type']}) is missing {miss}")
    types = {b["type"] for b in s["blocks"]}
    shows_price = "₹" in json.dumps(s["blocks"], ensure_ascii=False)
    for g in req:
        if not (types & set(g) or ("₹" in g and shows_price)):
            probs.append(f"the scene must include a {' or '.join(x for x in g if x != '₹')} block"
                         + (" (or show the price in a block)" if "₹" in g else ""))
    wc = word_count(s["narration"])
    if not budget * 0.8 <= wc <= budget * 1.35 + 2:
        probs.append(f"narration has {wc} words; write {max(3, -(-budget * 4 // 5))}-{budget + 3} words")
    for j, b in enumerate(s["blocks"]):
        txt = b.get("words") if b["type"] == "headline" else b.get("text")
        if isinstance(txt, str) and b["type"] in MAX_WORDS and word_count(txt) > MAX_WORDS[b["type"]]:
            probs.append(f"block {j} ({b['type']}) text has {word_count(txt)} words; on-screen text must be "
                         f"{MAX_WORDS[b['type']]} words or fewer (a short label, not the narration)")
    texts = [s["narration"]] + [t for _, t in block_texts_all(s["blocks"])]
    odd = sorted({ch for t in texts for ch in t if ord(ch) > 0x24F and ch not in ALLOWED_SYMBOLS})
    if odd:
        probs.append(f"use English (Latin script) only; remove {''.join(odd[:8])!r}")
    for j, b in enumerate(s["blocks"]):
        if b["type"] == "pill" and not re.search(r"[A-Za-z]{2}", str(b.get("text", ""))):
            probs.append(f"block {j} (pill) needs a word label, not just {b.get('text')!r}")
    for p in previous or []:
        if difflib.SequenceMatcher(None, p["narration"].lower(), s["narration"].lower()).ratio() > 0.7:
            probs.append(f"narration repeats scene '{p['id']}'; say something new for this beat")
    if s["purpose"] == "cta":
        dom = fb.domain().split(".")[0] if fb.domain() else ""
        first = (brief.get("cta") or "").split()[:1]
        if dom and dom.lower() not in s["narration"].lower():
            probs.append(f"the CTA narration must say the site '{fb.domain()}'")
        if first and not _word_in(s["narration"], first[0]):
            probs.append(f"the CTA narration must say the call to action '{brief.get('cta')}'")
    cl = verify_storyboard(sb, fb, brief)
    for c in cl["needs_review"]:
        if c["origin"] == "generated":
            probs.append(f"unverified claim {c['text']!r}: {c.get('reason', '')[:120]}. Remove it or use a FACT SHEET item")
    return s, probs, fixes


def _gen_publishing(provider: Provider, prefix: str, sb: dict, brief: dict, fb: FactBase, log: list, seed: int) -> dict | None:
    from .claims import Verifier
    narr = " ".join(s["narration"] for s in sb["scenes"])
    msgs = [{"role": "user", "content": f"{prefix}\nFINAL NARRATION:\n{narr}\n\nWrite YouTube Shorts publishing metadata: a title "
                                        f"(under 70 characters), a 1-2 sentence description ending with https://{fb.domain()}, and 3-6 "
                                        "hashtags. Only verified facts and the brief's price."}]
    v = Verifier(fb, brief)
    for attempt in range(2):
        try:
            r = provider.generate_json(system=SYSTEM, messages=msgs, schema=PUBLISHING_SCHEMA, task="publishing",
                                       context={"brief": brief, "storyboard": sb}, temperature=0.5, seed=seed + attempt, max_tokens=300)
        except LLMError as e:
            log.append({"event": "llm_error", "task": "publishing", "error": e.message}); return None
        bad = [c for k in ("title", "description") for c in v.verify_text(r.data.get(k, ""), k)
               if c.status == "NEEDS_REVIEW" and c.origin == "generated"]
        log.append({"event": "publishing_generated", "attempt": attempt, "stats": r.stats.as_dict(), "schema_errors": r.schema_errors[:5],
                    "invented": [c.text for c in bad]})
        if not r.schema_errors and not bad:
            return r.data
        msgs = msgs + [{"role": "assistant", "content": r.raw},
                       {"role": "user", "content": "Problems: " + "; ".join([*r.schema_errors[:4], *(f"unverified {c.text!r}" for c in bad)]) +
                        ". Return corrected JSON."}]
    return None


def build_storyboard(brief: dict, concept: dict, fb: FactBase, provider: Provider | None = None, *, max_repairs: int = 2,
                     seed: int = 11, log: list | None = None) -> dict:
    """-> {"storyboard", "publishing", "check", "path", "fixes", "log", "scene_sources"}"""
    from .planner import Copy, template_publishing, template_scenes
    log = log if log is not None else []
    pid = concept["pattern"]
    beats = PATTERNS[pid]["beats"]
    tpl = template_scenes(brief, fb, pid, (concept.get("cta_treatment") or {}).get("style"))
    use_llm = provider is not None
    if use_llm:
        ok, why = provider.available()
        if not ok:
            log.append({"event": "llm_unavailable", "reason": why}); use_llm = False
    scenes, sources, fixes = [], [], []
    publishing = None
    if use_llm:
        copy_ = Copy(brief, fb)
        prefix = _prefix(brief, concept, fb)
        tw = [word_count(t["narration"]) for t in tpl]
        want = (brief.get("duration_seconds", 35) - SCENE_GAP * len(beats) - PAD) * WPS
        budgets = [max(4, round(w * want / max(1, sum(tw)))) for w in tw]       # pattern-shaped, duration-scaled
        assigned = assign_requirements(beats, brief)
        for k, beat in enumerate(beats):
            allowed, req = _scene_spec(beat, assigned.get(k, []), copy_.price_verified or not copy_.price_from_brief)
            schema = scene_schema(allowed, budgets[k], req)
            msgs = [{"role": "user", "content": _scene_prompt(prefix, scenes, beat, k, len(beats), _concept_idea(concept, beat, k),
                                                              budgets[k], allowed, req, fb)}]
            got, src = None, None
            for attempt in range(max_repairs + 1):
                try:
                    r = provider.generate_json(system=SYSTEM, messages=msgs, schema=schema, task="scene",
                                               context={"brief": brief, "concept": concept, "index": k, "attempt": attempt},
                                               temperature=0.7 if attempt == 0 else 0.4, seed=seed + 17 * k + attempt, max_tokens=700)
                except LLMError as e:
                    log.append({"event": "llm_error", "scene": k, "attempt": attempt, "error": e.message})
                    if e.code == "LLM_UNAVAILABLE":
                        use_llm = False
                        break
                    continue
                draft_scene = {"id": tpl[k]["id"], "purpose": beat["purpose"], "blocks": scene_blocks(r.data),
                               **{x: r.data[x] for x in ("narration", "mood") if x in r.data}}
                s, probs, fx = check_scene(draft_scene, brief, fb, budgets[k], req, scenes)
                # schema mismatches are logged, not blocking: Ollama enforces the schema with a grammar and
                # compile_draft sanitises; the semantic checks above decide
                log.append({"event": "scene_generated", "scene": k, "attempt": attempt, "stats": r.stats.as_dict(),
                            "schema_errors": r.schema_errors[:5], "problems": probs[:8]})
                if not probs:
                    got, src = s, "llm" if attempt == 0 else f"llm+repair({attempt})"
                    fixes += fx
                    break
                if attempt == max_repairs:
                    fixed, fx2 = autofix({"scenes": [s]})
                    s2, probs2, _ = check_scene(fixed["scenes"][0], brief, fb, budgets[k], req, scenes)
                    if not probs2:
                        got, src = s2, f"llm+repair({attempt})+autofix"
                        fixes += fx + fx2
                    else:
                        log.append({"event": "scene_gave_up", "scene": k, "problems": probs2[:8]})
                    break
                msgs = msgs + [{"role": "assistant", "content": r.raw},
                               {"role": "user", "content": "Problems with this scene:\n- " + "\n- ".join(probs[:10]) +
                                "\nReturn the corrected scene JSON."}]
            if got is None:
                got, src = tpl[k], "template"
            scenes.append(got)
            sources.append(src)
            if not use_llm:
                scenes += tpl[k + 1:]
                sources += ["template"] * (len(tpl) - k - 1)
                break
        if use_llm:
            draft_sb, _ = compile_draft({"scenes": scenes}, brief, fb, pattern=pid)
            publishing = _gen_publishing(provider, prefix, draft_sb, brief, fb, log, seed + 999)
        provider.unload()
    else:
        scenes, sources = tpl, ["template"] * len(tpl)
    c = Copy(brief, fb)
    draft = {"title": f"{brief['brand']} — {concept.get('name', PATTERNS[pid]['name'])}", "structure": structure_for(pid), "scenes": scenes}
    sb, fx = compile_draft(draft, brief, fb, pattern=pid)
    fixes += fx
    pub_src = "llm" if publishing else "template"
    publishing = publishing or template_publishing(brief, fb, c)
    tags = ["#" + re.sub(r"\W", "", str(h)) for h in publishing.get("hashtags", [])]
    publishing = {**publishing, "hashtags": list(dict.fromkeys(t for t in tags if len(t) > 2))[:8]}
    chk = check(sb, brief, fb, publishing)
    n_llm = sum(s != "template" for s in sources)
    if n_llm == 0:
        path = "template" if provider is None or any(e["event"] == "llm_unavailable" for e in log) else "template (llm fallback)"
    elif n_llm == len(sources):
        path = "llm" if all(s == "llm" for s in sources) else "llm+repair"
    else:
        path = f"llm+template({len(sources) - n_llm}/{len(sources)} scenes)"
    log.append({"event": "storyboard_done", "path": path, "scene_sources": sources, "publishing": pub_src, "problems": _problems(chk)})
    return {"storyboard": sb, "publishing": publishing, "check": chk, "path": path, "fixes": fixes, "log": log,
            "scene_sources": sources, "publishing_source": pub_src}
