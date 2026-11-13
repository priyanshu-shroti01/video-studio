"""Storyboard schema, validation and timeline resolution.

A storyboard is a list of scenes (purpose, narration, blocks, cues, sfx). Times inside blocks are
*expressions*, resolved against the real TTS word timings of that scene:

  1.2                 seconds after the scene's first spoken word
  "@start" / "@end"   scene start / scene end;  "@speech_end" = scene's last word end
  "@stop"             a named cue from scene.cues ({"word": "stop"} / {"word": "renewal", "nth": 2} / {"at": "@x+0.3"})
  "@word:triple"      first occurrence of a narration word in this scene (also "@word:renewal#2")
  any of the above with an offset: "@word:grow+0.45", "@end-0.3"

Resolution produces the RenderProps scenes (absolute seconds) and the SFX event list, so picture
and sound are driven by the same numbers."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from .contract import (BLOCK_TYPES, COMPOSITION_COLORS, COMPOSITION_KINDS, COMPOSITION_MOTIONS, COMPOSITION_ROLES,
                       COMPOSITION_SHAPES, ICONS, TIME_KEYS, TONES)
from .errors import ConfigError, TimingError
from .schema import validate
from .timing import Word, forms, norm, tokenize

PURPOSES = ["intro", "hook", "problem", "turn", "journey", "point", "example", "resolution", "cta", "conclusion", "custom"]
EXPR = re.compile(r"^@(start|end|speech_end|word:[^+\-#\s]+(?:#\d+)?|[A-Za-z_][\w-]*)([+-]\d+(?:\.\d+)?)?$")
KEY_RHYTHM = [2, 2, 3, 2, 2, 2, 3, 2, 2, 3, 2, 2]  # frames per keystroke (human, not metronomic)

TIME = {"type": ["number", "string"]}
SCENE_SCHEMA = {
    "type": "object",
    "required": ["id", "purpose", "narration", "blocks"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_-]{0,40}$"},
        "purpose": {"type": "string", "enum": PURPOSES},
        "narration": {"type": "string", "minLength": 1, "maxLength": 1500},
        "mood": {"type": "string", "enum": ["neutral", "danger", "brand"]},
        "transition": {"type": "string", "enum": ["fade", "slide-up", "none", "mask-wipe", "gradient-sweep"]},
        "camera": {"type": "string", "enum": ["none", "push-in", "pan-left", "pan-right", "drift"]},
        "backdrop": {"type": "string", "enum": ["glow", "spotlight", "grid", "split", "light", "deep"]},
        "motion": {"type": "string", "enum": ["calm", "standard", "energetic", "cinematic"]},
        "layout": {"type": "string", "enum": ["stack", "split"]},
        "splitAt": {"type": "integer", "minimum": 1},
        "splitRatio": {"type": "number", "minimum": 0.3, "maximum": 0.7},
        "brandBar": {"type": "boolean"},
        "cues": {"type": "object", "additionalProperties": {"type": "object"}},
        "blocks": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["type"]}},
        "sfx": {"type": "array", "items": {"type": "object", "required": ["at", "sound"],
                                            "properties": {"at": TIME, "sound": {"type": "string"},
                                                           "gain": {"type": "number", "minimum": -40, "maximum": 6}}}},
        "autoSfx": {"type": "boolean"},
        # seconds of silence after this scene's last word, so a visual payoff (install finished, domain
        # available) plays out on screen before the next scene starts
        "holdAfter": {"type": "number", "minimum": 0, "maximum": 3},
    },
}
STORYBOARD_SCHEMA = {
    "type": "object",
    "required": ["scenes"],
    "properties": {
        "version": {"type": "integer"},
        "title": {"type": "string"},
        "structure": {"type": "array", "items": {"type": "string", "enum": PURPOSES}},
        "scenes": {"type": "array", "minItems": 1, "items": SCENE_SCHEMA},
    },
}


# contract v2 block requirements (src/engine/types.ts)
REQUIRED = {"kinetic-text": ["words"], "counter": ["to"], "price-compare": ["columns", "rows"], "terminal": ["lines"],
            "dashboard": ["stats"], "device": ["frame"], "image": ["asset"], "progress": ["steps"],
            "scroll-demo": ["url", "sections", "scrollEnd"], "chart": ["kind", "data"],
            "feature-compare": ["columns", "rows"], "outro": ["url"],
            "plan-card": ["name", "price", "features"], "install-flow": ["app", "steps", "doneAt", "doneText"],
            "server-stack": ["nodes"], "footage": ["asset"], "composition": ["elements"]}
FOOTAGE_FRAMES = ("browser", "laptop", "phone", "none")
FOOTAGE_EXTS = (".mp4", ".webm")
FOOTAGE_ZOOM_MAX = 4.0          # src/engine/geometry-footage.ts FOOTAGE.zoomMax
FOOTAGE_RATE_MAX = 4.0
BRANDING_BLOCKS = ("logo", "cta", "logo-sting", "outro")
HERO_BLOCKS = {"browser", "bars", "compare-rows", "plans", "domain-input", "hook-tag", "flat-line", "price", "logo", "cta",
               "counter", "price-compare", "terminal", "dashboard", "device", "image", "progress", "scroll-demo", "chart",
               "feature-compare", "logo-sting", "outro", "plan-card", "install-flow", "server-stack", "kinetic-text",
               "checklist", "footage", "composition"}


def validate_storyboard(sb: dict, *, structure: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Static validation (before any TTS). Returns (errors, warnings)."""
    errors = validate(sb, STORYBOARD_SCHEMA, "$storyboard")
    warnings: list[str] = []
    if errors:
        return errors, warnings
    ids = [s["id"] for s in sb["scenes"]]
    if len(ids) != len(set(ids)):
        errors.append("$storyboard: scene ids must be unique")
    for si, sc in enumerate(sb["scenes"]):
        p = f"$storyboard.scenes[{si}]({sc['id']})"
        cues = sc.get("cues", {})
        for name, spec in cues.items():
            if not ({"word", "at"} & set(spec)):
                errors.append(f"{p}.cues.{name}: needs 'word' or 'at'")
        for bi, b in enumerate(sc["blocks"]):
            bp = f"{p}.blocks[{bi}]"
            if b["type"] not in BLOCK_TYPES:
                errors.append(f"{bp}: unknown block type {b['type']!r}")
                continue
            for path, key, val in _walk_times(b):
                if isinstance(val, str):
                    m = EXPR.match(val)
                    if not m:
                        errors.append(f"{bp}{path}.{key}: bad time expression {val!r}")
                    elif m.group(1) not in ("start", "end", "speech_end") and not m.group(1).startswith("word:") \
                            and m.group(1) not in cues:
                        errors.append(f"{bp}{path}.{key}: unknown cue '@{m.group(1)}'")
                    elif m.group(1).startswith("word:") and not _word_in(sc["narration"], m.group(1)[5:].split("#")[0]):
                        errors.append(f"{bp}{path}.{key}: word {m.group(1)[5:]!r} is not in this scene's narration")
            for tone in _find_key(b, "tone"):
                if tone not in TONES:
                    errors.append(f"{bp}: unknown tone {tone!r}")
            for icon in _find_key(b, "icon"):
                if icon not in ICONS:
                    errors.append(f"{bp}: unknown icon {icon!r}")
            if b["type"] == "domain-input" and "typeAt" not in b and "keyTimes" not in b:
                errors.append(f"{bp}: domain-input needs 'typeAt' (or explicit keyTimes)")
            for k in REQUIRED.get(b["type"], []):
                if k not in b:
                    errors.append(f"{bp}: {b['type']} needs '{k}'")
            if b["type"] in ("price-compare", "feature-compare") and isinstance(b.get("rows"), list):
                n = len(b.get("columns", []))
                for ri, row in enumerate(b["rows"]):
                    if len(row.get("values", [])) != n:
                        errors.append(f"{bp}.rows[{ri}]: {len(row.get('values', []))} values for {n} columns")
            if b["type"] == "device" and not (b.get("asset") or b.get("screen")):
                errors.append(f"{bp}: device needs 'asset' or 'screen'")
            if b["type"] == "chart" and b.get("kind") not in (None, "bar", "line"):
                errors.append(f"{bp}: chart kind must be bar or line")
            if b["type"] == "footage":
                errors += _footage_errors(b, bp)
            if b["type"] == "composition":
                errors += composition_errors(b, bp)
        for k, ev in enumerate(sc.get("sfx", [])):
            if isinstance(ev["at"], str) and not EXPR.match(ev["at"]):
                errors.append(f"{p}.sfx[{k}].at: bad time expression {ev['at']!r}")
    order = [s["purpose"] for s in sb["scenes"]]
    want = sb.get("structure") or structure
    if want:
        pos = [want.index(x) for x in order if x in want]
        if pos != sorted(pos):
            warnings.append(f"scene purposes {order} do not follow the intended structure {want}")
        missing = [x for x in want if x not in order]
        if missing:
            warnings.append(f"structure is missing: {missing}")
    if not any(b["type"] in BRANDING_BLOCKS for s in sb["scenes"] for b in s["blocks"]) and \
            not any(s.get("brandBar") for s in sb["scenes"]):
        warnings.append("no branding (logo / cta block / brandBar) anywhere in the storyboard")
    return errors, warnings


def _footage_errors(b: dict, bp: str) -> list[str]:
    """Static checks of a footage block (file checks + ffprobe aspect/duration fill: pipeline/footage.py)."""
    errs = []
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v == v  # noqa: E731
    asset = b.get("asset")
    if "asset" in b and (not isinstance(asset, str) or not asset.lower().endswith(FOOTAGE_EXTS)):
        errs.append(f"{bp}: footage asset must be a public/ path to a {' / '.join(FOOTAGE_EXTS)} video, got {asset!r}")
    if b.get("frame", "browser") not in FOOTAGE_FRAMES:
        errs.append(f"{bp}: footage frame must be one of {FOOTAGE_FRAMES}")
    for k in ("title", "caption"):
        if k in b and not isinstance(b[k], str):
            errs.append(f"{bp}: footage {k} must be a string")
    for k in ("aspect", "duration"):
        if k in b and not (num(b[k]) and b[k] > 0):
            errs.append(f"{bp}: footage {k} must be a positive number")
    if "startFrom" in b and not (num(b["startFrom"]) and b["startFrom"] >= 0):
        errs.append(f"{bp}: footage startFrom must be seconds >= 0")
    if "playbackRate" in b and not (num(b["playbackRate"]) and 0 < b["playbackRate"] <= FOOTAGE_RATE_MAX):
        errs.append(f"{bp}: footage playbackRate must be in (0, {FOOTAGE_RATE_MAX:g}]")
    zooms = b.get("zooms", [])
    if not isinstance(zooms, list):
        return errs + [f"{bp}: footage zooms must be a list"]
    for i, z in enumerate(zooms):
        zp = f"{bp}.zooms[{i}]"
        if not isinstance(z, dict) or not {"at", "x", "y", "scale"} <= set(z):
            errs.append(f"{zp}: needs at, x, y and scale")
            continue
        for k in ("x", "y"):
            if not (num(z[k]) and 0 <= z[k] <= 1):
                errs.append(f"{zp}.{k}: must be a normalised position 0..1")
        if not (num(z["scale"]) and 1 <= z["scale"] <= FOOTAGE_ZOOM_MAX):
            errs.append(f"{zp}.scale: must be between 1 and {FOOTAGE_ZOOM_MAX:g}")
    return errs


COMPOSITION_MAX_ELEMENTS = 64        # src/engine/geometry-composition.ts COMPOSITION.maxElements
COMPOSITION_ASPECT = (0.4, 3.0)      # COMPOSITION.aspectMin / aspectMax
COMPOSITION_MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")


def composition_errors(b: dict, bp: str) -> list[str]:
    """Static checks of a composition block (generated scene graphic). Geometry is normalised (0..1 of the canvas),
    colours are theme tokens only (never raw colours), connectors must join existing elements."""
    errs: list[str] = []
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v == v  # noqa: E731
    els = b.get("elements")
    if not isinstance(els, list) or not els:
        return [f"{bp}: composition needs a non-empty elements list"]
    if len(els) > COMPOSITION_MAX_ELEMENTS:
        errs.append(f"{bp}: composition has {len(els)} elements (max {COMPOSITION_MAX_ELEMENTS})")
    canvas = b.get("canvas", {})
    if not isinstance(canvas, dict) or set(canvas) - {"tall", "wide"} or \
            any(not (num(v) and COMPOSITION_ASPECT[0] <= v <= COMPOSITION_ASPECT[1]) for v in canvas.values()):
        errs.append(f"{bp}: composition canvas must be {{tall?, wide?}} aspects in {COMPOSITION_ASPECT}")
    if "design" in b and not (isinstance(b["design"], dict) and all(isinstance(v, str) for v in b["design"].values())):
        errs.append(f"{bp}: composition design must map names to strings")
    ids = [e.get("id") for e in els if isinstance(e, dict) and e.get("id") is not None]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not i for i in ids):
        errs.append(f"{bp}: composition element ids must be unique non-empty strings")
    known = set(ids)
    for i, e in enumerate(els):
        ep = f"{bp}.elements[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{ep}: must be an object"); continue
        kind = e.get("kind")
        if kind not in COMPOSITION_KINDS:
            errs.append(f"{ep}: kind must be one of {sorted(COMPOSITION_KINDS)}"); continue
        for key in ("box", "wide"):
            if key == "wide" and key not in e:
                continue
            bx = e.get(key)
            ok = isinstance(bx, list) and len(bx) == 4 and all(num(v) for v in bx)
            if ok:
                x, y, w, h = bx
                ok = 0 <= x <= 1 and 0 <= y <= 1 and 0 <= w <= 1 and 0 <= h <= 1 and x + w <= 1.0001 and y + h <= 1.0001 \
                    and (kind == "connector" or (w > 0 and h > 0))
            if not ok:
                errs.append(f"{ep}.{key}: must be [x, y, w, h] inside the 0..1 canvas")
        for key in ("color", "fill", "stroke"):
            if key in e and e[key] not in COMPOSITION_COLORS:
                errs.append(f"{ep}.{key}: {e[key]!r} is not a theme colour token {sorted(COMPOSITION_COLORS)}")
        if "motion" in e and e["motion"] not in COMPOSITION_MOTIONS:
            errs.append(f"{ep}.motion: must be one of {sorted(COMPOSITION_MOTIONS)}")
        if "opacity" in e and not (num(e["opacity"]) and 0 <= e["opacity"] <= 1):
            errs.append(f"{ep}.opacity: must be 0..1")
        if "strokeW" in e and not (num(e["strokeW"]) and 1 <= e["strokeW"] <= 40):
            errs.append(f"{ep}.strokeW: must be 1..40 design px")
        if kind == "text":
            if not isinstance(e.get("text"), str) or not e["text"].strip():
                errs.append(f"{ep}: text element needs a non-empty 'text'")
            if e.get("role", "label") not in COMPOSITION_ROLES:
                errs.append(f"{ep}.role: must be one of {sorted(COMPOSITION_ROLES)}")
            if e.get("align", "center") not in ("left", "center", "right"):
                errs.append(f"{ep}.align: must be left, center or right")
        elif kind == "shape":
            if e.get("shape") not in COMPOSITION_SHAPES:
                errs.append(f"{ep}.shape: must be one of {sorted(COMPOSITION_SHAPES)}")
            if "sweep" in e and not (num(e["sweep"]) and 0 < e["sweep"] <= 360):
                errs.append(f"{ep}.sweep: must be degrees in (0, 360]")
            if "start" in e and not num(e["start"]):
                errs.append(f"{ep}.start: must be degrees")
        elif kind == "connector":
            if e.get("fromId") not in known or e.get("toId") not in known or e.get("fromId") == e.get("toId"):
                errs.append(f"{ep}: connector needs fromId/toId naming two different elements")
            if "curve" in e and not (num(e["curve"]) and -1 <= e["curve"] <= 1):
                errs.append(f"{ep}.curve: must be -1..1")
        elif kind == "icon":
            if e.get("icon") not in ICONS:
                errs.append(f"{ep}: icon element needs a known icon")
        elif kind == "number":
            if not num(e.get("to")):
                errs.append(f"{ep}: number element needs a numeric 'to'")
            if "from" in e and not num(e["from"]):
                errs.append(f"{ep}.from: must be a number")
            if "decimals" in e and e["decimals"] not in (0, 1, 2, 3):
                errs.append(f"{ep}.decimals: must be 0..3")
            if e.get("grouping", "none") not in ("none", "western", "indian"):
                errs.append(f"{ep}.grouping: must be none, western or indian")
            for k in ("prefix", "suffix"):
                if k in e and not isinstance(e[k], str):
                    errs.append(f"{ep}.{k}: must be a string")
        elif kind == "logo":
            if e.get("variant", "onDark") not in ("onDark", "onLight", "mark"):
                errs.append(f"{ep}.variant: must be onDark, onLight or mark")
        elif kind == "media":
            a = e.get("asset")
            if not isinstance(a, str) or not a.lower().endswith(COMPOSITION_MEDIA_EXTS):
                errs.append(f"{ep}: media element needs a public/ image asset {COMPOSITION_MEDIA_EXTS}")
    return errs


def word_matches(token: str, w: str) -> bool:
    """A cue word matches a script token if their forms agree ("49" ~ "forty-nine") or it equals one
    part of a compound token ("shrotihost" in "shrotihost.in.")."""
    if forms(token) & forms(w):
        return True
    return norm(w) in {norm(x) for x in re.split(r"[^\w']+", token) if x}


def _word_in(narration: str, w: str) -> bool:
    return any(word_matches(t, w) for t in tokenize(narration))


def _walk_times(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TIME_KEYS and isinstance(v, (int, float, str)):
                yield path, k, v
            elif isinstance(v, (dict, list)):
                yield from _walk_times(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_times(v, f"{path}[{i}]")


def _find_key(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, str):
                yield v
            else:
                yield from _find_key(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find_key(v, key)


# ---------------------------------------------------------------------------------------------
@dataclass
class SceneTiming:
    id: str
    start: float          # scene visible from
    end: float            # scene gone at
    speech_start: float
    speech_end: float
    words: list[Word]     # absolute, this scene only


class Resolver:
    def __init__(self, st: SceneTiming, cues: dict):
        self.st, self.cues_spec, self.cache = st, cues, {}

    def word_time(self, w: str, nth: int = 1) -> float:
        n = 0
        for x in self.st.words:
            if word_matches(x.text, w):
                n += 1
                if n == nth:
                    return x.start
        raise TimingError(f"scene {self.st.id}: word {w!r} (#{nth}) not spoken in this scene")

    def cue(self, name: str) -> float:
        if name in self.cache:
            return self.cache[name]
        spec = self.cues_spec.get(name)
        if spec is None:
            raise TimingError(f"scene {self.st.id}: unknown cue @{name}")
        self.cache[name] = -1e9  # cycle guard
        t = self.word_time(spec["word"], spec.get("nth", 1)) if "word" in spec else self.time(spec["at"])
        t += float(spec.get("offset", 0))
        self.cache[name] = t
        return t

    def time(self, v) -> float:
        if isinstance(v, (int, float)):
            return self.st.speech_start + float(v)
        m = EXPR.match(v)
        if not m:
            raise TimingError(f"bad time expression {v!r}")
        base, off = m.group(1), float(m.group(2) or 0)
        if base == "start":
            t = self.st.start
        elif base == "end":
            t = self.st.end
        elif base == "speech_end":
            t = self.st.speech_end
        elif base.startswith("word:"):
            w, _, nth = base[5:].partition("#")
            t = self.word_time(w, int(nth or 1))
        else:
            t = self.cue(base)
        if t < -1e8:
            raise TimingError(f"cue cycle at {v!r}")
        return round(t + off, 3)


def resolve_block(b: dict, R: Resolver, idx: int, fps: int) -> dict:
    out = copy.deepcopy(b)
    out.pop("typeAt", None)

    def rec(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k in TIME_KEYS and isinstance(v, (int, float, str)):
                    o[k] = R.time(v)
                else:
                    rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(out)
    if "at" not in out:
        out["at"] = round(R.st.start + 0.1 + idx * 0.12, 3)
    if out["type"] in ("headline", "kinetic-text") and isinstance(out.get("words"), str):
        # "words": "Building a website in India?" -> each word revealed as it is spoken (falls back to stagger)
        tones = out.pop("tones", {})
        emphasis = {forms_key for w in out.pop("emphasis", []) for forms_key in forms(w)}
        ws, t_prev = [], out["at"]
        for k, w in enumerate(out["words"].split()):
            try:
                t = R.word_time(w, 1 + sum(1 for x in out["words"].split()[:k] if forms(x) & forms(w)))
                t = max(t - 0.06, t_prev)
            except TimingError:
                t = t_prev + 0.12
            ws.append({"text": w, "at": round(t, 3), **({"tone": tones[w]} if w in tones else {}),
                       **({"emphasis": True} if out["type"] == "kinetic-text" and forms(w) & emphasis else {})})
            t_prev = t
        out["words"] = ws
    if out["type"] == "domain-input" and "keyTimes" not in out:
        t0 = R.time(b["typeAt"])
        f = round(t0 * fps)
        kt = []
        for k, _ in enumerate(out["domain"]):
            kt.append(round(f / fps, 3)); f += KEY_RHYTHM[k % len(KEY_RHYTHM)]
        out["keyTimes"] = kt
        out.setdefault("availableAt", round(kt[-1] + 0.25, 3))
    return out


def auto_sfx(scene_i: int, sc: SceneTiming, blocks: list[dict], snd: dict) -> list[dict]:
    """Default sound conventions per block event (from the brand theme's `sfx` section)."""
    ev = []
    g = snd.get("gains", {})

    def add(t, kind, sound=None, gain=None):
        pool = snd.get(kind)
        if sound is None:
            if not pool:
                return
            sound = pool[len([e for e in ev if e["kind"] == kind]) % len(pool)] if isinstance(pool, list) else pool
        ev.append({"t": round(t, 3), "sound": sound, "gain": gain if gain is not None else g.get(kind, -12), "kind": kind})

    if scene_i > 0:
        add(sc.start + 0.1, "transition")
    for b in blocks:
        t, ty = b.get("at", sc.start), b["type"]
        if ty == "pill":
            add(t + 0.08, "impact" if b.get("stamp") else "appear")
        elif ty == "logo":
            add(t + 0.25, "impact"); add(t + 0.27, "success")
        elif ty == "price":
            end = b.get("countEnd", t + 0.5)
            for k in range(5):
                add(t + k * (end - t) / 5, "tick")
            add(end, "appear")
        elif ty == "checklist":
            for it in b["items"]:
                add(it["at"], "appear")
        elif ty == "bars":
            for bar in b["bars"]:
                add(bar.get("growEnd", bar["at"] + 0.5) - 0.1, "whoosh")
            if b.get("badge"):
                add(b["badge"]["at"], "impact")
        elif ty == "compare-rows":
            for r in b["rows"]:
                add(r["at"], "success")
            if b.get("badge"):
                add(b["badge"]["at"], "success")
        elif ty == "plans":
            for k in range(len(b["plans"])):
                add(t + 0.08 + 0.1 * k, "appear")
            if b.get("select"):
                add(b["select"]["clickAt"], "click")
        elif ty == "domain-input":
            for kt in b["keyTimes"]:
                add(kt, "keys")
            add(b["availableAt"], "success")
            add(b["button"]["clickAt"], "click")
            add(b["button"]["doneAt"], "success")
        elif ty == "browser" and b.get("tag"):
            add(b["tag"]["at"], "appear")
        elif ty == "hook-tag":
            add(t + 0.05, "whoosh")
        elif ty == "flat-line":
            add(b["drawEnd"], "success")
        elif ty == "cta":
            add(t, "whoosh"); add(b["urlAt"], "shimmer")
            if b.get("clickAt"):
                add(b["clickAt"], "click")
        elif ty == "headline" and b.get("strike"):
            add(b["strike"]["at"] + 0.1, "whoosh")
        # contract v2 blocks
        elif ty == "terminal":
            for ln in b.get("lines", []):
                if ln.get("kind", "out") == "cmd":
                    end = ln.get("typeEnd", ln["at"] + 0.06 * len(ln["text"]))
                    n = max(1, min(len(ln["text"]), int((end - ln["at"]) / 0.07)))
                    for k in range(n):
                        add(ln["at"] + k * (end - ln["at"]) / n, "keys")
                elif ln.get("kind") == "ok":
                    add(ln["at"], "success")
        elif ty == "counter":
            end = b.get("countEnd", t + 0.8)
            for k in range(5):
                add(t + k * (end - t) / 5, "tick")
        elif ty in ("price-compare", "feature-compare"):
            for r in b.get("rows", []):
                add(r["at"], "success")
            if b.get("winnerAt") or b.get("highlightAt"):
                add(b.get("winnerAt") or b.get("highlightAt"), "impact")
        elif ty == "logo-sting":
            add(t + 0.25, "impact"); add(t + 0.3, "shimmer")
        elif ty == "outro":
            add(b.get("urlAt", t + 0.6), "shimmer")
        elif ty == "progress":
            for st_ in b.get("steps", []):
                add(st_["at"], "appear")
        elif ty in ("chart", "dashboard"):
            ge = b.get("growEnd") or (b.get("chart") or {}).get("growEnd")
            add((ge or t + 0.9) - 0.1, "whoosh")
        elif ty == "composition":                    # generated graphic: a whoosh, then a soft pop per item label
            add(t + 0.05, "whoosh")
            items = [e for e in b.get("elements", []) if e.get("kind") == "text" and e.get("role", "label") == "label"
                     and isinstance(e.get("at"), (int, float))]
            for e in items[:6]:
                add(e["at"], "appear")
            for e in b.get("elements", []):
                if e.get("kind") == "number" and isinstance(e.get("at"), (int, float)):
                    end = e.get("countEnd", e["at"] + 0.8)
                    for k in range(5):
                        add(e["at"] + k * (end - e["at"]) / 5, "tick")
        elif ty in ("image", "device", "kinetic-text", "scroll-demo", "footage"):
            add(t + 0.05, "whoosh" if ty in ("image", "device", "scroll-demo", "footage") else "appear")
    return ev
