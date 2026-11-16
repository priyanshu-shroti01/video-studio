"""Industry pack: software products (developer tools, apps, platforms): launch films and product demos.

An unpriced pack (Pack.priced = False): the story is the product working, not a plan and a price. Everything on
screen comes from the brand's verified facts (knowledge/<id>/facts.json) or from the brand's own media clips
(brands/<id>/brand.json creative.footage: real screen recordings of the product). The pack expects these fact ids;
a template whose fact (or clip) is missing is simply not used:

  product.pipeline   {app, title, steps: [{label, cues}], done, done_cues}   the product's real workflow stages
  product.stack      {title, nodes: [{label, icon, cues}], status, status_cues} the real components it runs on
  evidence.qa        {title, checks, spoken, counter_label, counter_cues, items: [{text, icon, cues}]}
                     a measured QA result from a real render; `spoken` (e.g. "thirty") is how copy says the count
                     ({qa_spoken}), so the number always comes from the fact, never from the copy bank
  product.concepts   {count}                                                optional, for the copy

Media clips (creative.footage.<id>): {asset (public/-relative video), title, frame, startFrom?, playbackRate?,
beats: [{cues: [spoken words], x, y, scale, region?: {x, y, w, h}, callout?}]}: each beat zooms the recording to a region
on the word that names it. `region` is the named UI element (normalised, measured on the recording): the engine frames
it; small regions (or `callout: true`) get a magnified callout panel instead. In 9:16 the clip fills the column
(`fit: {short: "fill"}`) so the crop, not a small browser window, carries the UI."""
from __future__ import annotations

from ..explain import HOLD, display, first_at, gauge_proof, said, said_at, stepify
from ..templates import T, fmt_off, ic, kinetic, pill
from . import Pack

FACT_IDS = {"pipeline": "product.pipeline", "stack": "product.stack", "qa": "evidence.qa", "concepts": "product.concepts",
            "voice": "product.voice", "render": "product.render", "llm": "product.llm", "what": "product.what",
            "self_made": "product.self_made", "architecture": "product.architecture", "workflow": "product.workflow",
            "publishing": "product.publishing", "published": "evidence.published", "cost": "product.cost"}
GATED = tuple(FACT_IDS)
# copy naming one of these terms is only used when the brand's fact base backs it
TERM_ROLES = {"Kokoro": "voice", "Remotion": "render", "FFmpeg": "render", "Python": "stack", "Ollama": "llm",
              "three concepts": "concepts", "quality checks": "qa", "itself": "self_made", "deterministic": "architecture",
              "YouTube": "published", "teen concepts": "concepts"}   # (Hinglish: language.py)
FAMILIES = [{"id": "app", "match": None, "product": "app", "label": "Video production", "icon": "app"}]
BANNED = ["revolutionary", "game-changing", "fully autonomous", "replaces", "perfect", "unlimited", "magic", "effortless"]
STYLE = ("Engineering-launch voice: plain, specific, confident. Name the real component or stage on screen. "
         "No hype, no superlatives, no claims beyond the fact base.")


def has(*roles):
    return lambda pf: all(pf.allow.get(r, False) for r in roles)


def clip(*ids):
    """The brand declares the clip AND its recording exists (templates never point at a missing file)."""
    from ...paths import ROOT
    return lambda pf: all((pf.media or {}).get(i) and (ROOT / "public" / pf.media[i]["asset"]).exists() for i in ids)


def _fact(ctx, role) -> dict:
    return ctx.fb.by_id(FACT_IDS[role]) or {}


def footage_block(ctx, A, clip_id: str, name: str = "footage") -> dict:
    """A real screen recording from the brand's media; each beat zooms on the word that names it."""
    spec = ctx.pf.media[clip_id]
    b = {"type": "footage", "asset": spec["asset"], "frame": spec.get("frame", "browser"), "at": A.first_word(-0.1, name)}
    if spec.get("title"):
        b["title"] = ctx.L(spec["title"], "brand:media")
    for k in ("startFrom", "playbackRate", "aspect"):
        if spec.get(k) is not None:
            b[k] = spec[k]
    # 9:16: no browser chrome, the clip fills the column and the crop follows the beats (16:9 keeps the window)
    b["fit"] = {"short": "fill"}
    zooms, callouts = [], []
    prev_t = None
    for i, beat in enumerate(spec.get("beats") or []):
        at = A.at(beat["cues"], -0.15, name=f"zoom:{i}", advance=False)
        if A.used[-1]["word"] is None:
            continue            # its words aren't spoken: no move (a fallback would stack moves 0.45 s apart)
        t = A.time_of(at)
        if prev_t is not None and t - prev_t < MIN_ZOOM_GAP:
            continue            # let the view settle and be read before the camera moves again
        A.at(beat["cues"], -0.15, name=f"zoom:{i}")      # advance the cue cursor past the kept move
        A.used.pop()
        prev_t = t
        z = {"at": at, "x": beat["x"], "y": beat["y"], "scale": beat["scale"]}
        region = beat.get("region")
        if region and _wants_callout(beat):
            # a small element: the view moves to it with context, and a magnified lens of the element pops in on the word
            z["scale"] = min(beat["scale"], CALLOUT_CONTEXT_SCALE)
            callouts.append({"at": at, **{k: region[k] for k in ("x", "y", "w", "h")}})
        elif region:
            z["region"] = {k: region[k] for k in ("x", "y", "w", "h")}   # the engine frames the element (fits, centred)
        zooms.append(z)
    if zooms:
        b["zooms"] = zooms
    if callouts:
        b["callouts"] = callouts
    return b


MIN_ZOOM_GAP = 0.8            # seconds between camera moves on footage: at 0.45 s apart the view never settled to be read
CALLOUT_MAX_SIDE = 0.25       # beats naming a small element (both sides <= 1/4 of the clip) get a callout ("zoom lens");
                              # a wide element (a form row) is framed by the zoom instead, which already fills the width
CALLOUT_CONTEXT_SCALE = 1.6   # ... and the view behind the lens zooms only this far, so the viewer keeps the context


def _wants_callout(beat: dict) -> bool:
    """A beat's callout: the spec's explicit `callout` flag, else automatic for a small region."""
    if "callout" in beat:
        return bool(beat["callout"])
    r = beat.get("region") or {}
    return max(r.get("w", 1), r.get("h", 1)) <= CALLOUT_MAX_SIDE


# ---- templates --------------------------------------------------------------------------------------------
CHAIN = [("Script", ["script"]), ("Storyboard", ["storyboard"]), ("Voice-over", ["voice"]), ("Animation", ["animation"]),
         ("Render", ["rendering", "render"])]


def b_production_chain(ctx, A, copy):
    steps = [{"label": ctx.L(lbl, "pack:template"), "at": A.at(c, -0.1, name=f"step:{lbl}")} for lbl, c in CHAIN]
    # the card (its title says what the line says) is there from the first word; each step lights up as it is named
    prog = {"type": "progress", "title": ctx.L("A launch film, the usual way", "pack:template"), "steps": steps,
            "at": A.first_word(-0.1, "progress")}
    return [prog, kinetic(ctx, A, copy, "m")]


def b_hook_chain(ctx, A, copy):
    steps = [{"label": ctx.L(lbl, "pack:template"), "at": A.at(c, -0.1, name=f"step:{lbl}")} for lbl, c in CHAIN]
    prog = {"type": "progress", "title": ctx.L("Every launch film", "pack:template"), "steps": steps, "at": steps[0]["at"]}
    return [kinetic(ctx, A, copy, "l"), prog]


def b_app_footage(ctx, A, copy):
    f = footage_block(ctx, A, "app-tour")
    p = pill(ctx, "Recorded in the real app", "pack:template", A.after(0.4, "pill"), "app", "brand")
    return [f, p]


def b_storyboard_footage(ctx, A, copy):
    f = footage_block(ctx, A, "storyboard")
    p = pill(ctx, "Every beat tied to a spoken word", "pack:template", A.after(0.4, "pill"), "check", "brand")
    return [f, p]


def b_pipeline(ctx, A, copy):
    fact = _fact(ctx, "pipeline")
    v = fact["value"]
    src = f"fact:{fact['id']}"
    flow_at = A.first_word(-0.1, "window")
    steps = [{"label": ctx.L(s["label"], src), "at": A.at(s.get("cues") or [], 0.0, name=f"step:{i}")} for i, s in enumerate(v["steps"])]
    flow = {"type": "install-flow", "app": ctx.L(v["app"], src), "title": ctx.L(v["title"], src), "steps": steps,
            "doneAt": A.at(v.get("done_cues") or [], 0.0, name="done"), "doneText": ctx.L(v["done"], src), "at": flow_at}
    from ...shared_assets import app_icon
    icon = app_icon(v["app"])
    if icon:
        flow["appIcon"] = icon
    p = pill(ctx, "Human approval gates", src, A.at(["ships", "anything"], 0.0, name="pill", free=True), "check", "success")
    return [flow, p]


def b_local_stack(ctx, A, copy):
    fact = _fact(ctx, "stack")
    v = fact["value"]
    src = f"fact:{fact['id']}"
    nodes = [{"label": ctx.L(n["label"], src), "icon": ic(n.get("icon", "cpu")), "at": A.at(n.get("cues") or [], -0.1, name=f"node:{i}")}
             for i, n in enumerate(v["nodes"][:4])]
    st = {"type": "server-stack", "title": ctx.L(v["title"], src), "nodes": nodes, "at": nodes[0]["at"],
          "status": {"text": ctx.L(v["status"], src), "at": A.at(v.get("status_cues") or [], 0.0, name="status", free=True), "tone": "success"},
          "target": {"icon": ic(v.get("target_icon", "play"))}}
    return [st, pill(ctx, "No cloud required", "pack:template", A.at(["All", "all"], 0.0, name="pill", free=True), "check", "brand")]


def b_qa_proof(ctx, A, copy):
    """The measured QA count lands on its spoken number; each measured result checks in as it is named."""
    fact = _fact(ctx, "qa")
    v = fact["value"]
    src = f"fact:{fact['id']}"
    p = pill(ctx, "Measured on a real render", src, A.first_word(-0.05, "pill"), "check", "success")
    hit = A.at(v.get("counter_cues") or [], 0.0, name="counter", free=True)
    counter = {"type": "counter", "to": v["checks"], "suffix": f"/{v['checks']}", "label": ctx.L(v["counter_label"], src),
               "at": fmt_off(hit, -0.05), "countEnd": fmt_off(hit, 0.6), "tone": "success"}
    items = [{"text": ctx.L(it["text"], src), "icon": ic(it.get("icon", "check")), "at": A.at(it.get("cues") or [], -0.1, name=f"item:{i}")}
             for i, it in enumerate(v["items"])]
    return [counter, {"type": "checklist", "items": items, "at": items[0]["at"]}, p]


def b_outro_tagline(ctx, A, copy):
    """Outro (logo, CTA, repository URL) with the tagline landing word by word as it is spoken."""
    pf = ctx.pf
    first = (pf.cta.split() or ["Explore"])[0]
    o = {"type": "outro", "url": ctx.L(pf.display_url or pf.domain, "brand:domain"), "cta": ctx.L(pf.cta, "brief:cta"),
         "at": A.at([first], -0.1, name="outro"), "urlAt": A.at([pf.url_cue], 0.0, name="url")}
    return [o, kinetic(ctx, A, copy, "m")]


def b_self_footage(ctx, A, copy):
    f = footage_block(ctx, A, "self")
    return [f, kinetic(ctx, A, copy, "m")]


def b_architecture(ctx, A, copy):
    """The product's architecture principle: each layer checks in as it is named; the exact parts land as a line.
    (A library rendering; with `"components": "generate"` the composer may design this scene's hero instead.)"""
    fact = _fact(ctx, "architecture")
    v = fact["value"]
    src = f"fact:{fact['id']}"
    items = [{"text": ctx.L(l["label"], src), "icon": ic(l.get("icon", "check")), "at": A.at(l.get("cues") or [], -0.1, name=f"layer:{i}")}
             for i, l in enumerate(v["layers"])]
    # the title is there from the first word (a checklist draws nothing until its first item lands)
    title = pill(ctx, v.get("title", "How it is built"), src, A.first_word(-0.1, "title"), "settings", "brand")
    first = {"type": "checklist", "items": items, "at": items[0]["at"]}
    # the exact parts land word by word as they are spoken (the copy's headline)
    return [title, first, kinetic(ctx, A, copy, "m")] if copy.get("headline") else [title, first]


def _footage_pill(clip_id: str, text: str, icon: str, tone: str = "brand", cues: tuple[str, ...] = ()):
    """Footage plus one pill: on its cue word when given (free: it does not move the zoom cursor), else after the last zoom."""
    def build(ctx, A, copy):
        f = footage_block(ctx, A, clip_id)
        at = A.at(list(cues), -0.05, name="pill", free=True, priority=True) if cues and any(A.has(c) for c in cues) else A.after(0.4, "pill")
        return [f, pill(ctx, text, "pack:template", at, icon, tone)]
    return build


def b_hook_cost(ctx, A, copy):
    """The price promise: the line lands word by word; what it costs nothing in checks in on its spoken words."""
    fact = _fact(ctx, "cost")
    src = f"fact:{fact.get('id', 'product.cost')}"
    items = [{"text": ctx.L(i["text"], src), "icon": ic("check"), "at": A.at(i.get("cues") or [], -0.1, name=f"free:{k}")}
             for k, i in enumerate((fact.get("value") or {}).get("items") or [])]
    words = (copy.get("headline") or "").split()
    head = kinetic(ctx, A, {**copy, "emphasis": copy.get("emphasis") or words[-1:]}, "xl")   # the price word lands hardest
    return [head, {"type": "checklist", "items": items, "at": items[0]["at"]}] if items else [head]


def b_hook_self(ctx, A, copy):
    f = footage_block(ctx, A, "self")
    f["at"] = A.first_word(-0.4, "cold-open")   # a cold open shows the recording from the first frame, not a bare backdrop
    return [kinetic(ctx, A, copy, "l"), f]


IND = ("software",)
_always = lambda pf: True  # noqa: E731
TEMPLATES = [
    T("hook-zero-cost", "Free to run", "hook", IND, None, "kinetic-text", "checklist", ("spotlight", "deep"), "push-in", "energetic",
      "fade", None, (10, 22), (2, 6), {"kinetic-text": "the price, as spoken", "pill": "what it costs nothing"}, (), (),
      lambda pf: has("cost")(pf) and "cost_spoken" in (pf.spoken or {}), b_hook_cost, "The promise lands word by word, then what it needs: no subscription, no API keys."),
    T("hook-chain-progress", "The long chain", "hook", IND, None, "progress", "kinetic-text", ("spotlight", "deep"), "drift", "energetic",
      "fade", None, (9, 22), (2, 8), {"steps": ["script", "storyboard", "voice", "animation", "render"]}, (), (), _always, b_hook_chain,
      "The steps of a launch film light up one by one as they are named; the line lands beneath."),
    T("hook-self-footage", "Cold open: the film itself", "hook", IND, None, "footage", "kinetic-text", ("deep", "spotlight"), "push-in",
      "cinematic", "fade", None, (8, 20), (2, 8), {"footage": "first word", "kinetic-text": "the line"}, (), (),
      lambda pf: clip("self")(pf) and has("self_made")(pf), b_hook_self,
      "Opens on the real production page of the film being watched, then names the twist."),
    T("problem-production-chain", "The usual way", "problem", IND, None, "progress", "kinetic-text", ("grid", "deep"), "pan-left", "standard",
      "slide-up", "danger", (14, 30), (2, 8), {"steps": ["script", "storyboard", "voice", "animation", "rendering"]}, (), (), _always,
      b_production_chain, "Script, storyboard, voice-over, animation, render: each step lights as it is named; the cost lands beneath."),
    T("demo-app-footage", "The real app", "demo", IND, None, "footage", "pill", ("light", "glow"), "none", "standard", "slide-up", None,
      (14, 32), None, {"zooms": "one per beat in the brand's clip"}, (), (3,), clip("app-tour"), b_app_footage,
      "A real recording of the product; zooms land on the regions the narration names."),
    T("demo-storyboard-footage", "Inside the storyboard", "demo", IND, None, "footage", "pill", ("glow", "light"), "none", "standard",
      "mask-wipe", None, (14, 32), None, {"zooms": "one per beat in the brand's clip"}, (), (), clip("storyboard"), b_storyboard_footage,
      "A real recording of the storyboard editor; zooms follow the narration."),
    T("demo-pipeline", "The production pipeline", "demo", IND, None, "install-flow", "pill", ("light", "spotlight"), "push-in", "standard",
      "slide-up", None, (16, 34), None, {"steps": "each stage on its spoken word", "done": ["approves", "person"]}, (), (),
      has("pipeline"), b_pipeline, "The product's real stages tick through on their spoken words, ending on human approval."),
    T("proof-local-stack", "What it runs on", "proof", IND, None, "server-stack", "pill", ("grid", "deep"), "drift", "standard",
      "fade", None, (12, 30), None, {"nodes": "each component on its spoken name", "status": ["Mac"]}, (), (), has("stack"),
      b_local_stack, "The real local components light up as they are named; the status lands on the machine."),
    T("proof-qa-counter", "It checks its own work", "proof", IND, None, "counter", "checklist", ("deep", "glow"), "push-in", "standard",
      "fade", None, (14, 32), None, {"counter": "the spoken count", "checklist": "each measured result as it is named"}, (), (),
      lambda pf: has("qa")(pf) and "qa_spoken" in (pf.spoken or {}), b_qa_proof, "The measured QA count lands on its spoken number; each measured result checks in as it is named."),
    T("cta-outro", "Outro with tagline", "cta", IND, None, "outro", "kinetic-text", ("glow", "spotlight"), "none", "cinematic", "fade",
      "brand", (8, 16), (2, 8), {"outro": "the CTA's first word", "url": "<domain cue>", "kinetic-text": "the tagline"}, (), (), _always,
      b_outro_tagline, "Logo, CTA and repository URL; the tagline lands word by word as it is spoken."),
    T("explain-architecture", "How it is built", "proof", IND, None, "checklist", "kinetic-text", ("grid", "spotlight"), "drift", "standard",
      "fade", None, (16, 34), (3, 8), {"items": "each layer on its spoken name", "kinetic-text": "the exact parts, as spoken"}, (), (),
      has("architecture"), b_architecture, "The architecture principle: AI proposes, people decide, code owns the exact parts."),
    T("demo-preview-gate", "The preview gate", "demo", IND, None, "footage", "pill", ("light", "glow"), "none", "standard",
      "slide-up", None, (12, 40), None, {"zooms": "one per beat in the brand's clip"}, (), (), clip("preview"),
      _footage_pill("preview", "Checked before the render", "check", cues=("Before", "before")),
      "A real recording of the scene preview and quality gate, before the full render."),
    T("demo-render-footage", "The render, stage by stage", "demo", IND, None, "footage", "pill", ("glow", "light"), "none", "standard",
      "fade", None, (14, 32), None, {"zooms": "one per beat in the brand's clip"}, (), (), clip("render"),
      _footage_pill("render", "Every stage timed", "clock"),
      "A real recording of the render monitor: each stage and its timing."),
    T("demo-publishing-footage", "Approval and publishing", "demo", IND, None, "footage", "pill", ("light", "glow"), "none", "standard",
      "slide-up", None, (16, 36), None, {"zooms": "one per beat in the brand's clip"}, (), (),
      lambda pf: clip("publishing")(pf) and has("publishing")(pf),
      _footage_pill("publishing", "Nothing ships without a person", "users", "success", cues=("real", "Short")),
      "A real recording of the publishing page: the approved package, the hash-bound approval and the upload."),
    T("reveal-self-footage", "The reveal", "reveal", IND, None, "footage", "kinetic-text", ("spotlight", "deep"), "push-in", "cinematic",
      "fade", "brand", (8, 24), (2, 9), {"footage": "first word", "kinetic-text": "the reveal line"}, (), (),
      lambda pf: clip("self")(pf) and has("self_made")(pf), b_self_footage,
      "The real production record of this very film plays while the reveal line lands."),
]

# ---- explainer style (pipeline/creative/explain.py) ---------------------------------------------------------------
def b_qa_gauge(ctx, A, copy):
    """The measured QA count on a score ring: on screen from the first word, the readout lands on the spoken count."""
    fact = _fact(ctx, "qa")
    v = fact["value"]
    n = v["checks"]
    spec = {"value": n, "min": 0, "max": n, "label": v["counter_label"], "src": f"fact:{fact['id']}",
            "cues": list(v.get("counter_cues") or []) + [str(n)], "caption": v.get("title"),
            "zones": [{"to": n - 1, "tone": "warning"}, {"to": n, "tone": "success"}] if n > 1 else None}
    return gauge_proof(ctx, A, copy, spec)


def b_point_cost(ctx, A, copy):
    """The value line: the spoken question as a pill from the first word, the fact's spoken price landing word by word
    as it is said (in words: an unpriced product shows no currency amount), what it costs nothing checking in as named."""
    fact = _fact(ctx, "cost")
    v = fact.get("value") or {}
    src = f"fact:{fact.get('id', FACT_IDS['cost'])}"
    out = []
    if said(A, copy.get("pill")) is not None:
        out.append(pill(ctx, display(copy["pill"]), "narration", first_at(A, -0.05), "zap", "brand"))
    spoken = (ctx.pf.spoken or {}).get("cost_spoken", "")
    land = said_at(A, spoken, -0.05, "price") if spoken else None
    if land:
        words = display(spoken)
        out.append({"type": "kinetic-text", "words": ctx.L(words, "narration"), "size": "xl", "align": "center", "at": land,
                    "emphasis": [words.split()[-1]]})
    named = [i for i in v.get("items") or [] if any(A.has(c) for c in i.get("cues") or [])]   # only what the line names
    items = [{"text": ctx.L(i["text"], src), "icon": ic("check"), "at": A.at(i.get("cues") or [], -0.1, name=f"free:{k}")}
             for k, i in enumerate(named)]
    if items:
        out.append({"type": "checklist", "items": items, "at": items[0]["at"]})
    return out


IND_EXPLAINER = [
    T("step-brief-footage", "Step: the brief", "demo", IND, None, "footage", "pill", ("light", "glow"), "none", "standard", "whip-pan",
      None, (8, 18), None, {"zooms": "one per beat in the brand's clip", "chip": ["brief"]}, (), (3,), clip("app-tour"),
      stepify(_footage_pill("app-tour", "Recorded in the real app", "app"), "Brief", "Brief", ["brief", "product"]),
      "Explainer step: the real app turns a short brief into three ideas; the header advances, the chip lands on 'brief'.",
      hero_key="footage:app-tour"),
    T("step-preview-footage", "Step: the preview", "demo", IND, None, "footage", "pill", ("glow", "light"), "none", "standard", "push",
      None, (8, 18), None, {"zooms": "one per beat in the brand's clip", "chip": ["preview", "frame"]}, (), (), clip("preview"),
      stepify(_footage_pill("preview", "Checked before the render", "check", cues=("before", "Before")), "Preview", "Preview",
              ["preview", "frame"]),
      "Explainer step: every frame watched with the real voice before the render.", hero_key="footage:preview"),
    T("step-qa-gauge", "Step: it checks itself", "proof", IND, None, "gauge", "verdict", ("glow", "spotlight"), "none", "standard",
      "push", None, (6, 16), None, {"gauge": "from the first word; the readout on the spoken count", "verdict": "the spoken verdict"},
      (), (), lambda pf: has("qa")(pf) and "qa_spoken" in (pf.spoken or {}),
      stepify(b_qa_gauge, "QA", "QA", ["checks", "check"]),
      "Explainer step and proof: the measured QA count fills a ring on its spoken number; a success stamp lands.", hold=HOLD),
    T("point-zero-cost", "The cost line", "point", IND, None, "kinetic-text", "checklist", ("spotlight", "glow"), "push-in", "energetic",
      "zoom-through", "brand", (6, 14), None, {"kinetic-text": "the spoken price", "checklist": "what it costs nothing, as named"},
      (), (), lambda pf: has("cost")(pf) and "cost_spoken" in (pf.spoken or {}), b_point_cost,
      "The value line after the steps: the question, the fact's price line on its spoken words, then what it needs: nothing."),
]
TEMPLATES += IND_EXPLAINER

# ---- blueprints ---------------------------------------------------------------------------------------------
BLUEPRINTS = [
    {"id": "teaser-zero-cost", "name": "Zero Cost", "pattern": "promise-demo-proof-close",
     "pattern_name": "Price promise → The real app → What it runs on → Watch every frame → Close",
     "logline": "A fast teaser: the price promise, the real app making a video, the local stack that makes it free, "
                "and the frame-by-frame preview, then the code.",
     "slots": [("hook", ["hook-zero-cost"]), ("demo", ["demo-app-footage"]), ("proof", ["proof-local-stack"]),
               ("demo", ["demo-preview-gate"]), ("cta", ["cta-outro"])],
     "hook_tags": ["promise"], "music": "technology", "cta_style": "url-click",
     "pacing": {"label": "teaser", "detail": "quick promise, two real-app beats around the proof, a short close"}},
    {"id": "whole-pipeline", "name": "The Whole Pipeline", "pattern": "question-problem-reveal-architecture-walkthrough-twist",
     "pattern_name": "Cold open on this film → The usual way → Reveal → Architecture → Every stage, in the real app → Close",
     "logline": "Open on the studio playing this very film, then explain how it is built and walk every stage of a real "
                "production in the real app, from brief to publishing, with recordings and explanations alternating.",
     "slots": [("hook", ["hook-self-footage"]), ("problem", ["problem-production-chain"]), ("turn", ["turn-logo-sting"]),
               ("proof", ["explain-architecture"]), ("demo", ["demo-app-footage"]), ("demo", ["demo-pipeline"]),
               ("demo", ["demo-preview-gate"]), ("proof", ["proof-local-stack"]), ("demo", ["demo-render-footage"]),
               ("proof", ["proof-qa-counter"]), ("demo", ["demo-publishing-footage"]), ("cta", ["cta-outro"])],
     "hook_tags": ["twist"], "music": "technology", "cta_style": "url-click",
     "pacing": {"label": "full walkthrough", "detail": "a quick setup, the architecture, then one beat per real stage, a held twist"}},
    {"id": "it-created-itself", "name": "It Created Itself", "pattern": "question-problem-reveal-demo-proof-twist",
     "pattern_name": "Question → The usual way → Reveal → Real app → Pipeline → Stack → Proof → Twist → Close",
     "logline": "Ask what a launch film would look like if the software made it, show the long usual chain, reveal the studio, "
                "walk its real workflow and machinery, prove the result, then reveal this film is its own output.",
     "slots": [("hook", ["hook-kinetic-spotlight"]), ("problem", ["problem-production-chain"]), ("turn", ["turn-logo-sting"]),
               ("demo", ["demo-app-footage", "demo-storyboard-footage"]), ("demo", ["demo-pipeline"]),
               ("proof", ["proof-local-stack"]), ("proof", ["proof-qa-counter"]), ("reveal", ["reveal-self-footage"]),
               ("cta", ["cta-outro"])],
     "hook_tags": ["question"], "music": "technology", "cta_style": "url-click",
     "pacing": {"label": "launch keynote", "detail": "quiet question, quick problem, long product middle, a held beat before the twist"}},
    {"id": "proof-first", "name": "Proof First", "pattern": "cold-open-explanation",
     "pattern_name": "Cold open on the film itself → Reveal → Pipeline → Real app → Proof → Close",
     "logline": "Open on the production record of the film being watched, name the twist immediately, then explain how.",
     "slots": [("hook", ["hook-self-footage"]), ("turn", ["turn-logo-sting"]), ("demo", ["demo-pipeline"]),
               ("demo", ["demo-app-footage", "demo-storyboard-footage"]), ("proof", ["proof-qa-counter"]),
               ("cta", ["cta-outro"])],
     "hook_tags": ["twist"], "music": "cinematic", "cta_style": "logo-lockup",
     "pacing": {"label": "twist first", "detail": "the payoff up front, then a brisk explanation"}},
    {"id": "brief-to-film", "name": "From Brief to Film", "pattern": "tutorial-walkthrough",
     "pattern_name": "The chain → Inside the storyboard → What it runs on → Proof → Twist → Close",
     "logline": "A walkthrough: the chain every film needs, the storyboard where it is designed, the machine it runs on, the evidence, "
                "and the reveal that this walkthrough is itself an output.",
     "slots": [("hook", ["hook-chain-progress"]), ("demo", ["demo-storyboard-footage", "demo-app-footage", "demo-preview-gate"]),
               ("proof", ["proof-local-stack"]), ("proof", ["proof-qa-counter"]), ("reveal", ["reveal-self-footage"]),
               ("cta", ["cta-outro"])],
     # longer briefs: how it is built, then the render itself
     "optional": [(2, "proof", ["explain-architecture"]), (3, "demo", ["demo-render-footage"])],
     "hook_tags": ["promise"], "music": "educational", "cta_style": "url-click",
     "pacing": {"label": "walkthrough", "detail": "even beats, the product on screen most of the time"}},
    # explainer style (explain.py): a step header and term chips across the step scenes; a poll before the close when
    # the brief's scene window has room
    {"id": "explainer-steps", "name": "Myth, Steps, Proof", "pattern": "explainer-myth-steps",
     "pattern_name": "Myth, crossed out → Name it → Step 1: brief → Step 2: preview → Step 3: QA on a gauge → The cost → (Poll) → Close",
     "logline": "Cross out the belief that product videos need an agency or a subscription, name the studio, walk three steps "
                "on a step header in the real app, prove the QA score on a gauge, land the zero cost, then ask and close.",
     "slots": [("hook", ["hook-myth-verdict"]), ("turn", ["turn-term-reveal"]), ("demo", ["step-brief-footage"]),
               ("demo", ["step-preview-footage"]), ("proof", ["step-qa-gauge"]), ("point", ["point-zero-cost"]),
               ("cta", ["cta-outro"])],
     "engage": [(6, "cta", ["cta-poll", "cta-comment-keyword", "cta-next-episode"])],
     "hud": "steps", "hook_tags": ["myth"], "music": "technology", "cta_style": "url-click",
     "pacing": {"label": "explainer", "detail": "a stamped myth, three numbered steps under a step header, a proof, an ask"}},
]

# ---- copy bank (family "app") ---------------------------------------------------------------------------------
BANK: dict[str, dict[str, list[dict]]] = {
    "hook-kinetic-spotlight": {"app": [
        {"id": "question", "narration": "What if the software you built could make its own launch film?",
         "headline": "make its own launch film", "emphasis": ["film?"], "tags": ["question"]},
    ]},
    "hook-chain-progress": {"app": [
        {"id": "chain", "narration": "Script. Storyboard. Voice. Animation. Render. Every launch film is a long chain.",
         "headline": "Every launch film is a long chain.", "emphasis": ["chain."], "tags": ["promise"]},
    ]},
    "hook-self-footage": {"app": [
        {"id": "watching", "narration": "You are watching a film that was made by the software it is about.",
         "headline": "made by the software it is about", "emphasis": ["about."], "tags": ["twist"]},
    ]},
    "problem-production-chain": {"app": [
        {"id": "usual", "narration": "A launch film usually means a script, a storyboard, a voice-over, animation and rendering. "
                                     "Every step needs its own tool, and its own time.",
         "headline": "its own tool, and its own time.", "emphasis": ["time."]},
    ]},
    "turn-logo-sting": {"app": [
        {"id": "meet", "narration": "Meet {brand}. A brief goes in. A finished film comes out.",
         "headline": "A brief goes in. A finished film comes out."},
    ]},
    "hook-zero-cost": {"app": [
        {"id": "promise", "narration": "Make product videos for {cost_spoken}, right on your Mac. No subscription. No API keys.",
         "headline": "Make product videos for {cost_spoken}.", "tags": ["promise"]},
    ]},
    "demo-app-footage": {"app": [
        {"id": "wizard", "narration": "Pick your website, say what you want to promote, and the studio offers three ideas "
                                      "to choose from."},
        {"id": "brief", "narration": "Write a short brief: the product, the audience, the goal. "
                                     "The studio drafts three concepts, each one a sequence of designed scenes."},
    ]},
    "demo-storyboard-footage": {"app": [
        {"id": "storyboard", "narration": "Pick a concept, and the storyboard appears: every scene designed, "
                                          "every animation tied to the exact word that names it."},
    ]},
    "demo-pipeline": {"app": [
        {"id": "stages", "narration": "Then the pipeline runs. Concepts. Storyboard. A preview gate. A local voice. "
                                      "The render. Quality checks. And a person approves before anything ships."},
    ]},
    "explain-architecture": {"app": [
        {"id": "principle", "narration": "Under the hood, AI proposes, humans decide, and code owns what must be "
                                         "exact: timing, layout, facts and files.",
         "headline": "timing, layout, facts and files.", "emphasis": ["files."]},
    ]},
    "demo-preview-gate": {"app": [
        {"id": "watch", "narration": "Before anything renders, watch every frame with the real voice and approve it."},
        {"id": "gate", "narration": "In the storyboard, every animation is tied to the word that names it. Before the voice, "
                                    "each scene renders as a quick preview. A quality gate checks it, and a person approves it."},
    ]},
    "demo-render-footage": {"app": [
        {"id": "stages", "narration": "Then the render runs in stages you can watch: the voice, the timeline, the frames, "
                                      "the mix, and the checks."},
    ]},
    "demo-publishing-footage": {"app": [
        {"id": "publish", "narration": "Last, a person approves the exact package. Publishing is a separate, confirmed step. "
                                       "A real Short reached YouTube exactly this way."},
    ]},
    "proof-local-stack": {"app": [
        {"id": "local", "narration": "Python, Kokoro, Remotion and FFmpeg. All of it runs locally, on one Mac."},
        {"id": "stack", "narration": "Python orchestrates. Kokoro speaks. Remotion renders. FFmpeg masters the sound. "
                                     "All of it runs on one Mac."},
    ]},
    "proof-qa-counter": {"app": [
        {"id": "checks", "narration": "Then it checks its own work: {qa_spoken} blocking checks. Audio and picture in sync. "
                                      "Every claim verified. Captions and layout checked."},
    ]},
    "reveal-self-footage": {"app": [
        {"id": "itself", "narration": "And this film? It was produced with {brand} itself.",
         "headline": "produced with {brand} itself.", "emphasis": ["itself."]},
    ]},
    "cta-outro": {"app": [
        {"id": "code", "narration": "{cta_spoken} on GitHub. Built to create. Used to create itself.",
         "headline": "Built to create. Used to create itself."},
    ]},
    "cta-logo-lockup": {"app": [
        {"id": "code", "narration": "{cta_spoken} on GitHub, and see how it was made."},
    ]},
}

# explainer copy (English; kept apart from the entries above so language variants merge cleanly). Every on-screen
# phrase (headline, verdict, sub, pill, question, options, prompt, keyword) is spoken verbatim in its line.
BANK_EXPLAINER: dict[str, dict[str, list[dict]]] = {
    "hook-myth-verdict": {"app": [
        {"id": "agency", "narration": "Product videos need an agency, or a pricey subscription? Wrong.",
         "headline": "Product videos need an agency, or a pricey subscription?", "verdict": "Wrong", "danger": ["agency", "pricey subscription"],
         "tags": ["myth"]},
        {"id": "budget", "narration": "A product video needs a big budget? Wrong.", "headline": "A product video needs a big budget?",
         "verdict": "Wrong", "danger": ["big budget"], "tags": ["myth"]},
        {"id": "team", "narration": "Making a launch film takes a whole team? Wrong. It takes a brief.",
         "headline": "Making a launch film takes a whole team?", "verdict": "Wrong", "danger": ["whole team"], "tags": ["myth"]},
    ]},
    "turn-term-reveal": {"app": [
        {"id": "meet", "narration": "Meet {brand}: brief in, film out, all on your Mac.", "kicker": "Meet",
         "sub": "brief in, film out", "pill": "all on your Mac"},
        {"id": "short", "narration": "Meet {brand}. Brief in, film out.", "kicker": "Meet", "sub": "Brief in, film out"},
    ]},
    "step-brief-footage": {"app": [
        {"id": "brief", "narration": "Step {step}: pick your website, write a short brief, and get three ideas."},
        {"id": "short", "narration": "Step {step}: write a short brief, and get three ideas."},
    ]},
    "step-preview-footage": {"app": [
        {"id": "watch", "narration": "Step {step}: preview every frame with the real voice, before anything renders."},
        {"id": "short", "narration": "Step {step}: preview every frame before it renders."},
    ]},
    "step-qa-gauge": {"app": [
        {"id": "checks", "narration": "Step {step}: it checks its own work, {qa_spoken} blocking checks. All pass.", "verdict": "All pass"},
        {"id": "short", "narration": "Step {step}: {qa_spoken} blocking checks. All pass.", "verdict": "All pass"},
    ]},
    "point-zero-cost": {"app": [
        {"id": "cost", "narration": "The cost? Just {cost_spoken}. No subscription, no API keys.", "pill": "The cost?"},
        {"id": "short", "narration": "The cost? It is {cost_spoken}. No subscription.", "pill": "The cost?"},
    ]},
    "cta-poll": {"app": [
        {"id": "first", "narration": "What will you make first? A product demo, a launch film, or a YouTube Short?",
         "question": "What will you make first?", "options": ["product demo", "launch film", "YouTube Short"]},
        {"id": "short", "narration": "What will you make first? A demo, a launch film, or a Short?",
         "question": "What will you make first?", "options": ["demo", "launch film", "Short"]},
    ]},
    "cta-comment-keyword": {"app": [
        {"id": "step", "narration": "Which step would you try first? Comment its name, like PREVIEW.",
         "prompt": "Which step would you try first?", "keyword": "PREVIEW"},
    ]},
}
for _tid, _fams in BANK_EXPLAINER.items():
    BANK.setdefault(_tid, {}).update(_fams)

PACK = Pack(id="software", name="Software products (launch films, product demos)", families=FAMILIES, fact_ids=FACT_IDS,
            gated_roles=GATED, features={}, feature_cues={}, templates=TEMPLATES, bank=BANK, blueprints=BLUEPRINTS,
            plan_features=lambda ctx: [], plan_detail=lambda ctx, plan: None, compare_rows=lambda ctx, plans, A: [],
            checklist_keys=lambda family: [], cta_sub_keys=[], banned=BANNED, style=STYLE, term_roles=TERM_ROLES,
            priced=False)
