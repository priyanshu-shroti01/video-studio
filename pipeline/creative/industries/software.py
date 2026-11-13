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
beats: [{cues: [spoken words], x, y, scale}]}: each beat zooms the recording to a region on the word that names it."""
from __future__ import annotations

from ..templates import T, fmt_off, ic, kinetic, pill
from . import Pack

FACT_IDS = {"pipeline": "product.pipeline", "stack": "product.stack", "qa": "evidence.qa", "concepts": "product.concepts",
            "voice": "product.voice", "render": "product.render", "llm": "product.llm", "what": "product.what",
            "self_made": "product.self_made", "architecture": "product.architecture", "workflow": "product.workflow",
            "publishing": "product.publishing", "published": "evidence.published"}
GATED = tuple(FACT_IDS)
# copy naming one of these terms is only used when the brand's fact base backs it
TERM_ROLES = {"Kokoro": "voice", "Remotion": "render", "FFmpeg": "render", "Python": "stack", "Ollama": "llm",
              "three concepts": "concepts", "quality checks": "qa", "itself": "self_made", "deterministic": "architecture",
              "YouTube": "published"}
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
    zooms = [{"at": A.at(beat["cues"], -0.15, name=f"zoom:{i}"), "x": beat["x"], "y": beat["y"], "scale": beat["scale"]}
             for i, beat in enumerate(spec.get("beats") or [])]
    if zooms:
        b["zooms"] = zooms
    return b


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


def b_hook_self(ctx, A, copy):
    f = footage_block(ctx, A, "self")
    f["at"] = A.first_word(-0.4, "cold-open")   # a cold open shows the recording from the first frame, not a bare backdrop
    return [kinetic(ctx, A, copy, "l"), f]


IND = ("software",)
_always = lambda pf: True  # noqa: E731
TEMPLATES = [
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
      "fade", None, (14, 30), None, {"nodes": "each component on its spoken name", "status": ["Mac"]}, (), (), has("stack"),
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
      "slide-up", None, (16, 40), None, {"zooms": "one per beat in the brand's clip"}, (), (), clip("preview"),
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

# ---- blueprints ---------------------------------------------------------------------------------------------
BLUEPRINTS = [
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
     "hook_tags": ["promise"], "music": "educational", "cta_style": "url-click",
     "pacing": {"label": "walkthrough", "detail": "even beats, the product on screen most of the time"}},
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
    "demo-app-footage": {"app": [
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

PACK = Pack(id="software", name="Software products (launch films, product demos)", families=FAMILIES, fact_ids=FACT_IDS,
            gated_roles=GATED, features={}, feature_cues={}, templates=TEMPLATES, bank=BANK, blueprints=BLUEPRINTS,
            plan_features=lambda ctx: [], plan_detail=lambda ctx, plan: None, compare_rows=lambda ctx, plans, A: [],
            checklist_keys=lambda family: [], cta_sub_keys=[], banned=BANNED, style=STYLE, term_roles=TERM_ROLES,
            priced=False)
