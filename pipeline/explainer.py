"""v3 explainer blocks (render contract v3, additive): static validation, the numbers they put on screen (and when),
their default sound cues and the verdict-tint photosensitivity budget. Python mirror of src/engine/types.ts `BlockV3`
and src/engine/geometry-explainer.ts (limits and defaults only).

  gauge         dial / score ring moved through `keys` [{at, value, dur?}]; colours from `zones` [{to, tone}]
  countdown     ring counting `from` -> `to` (default 0) between `at` and `countEnd` (default real time)
  chat-thread   `messages` [{side, text, name?, time?, at, typing?}]
  notification  `items` [{app, title, body?, time?, icon?, at}] sliding down from the top (1-3)
  term-reveal   `kicker`, then `term` slams in at `termAt`, then `sub` at `subAt`
  verdict       stamp `text` (+ `mark`, `sub`), optional frame `tint` (a flash), sound kind `sfx`
  comment-cta   comment box typing `keyword` (`typeStart`/`typeEnd`), send at `sendAt`
  poll          `question`, 2-4 `options` [{text, at}], `pick` fills at `pickAt`
  next-episode  `label` ("Part 2"), `title`, `sub`

Every visible word comes from the storyboard. Times accept `@word:` expressions like every block time."""
from __future__ import annotations

from .contract import TONES

TYPES = ("gauge", "countdown", "chat-thread", "notification", "term-reveal", "verdict", "comment-cta", "poll",
         "next-episode")
REQUIRED = {"gauge": ["keys"], "countdown": ["from"], "chat-thread": ["messages"], "notification": ["items"],
            "term-reveal": ["term"], "verdict": ["text"], "comment-cta": ["keyword"], "poll": ["question", "options"],
            "next-episode": ["label", "title"]}
GAUGE_STYLES = ("dial", "ring")
GAUGE_DUR = 0.8                       # geometry-explainer.ts GAUGE.dur (DUR.slower)
VERDICT_MARKS = ("cross", "check", "none")
CHAT_SIDES = ("left", "right")
LIMITS = {"gauge.keys": (1, 8), "chat-thread.messages": (1, 8), "notification.items": (1, 3), "poll.options": (2, 4)}
MAX_TEXT = {"verdict.text": 24, "comment-cta.keyword": 24, "term-reveal.term": 40, "next-episode.label": 24}
TERM_AT, SUB_AFTER = 0.6, 0.45        # term-reveal defaults (TERM.* in geometry-explainer.ts)
TYPE_AFTER = 0.35                     # comment-cta typing starts at + 0.35 s by default


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def errors(b: dict, bp: str) -> list[str]:
    """Static checks of one v3 block (time expressions / anchors are checked by storyboard.validate_storyboard)."""
    ty = b.get("type")
    errs: list[str] = []
    if any(k not in b for k in REQUIRED.get(ty, [])):
        return errs                    # storyboard.validate_storyboard reports the missing fields (REQUIRED)

    def opt_str(*keys):
        for k in keys:
            if k in b and not isinstance(b[k], str):
                errs.append(f"{bp}.{k}: must be a string")

    def need_str(key):
        if not _str(b.get(key)):
            errs.append(f"{bp}.{key}: must be a non-empty string")
        elif f"{ty}.{key}" in MAX_TEXT and len(b[key]) > MAX_TEXT[f"{ty}.{key}"]:
            errs.append(f"{bp}.{key}: at most {MAX_TEXT[f'{ty}.{key}']} characters")

    def items(key):
        v = b.get(key)
        lo, hi = LIMITS[f"{ty}.{key}"]
        if not isinstance(v, list) or not (lo <= len(v) <= hi) or not all(isinstance(x, dict) for x in v):
            errs.append(f"{bp}.{key}: must be a list of {lo}-{hi} objects")
            return []
        for i, x in enumerate(v):
            if "at" not in x:
                errs.append(f"{bp}.{key}[{i}]: needs 'at' (a time, e.g. '@word:…')")
        return v

    if "tone" in b and b["tone"] not in TONES:
        errs.append(f"{bp}.tone: unknown tone {b['tone']!r}")
    if ty == "gauge":
        opt_str("label", "caption", "prefix", "suffix")
        if b.get("style", "dial") not in GAUGE_STYLES:
            errs.append(f"{bp}.style: must be one of {GAUGE_STYLES}")
        for k in ("min", "max"):
            if k in b and not _num(b[k]):
                errs.append(f"{bp}.{k}: must be a number")
        if "decimals" in b and b["decimals"] not in (0, 1, 2, 3):
            errs.append(f"{bp}.decimals: must be 0..3")
        keys = items("keys")
        vals = [k.get("value") for k in keys]
        if any(not _num(v) for v in vals):
            errs.append(f"{bp}.keys: every key needs a numeric 'value'")
            vals = []
        for i, k in enumerate(keys):
            if "dur" in k and not (_num(k["dur"]) and 0.1 <= k["dur"] <= 3):
                errs.append(f"{bp}.keys[{i}].dur: must be seconds in [0.1, 3]")
        lo = b.get("min", 0) if _num(b.get("min", 0)) else 0
        hi = b.get("max", max([100, *vals])) if _num(b.get("max", 0)) else 100
        if hi <= lo:
            errs.append(f"{bp}: gauge max must be greater than min")
        elif any(not (lo <= v <= hi) for v in vals):
            errs.append(f"{bp}.keys: values must lie in [min, max] = [{lo:g}, {hi:g}]")
        zones = b.get("zones", [])
        if not isinstance(zones, list) or not all(isinstance(z, dict) and _num(z.get("to")) and z.get("tone") in TONES
                                                  for z in zones):
            errs.append(f"{bp}.zones: must be a list of {{to: number, tone}} with known tones")
        elif [z["to"] for z in zones] != sorted({z["to"] for z in zones}):
            errs.append(f"{bp}.zones: upper bounds 'to' must be strictly ascending")
    elif ty == "countdown":
        opt_str("label", "suffix")
        if not _num(b.get("from")) or ("to" in b and not _num(b["to"])):
            errs.append(f"{bp}: countdown 'from' / 'to' must be numbers")
        elif b["from"] == b.get("to", 0):
            errs.append(f"{bp}: countdown 'from' and 'to' must differ")
        if "decimals" in b and b["decimals"] not in (0, 1, 2):
            errs.append(f"{bp}.decimals: must be 0..2")
    elif ty == "chat-thread":
        opt_str("title")
        for i, m in enumerate(items("messages")):
            mp = f"{bp}.messages[{i}]"
            if m.get("side") not in CHAT_SIDES:
                errs.append(f"{mp}.side: must be left or right")
            if not _str(m.get("text")):
                errs.append(f"{mp}.text: must be a non-empty string")
            for k in ("name", "time"):
                if k in m and not _str(m[k]):
                    errs.append(f"{mp}.{k}: must be a non-empty string")
            if "typing" in m and not (_num(m["typing"]) and 0 <= m["typing"] <= 3):
                errs.append(f"{mp}.typing: must be seconds in [0, 3]")
    elif ty == "notification":
        for i, it in enumerate(items("items")):
            ip = f"{bp}.items[{i}]"
            for k in ("app", "title"):
                if not _str(it.get(k)):
                    errs.append(f"{ip}.{k}: must be a non-empty string")
            for k in ("body", "time"):
                if k in it and not _str(it[k]):
                    errs.append(f"{ip}.{k}: must be a non-empty string")
    elif ty == "term-reveal":
        need_str("term")
        opt_str("kicker", "sub")
        if "uppercase" in b and not isinstance(b["uppercase"], bool):
            errs.append(f"{bp}.uppercase: must be true or false")
    elif ty == "verdict":
        need_str("text")
        opt_str("sub")
        if b.get("mark", "none") not in VERDICT_MARKS:
            errs.append(f"{bp}.mark: must be one of {VERDICT_MARKS}")
        if "tint" in b and not isinstance(b["tint"], bool):
            errs.append(f"{bp}.tint: must be true or false")
        if "sfx" in b and not (b["sfx"] is False or _str(b["sfx"])):
            errs.append(f"{bp}.sfx: must be a sound kind of the brand theme (e.g. 'impact') or false")
    elif ty == "comment-cta":
        need_str("keyword")
        opt_str("prompt", "sub")
    elif ty == "poll":
        need_str("question")
        opts = items("options")
        for i, o in enumerate(opts):
            if not _str(o.get("text")):
                errs.append(f"{bp}.options[{i}].text: must be a non-empty string")
        if ("pick" in b) != ("pickAt" in b):
            errs.append(f"{bp}: poll 'pick' and 'pickAt' go together")
        if "pick" in b and not (isinstance(b["pick"], int) and not isinstance(b["pick"], bool) and 0 <= b["pick"] < len(opts)):
            errs.append(f"{bp}.pick: must be an option index 0..{max(0, len(opts) - 1)}")
    elif ty == "next-episode":
        need_str("label")
        need_str("title")
        opt_str("sub")
    return errs


# ---------------------------------------------------------------------------------------------- numbers on screen
def _nums(text, t, out, NUM):
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        text = str(int(text)) if float(text).is_integer() else str(text)
    if isinstance(text, str) and t is not None:
        for n in NUM.findall(text):
            out.append((n.replace(",", "").removesuffix(".0"), float(t)))


def numbers_shown(b: dict, NUM) -> list[tuple[str, float]] | None:
    """(number, first display time) of a RESOLVED v3 block, or None for other block types. Exact per part: a gauge value
    when its key starts moving (the readout is hidden before the first key), a countdown's start value at `at`, the term
    at `termAt`, the keyword when typing starts."""
    ty = b.get("type")
    if ty not in TYPES:
        return None
    at = b.get("at") if _num(b.get("at")) else None
    out: list[tuple[str, float]] = []
    if ty == "gauge":
        for k in b.get("keys", []):
            if _num(k.get("at")):
                _nums(k.get("value"), k["at"], out, NUM)
        for key in ("label", "caption"):
            _nums(b.get(key), at, out, NUM)
    elif ty == "countdown":
        _nums(b.get("from"), at, out, NUM)
        _nums(b.get("label"), at, out, NUM)
    elif ty == "chat-thread":
        _nums(b.get("title"), at, out, NUM)
        for m in b.get("messages", []):
            _nums(m.get("text"), m.get("at"), out, NUM)
    elif ty == "notification":
        for it in b.get("items", []):
            for key in ("title", "body"):
                _nums(it.get(key), it.get("at"), out, NUM)
    elif ty == "term-reveal":
        term_at = b.get("termAt", (at or 0) + TERM_AT)
        _nums(b.get("kicker"), at, out, NUM)
        _nums(b.get("term"), term_at, out, NUM)
        _nums(b.get("sub"), b.get("subAt", term_at + SUB_AFTER), out, NUM)
    elif ty == "verdict":
        _nums(b.get("text"), at, out, NUM)
        _nums(b.get("sub"), at, out, NUM)
    elif ty == "comment-cta":
        _nums(b.get("prompt"), at, out, NUM)
        _nums(b.get("keyword"), b.get("typeStart", (at or 0) + TYPE_AFTER), out, NUM)
        _nums(b.get("sub"), at, out, NUM)
    elif ty == "poll":
        _nums(b.get("question"), at, out, NUM)
        for o in b.get("options", []):
            _nums(o.get("text"), o.get("at"), out, NUM)
    elif ty == "next-episode":
        for key in ("label", "title", "sub"):
            _nums(b.get(key), at, out, NUM)
    return out


def claimed_values(b: dict) -> list:
    """Numeric values a v3 block presents as claims (the preview gate checks them against the verified facts)."""
    if b.get("type") == "gauge":
        return [k.get("value") for k in b.get("keys", []) if _num(k.get("value"))]
    if b.get("type") == "countdown" and _num(b.get("from")):
        return [b["from"]]
    return []


# ---------------------------------------------------------------------------------------------- sound
def sfx_events(b: dict) -> list[tuple[float, str]]:
    """Default sound cues (time, theme sound kind) of a RESOLVED v3 block (storyboard.auto_sfx)."""
    ty, t = b.get("type"), b.get("at", 0.0)
    ev: list[tuple[float, str]] = []
    if ty == "gauge":
        for k in b.get("keys", []):
            d = k.get("dur", GAUGE_DUR)
            ev += [(k["at"] + i * d / 4, "tick") for i in range(4)]
    elif ty == "countdown":
        end = b.get("countEnd", t + abs(b["from"] - b.get("to", 0)))
        n = min(10, max(1, int(round(end - t))))
        ev += [(t + i * (end - t) / n, "tick") for i in range(n)]
    elif ty == "chat-thread":
        ev += [(m["at"], "appear") for m in b.get("messages", [])]
    elif ty == "notification":
        ev += [(it["at"], "success") for it in b.get("items", [])]
    elif ty == "term-reveal":
        ev.append((b.get("termAt", t + TERM_AT), "impact"))
    elif ty == "verdict":
        kind = b.get("sfx", "impact")
        if kind is not False:
            ev.append((t, kind))
    elif ty == "comment-cta":
        start = b.get("typeStart", t + TYPE_AFTER)
        end = b.get("typeEnd", start + min(1.0, 0.09 * max(1, len(b.get("keyword", "")))))
        n = max(1, len(b.get("keyword", "")))
        ev += [(start + i * (end - start) / n, "keys") for i in range(n)]
        if "sendAt" in b:
            ev.append((b["sendAt"], "click"))
    elif ty == "poll":
        ev += [(o["at"], "appear") for o in b.get("options", [])]
        if "pickAt" in b:
            ev.append((b["pickAt"], "click"))
    elif ty == "next-episode":
        ev += [(t + 0.05, "whoosh"), (t + 0.3, "shimmer")]
    return ev


# ---------------------------------------------------------------------------------------------- photosensitivity
def tint_events(resolved: list[dict]) -> list[tuple[float, int, int]]:
    """(time, scene index, block index) of every verdict tint (a flash: src/engine/motion/effects.ts flashEvents)."""
    return [(b["at"], k, bi) for k, s in enumerate(resolved) for bi, b in enumerate(s.get("blocks", []))
            if b.get("type") == "verdict" and b.get("tint", True) is not False and _num(b.get("at"))]


# ---------------------------------------------------------------------------------------------- timing
def timing_warnings(resolved: list[dict]) -> list[str]:
    """Payoffs of v3 blocks that would still be moving at the scene's cut (fix: later anchors, `holdAfter`, shorter `dur`)."""
    w: list[str] = []
    for s in resolved:
        end = s["end"] - 0.15
        for b in s.get("blocks", []):
            ty, at = b.get("type"), b.get("at", s["start"])
            late: list[tuple[str, float]] = []
            if ty == "gauge":
                late = [(f"gauge key {k.get('value')}", k["at"] + k.get("dur", GAUGE_DUR)) for k in b.get("keys", [])]
            elif ty == "countdown":
                late = [("countdown end", b.get("countEnd", at + abs(b["from"] - b.get("to", 0))))]
            elif ty == "term-reveal":
                late = [("term", b.get("termAt", at + TERM_AT) + 0.4)]
            elif ty == "poll" and "pickAt" in b:
                late = [("poll pick", b["pickAt"] + 0.5)]
            elif ty == "comment-cta" and "sendAt" in b:
                late = [("comment send", b["sendAt"] + 0.3)]
            for what, t in late:
                if t > end:
                    w.append(f"scene {s['id']}: {what} still animating at the cut ({t:.2f}s > {end:.2f}s); "
                             f"anchor it earlier or add holdAfter")
    return w
