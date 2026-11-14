"""Effects director: chooses effect transitions and word-anchored emphasis effects for a NEW concept's storyboard.

Taste rules (restraint):
  * the mood comes from the scene's motion preset (template), else the concept's music mood:
      energetic  → whip-pan / push transitions; punch-zoom on the key word, shake when a stamp lands, burst on a count
      cinematic  → zoom-through / light-leak transitions; tilt-in of recordings and devices, draw-on circle
      standard   → push / iris on a few cuts; circle or burst on the key moment, cursor clicks in recordings
      calm       → the template's own transition; at most a draw-on circle
  * at most ONE emphasis effect per scene (cursor clicks and tilt entrances are demo moves, not emphasis);
  * never the same effect transition twice in a row; flash and glitch at most twice per video (light leaks count as
    flashes, and the photosensitivity guard keeps ≤ 3 flashes in any second);
  * every effect is anchored to a time expression that already exists in the scene (a block's own `@word:` cue), so
    nothing can appear before its word, and numbers are only ever emphasised after they have landed.
Only concepts that carry `concept["effects"]` (set for new concepts by director.plan_concept) get effects, so
storyboards of existing concepts are rebuilt byte-identically."""
from __future__ import annotations

import re

from ..effects import EMPHASIS, MAX_FLASH_PER_VIDEO, MAX_GLITCH_PER_VIDEO

VERSION = 1
STYLES = ("energetic", "cinematic", "standard", "calm")
MUSIC_STYLE = {"energetic": "energetic", "technology": "energetic", "cinematic": "cinematic",
               "educational": "standard", "corporate": "standard"}
# transition cycles per style (scene 2..n); the first scene keeps its fade
CYCLE = {
    "energetic": [("whip-pan", "left"), ("push", None), ("whip-pan", "right"), ("zoom-through", None)],
    "cinematic": [("zoom-through", None), ("light-leak", None), ("zoom-through", None), ("iris", None)],
    "standard": [("push", None), (None, None), ("iris", None), (None, None)],
    "calm": [(None, None)],
}
FOOTAGE_LIKE = ("footage", "device")


def concept_style(music_mood: str | None) -> str:
    return MUSIC_STYLE.get(music_mood or "", "standard")


def scene_style(sc: dict, video_style: str) -> str:
    m = sc.get("motion")
    if m in ("energetic", "cinematic", "calm"):
        return m
    return video_style


def _word(w: str) -> str | None:
    """A narration token as an `@word:` anchor (punctuation stripped; None if it cannot be one)."""
    x = re.sub(r"[^\w'₹$%]", "", w or "")
    return x if x and re.fullmatch(r"[^+\-#\s]+", x) else None


def _off(expr, off: float):
    """Offset a time expression (string or number) by `off` seconds."""
    if isinstance(expr, (int, float)):
        return round(expr + off, 3)
    m = re.match(r"^(.*?)([+-]\d+(?:\.\d+)?)?$", expr)
    base, cur = m.group(1), float(m.group(2) or 0)
    v = round(cur + off, 3)
    return base if v == 0 else f"{base}{'+' if v > 0 else '-'}{abs(v):g}"


def _key_moment(sc: dict, style: str) -> dict | None:
    """The one emphasis effect of a scene (or None), anchored on an existing cue of its blocks."""
    blocks = sc["blocks"]
    for i, b in enumerate(blocks):
        ty = b.get("type")
        if ty in ("counter", "plan-card", "price") and "at" in b:
            if style == "calm":
                return None
            land = b.get("countEnd") or _off(b["at"], 0.8)
            return {"type": "burst", "at": land, "target": i, "count": 26 if style == "energetic" else 18,
                    **({"spread": "up"} if style != "energetic" else {})}
        if ty == "composition" and any(e.get("kind") == "number" for e in b.get("elements", [])) and style in ("energetic", "standard"):
            el = next(e for e in b["elements"] if e.get("kind") == "number")
            if "at" in el:
                return {"type": "burst", "at": el.get("countEnd") or _off(el["at"], 0.8), "target": i, "count": 18}
    for i, b in enumerate(blocks):
        if b.get("type") == "pill" and b.get("stamp") and "at" in b and style == "energetic":
            return {"type": "shake", "at": _off(b["at"], 0.08), "amp": 6}
    for i, b in enumerate(blocks):
        if b.get("type") != "kinetic-text" or not b.get("emphasis") or not isinstance(b.get("words"), str):
            continue
        w = _word(b["emphasis"][0])
        if not w:
            continue
        if style == "energetic":
            # a kick on the scene's very last word would still be settling at the cut (and at the QA sample just before
            # it): then the line's first word gets the kick instead
            last = _word((sc.get("narration") or "").split()[-1:] and sc["narration"].split()[-1])
            if last and last.lower() == w.lower():
                # ... the line's first word that carries meaning (≥ 4 letters), else no kick
                alt = next((x for x in map(_word, b["words"].split()[:-1]) if x and len(x) >= 4), None)
                if not alt:
                    continue
                w = alt
            return {"type": "punch-zoom", "at": f"@word:{w}", "scale": 1.06}
        if style in ("standard", "cinematic", "calm"):
            # the polished look already underlines kinetic emphasis words: a hand-drawn circle adds a second gesture
            return {"type": "annotate", "kind": "circle", "target": i, "text": b["emphasis"][0].strip(".,!?;:"),
                    "at": f"@word:{w}"}
    return None


def _demo_moves(sc: dict, style: str) -> list[dict]:
    """Cursor click on the first zoom of a recording; tilt-in of a recording / device frame (not in calm scenes)."""
    if style == "calm":
        return []
    out = []
    for i, b in enumerate(sc["blocks"]):
        if b.get("type") not in FOOTAGE_LIKE:
            continue
        if style in ("cinematic", "standard", "energetic") and len(sc["blocks"]) <= 2:
            out.append({"type": "tilt", "target": i, **({"rx": 8, "ry": -12} if style != "cinematic" else {})})
        zs = [z for z in b.get("zooms", []) if z.get("scale", 1) > 1.05 and "at" in z]
        if b.get("type") == "footage" and zs and style in ("standard", "energetic"):
            out.append({"type": "cursor", "target": i, "at": zs[0]["at"]})
        break
    return out


def plan(sb: dict, fx: dict) -> dict:
    """Add effect transitions + effects to the scenes of a freshly composed storyboard (in place). -> sb"""
    video_style = fx.get("style") if fx.get("style") in STYLES else "standard"
    prev_tr, flashes, glitches, k_cycle = sb["scenes"][0].get("transition"), 0, 0, 0
    for k, sc in enumerate(sb["scenes"]):
        style = scene_style(sc, video_style)
        effects: list[dict] = []
        if k > 0:
            cyc = CYCLE[style]
            cand = [cyc[(k_cycle + j) % len(cyc)] for j in range(len(cyc))]
            if sc.get("purpose") == "cta" and style != "calm":
                cand = [("light-leak", None) if style == "cinematic" else ("iris", None)] + cand
            for tr, d in cand:
                if tr is None:
                    break                                 # keep the template's own transition on this cut
                if tr == prev_tr:
                    continue                              # never the same effect transition twice in a row
                if tr == "light-leak" and flashes >= MAX_FLASH_PER_VIDEO:
                    continue
                if tr == "glitch" and glitches >= MAX_GLITCH_PER_VIDEO:
                    continue
                sc["transition"] = tr
                sc.pop("transitionDir", None)
                if d:
                    sc["transitionDir"] = d
                flashes += tr == "light-leak"
                glitches += tr == "glitch"
                break
            k_cycle += 1
        km = _key_moment(sc, style)
        if km:
            effects.append(km)
        if any(b.get("type") == "logo-sting" for b in sc["blocks"]) and style == "energetic" and flashes < MAX_FLASH_PER_VIDEO \
                and not any(e["type"] in EMPHASIS for e in effects):
            b = next(b for b in sc["blocks"] if b.get("type") == "logo-sting")
            if "at" in b:
                effects.append({"type": "flash", "at": _off(b["at"], 0.25), "intensity": 0.28})
                flashes += 1
        effects += _demo_moves(sc, style)
        if effects:
            sc["effects"] = effects
        prev_tr = sc.get("transition")
    if video_style != "calm":
        sb["beatSync"] = True
    return sb
