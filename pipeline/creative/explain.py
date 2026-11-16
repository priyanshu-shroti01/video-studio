"""Explainer style: generic scene templates, step helpers and the storyboard HUD (render contract v3).

The short-form explainer: a myth crossed out and stamped, the product named in a term reveal, numbered steps on a
persistent step header with a term chip added on each step's cue word, a proof on a gauge (or a countdown when the
fact is a duration) with a success stamp, the value line, an engagement ending (poll / comment / next part), the outro.

Everything follows the template contract (templates.py): every on-screen string is a template constant, a verified
fact, a brief / brand value or a phrase spoken in that scene (`Ctx.labels`); every beat is anchored on its spoken word.
Builders here may return a dict instead of a block list:

  {"blocks": [...], "effects": [...] (scene emphasis effects, e.g. an annotate cross), "tones": {word: tone}
   (caption tones), "step": {"label", "chip", "chip_at"} (a step scene: the director builds the HUD from these)}

Copy-bank fields these templates read (each phrase must be spoken verbatim in the narration, or it is not used):
  headline (the myth), verdict (the stamp word), sub, danger [words], kicker, pill, question, options [..],
  prompt, keyword. Step copy says "{step}" where the ordinal goes ("Step {step}: ..."); the director fills it in
  from the scene's place among the step scenes."""
from __future__ import annotations

import re

from .anchors import Anchors
from .templates import T, Ctx, fmt_off, phrase_index, pill

ORDINALS = ("one", "two", "three", "four", "five", "six", "seven", "eight")
HUD_STEP, HUD_TERMS = "step", "terms"
STEP_PREFIX = "Step"
HOLD = 0.6                  # a stamp / gauge / poll payoff plays this long after the last word


# ---- helpers -----------------------------------------------------------------------------------------
def clean(tok: str) -> str:
    """A narration token without surrounding punctuation ("pass." -> "pass", "99.9" stays)."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", tok or "")


def first_at(A: Anchors, off: float = -0.1) -> str:
    """The scene's first spoken word (the scene start, in practice): the hero is there from the first frame."""
    return fmt_off(A.word_expr(0), off)


def said(A: Anchors, phrase: str | None) -> int | None:
    """Token index where `phrase` is spoken in this scene, or None."""
    return phrase_index(A, phrase) if phrase and phrase.strip() else None


def said_at(A: Anchors, phrase: str, off: float = -0.05, name: str = "", last: bool = False) -> str | None:
    """`@word:` expression of the first (or last) word of a spoken phrase; recorded as a beat (so an LLM line that drops
    the phrase is rejected like any line that loses a cue word)."""
    i = said(A, phrase)
    if i is None:
        return None
    if last:
        i += len([w for w in phrase.split() if re.search(r"\w", w)]) - 1
    expr = fmt_off(A.word_expr(i), off)
    A.used.append({"element": name, "cues": [phrase], "word": clean(A.tokens[i]), "expr": expr})
    return expr


def display(phrase: str) -> str:
    """A spoken phrase as an on-screen label: first letter up, trailing punctuation off."""
    p = phrase.strip().rstrip(".,;:")
    return p[:1].upper() + p[1:]


def tone_words(A: Anchors, phrase: str | None) -> list[str]:
    """The cleaned tokens of a spoken phrase, as caption-tone keys."""
    i = said(A, phrase)
    if i is None:
        return []
    n = len([w for w in phrase.split() if re.search(r"\w", w)])
    return [clean(t) for t in A.tokens[i:i + n] if clean(t)]


def result(blocks: list[dict], **extra) -> dict:
    return {"blocks": [b for b in blocks if b], **{k: v for k, v in extra.items() if v}}


# ---- generic explainer builders ----------------------------------------------------------------------
def b_myth_verdict(ctx: Ctx, A: Anchors, copy: dict):
    """The myth is on screen from the first word; a hand-drawn cross strikes it as its last word is said; the
    verdict stamp slams on the spoken verdict word. Danger tones on the myth words and the verdict."""
    head, vt = copy.get("headline"), copy.get("verdict")
    blocks, effects, tones = [], [], {}
    if said(A, head) is not None:
        blocks.append({"type": "headline", "size": "m", "words": ctx.L(display(head), "narration"), "at": first_at(A)})
        cross_at = said_at(A, copy.get("cross") or head, 0.0, "cross", last=not copy.get("cross"))
        effects.append({"type": "annotate", "kind": "cross", "target": 0, "at": cross_at})
    if said(A, vt) is not None:
        v = {"type": "verdict", "text": ctx.L(display(vt), "narration"), "at": said_at(A, vt, -0.05, "verdict")}
        if said(A, copy.get("sub")) is not None:
            v["sub"] = ctx.L(display(copy["sub"]), "narration")
        blocks.append(v)
        tones.update({w: "danger" for w in tone_words(A, vt)})
    for ph in copy.get("danger") or []:
        tones.update({w: "danger" for w in tone_words(A, ph)})
    return result(blocks, effects=effects, tones=tones)


def b_term_reveal(ctx: Ctx, A: Anchors, copy: dict):
    """Mechanism first, then the name: the spoken kicker, the brand slamming in on its spoken name, the spoken line
    beneath; a pill lands on its own words."""
    pf = ctx.pf
    kicker = copy.get("kicker") or clean(A.tokens[0])
    tr = {"type": "term-reveal", "at": first_at(A), "term": ctx.L(pf.brand, "brand:name"),
          "termAt": A.at([pf.name_cue], 0.0, name="term")}
    if said(A, kicker) is not None:
        tr["kicker"] = ctx.L(display(kicker), "narration")
    if said(A, copy.get("sub")) is not None:
        tr["sub"] = ctx.L(display(copy["sub"]), "narration")
        tr["subAt"] = said_at(A, copy["sub"], -0.05, "sub")
    blocks = [tr]
    if said(A, copy.get("pill")) is not None:
        blocks.append(pill(ctx, display(copy["pill"]), "narration", said_at(A, copy["pill"], -0.05, "pill"),
                           copy.get("pill_icon", "check")))
    return result(blocks)


def b_poll(ctx: Ctx, A: Anchors, copy: dict):
    """A spoken question; each option pill slides in on its own words. No pick and no percentages (they would be
    invented votes)."""
    q = copy.get("question")
    opts = [o for o in copy.get("options") or [] if said(A, o) is not None]
    if said(A, q) is None or len(opts) < 2:
        return result([])
    return result([{"type": "poll", "at": first_at(A), "question": ctx.L(display(q), "narration"),
                    "options": [{"text": ctx.L(display(o), "narration"), "at": said_at(A, o, -0.05, f"option:{k}")}
                                for k, o in enumerate(opts[:4])]}])


def b_comment(ctx: Ctx, A: Anchors, copy: dict):
    """A comment box types the spoken keyword and sends it. The copy asks for a comment; it never promises a reply,
    a DM or a download (nothing the brand does not verifiably offer)."""
    kw, prompt = copy.get("keyword"), copy.get("prompt")
    if said(A, kw) is None:
        return result([])
    t = said_at(A, kw, -0.05, "keyword")
    c = {"type": "comment-cta", "at": first_at(A), "keyword": ctx.L(kw.strip().upper(), "narration"), "typeStart": t,
         "sendAt": fmt_off(t, 0.7)}
    if said(A, prompt) is not None:
        c["prompt"] = ctx.L(display(prompt), "narration")
    out = [c]
    if said(A, copy.get("pill")) is not None:
        out.append(pill(ctx, display(copy["pill"]), "narration", said_at(A, copy["pill"], -0.05, "pill"), "users"))
    return result(out, tones={w: "term" for w in tone_words(A, kw)})


def b_next_episode(ctx: Ctx, A: Anchors, copy: dict):
    """The next part, only as the brief names it (brief.next_episode {label, title, sub?})."""
    nx = (ctx.brief or {}).get("next_episode") or {}
    if not nx.get("label") or not nx.get("title"):
        return result([])
    lead = clean(A.tokens[0]) + (" " + clean(A.tokens[1]) if len(A.tokens) > 1 and A.tokens[0][-1:].isalpha() else "")
    p = pill(ctx, display(lead), "narration", first_at(A), "play")          # "Next up" from the first word
    # the card lands on the spoken title (or the label): its "up next" bar then fills while the title is said
    at = said_at(A, nx["title"], -0.1, "next") or said_at(A, nx["label"], -0.1, "next") or first_at(A)
    b = {"type": "next-episode", "at": at, "label": ctx.L(nx["label"], "brief:next_episode"),
         "title": ctx.L(nx["title"], "brief:next_episode")}
    if nx.get("sub"):
        b["sub"] = ctx.L(nx["sub"], "brief:next_episode")
    return result([p, b])


# ---- proof helpers (packs bind the values to their facts) ---------------------------------------------
def gauge_proof(ctx: Ctx, A: Anchors, copy: dict, spec: dict) -> dict:
    """A score ring that is on screen from the scene start; its readout waits for the spoken number (a verified fact
    value, `spec`) and lands there; the success stamp slams on the spoken verdict word.
    spec: {value, min?, max?, label, src, cues (the spoken number's words), suffix?, decimals?, zones?, caption?}"""
    key_at = A.at(spec["cues"], -0.05, name="gauge:value", free=True)
    g = {"type": "gauge", "style": "ring", "at": first_at(A), "min": spec.get("min", 0), "max": spec.get("max", 100),
         "label": ctx.L(spec["label"], spec["src"]), "keys": [{"at": key_at, "value": spec["value"], "dur": 0.9}]}
    for k in ("suffix", "decimals"):
        if spec.get(k) is not None:
            g[k] = spec[k]
    if spec.get("caption"):
        g["caption"] = ctx.L(spec["caption"], spec.get("caption_src", spec["src"]))
    g["zones"] = spec.get("zones") or [{"to": g["max"], "tone": "success"}]
    tones = {clean(A.tokens[i]): "success" for i, t in enumerate(A.tokens)
             if any(re.fullmatch(re.escape(c), clean(t), re.I) for c in spec["cues"])}
    out = [g]
    vt = copy.get("verdict")
    if said(A, vt) is not None:
        out.append({"type": "verdict", "text": ctx.L(display(vt), "narration"), "tone": "success", "mark": "check",
                    "at": said_at(A, vt, -0.05, "verdict"), "sfx": "success"})
        tones.update({w: "success" for w in tone_words(A, vt)})
    return result(out, tones=tones)


def countdown_proof(ctx: Ctx, A: Anchors, copy: dict, spec: dict) -> dict:
    """A duration fact as a ring that empties: a fact-bound pill holds the frame from the first word, the count starts
    on the spoken number (never before it) and runs to the line's last word.
    spec: {from, label, src, cues, pill, pill_icon?, suffix?}"""
    p = pill(ctx, spec["pill"], spec["src"], first_at(A, -0.05), spec.get("pill_icon", "shield"), "success")
    at = A.at(spec["cues"], -0.05, name="countdown", free=True)
    cd = {"type": "countdown", "at": at, "from": spec["from"], "label": ctx.L(spec["label"], spec["src"]),
          "countEnd": A.last_word(0.1, "countEnd"), "tone": "success"}
    if spec.get("suffix"):
        cd["suffix"] = spec["suffix"]
    tones = {clean(A.tokens[i]): "success" for i, t in enumerate(A.tokens)
             if any(re.fullmatch(re.escape(c), clean(t), re.I) for c in spec["cues"])}
    return result([p, cd], tones=tones)


def stepify(build, label: str, chip: str, chip_cues: list[str], src: str = "pack:template"):
    """A scene builder as an explainer step: its hero is on screen from the first word (only its beats wait), and it
    reports its header step name and the term chip added on the first spoken chip cue."""
    def b(ctx: Ctx, A: Anchors, copy: dict):
        out = build(ctx, A, copy)
        res = out if isinstance(out, dict) else {"blocks": out}
        blocks = []
        for blk in res["blocks"]:          # a step shows what it says: checklist items its line never names are dropped
            if blk.get("type") == "checklist":
                items = [it for it in blk["items"] if A.time_of(it["at"]) <= A.speech_end]
                if len(items) < 2:
                    continue
                blk = {**blk, "items": items, "at": items[0]["at"]}
            blocks.append(blk)
        res["blocks"] = blocks
        start = first_at(A)
        if blocks and A.time_of(blocks[0]["at"]) > A.time_of(start) + 0.3:
            blocks[0]["at"] = start
        chip_at = A.at(chip_cues, 0.0, name="chip", free=True) if any(A.has(c) for c in chip_cues) else None
        res["step"] = {"label": ctx.L(label, src), "chip": ctx.L(chip, src), "chip_at": chip_at}
        return res
    return b


# ---- the storyboard HUD (director) ----------------------------------------------------------------------
def step_copies(scene_plan: list[dict], copies: dict[str, dict]) -> dict[str, dict]:
    """Fill "{step}" in step copy with the scene's ordinal among the step scenes ("Step {step}:" -> "Step two:")."""
    out, n = dict(copies), 0
    for sp in scene_plan:
        c = copies.get(sp["scene"])
        if not c or "{step}" not in c.get("narration", ""):
            continue
        word = ORDINALS[min(n, len(ORDINALS) - 1)]
        out[sp["scene"]] = {**c, **{k: c[k].replace("{step}", word) for k in ("narration", "headline") if isinstance(c.get(k), str)}}
        n += 1
    return out


def _header_at(A: Anchors, n: int) -> str:
    """The header changes on the step's ordinal word ("two"), the first step shows on "Step"; else the first word."""
    head = [clean(t).lower() for t in A.tokens[:3]]
    if n == 0 and head and head[0] == STEP_PREFIX.lower():
        return A.word_expr(0)
    for i, w in enumerate(head):
        if w in ORDINALS or w.isdigit():
            return A.word_expr(i)
    return A.word_expr(0)


def compose_hud(sb: dict, steps: dict[int, dict], anchors: list[Anchors], ctx: Ctx) -> None:
    """Storyboard `hud` from the step scenes (in place): a header whose steps are the step scenes' names, shown on the
    first step and advanced on each next step's ordinal; a chip row that gains each step's term on its cue word; both
    hidden from the first scene after the last step (the value line and the endings run without them)."""
    if len(steps) < 2:
        return
    order = sorted(steps)
    sb["hud"] = {"elements": [{"id": HUD_STEP, "kind": "header", "prefix": ctx.L(STEP_PREFIX, "template"),
                               "steps": [steps[k]["label"] for k in order]},
                              {"id": HUD_TERMS, "kind": "chips"}]}
    for n, k in enumerate(order):
        A, info = anchors[k], steps[k]
        evs = [{"at": _header_at(A, n), "target": HUD_STEP, "op": "show" if n == 0 else "advance"}]
        if info.get("chip_at"):
            evs.append({"at": info["chip_at"], "target": HUD_TERMS, "op": "add", "text": info["chip"]})
        sb["scenes"][k]["hud"] = evs
    nxt = order[-1] + 1
    if nxt < len(sb["scenes"]):
        at = anchors[nxt].word_expr(0)
        sb["scenes"][nxt]["hud"] = [{"at": at, "target": HUD_STEP, "op": "hide"}, {"at": at, "target": HUD_TERMS, "op": "hide"}]


def _texts(o):
    """Every string inside a block (to avoid an eyebrow that repeats a label already on screen)."""
    if isinstance(o, dict):
        for v in o.values():
            yield from _texts(v)
    elif isinstance(o, list):
        for v in o:
            yield from _texts(v)
    elif isinstance(o, str):
        yield o


def open_scenes(sb: dict, anchors: list[Anchors], ctx: Ctx) -> None:
    """Explainer scenes open on content: a scene on a dark backdrop whose first block lands > 0.6 s in (a price card
    that waits for its spoken price, an outro that waits for the CTA) gets its opening words as a pill from the first
    word when they are a short clause ("Ready to go live?", "WP Starter:"; spoken, so bound), else the product family
    label. It goes on top as an eyebrow (last, when a template effect already targets a block by index). Runs before
    the effects director, so its block indices are final."""
    from .rules import MAX_EMPTY_OPEN, sync_report
    late = {r["scene"] for r in sync_report(sb)["scenes"] if r["opens_empty_s"] > MAX_EMPTY_OPEN}
    for k, sc in enumerate(sb["scenes"]):
        if sc["id"] not in late or sc.get("backdrop") == "light":
            continue
        m = re.match(r"^\s*([^.?!:;]{2,40}[.?!:;])", sc["narration"])
        words = m.group(1).split() if m else []
        at = first_at(anchors[k], -0.05)
        shown = {str(v).strip().lower() for b in sc["blocks"] for v in _texts(b)}
        if 1 <= len(words) <= 5 and not re.search(r"\d", m.group(1)) and display(m.group(1).rstrip(".:;")).lower() not in shown:
            text = display(m.group(1).rstrip(".:;"))
            p = pill(ctx, text, "narration", at, "zap" if text.endswith("?") else "star")
        else:                              # no short opening clause: the product family ("WordPress hosting")
            p = pill(ctx, ctx.pf.family_label, "pack:family", at, ctx.pf.family_icon)
        # an eyebrow above the scene's content; last when a template effect already targets a block index
        sc["blocks"].insert(len(sc["blocks"]) if sc.get("effects") else 0, p)


def hud_texts(sb: dict) -> list[tuple[str, str]]:
    """(where, text) of every string the storyboard HUD draws (header prefix and steps, chips, labels)."""
    out = []
    for e in (sb.get("hud") or {}).get("elements", []):
        for k in ("prefix", "label"):
            if isinstance(e.get(k), str):
                out.append((f"hud.{e.get('id')}.{k}", e[k]))
        for i, s in enumerate(e.get("steps") or []):
            out.append((f"hud.{e.get('id')}.steps[{i}]", s))
        for j, p in enumerate(e.get("parts") or []):
            if isinstance(p, dict) and isinstance(p.get("label"), str):
                out.append((f"hud.{e.get('id')}.parts[{j}]", p["label"]))
    for sc in sb.get("scenes", []):
        for ev in sc.get("hud") or []:
            if isinstance(ev.get("text"), str):
                out.append((f"{sc['id']}.hud.{ev.get('target')}", ev["text"]))
    return out


def hud_step_report(sb: dict) -> list[str]:
    """Problems with a step header: its steps must match the step scenes (one show / advance per step scene, the first
    a show, in consecutive scenes), and it must be hidden before the last (CTA) scene."""
    hud = sb.get("hud") or {}
    headers = [e for e in hud.get("elements", []) if e.get("kind") == "header"]
    if not headers:
        return []
    h = headers[0]
    probs = []
    marks = []
    for k, sc in enumerate(sb["scenes"]):
        ops = [ev.get("op") for ev in sc.get("hud") or [] if ev.get("target") == h["id"] and ev.get("op") in ("show", "advance")]
        if len(ops) > 1:
            probs.append(f"{sc['id']}: {len(ops)} header changes in one scene")
        if ops:
            marks.append((k, ops[0]))
    if len(marks) != len(h.get("steps", [])):
        probs.append(f"{len(h.get('steps', []))} header steps but {len(marks)} step scenes")
    if marks and marks[0][1] != "show":
        probs.append("the first step scene must show the header")
    ks = [k for k, _ in marks]
    if ks and ks != list(range(ks[0], ks[0] + len(ks))):
        probs.append("step scenes are not consecutive")
    hidden = any(ev.get("target") == h["id"] and ev.get("op") == "hide"
                 for sc in sb["scenes"][(ks[-1] + 1 if ks else 0):] for ev in sc.get("hud") or [])
    if ks and not hidden:
        probs.append("the step header is still on screen in the CTA scenes")
    return probs


# ---- generic library -----------------------------------------------------------------------------------
_always = lambda pf: True  # noqa: E731
GENERIC_EXPLAINER = [
    T("hook-myth-verdict", "Myth, crossed out", "hook", None, None, "verdict", "headline", ("deep", "spotlight"), "push-in", "energetic",
      "fade", "danger", (6, 14), (2, 7), {"headline": "the myth, from the first word", "cross": "the myth's last word",
                                         "verdict": "the spoken verdict word"}, (), (), _always, b_myth_verdict,
      "The myth is on screen from the first word; a hand-drawn cross strikes it and a stamp slams on the spoken verdict.",
      hold=HOLD),
    T("turn-term-reveal", "Name the product", "turn", None, None, "term-reveal", "pill", ("light", "glow"), "none", "standard",
      "whip-pan", "brand", (6, 14), None, {"kicker": "first word", "term": "<brand>", "sub": "the spoken line", "pill": "its words"},
      (), (), _always, b_term_reveal, "The spoken kicker, then the brand name slams in on its word, the spoken line beneath."),
    T("cta-poll", "Poll ending", "cta", None, None, "poll", "pill", ("grid", "spotlight"), "none", "standard", "push", None, (8, 16),
      None, {"options": "each option on its spoken words"}, (), (), _always, b_poll,
      "A spoken question; each option slides in as it is said. No votes or percentages are drawn.", hold=HOLD),
    T("cta-comment-keyword", "Comment ending", "cta", None, None, "comment-cta", "pill", ("grid", "spotlight"), "none", "standard",
      "push", None, (7, 15), None, {"keyword": "the spoken keyword"}, (), (), _always, b_comment,
      "A comment box types the spoken keyword and sends it. It asks; it never promises a reply or a download.", hold=HOLD),
    T("cta-next-episode", "Next part", "cta", None, None, "next-episode", "pill", ("spotlight", "grid"), "none", "standard", "push",
      None, (4, 12), None, {"next-episode": "first word"}, (), (), _always, b_next_episode,
      "A teaser card for the next part, exactly as the brief names it (only when the brief has next_episode).",
      hold=HOLD, needs_brief="next_episode"),
]
