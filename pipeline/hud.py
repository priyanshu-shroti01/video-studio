"""Persistent HUD and caption meaning colours (render contract v3). Python mirror of src/engine/hud.ts (limits and
state rules only), static validation, `@word:` time resolution and the caption annotations (tones, speakers).

Storyboard (top level):
  "hud": {"elements": [
      {"id": "step", "kind": "header", "prefix": "Step", "steps": ["Hashing", "Caching", "Queues"]},
      {"id": "terms", "kind": "chips"},
      {"id": "series", "kind": "progress", "label": "Day", "total": 30, "value": 3},
      {"id": "stakes", "kind": "stakes", "parts": [{"value": 212, "label": "applications"},
                                                    {"value": 0, "label": "replies", "tone": "danger"}]}]}
  "speakers": {"MOM": {"label": "Mom", "tone": "danger"}, "HR": {"tone": "info"}}       (optional)
Storyboard (per scene):
  "hud": [{"at": "@word:caching", "target": "step", "op": "advance"},
          {"at": "@word:hash", "target": "terms", "op": "add", "text": "Hash"},
          {"at": "@word:212", "target": "stakes", "op": "show"}]
  "captionTones": {"wrong": "danger", "fixed": "success", "cache#2": "term"}
  "speaker": "MOM"   or   [{"name": "MOM"}, {"name": "HR", "from": "@word:sorry"}]

Ops: show / hide (any element), advance (header: next step; progress: +1), set (header `index`, progress `value`,
stakes `part` + `value` [+ `tone`]), add (chips: `text` [+ `tone`]). An element is hidden until its first event.
A chip added on an `@word:` anchor also gives that spoken word the caption tone `term` (unless the scene's
captionTones says otherwise, or `hud.termTones` is false).

Storyboards without these keys produce exactly the props they produced before (no `hud`, no page tones)."""
from __future__ import annotations

import re

from .contract import CAPTION_TONES, HUD_KINDS, HUD_OPS, TONES

ID_RE = r"^[a-z0-9][a-z0-9_-]{0,31}$"
MAX_STEPS = 12
MAX_CHIPS = 12          # more than this cannot stay readable in two rows on a Short
CHIPS_WARN = 8
MAX_STAKES_PARTS = 3
MAX_TOTAL = 999
COUNT_S = 0.6           # src/engine/hud.ts HUD.count: a stakes value lands this long after its event
LEAD_S = 0.06           # HUD.lead
OPS = {"header": {"show", "hide", "advance", "set"}, "chips": {"show", "hide", "add"},
       "progress": {"show", "hide", "advance", "set"}, "stakes": {"show", "hide", "set"}}
EVENT_FIELDS = {"at", "target", "op", "index", "value", "part", "text", "tone"}
ELEMENT_FIELDS = {"header": {"id", "kind", "steps", "prefix", "numbered"}, "chips": {"id", "kind"},
                  "progress": {"id", "kind", "total", "value", "label", "style", "pad", "showCount"},
                  "stakes": {"id", "kind", "parts"}}
TEXT_MAX = {"step": 28, "prefix": 12, "chip": 22, "label": 14, "stakes": 28, "speaker": 16}

HUD_SCHEMA = {"type": "object", "required": ["elements"], "additionalProperties": False,
              "properties": {"elements": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "kind"]}},
                             "termTones": {"type": "boolean"}}}
SPEAKERS_SCHEMA = {"type": "object", "additionalProperties": {
    "type": "object", "additionalProperties": False,
    "properties": {"label": {"type": "string", "minLength": 1, "maxLength": TEXT_MAX["speaker"]},
                   "tone": {"type": "string", "enum": sorted(TONES)}}}}
SCENE_HUD_SCHEMA = {"type": "array", "maxItems": 24, "items": {"type": "object", "required": ["at", "target", "op"]}}
CAPTION_TONES_SCHEMA = {"type": "object", "additionalProperties": {"type": "string", "enum": sorted(CAPTION_TONES)}}
SPEAKER_SCHEMA = {"type": ["string", "array"]}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _text(v, n: int) -> bool:
    return isinstance(v, str) and 0 < len(v.strip()) and len(v) <= n


# ---------------------------------------------------------------------------------------------------------------
def element_errors(els: list[dict], path: str = "$storyboard.hud") -> list[str]:
    errs: list[str] = []
    ids, kinds = set(), set()
    for i, e in enumerate(els):
        ep = f"{path}.elements[{i}]"
        k = e.get("kind")
        if k not in HUD_KINDS:
            errs.append(f"{ep}.kind: must be one of {sorted(HUD_KINDS)}")
            continue
        if not (isinstance(e.get("id"), str) and re.match(ID_RE, e["id"])):
            errs.append(f"{ep}.id: must match {ID_RE}")
        elif e["id"] in ids:
            errs.append(f"{ep}.id: duplicate HUD element id {e['id']!r}")
        ids.add(e.get("id"))
        if k in kinds:
            errs.append(f"{ep}: only one HUD element of kind {k!r} (each kind has its own row)")
        kinds.add(k)
        extra = set(e) - ELEMENT_FIELDS[k]
        if extra:
            errs.append(f"{ep}: unknown field(s) for {k}: {sorted(extra)}")
        if k == "header":
            st = e.get("steps")
            if not (isinstance(st, list) and 1 <= len(st) <= MAX_STEPS and all(_text(x, TEXT_MAX["step"]) for x in st)):
                errs.append(f"{ep}.steps: 1–{MAX_STEPS} non-empty strings of at most {TEXT_MAX['step']} characters")
            if "prefix" in e and not _text(e["prefix"], TEXT_MAX["prefix"]):
                errs.append(f"{ep}.prefix: a short label (≤ {TEXT_MAX['prefix']} characters), e.g. 'Step'")
            if "numbered" in e and not isinstance(e["numbered"], bool):
                errs.append(f"{ep}.numbered: must be true or false")
        elif k == "progress":
            tot = e.get("total")
            if not (_int(tot) and 1 <= tot <= MAX_TOTAL):
                errs.append(f"{ep}.total: an integer 1–{MAX_TOTAL}")
            elif "value" in e and not (_num(e["value"]) and 0 <= e["value"] <= tot):
                errs.append(f"{ep}.value: a number 0..total")
            if "label" in e and not _text(e["label"], TEXT_MAX["label"]):
                errs.append(f"{ep}.label: a short label (≤ {TEXT_MAX['label']} characters), e.g. 'Day'")
            if e.get("style", "bar") not in ("bar", "segments"):
                errs.append(f"{ep}.style: 'bar' or 'segments'")
            if e.get("style") == "segments" and _int(tot) and tot > 12:
                errs.append(f"{ep}: 'segments' is for chapters (total ≤ 12); use 'bar' for a long series")
            if "pad" in e and not (_int(e["pad"]) and 0 <= e["pad"] <= 3):
                errs.append(f"{ep}.pad: digits 0–3")
            if "showCount" in e and not isinstance(e["showCount"], bool):
                errs.append(f"{ep}.showCount: must be true or false")
        elif k == "stakes":
            parts = e.get("parts")
            if not (isinstance(parts, list) and 1 <= len(parts) <= MAX_STAKES_PARTS):
                errs.append(f"{ep}.parts: 1–{MAX_STAKES_PARTS} parts")
                continue
            for j, p in enumerate(parts):
                pp = f"{ep}.parts[{j}]"
                if not isinstance(p, dict) or not _text(p.get("label"), TEXT_MAX["stakes"]):
                    errs.append(f"{pp}.label: a short label (≤ {TEXT_MAX['stakes']} characters)")
                    continue
                if set(p) - {"label", "value", "prefix", "suffix", "tone"}:
                    errs.append(f"{pp}: unknown field(s) {sorted(set(p) - {'label', 'value', 'prefix', 'suffix', 'tone'})}")
                if "value" in p and not _num(p["value"]):
                    errs.append(f"{pp}.value: must be a number")
                for f in ("prefix", "suffix"):
                    if f in p and not (isinstance(p[f], str) and len(p[f]) <= 4):
                        errs.append(f"{pp}.{f}: at most 4 characters (e.g. '₹', '%')")
                if "tone" in p and p["tone"] not in TONES:
                    errs.append(f"{pp}.tone: one of {sorted(TONES)}")
    return errs


def event_errors(sc: dict, sp: str, elements: dict[str, dict], check_time) -> list[str]:
    """A scene's HUD events. `check_time(path, value)` validates a time expression (storyboard.py)."""
    errs: list[str] = []
    for i, ev in enumerate(sc.get("hud", [])):
        ep = f"{sp}.hud[{i}]"
        errs += check_time(ep + ".at", ev.get("at"))
        el = elements.get(ev.get("target"))
        if el is None:
            errs.append(f"{ep}.target: no HUD element {ev.get('target')!r} (define it in storyboard.hud.elements)")
            continue
        op, k = ev.get("op"), el["kind"]
        if op not in HUD_OPS:
            errs.append(f"{ep}.op: one of {sorted(HUD_OPS)}")
            continue
        if op not in OPS[k]:
            errs.append(f"{ep}.op: {op!r} does not apply to a {k} (use {sorted(OPS[k])})")
            continue
        extra = set(ev) - EVENT_FIELDS
        if extra:
            errs.append(f"{ep}: unknown field(s) {sorted(extra)}")
        if op == "add" and not _text(ev.get("text"), TEXT_MAX["chip"]):
            errs.append(f"{ep}.text: the chip (≤ {TEXT_MAX['chip']} characters)")
        if "tone" in ev and ev["tone"] not in TONES:
            errs.append(f"{ep}.tone: one of {sorted(TONES)}")
        if op == "set":
            if k == "header" and not (_int(ev.get("index")) and 0 <= ev["index"] < len(el.get("steps", []))):
                errs.append(f"{ep}.index: a step index 0..{len(el.get('steps', [])) - 1}")
            if k == "progress" and not (_num(ev.get("value")) and 0 <= ev["value"] <= el.get("total", 0)):
                errs.append(f"{ep}.value: a number 0..{el.get('total')}")
            if k == "stakes":
                n = len(el.get("parts", []))
                if not (_int(ev.get("part", 0)) and 0 <= ev.get("part", 0) < n):
                    errs.append(f"{ep}.part: a part index 0..{n - 1}")
                if "value" not in ev and "tone" not in ev:
                    errs.append(f"{ep}: a stakes set needs 'value' (and / or 'tone')")
                elif "value" in ev and not _num(ev["value"]):
                    errs.append(f"{ep}.value: must be a number")
    return errs


def hud_errors(sb: dict, check_time_for) -> tuple[list[str], list[str]]:
    """Whole-storyboard HUD checks. `check_time_for(scene)` returns that scene's `check_time(path, value)`."""
    from .schema import validate
    errors: list[str] = []
    warnings: list[str] = []
    hud = sb.get("hud")
    if hud is not None:
        errors += validate(hud, HUD_SCHEMA, "$storyboard.hud")
        if errors:
            return errors, warnings
        errors += element_errors(hud["elements"])
    elements = {e.get("id"): e for e in (hud or {}).get("elements", []) if isinstance(e, dict)}
    used: set[str] = set()
    steps: dict[str, int] = {}
    chips: dict[str, int] = {}
    for si, sc in enumerate(sb["scenes"]):
        sp = f"$storyboard.scenes[{si}]({sc['id']})"
        if "hud" in sc:
            if hud is None:
                errors.append(f"{sp}.hud: HUD events need a storyboard.hud definition")
                continue
            errs = validate(sc["hud"], SCENE_HUD_SCHEMA, f"{sp}.hud")
            if errs:
                errors += errs
                continue
            errors += event_errors(sc, sp, elements, check_time_for(sc))
            for ev in sc["hud"]:
                tgt = ev.get("target")
                used.add(tgt)
                el = elements.get(tgt, {})
                if el.get("kind") == "header" and ev.get("op") == "advance":
                    steps[tgt] = steps.get(tgt, 0) + 1
                if el.get("kind") == "chips" and ev.get("op") == "add":
                    chips[tgt] = chips.get(tgt, 0) + 1
        for key, schema in (("captionTones", CAPTION_TONES_SCHEMA), ("speaker", SPEAKER_SCHEMA)):
            if key in sc:
                errors += validate(sc[key], schema, f"{sp}.{key}")
        errors += _tone_errors(sc, sp)
        errors += _speaker_errors(sc, sp, sb.get("speakers"), check_time_for(sc))
    if "speakers" in sb:
        errors += validate(sb["speakers"], SPEAKERS_SCHEMA, "$storyboard.speakers")
        for name in sb["speakers"] if isinstance(sb["speakers"], dict) else []:
            if not _text(name, TEXT_MAX["speaker"]):
                errors.append(f"$storyboard.speakers: name {name!r} must be 1–{TEXT_MAX['speaker']} characters")
    for tgt, n in steps.items():
        if n > len(elements[tgt].get("steps", [])) - 1:
            errors.append(f"$storyboard.hud: header {tgt!r} advances {n}× but has only {len(elements[tgt].get('steps', []))} steps")
    for tgt, n in chips.items():
        if n > MAX_CHIPS:
            errors.append(f"$storyboard.hud: {n} chips in {tgt!r} (at most {MAX_CHIPS} stay readable)")
        elif n > CHIPS_WARN:
            warnings.append(f"$storyboard.hud: {n} chips in {tgt!r}; more than {CHIPS_WARN} shrink the chip row")
    for eid in elements:
        if eid not in used:
            warnings.append(f"$storyboard.hud: element {eid!r} never appears (no scene event targets it)")
    return errors, warnings


def _tone_errors(sc: dict, sp: str) -> list[str]:
    from .storyboard import _word_in
    errs = []
    tones = sc.get("captionTones")
    if not isinstance(tones, dict):
        return errs
    for key in tones:
        w = key.split("#")[0]
        if not w or not _word_in(sc["narration"], w):
            errs.append(f"{sp}.captionTones: word {w!r} is not in this scene's narration")
        if "#" in key and not key.split("#", 1)[1].isdigit():
            errs.append(f"{sp}.captionTones: {key!r} (use 'word' or 'word#2')")
    return errs


def _speaker_errors(sc: dict, sp: str, declared, check_time) -> list[str]:
    errs = []
    spk = sc.get("speaker")
    if spk is None:
        return errs
    entries = [{"name": spk}] if isinstance(spk, str) else spk
    if not isinstance(entries, list) or not entries:
        return [f"{sp}.speaker: a name, or a list of {{name, from}}"]
    for i, e in enumerate(entries):
        ep = f"{sp}.speaker[{i}]" if isinstance(spk, list) else f"{sp}.speaker"
        if not isinstance(e, dict) or not _text(e.get("name"), TEXT_MAX["speaker"]) or set(e) - {"name", "from"}:
            errs.append(f"{ep}: needs 'name' (1–{TEXT_MAX['speaker']} characters) and optional 'from'")
            continue
        if isinstance(declared, dict) and e["name"] not in declared:
            errs.append(f"{ep}: speaker {e['name']!r} is not in storyboard.speakers")
        if "from" in e:
            errs += check_time(ep + ".from", e["from"])
        elif i > 0:
            errs.append(f"{ep}: every speaker after the first needs 'from' (the word they start on)")
    return errs


# ---------------------------------------------------------------------------------------------------------------
# Resolution (pipeline/timeline.py)
# ---------------------------------------------------------------------------------------------------------------
def anchor_word(R, expr) -> int | None:
    """Position in the scene's words (R.st.words) of the word an `@word:x[#n]` expression without offset names,
    else None (an offset or a cue is not "on" a word)."""
    from .storyboard import EXPR, word_matches
    if not isinstance(expr, str):
        return None
    m = EXPR.match(expr)
    if not m or not m.group(1).startswith("word:") or m.group(2):
        return None
    w, _, nth = m.group(1)[5:].partition("#")
    n = 0
    for i, x in enumerate(R.st.words):
        if word_matches(x.text, w):
            n += 1
            if n == int(nth or 1):
                return i
    return None


def resolve_events(sc: dict, R) -> list[dict]:
    """The scene's HUD events with absolute times (`_word` = the scene word index a chip names, for term tones)."""
    out = []
    for ev in sc.get("hud", []):
        e = {k: v for k, v in ev.items() if k in EVENT_FIELDS}
        e["at"] = R.time(ev["at"])
        if ev["op"] == "add":
            wi = anchor_word(R, ev["at"])
            if wi is not None:
                e["_word"] = wi
        out.append(e)
    return out


def contract_hud(sb: dict, events: list[dict]) -> dict | None:
    """RenderProps `hud` (or None): element definitions as written, events sorted by time (stable)."""
    hud = sb.get("hud")
    if not hud:
        return None
    evs = [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]
    evs = [e for _, e in sorted(enumerate(evs), key=lambda p: (p[1]["at"], p[0]))]
    return {"elements": [dict(e) for e in hud["elements"]], "events": evs}


def word_annotations(sb: dict, scene_words: list[list[int]], words, resolvers, hud_events: list[list[dict]]):
    """Per global word index: caption tone and speaker. `scene_words[k]` = global indices of scene k's words,
    `resolvers[k]` its Resolver, `hud_events[k]` its resolved HUD events."""
    from .storyboard import word_matches
    tones: dict[int, str] = {}
    speakers: dict[int, str] = {}
    term = (sb.get("hud") or {}).get("termTones", True)
    for k, sc in enumerate(sb["scenes"]):
        idx = scene_words[k]
        if term:
            for ev in hud_events[k]:
                if "_word" in ev and ev["_word"] < len(idx):
                    tones[idx[ev["_word"]]] = "term"
        for key, tone in (sc.get("captionTones") or {}).items():
            w, _, nth = key.partition("#")
            hits = [gi for gi in idx if word_matches(words[gi].text, w)]
            if nth:
                hits = hits[int(nth) - 1:int(nth)]
            for gi in hits:
                tones[gi] = tone
        spk = sc.get("speaker")
        if spk:
            entries = [{"name": spk}] if isinstance(spk, str) else spk
            starts = [(resolvers[k].time(e["from"]) if "from" in e else -1e9, e["name"]) for e in entries]
            for gi in idx:
                cur = None
                for t0, name in starts:
                    if words[gi].start >= t0 - 1e-6:
                        cur = name
                speakers[gi] = cur or entries[0]["name"]
    return tones, speakers


def split_pages_by_speaker(pages, speakers: dict[int, str]):
    """Word groups split wherever the speaker changes (a tag names exactly one speaker)."""
    out = []
    for pg in pages:
        cur = [pg.word_idx[0]]
        for wi in pg.word_idx[1:]:
            if speakers.get(wi) != speakers.get(cur[-1]):
                out.append(cur)
                cur = []
            cur.append(wi)
        out.append(cur)
    return out


def page_props(pg, tones: dict[int, str], speakers: dict[int, str]) -> dict:
    """Contract fields of one caption page (`tones` / `speaker` only when present: classic props stay identical)."""
    d = {"start": pg.start, "end": pg.end, "wordIdx": pg.word_idx}
    tn = [tones.get(i) for i in pg.word_idx]
    if any(tn):
        d["tones"] = tn
    s = speakers.get(pg.word_idx[0])
    if s:
        d["speaker"] = s
    return d


def speakers_props(sb: dict, speakers: dict[int, str]) -> dict | None:
    """RenderProps captions.speakers: the declared speakers (storyboard order), plus any undeclared name in order of
    appearance. None when no word has a speaker."""
    if not speakers:
        return None
    out = {name: dict(v) for name, v in (sb.get("speakers") or {}).items()}
    for gi in sorted(speakers):
        out.setdefault(speakers[gi], {})
    return out


# ---------------------------------------------------------------------------------------------------------------
# QA (pipeline/sync_check.py)
# ---------------------------------------------------------------------------------------------------------------
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_shown(hud: dict | None) -> list[tuple[str, float]]:
    """(number, first display time) of the HUD's claims: stakes values when the part is first shown and when a set
    lands (counted). Header step numbers and series counts ("STEP 2", "DAY 03 / 30") are structure, not claims."""
    if not hud:
        return []
    els = {e["id"]: e for e in hud.get("elements", [])}
    out: list[tuple[str, float]] = []
    shown: set[str] = set()
    for ev in sorted(hud.get("events", []), key=lambda e: e["at"]):
        el = els.get(ev.get("target"))
        if not el or el.get("kind") != "stakes":
            continue
        t = float(ev["at"]) - LEAD_S
        if ev["target"] not in shown and ev["op"] != "hide":
            shown.add(ev["target"])
            for p in el.get("parts", []):
                if _num(p.get("value")):
                    out.append((_fmt(p["value"]), t))
        if ev["op"] == "set" and _num(ev.get("value")):
            out.append((_fmt(ev["value"]), t + COUNT_S))
    return out


def _fmt(v) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def storyboard_numbers(sb: dict) -> list[tuple[str, str]]:
    """(number, where) of every number the storyboard's HUD can put on screen: stakes values (defined or set) and
    digits written in chip, step, label and stakes texts. For the preview gate's verified-facts check."""
    out: list[tuple[str, str]] = []
    els = {e.get("id"): e for e in (sb.get("hud") or {}).get("elements", []) if isinstance(e, dict)}
    for eid, el in els.items():
        texts = list(el.get("steps", [])) + [el.get("prefix", ""), el.get("label", "")]
        for j, p in enumerate(el.get("parts", []) if isinstance(el.get("parts"), list) else []):
            if _num(p.get("value")):
                out.append((_fmt(p["value"]), f"hud.{eid}.parts[{j}].value"))
            texts.append(p.get("label", ""))
        for t in texts:
            for n in NUM.findall(t if isinstance(t, str) else ""):
                out.append((n.replace(",", ""), f"hud.{eid}: {t!r}"))
    for sc in sb.get("scenes", []):
        for ev in sc.get("hud", []) if isinstance(sc.get("hud"), list) else []:
            el = els.get(ev.get("target"), {})
            if el.get("kind") == "stakes" and _num(ev.get("value")):
                out.append((_fmt(ev["value"]), f"{sc['id']}/hud.{ev['target']}.set"))
            for n in NUM.findall(ev.get("text", "") if isinstance(ev.get("text"), str) else ""):
                out.append((n.replace(",", ""), f"{sc['id']}/hud.{ev.get('target')}: {ev['text']!r}"))
    return out


def event_times(hud: dict | None) -> list[float]:
    """Visible HUD changes (each is anchored to a spoken word), for the static-narration check."""
    return [float(e["at"]) for e in (hud or {}).get("events", []) if _num(e.get("at"))]
