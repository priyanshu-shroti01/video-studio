"""Scene effects (render contract, additive, same CONTRACT_VERSION): effect transitions and word-anchored emphasis
effects. Python mirror of src/engine/motion/effects.ts + fx-transitions.ts (limits only), static validation, time
resolution (`@word:` anchors, like block times) and the restraint / photosensitivity rules.

Storyboard (per scene):
  "transition": "whip-pan" | "zoom-through" | "push" | "iris" | "light-leak" | "glitch"  (+ the classic ones)
  "transitionDir": "left" | "right" | "up" | "down"                                 (whip-pan / push)
  "effects": [{"type": "punch-zoom", "at": "@word:minutes"}, {"type": "annotate", "kind": "underline",
               "target": 1, "text": "₹149", "at": "@word:149"}, ...]

Scenes without `effects` and with classic transitions are untouched (the props are byte-identical)."""
from __future__ import annotations

import copy
import re

FX_TRANSITIONS = ("whip-pan", "zoom-through", "push", "iris", "light-leak", "glitch")
CLASSIC_TRANSITIONS = ("fade", "slide-up", "none", "mask-wipe", "gradient-sweep")
TRANSITIONS = CLASSIC_TRANSITIONS + FX_TRANSITIONS
DIRS = ("left", "right", "up", "down")
EFFECT_TYPES = ("punch-zoom", "shake", "flash", "burst", "annotate", "cursor", "tilt")
ANNOTATE_KINDS = ("underline", "circle", "arrow")
# emphasis effects (restraint: at most one per scene by default); cursor / tilt are demo moves, not emphasis
EMPHASIS = {"punch-zoom", "shake", "flash", "burst", "annotate"}
# numeric limits (src/engine/motion/effects.ts FX)
LIMITS = {"punch-zoom": {"scale": (1.01, 1.12), "dur": (0.25, 1.5)},
          "shake": {"amp": (0.0, 8.0), "dur": (0.1, 0.8)},
          "flash": {"intensity": (0.0, 0.45)},
          "burst": {"count": (4, 40)},
          "annotate": {"dur": (0.2, 1.5)},
          "cursor": {"x": (0.0, 1.0), "y": (0.0, 1.0)},
          "tilt": {"rx": (-25.0, 25.0), "ry": (-25.0, 25.0), "dur": (0.3, 2.0)}}
FIELDS = {"punch-zoom": {"type", "at", "scale", "dur"}, "shake": {"type", "at", "amp", "dur"},
          "flash": {"type", "at", "intensity"}, "burst": {"type", "at", "target", "count", "spread"},
          "annotate": {"type", "at", "kind", "target", "text", "tone", "dur"},
          "cursor": {"type", "at", "target", "x", "y"}, "tilt": {"type", "at", "target", "rx", "ry", "dur"}}
NEEDS_TARGET = {"annotate", "cursor", "tilt"}
# photosensitivity (WCAG 2.3.1): ≤ 3 flashes in any 1 s; the director also keeps flash/glitch to ≤ 2 per video
PHOTO_MAX, PHOTO_WINDOW = 3, 1.0
CUT_CLEAR = 0.45          # transient effects end this long before a scene's cut (QA samples at end − 0.4 s)
MAX_FLASH_PER_VIDEO = 2
MAX_GLITCH_PER_VIDEO = 2

EFFECT_SCHEMA = {"type": "array", "maxItems": 8, "items": {"type": "object", "required": ["type"]}}
NUM = re.compile(r"\d")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def effect_errors(sc: dict, sp: str, check_time) -> list[str]:
    """Static checks of a scene's effects. `check_time(path, value)` validates a time expression (storyboard.py)."""
    errs: list[str] = []
    if sc.get("transitionDir") is not None and sc.get("transition") not in ("whip-pan", "push"):
        errs.append(f"{sp}.transitionDir: only used by whip-pan / push transitions")
    n_blocks = len(sc.get("blocks", []))
    for i, e in enumerate(sc.get("effects", [])):
        ep = f"{sp}.effects[{i}]"
        ty = e.get("type")
        if ty not in EFFECT_TYPES:
            errs.append(f"{ep}: unknown effect type {ty!r} (one of {', '.join(EFFECT_TYPES)})")
            continue
        extra = set(e) - FIELDS[ty]
        if extra:
            errs.append(f"{ep}: unknown field(s) for {ty}: {sorted(extra)}")
        if "at" not in e and ty != "tilt":
            errs.append(f"{ep}: {ty} needs 'at' (a time expression, e.g. '@word:fast')")
        if "at" in e:
            errs += check_time(ep + ".at", e["at"])
        if ty in NEEDS_TARGET and "target" not in e:
            errs.append(f"{ep}: {ty} needs 'target' (a block index of this scene)")
        if "target" in e and not (isinstance(e["target"], int) and not isinstance(e["target"], bool) and 0 <= e["target"] < n_blocks):
            errs.append(f"{ep}.target: must be a block index 0..{n_blocks - 1}")
        for k, (lo, hi) in LIMITS.get(ty, {}).items():
            if k in e and not (_num(e[k]) and lo <= e[k] <= hi):
                errs.append(f"{ep}.{k}: must be a number in [{lo:g}, {hi:g}]")
        if ty == "annotate":
            if e.get("kind") not in ANNOTATE_KINDS:
                errs.append(f"{ep}.kind: must be one of {ANNOTATE_KINDS}")
            if "text" in e and not (isinstance(e["text"], str) and e["text"].strip()):
                errs.append(f"{ep}.text: must be a non-empty string shown in the target block")
        if ty == "burst" and e.get("spread", "radial") not in ("radial", "up"):
            errs.append(f"{ep}.spread: must be radial or up")
        if ty == "cursor" and 0 <= e.get("target", -1) < n_blocks and \
                sc["blocks"][e["target"]].get("type") not in ("footage", "device", "browser", "scroll-demo", "dashboard"):
            errs.append(f"{ep}.target: a cursor clicks on a footage / device / browser / scroll-demo / dashboard block")
        if ty == "tilt" and 0 <= e.get("target", -1) < n_blocks and \
                sc["blocks"][e["target"]].get("type") not in ("footage", "device", "image", "dashboard", "browser", "scroll-demo"):
            errs.append(f"{ep}.target: tilt is for footage / device / image / dashboard / browser frames")
    return errs


def restraint_warnings(scenes: list[dict]) -> list[str]:
    """Taste rules the director follows (warnings for hand-edited storyboards)."""
    w: list[str] = []
    prev = None
    flashes = glitches = 0
    for s in scenes:
        fx = s.get("effects", [])
        emph = [e for e in fx if e.get("type") in EMPHASIS]
        if len(emph) > 1:
            w.append(f"scene {s['id']}: {len(emph)} emphasis effects (restraint: one per scene)")
        tr = s.get("transition")
        if tr in FX_TRANSITIONS and tr == prev:
            w.append(f"scene {s['id']}: the same transition {tr!r} twice in a row")
        prev = tr
        flashes += sum(1 for e in fx if e.get("type") == "flash")
        glitches += tr == "glitch"
    if flashes > MAX_FLASH_PER_VIDEO:
        w.append(f"{flashes} flash effects (at most {MAX_FLASH_PER_VIDEO} per video)")
    if glitches > MAX_GLITCH_PER_VIDEO:
        w.append(f"{glitches} glitch transitions (at most {MAX_GLITCH_PER_VIDEO} per video)")
    return w


# ---------------------------------------------------------------------------------------------- resolution
def anchor_word(expr, R) -> dict | None:
    """The spoken word an `@word:` time expression is anchored to (start, end, text, numeric) or None."""
    from .storyboard import EXPR, word_matches
    if not isinstance(expr, str):
        return None
    m = EXPR.match(expr)
    if not m:
        return None
    base = m.group(1)
    if not base.startswith("word:"):
        spec = R.cues_spec.get(base)
        if not spec or "word" not in spec:
            return None
        w, nth = spec["word"], int(spec.get("nth", 1))
    else:
        w, _, n = base[5:].partition("#")
        nth = int(n or 1)
    k = 0
    for x in R.st.words:
        if word_matches(x.text, w):
            k += 1
            if k == nth:
                return {"start": x.start, "end": x.end, "text": x.text, "numeric": bool(NUM.search(x.text))}
    return None


def resolve_effects(sc: dict, R, si: int, anchors: dict) -> list[dict]:
    """Effects with absolute times (like block times). Records each effect's anchor word in `anchors[(si, i)]`."""
    out = []
    for i, e in enumerate(sc.get("effects", [])):
        r = copy.deepcopy(e)
        if "at" in r:
            r["at"] = R.time(r["at"])
            a = anchor_word(e["at"], R)
            if a:
                anchors[(si, i)] = a
        out.append(r)
    return out


def photosensitivity(resolved: list[dict]) -> tuple[list[dict], list[str]]:
    """Drops flash effects that would make more than PHOTO_MAX flashes in any PHOTO_WINDOW s (light-leak transitions
    count as flashes too); the engine applies the same guard. -> (scenes, warnings)."""
    ev = []
    for k, s in enumerate(resolved):
        if k > 0 and s.get("transition") == "light-leak":
            ev.append((s["start"], k, None))
        for i, e in enumerate(s.get("effects", [])):
            if e.get("type") == "flash":
                ev.append((e["at"], k, i))
    ev.sort(key=lambda x: (x[0], x[1], -1 if x[2] is None else x[2]))
    ok, drop, warns = [], set(), []
    for t, k, i in ev:
        if sum(1 for x in ok if t - x < PHOTO_WINDOW) >= PHOTO_MAX:
            if i is not None:
                drop.add((k, i))
                warns.append(f"scene {resolved[k]['id']}: flash at {t:.2f}s dropped (photosensitivity: ≤ {PHOTO_MAX} flashes per second)")
            continue
        ok.append(t)
    for k, s in enumerate(resolved):
        if any((k, i) in drop for i in range(len(s.get("effects", [])))):
            s["effects"] = [e for i, e in enumerate(s["effects"]) if (k, i) not in drop]
    return resolved, warns


def fit_before_cut(resolved: list[dict]) -> None:
    """Shortens a punch-zoom / shake that would still be running in the scene's last CUT_CLEAR s (the exit transition and
    the QA sample at end − 0.4 s), when the shortened move keeps its minimum length."""
    for s in resolved:
        limit = s["end"] - CUT_CLEAR
        for e in s.get("effects", []):
            if e.get("type") not in ("punch-zoom", "shake") or not isinstance(e.get("at"), (int, float)):
                continue
            ty = e["type"]
            if ty == "punch-zoom":
                start, default, lo = e["at"] - 0.03 + 0.08, 0.55, 0.25        # FX.punch lead / attack / dur
            else:
                start, default, lo = e["at"], 0.36, 0.1
            dur = e.get("dur", default)
            if start + dur > limit and limit - start >= lo:
                e["dur"] = round(limit - start, 3)


def qa_overlap_warnings(resolved: list[dict]) -> list[str]:
    """Transient effects still running at the QA OCR sample (scene end − 0.4 s) would blur / cover text there."""
    w = []
    life = {"punch-zoom": 0.65, "shake": 0.4, "flash": 0.4, "burst": 1.0}
    for s in resolved:
        sample = max(s["start"] + 0.5, s["end"] - 0.4)
        for e in s.get("effects", []):
            d = life.get(e.get("type"))
            if d and e.get("type") in ("punch-zoom", "shake") and isinstance(e.get("dur"), (int, float)):
                d = e["dur"] + (0.05 if e["type"] == "punch-zoom" else 0.0)
            if d and isinstance(e.get("at"), (int, float)) and e["at"] - 0.05 <= sample < e["at"] + d:
                w.append(f"scene {s['id']}: {e['type']} at {e['at']:.2f}s is still running at the QA sample {sample:.2f}s")
    return w


def timeline_pass(cfg: dict, resolved: list[dict], words: list[dict], duration: float, fps: int, anchors: dict,
                  sfx: list[dict], warnings: list[str]) -> dict | None:
    """After the scenes are resolved (timeline.build_timeline): photosensitivity guard, beat snapping (storyboard
    `beatSync`, with a configured music file) and QA-sample overlap warnings. -> the beat-sync report (or None)."""
    _, w = photosensitivity(resolved)
    warnings += w
    report = None
    if cfg["storyboard"].get("beatSync"):
        music = (cfg.get("audio") or {}).get("music")
        if not music or str(music).startswith("mood:"):
            report = {"track": None, "snapped": [], "kept": [], "note": "no music file: nothing to snap to"}
        else:
            from . import beats
            try:
                info = beats.beats_for(music)
            except (OSError, RuntimeError, ValueError) as e:
                warnings.append(f"beat sync skipped: {e}")
                report = {"track": str(music), "snapped": [], "kept": [], "note": f"beat detection failed: {e}"}
            else:
                rep = beats.snap_timeline(resolved, words, beats.timeline_beats(info, duration), duration, fps, anchors, sfx)
                report = {"track": info.get("file"), "sha256": info.get("sha256"), "bpm": info.get("bpm"), **rep}
    fit_before_cut(resolved)
    warnings += qa_overlap_warnings(resolved)
    return report
