"""Scene template library — generic layer (any industry). Industry packs (pipeline/creative/industries) add
their own templates and supply the industry-specific bits the generic templates need (feature labels,
plan details, comparison rows, product-family pill).

A template owns the COMPOSITION of a scene: hero block(s), supporting block, backdrop, camera, motion,
transition and mood, the narration word budget, which narration words trigger which visual beat (cue mapping),
and which verified facts feed which on-screen fields (fact bindings). Copy (narration and an optional on-screen
phrase that must be spoken in the narration) comes from the copy bank or the LLM copy assistant; every other
visible string is a template constant or a verified fact, recorded in `Ctx.labels` with its source so the
"labels are bound" rule can prove it.

Sync contract (every template): each visual beat is anchored to the spoken word it illustrates
("@word:theme"), never to the scene start; every enumerated spoken item gets its own beat; a price or number
appears on the word that says it (never > 0.3 s early); at most ~2.4 s of estimated narration (QA limit 2.5 s)
without a visual event (checked by rules.sync_report)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from ..contract import ICONS
from ..intelligence.facts import FactBase
from .anchors import Anchors, _fmt
from .product import ProductFacts

ROLES = ("hook", "problem", "turn", "demo", "proof", "pricing", "cta")
ROLE_PURPOSE = {"hook": "hook", "problem": "problem", "turn": "turn", "demo": "journey", "proof": "point",
                "pricing": "resolution", "reveal": "resolution", "cta": "cta"}


def ic(name: str, fallback: str = "check") -> str:
    return name if name in ICONS else fallback


@dataclass
class Ctx:
    pf: ProductFacts
    fb: FactBase
    pack: object
    labels: dict[str, str] = field(default_factory=dict)     # every on-screen string -> its source

    def L(self, text: str, src: str = "template") -> str:
        self.labels.setdefault(text, src)
        return text

    def feature(self, key: str) -> tuple[str, str] | None:
        """(label, icon) of a fact-bound feature, or None when its fact is missing / not for this product."""
        ent = self.pack.features.get(key)
        if not ent:
            return None
        label, icon, fid, fams, role = (list(ent) + [None])[:5]
        if not self.fb.by_id(fid) or (fams and self.pf.family not in fams):
            return None
        if role and not self.pf.allow.get(role, False):
            return None
        return self.L(label, f"fact:{fid}"), ic(icon)

    def feature_fact(self, key: str) -> str:
        return self.pack.features[key][2]

    def cues(self, key: str) -> list[str]:
        c = self.pack.feature_cues.get(key)
        if c:
            return list(c)
        ent = self.pack.features.get(key)
        return [w for w in re.findall(r"[A-Za-z][\w]+", ent[0]) if len(w) > 3] if ent else []

    def features(self, keys: list[str]) -> list[tuple[str, str, str]]:
        out = []
        for k in keys:
            f = self.feature(k)
            if f:
                out.append((k, *f))
        return out

    def fact(self, role: str) -> str | None:
        fid = self.pf.fact_ids.get(role)
        return fid if fid and self.fb.by_id(fid) else None


@dataclass(frozen=True)
class SceneTemplate:
    id: str
    name: str
    role: str
    industries: tuple[str, ...] | None         # None = generic (any industry)
    families: tuple[str, ...] | None           # None = every product family of the pack
    hero: str
    support: str
    backdrops: tuple[str, ...]
    camera: str
    motion: str
    transition: str
    mood: str | None
    words: tuple[int, int]
    headline: tuple[int, int] | None           # on-screen phrase (words), must be spoken in the narration
    cues: dict                                 # element -> spoken trigger words (documentation + LLM brief)
    binds: tuple[str, ...]                     # bound fact values copy may say (prices, GB...)
    numbers: tuple[int, ...]                   # narrative counts copy may say ("six months", "seven-day")
    requires: Callable[[ProductFacts], bool]
    build: Callable[["Ctx", Anchors, dict], list[dict]]
    describe: str

    @property
    def generic(self) -> bool:
        return self.industries is None

    def available(self, pf: ProductFacts) -> bool:
        return (self.families is None or pf.family in self.families) and self.requires(pf)


def T(id, name, role, industries, families, hero, support, backdrops, camera, motion, transition, mood, words, headline, cues,
      binds, numbers, requires, build, describe) -> SceneTemplate:
    return SceneTemplate(id, name, role, industries, families, hero, support, backdrops, camera, motion, transition, mood, words,
                         headline, cues, binds, numbers, requires, build, describe)


_always = lambda pf: True  # noqa: E731


# ---- block helpers -----------------------------------------------------------------------------------
def fmt_off(expr: str, off: float) -> str:
    m = re.match(r"^(.*?)([+-]\d+(?:\.\d+)?)?$", expr)
    return _fmt(m.group(1), float(m.group(2) or 0) + off)


def phrase_index(A: Anchors, phrase: str) -> int | None:
    from ..timing import norm
    want = [norm(w) for w in phrase.split() if norm(w)]
    toks = [norm(t) for t in A.tokens]
    for i in range(len(toks) - len(want) + 1):
        if toks[i:i + len(want)] == want:
            return i
    return None


def kinetic(ctx: Ctx, A: Anchors, copy: dict, size: str = "l") -> dict:
    head = copy.get("headline") or ""
    i = phrase_index(A, head)
    b = {"type": "kinetic-text", "words": ctx.L(head, "narration"), "size": size, "align": "center",
         "at": fmt_off(A.word_expr(i if i is not None else 0), -0.05)}
    if copy.get("emphasis"):
        b["emphasis"] = list(copy["emphasis"])
    return b


def pill(ctx: Ctx, text: str, src: str, at: str, icon: str = "check", tone: str = "brand") -> dict:
    return {"type": "pill", "text": ctx.L(text, src), "tone": tone, "icon": ic(icon), "at": at}


def checklist(ctx: Ctx, A: Anchors, keys: list[str], name: str = "checklist") -> dict | None:
    items = []
    for k, label, icon in ctx.features(keys):
        items.append({"text": label, "icon": icon, "at": A.at(ctx.cues(k), -0.1, name=f"{name}:{k}")})
    return {"type": "checklist", "items": items, "at": items[0]["at"]} if len(items) >= 2 else None


def num(n) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def plan_word(name: str) -> str:
    return name.split()[-1]


def trio_of(pf: ProductFacts):
    i = pf.plans.index(pf.featured)
    return pf.plans[max(0, min(i - 1, len(pf.plans) - 3)):][:3] if i > 0 else pf.plans[:3]


def side_feature(ctx: Ctx, keys: list[str]) -> tuple[str, str, str] | None:
    for k in keys:
        f = ctx.feature(k)
        if f:
            return k, f[0], f[1]
    return None


# ---- generic builders --------------------------------------------------------------------------------
def b_hook_kinetic(ctx, A, copy):
    pf = ctx.pf
    p = pill(ctx, pf.family_label, "pack:family", A.first_word(0.0, "pill"), pf.family_icon)
    # cinematic opener: the whole spoken line lands word by word (every word is a visual beat)
    return [p, kinetic(ctx, A, {**copy, "headline": copy["narration"]}, "l")]


def b_logo_sting(ctx, A, copy):
    at = A.at(["Meet", "This", ctx.pf.name_cue], -0.05, name="sting")
    # the spoken positioning line lands word by word under the logo
    return [{"type": "logo-sting", "variant": "onDark", "at": at}, kinetic(ctx, A, copy, "m")]


def b_feature_checklist(ctx, A, copy):
    keys = ctx.pack.checklist_keys(ctx.pf.family)
    cl = checklist(ctx, A, keys, name="features")
    out = [cl] if cl else []
    side = side_feature(ctx, ["activation", "money_back"])
    if side:
        out.append(pill(ctx, side[1], f"fact:{ctx.feature_fact(side[0])}", A.at(ctx.cues(side[0]), 0.0, name="pill", free=True), side[2], "success"))
    return out


def _billing(ctx) -> str:
    base = "Billed monthly" if ctx.pf.period == "month" else "Billed yearly"
    return base + (" · excl. taxes" if ctx.fact("taxes") else "")


def b_plan_card(ctx, A, copy):
    pf, p = ctx.pf, ctx.pf.featured
    price_at = A.at([num(pf.price)], -0.1, name="price")
    feats = ctx.pack.plan_features(ctx)
    features = [{"text": ctx.L(t, src), "icon": ic(icon), "at": A.at(cues, -0.1, name=f"feature:{t}")} for t, icon, src, cues in feats[:4]]
    card = {"type": "plan-card", "name": ctx.L(p.name, f"fact:{pf.price_fact}"), "price": pf.price, "currency": pf.currency_symbol,
            "period": pf.per_short, "billing": ctx.L(_billing(ctx), f"fact:{ctx.fact('taxes') or pf.price_fact}"), "features": features,
            "ctaLabel": ctx.L(pf.cta, "brief:cta"), "countFrom": 0, "at": price_at, "countEnd": fmt_off(price_at, 0.7)}
    if p.badge:
        card["badge"] = ctx.L(p.badge, f"fact:{p.facts['badge']}")
    out = [card]
    side = side_feature(ctx, ["renewal", "activation"])
    if side:
        card["highlightAt"] = A.at(ctx.cues(side[0]) + ["same"], 0.0, name="highlight")
        out.append(pill(ctx, side[1], f"fact:{ctx.feature_fact(side[0])}", card["highlightAt"], side[2], "success"))
    return out


def b_price_compare(ctx, A, copy):
    pf = ctx.pf
    p = pf.featured
    winner: dict = {}
    cyc = ctx.fact("billing_cycles")
    if p.semi and p.annual and pf.period == "month":
        s = pf.second
        xs = [p, s] if s and s.semi and s.annual else [p]
        cols = [ctx.L(x.name, f"fact:{x.facts['monthly']}") for x in xs]
        def vals(attr):
            return [ctx.L(pf.money(getattr(x, attr)), f"fact:{x.facts[attr]}") for x in xs]
        rows = [{"label": ctx.L("Monthly", f"fact:{cyc}" if cyc else "template"), "values": vals("monthly"),
                 "at": A.at([num(p.monthly)], -0.1, name="row:monthly"), "highlight": 0},
                {"label": ctx.L("6 months", f"fact:{cyc}" if cyc else "template"), "values": vals("semi"),
                 "at": A.at(["six", num(p.semi)], -0.1, name="row:semi", priority=True)},
                {"label": ctx.L("Yearly", f"fact:{cyc}" if cyc else "template"), "values": vals("annual"),
                 "at": A.at([num(p.annual), "yearly", "year"], -0.1, name="row:annual", priority=True), "highlight": 0}]
        title = ctx.L("Choose your billing", "template")
    else:
        trio = trio_of(pf)
        per = "monthly" if pf.period == "month" else "annual"
        cols = [ctx.L(x.name, f"fact:{x.facts[per]}") for x in trio]
        rows = [{"label": ctx.L("Monthly" if per == "monthly" else "Yearly", "template"),
                 "values": [ctx.L(pf.money(x.price(pf.period)), f"fact:{x.facts[per]}") for x in trio],
                 "at": A.at([num(pf.price)], -0.1, name="row:price"), "highlight": trio.index(p)}]
        rows += ctx.pack.compare_rows(ctx, trio, A)
        nxt = trio.index(p) + 1
        if nxt < len(trio):
            winner = {"winner": nxt, "winnerAt": A.at(["Bigger", "bigger", "step"], 0.0, name="winner", free=True),
                      "winnerLabel": ctx.L("More room", "template")}
        title = ctx.L("Compare plans", "template")
    pc = {"type": "price-compare", "title": title, "columns": cols, "rows": rows, "at": rows[0]["at"], **winner}
    out = [pc]
    side = side_feature(ctx, ["renewal", "free_domain", "activation"])
    if side:
        out.append(pill(ctx, side[1], f"fact:{ctx.feature_fact(side[0])}",
                        A.at(["free", "domain", "renewal", "renews", "instant"], 0.0, name="pill", free=True, priority=True), side[2], "success"))
    return out


def b_plans_lineup(ctx, A, copy):
    pf = ctx.pf
    p = pf.featured
    trio = trio_of(pf)
    # three cards only fit short names / prices; otherwise show the featured plan and its neighbour
    if any(len(x.name) > 8 or len(pf.money(x.price(pf.period))) > 5 for x in trio):
        s = pf.second
        trio = sorted([p] + ([s] if s else []), key=lambda x: x.price(pf.period))
    key = "monthly" if pf.period == "month" else "annual"
    plans = []
    for x in trio:
        d = {"name": ctx.L(x.name, f"fact:{x.facts[key]}"), "price": ctx.L(pf.money(x.price(pf.period)), f"fact:{x.facts[key]}"),
             "period": pf.per_short}
        det = ctx.pack.plan_detail(ctx, x)
        if det:
            d["detail"] = ctx.L(*det)
        if x.badge:
            d["badge"] = ctx.L(x.badge, f"fact:{x.facts['badge']}")
        plans.append(d)
    at = A.at([num(pf.price)], -0.1, name="plans")
    cur = A.at(["plan", "Pick", plan_word(p.name)], -0.1, gap=0.4, name="cursor")
    blk = {"type": "plans", "plans": plans, "at": at, "emphasizeAt": fmt_off(at, 0.3),
           "select": {"index": trio.index(p), "cursorStart": cur, "clickAt": fmt_off(cur, 0.45)}}
    out = [blk]
    s = pf.second
    if s and s.badge and s in trio and A.has("popular"):
        out.append(pill(ctx, f"{s.name}: {s.badge}", f"fact:{s.facts['badge']}", A.at(["popular"], 0.0, name="pill", free=True), "star"))
    elif A.has("upgrade") and ctx.fact("upgrade"):
        out.append(pill(ctx, "Upgrade any time", f"fact:{ctx.fact('upgrade')}", A.at(["upgrade"], 0.0, name="pill", free=True), "arrowUp", "success"))
    else:
        side = side_feature(ctx, ["free_domain", "renewal", "activation"])
        if side:
            out.append(pill(ctx, side[1], f"fact:{ctx.feature_fact(side[0])}", A.at(["free", "domain", "renewal", "instant"], 0.0,
                                                                                     name="pill", free=True), side[2], "success"))
    return out


def b_counter_flat(ctx, A, copy):
    pf, p = ctx.pf, ctx.pf.featured
    yearly = bool(p.annual)
    amount = p.annual if yearly else p.monthly
    src = f"fact:{p.facts['annual' if yearly else 'monthly']}"
    c_at = A.at([num(amount)], -0.1, name="counter")
    counter = {"type": "counter", "to": amount, "from": 0, "prefix": pf.currency_symbol, "suffix": "/yr" if yearly else "/mo",
               "grouping": "indian" if p.currency == "INR" else "western",
               "label": ctx.L(f"{p.name} · billed {'yearly' if yearly else 'monthly'}", src),
               "at": c_at, "countEnd": fmt_off(c_at, 0.8), "tone": "brand", "size": "l"}
    lbls = ["Year 1", "Year 2", "Year 3"] if yearly else ["Month 1", "Month 12", "Month 24"]
    val = ctx.L(pf.money(amount), src)
    fl_at = A.at(["renews", "renewal", "renew", "next", "still"], -0.1, gap=0.9, name="flat-line")
    fl = {"type": "flat-line", "title": ctx.L(f"Your {p.name} bill", "template"),
          "points": [{"label": ctx.L(x, "template"), "value": val} for x in lbls], "at": fl_at,
          "drawEnd": A.at([num(amount), "again", "still", "renewal"], 0.3, gap=0.8, name="drawEnd")}
    return [counter, fl]


def b_outro(ctx, A, copy):
    pf = ctx.pf
    first = (pf.cta.split() or ["Get"])[0]
    o = {"type": "outro", "url": ctx.L(pf.display_url or pf.domain, "brand:domain"), "cta": ctx.L(pf.cta, "brief:cta"),
         "at": A.at([first], -0.1, name="outro"), "urlAt": A.at([pf.url_cue], 0.0, name="url")}
    if pf.tagline:
        o["tagline"] = ctx.L(pf.tagline, f"fact:{pf.tagline_fact}" if pf.tagline_fact else "brand:tagline")
    out = [o]
    side = side_feature(ctx, ["money_back", "renewal", "activation"])
    if side:
        out.append(pill(ctx, side[1], f"fact:{ctx.feature_fact(side[0])}", A.at(ctx.cues(side[0]), 0.0, gap=0.6, name="pill"),
                        side[2], "success"))
    return out


def b_logo_lockup(ctx, A, copy):
    pf = ctx.pf
    first = (pf.cta.split() or ["Get"])[0]
    logo = {"type": "logo", "variant": "onDark", "width": 720, "at": A.first_word(-0.05, "logo")}
    cta_at = A.at([first], -0.1, name="cta")
    url_at = A.at([pf.url_cue], 0.0, name="url")
    subs = [f[1] for f in ctx.features(ctx.pack.cta_sub_keys)][:2]
    cta = {"type": "cta", "text": ctx.L(pf.cta, "brief:cta"), "url": ctx.L(pf.display_url or pf.domain, "brand:domain"), "at": cta_at, "urlAt": url_at,
           "clickAt": fmt_off(url_at, 0.55)}
    if subs:
        cta["sub"] = ctx.L(" · ".join(subs), "facts")
    return [logo, cta]


# ---- generic library ---------------------------------------------------------------------------------
GENERIC: list[SceneTemplate] = [
    T("hook-kinetic-spotlight", "Cinematic opening", "hook", None, None, "kinetic-text", "pill", ("spotlight",), "push-in", "cinematic",
      "fade", None, (8, 12), None, {"pill": "first word", "kinetic-text": "the whole line, each word as spoken"}, (), (), _always,
      b_hook_kinetic, "Kinetic type lands word by word under a spotlight; a product eyebrow pill sets context."),
    T("turn-logo-sting", "Brand reveal", "turn", None, None, "logo-sting", "kinetic-text", ("glow",), "none", "cinematic", "mask-wipe",
      "brand", (7, 12), (3, 9), {"sting": ["Meet", "This", "<brand>"], "kinetic-text": "the positioning line, word by word"}, (), (),
      _always, b_logo_sting, "Animated logo reveal; the spoken positioning line lands word by word beneath it."),
    T("proof-feature-checklist", "Feature checklist", "proof", None, None, "checklist", "pill", ("deep", "glow"), "push-in", "standard",
      "fade", None, (10, 16), None, {"checklist": "one item per spoken feature"}, (), (), _always, b_feature_checklist,
      "The plan's verified features check in one by one as they are named."),
    T("price-plan-card", "Plan price card", "pricing", None, None, "plan-card", "pill", ("spotlight", "glow"), "push-in", "energetic",
      "slide-up", None, (11, 18), None, {"price": "the price digits", "features": "one per spoken feature", "highlight": ["renewal"]},
      ("price", "storage", "websites"), (), _always, b_plan_card,
      "One premium card for the brief's plan: verified price counts up on its spoken digits, features tick in."),
    T("price-compare-cycles", "Pricing table", "pricing", None, None, "price-compare", "pill", ("split",), "none", "standard", "mask-wipe",
      None, (11, 18), None, {"rows": "each row on its spoken price"}, ("price", "monthly", "semi", "annual"), (6,), _always,
      b_price_compare, "Billing cycles (when the plan has them) or a plan matrix: each row lands on the price that is spoken."),
    T("price-plans-lineup", "Plan lineup", "pricing", None, None, "plans", "pill", ("spotlight", "glow"), "push-in", "standard", "fade", None,
      (12, 18), None, {"plans": "the featured price", "cursor": "plan / the plan name"}, ("price",), (), _always, b_plans_lineup,
      "Three verified plans; the cursor picks the featured plan."),
    T("price-counter-flat", "The price that stays", "pricing", None, None, "counter", "flat-line", ("deep", "spotlight"), "push-in",
      "standard", "fade", None, (10, 16), None, {"counter": "the price digits", "flat-line": ["renews", "again"]},
      ("price", "annual", "monthly"), (), lambda pf: pf.allow.get("renewal", False), b_counter_flat,
      "Price counts up, then a flat line shows it renews at the same amount (only with the renewal fact)."),
    T("cta-outro", "Outro", "cta", None, None, "outro", "pill", ("glow",), "none", "cinematic", "fade", "brand", (8, 13), None,
      {"outro": "the CTA's first word", "url": "<domain>", "pill": "the trust statement"}, (), (7,), _always, b_outro,
      "Logo, tagline, CTA and URL button; a fact-bound trust pill."),
    T("cta-logo-lockup", "Logo lockup CTA", "cta", None, None, "cta", "logo", ("spotlight", "glow"), "none", "standard", "fade", "brand",
      (6, 11), None, {"logo": "first word", "cta": "the CTA's first word", "url": "<domain>"}, (), (), _always, b_logo_lockup,
      "Logo lockup with a CTA button that is clicked on the spoken URL."),
]


def library(pack) -> dict[str, SceneTemplate]:
    """Generic templates + the pack's industry templates (a pack may override a generic id)."""
    out = {t.id: t for t in GENERIC}
    out.update({t.id: t for t in pack.templates})
    return out
