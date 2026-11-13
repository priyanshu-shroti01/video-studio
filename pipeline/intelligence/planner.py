"""Deterministic template planner: the fallback when no model is available (or the model keeps failing),
and the default answer of the mock provider. Copy is assembled ONLY from brief values and verified facts;
every "@word:X" anchor is taken from the narration it builds, so the result always passes
validate_storyboard. Brief-supplied values that are not on the site are used as given and flagged by the
claim verifier (owner must confirm)."""
from __future__ import annotations

import re

from .claims import Verifier, VERIFIED
from .facts import FactBase
from .patterns import PATTERNS, coverage, rank_patterns, structure_for

# per-pattern creative defaults (so the three fallback concepts differ on every axis)
STYLE = {
    "hook-problem-solution-demo-cta": dict(name="Setup Without the Struggle", hook_style="question", animation="ui-walkthrough",
                                           music="technology", cta="url-click", wps=2.6),
    "myth-reality-explanation": dict(name="The Cheap-Hosting Myth", hook_style="myth", animation="stamp-and-strike",
                                     music="cinematic", cta="callback-question", wps=2.5),
    "before-after": dict(name="Before / After", hook_style="before-after", animation="minimal-reveal", music="corporate",
                         cta="logo-lockup", wps=2.5),
    "feature-benefit-proof": dict(name="One Click, Live", hook_style="bold-claim", animation="kinetic-type", music="energetic",
                                  cta="button-press", wps=2.8),
    "problem-discovery-transformation": dict(name="Stuck at Step One", hook_style="pain-point", animation="data-viz",
                                             music="calm", cta="logo-lockup", wps=2.5),
    "tutorial-demo-result": dict(name="Live in Three Steps", hook_style="promise", animation="ui-walkthrough",
                                 music="educational", cta="button-press", wps=2.7),
}


# ---------------------------------------------------------------------------------------------
class Copy:
    """Everything the templates may say, derived from the brief + verified facts."""

    def __init__(self, brief: dict, fb: FactBase):
        self.brief, self.fb = brief, fb
        self.brand = brief["brand"]
        self.product = brief["product"]
        self.is_wp = "wordpress" in self.product.lower()
        self.domain = fb.domain() or (brief.get("url") or "").replace("https://", "")
        self.cta = (brief.get("cta") or "Get started").strip().rstrip(".")
        self.renewal = bool(fb.by_id("policy.same_renewal"))
        self.typical_renewal = bool(fb.by_id("comparison.typical_renewal"))
        v = Verifier(fb, brief)
        bp = brief.get("price_parsed")
        self.price_from_brief = bp is not None
        if bp:
            self.amount, self.period = bp["amount"], bp.get("period", "month")
            c = v.verify_text(f"{self.product} {bp['text']}", "probe")
            self.price_verified = any(x.kind == "price" and x.status == VERIFIED for x in c)
        else:
            f = fb.by_id("wp.from_price" if self.is_wp else "shared.from_price") or (fb.prices() or [None])[0]
            self.amount, self.period = (f["value"]["amount"], "month") if f else (None, "month")
            self.price_verified = f is not None
        prod = "wordpress" if self.is_wp else "shared"
        self.plans = [f for f in fb.facts if f["category"] == "price" and f.get("product") == prod and f["id"].endswith(".price.monthly")]
        self.storage = {f["plan"]: f["value"]["storage_gb"] for f in fb.facts if f["category"] == "spec" and "storage_gb" in f["value"]}
        if self.is_wp:
            self.features = [("One-click WordPress install", "zap", "one-click"), ("LiteSpeed Cache", "server", "LiteSpeed"),
                             ("Free SSL", "lock", "SSL"), ("Daily backups", "cloud", "backups")]
        else:
            self.features = [("NVMe storage", "zap", "NVMe"), ("LiteSpeed servers", "server", "LiteSpeed"),
                             ("Free SSL", "lock", "SSL"), ("Daily backups", "cloud", "backups")]
        self.features = [f for f in self.features if v.verify_text(f[0], "probe") and
                         all(x.status == VERIFIED for x in v.verify_text(f[0], "probe"))] or self.features[:0]
        self.short_product = "WordPress hosting" if self.is_wp else "hosting"

    @property
    def amt(self) -> str:
        a = self.amount
        return str(int(a)) if a is not None and float(a).is_integer() else str(a)

    @property
    def per(self) -> str:
        return "/mo" if self.period == "month" else "/yr"

    @property
    def spoken_price(self) -> str:
        return f"{self.amt} rupees a {'month' if self.period == 'month' else 'year'}"

    def use_plans_block(self) -> bool:
        # showing the site's real plan prices next to an unverified brief price would contradict itself
        return bool(self.plans) and (self.price_verified or not self.price_from_brief)


def _w(narr: str, word: str, off: float = 0.0) -> str:
    """'@word:X' for a word that is (asserted) in the narration."""
    from ..storyboard import _word_in
    w = re.sub(r"[^\w']", "", word.split("-")[0].split(".")[0])
    if not w or not _word_in(narr, w):
        raise AssertionError(f"planner bug: {word!r} not in {narr!r}")
    return f"@word:{w}" + (f"+{off}" if off > 0 else f"{off}" if off < 0 else "")


def S(id, purpose, narration, blocks, extra: str | None = None, **kw) -> dict:
    """A scene. `extra` is an optional sentence appended only if the duration budget allows (never anchored)."""
    return {"id": id, "purpose": purpose, "narration": narration, "blocks": blocks, **({"_extra": extra} if extra else {}), **kw}


def _feature_checklist(c: Copy, narr: str, n: int = 3) -> dict:
    items = []
    for label, icon, spoken in c.features[:n]:
        anchor = spoken if re.search(rf"(?<![\w-]){re.escape(spoken)}(?![\w-])", narr, re.I) else None
        it = {"text": label, "icon": icon}
        it["at"] = _w(narr, anchor) if anchor else "@speech_end-0.2"
        items.append(it)
    return {"type": "checklist", "items": items}


def _feature_phrase(c: Copy, n: int = 2) -> str:
    sp = {"one-click": "one-click installs", "LiteSpeed": "LiteSpeed", "SSL": "free SSL", "backups": "daily backups",
          "NVMe": "NVMe storage"}
    words = [sp.get(f[2], f[2]) for f in c.features[1:1 + n]]
    return " and ".join(words) if words else "everything set up for you"


def _cta_scene(c: Copy, style: str, extra: str | None = None) -> dict:
    lead = {"url-click": f"{c.cta} today at {c.domain}.", "callback-question": f"Ready? {c.cta} at {c.domain}.",
            "logo-lockup": f"{c.brand}. {c.cta} at {c.domain}.", "button-press": f"{c.cta} now at {c.domain}.",
            "offer-stamp": f"{c.cta} today at {c.domain}."}[style]
    first = c.cta.split()[0]
    blocks = [{"type": "logo", "variant": "onDark", "width": 760},
              {"type": "cta", "text": c.cta, "url": c.domain, "at": _w(lead, first, -0.05), "urlAt": _w(lead, c.domain.split(".")[0]),
               "clickAt": _w(lead, c.domain.split(".")[0], 0.55),
               "sub": " · ".join(x for x in ["Same price on renewal" if c.renewal else "", *(f[0] for f in c.features[1:3])] if x)}]
    return S("cta", "cta", lead, blocks, mood="brand", extra=extra)


def _price_block(c: Copy, narr: str, start_word: str, label: str) -> dict:
    return {"type": "price", "currency": "₹", "amount": c.amount, "period": c.per, "label": label, "note": "excl. taxes",
            "at": _w(narr, start_word, -0.1), "countEnd": _w(narr, c.amt, 0.5)}


def _renewal_rows(c: Copy, narr: str, today_word: str, renew_word: str) -> dict:
    b = {"type": "compare-rows", "rows": [{"label": "Today", "value": f"₹{c.amt}{c.per}", "at": _w(narr, today_word)},
                                          {"label": "On renewal", "value": f"₹{c.amt}{c.per}", "at": _w(narr, renew_word)}]}
    if c.renewal:
        b["badge"] = {"text": "Same price", "tone": "success", "at": _w(narr, renew_word, 0.4)}
    return b


def _plans_block(c: Copy, narr: str, word: str) -> dict:
    plans = []
    for f in c.plans[:3]:
        p = {"name": f["plan"], "price": f"₹{f['value']['amount']}", "period": "/mo"}
        if f["plan"] in c.storage:
            p["detail"] = f"{c.storage[f['plan']]} GB NVMe"
        if c.fb.by_id(("wp." if c.is_wp else "shared.") + f["plan"].split()[-1].lower() + ".most_popular"):
            p["badge"] = "Most popular"
        plans.append(p)
    return {"type": "plans", "plans": plans, "emphasizeAt": _w(narr, word)}


# ---- scene templates per pattern -----------------------------------------------------------------------
def _p_hpsdc(c: Copy, st: dict) -> list[dict]:
    prod = "WordPress" if c.is_wp else "hosting"
    hook = f"New to {prod}? Your first website shouldn't feel this hard."
    prob = "Most hosts bury you in setup, and their renewal prices often go up." if c.typical_renewal else \
        "Most hosts bury you in setup screens and add-ons."
    turn = f"Meet {c.brand} {c.short_product}."
    demo = ("Type your domain, install WordPress in one click, and launch with LiteSpeed and free SSL." if c.is_wp else
            "Type your domain and launch on NVMe and LiteSpeed, with free SSL.")
    price = f"Plans start at {c.spoken_price}, and renew at the exact same price." if c.renewal else f"Plans start at {c.spoken_price}."
    scenes = [
        S("hook", "hook", hook, [{"type": "headline", "size": "xl", "words": f"New to {prod}?", "tones": {f"{prod}?": "brand"}},
                                 {"type": "text", "text": "Your first website shouldn't feel this hard", "size": "m", "tone": "muted",
                                  "at": _w(hook, "first", -0.1)}], transition="fade"),
        S("problem", "problem", prob, extra="You just wanted a website.", blocks=[{"type": "browser", "url": "your-website.in", "at": _w(prob, "bury", -0.1),
                                        "loadUntil": _w(prob, "setup", 0.8), "stallAt": _w(prob, "setup")},
                                       {"type": "compare-rows", "rows": [{"label": "Setup", "value": "Confusing", "at": _w(prob, "setup")}] +
                                        ([{"label": "Renewal", "value": "Often increases", "at": _w(prob, "renewal")}] if c.typical_renewal else [])}],
          mood="danger"),
        S("turn", "turn", turn, [{"type": "logo", "variant": "onDark", "width": 840, "at": _w(turn, "Meet")}], mood="brand",
          extra="WordPress, tuned to run fast." if c.is_wp else "Fast hosting, priced honestly."),
        S("demo", "journey", demo, [
            {"type": "domain-input", "title": "Find your domain", "domain": "yourbrand.in", "typeAt": _w(demo, "Type", 0.1),
             "availableText": "is available",
             "button": {"idle": "Install WordPress" if c.is_wp else "Launch site", "busy": "Installing…" if c.is_wp else "Launching…",
                        "done": "Your site is live", "clickAt": _w(demo, "install" if c.is_wp else "launch"),
                        "doneAt": _w(demo, "launch", 0.2)}},
            _feature_checklist(c, demo)], brandBar=True, layout="split", splitAt=1, extra="Daily backups run automatically."),
        S("pricing", "resolution", price, extra="No surprises later." if c.renewal else None, blocks= [_price_block(c, price, "start", f"{c.short_product.capitalize()} · starting at"),
                                           *([_renewal_rows(c, price, "start", "renew")] if c.renewal else [])], brandBar=True),
        _cta_scene(c, st["cta"], "Your first website starts here."),
    ]
    return scenes


def _p_myth(c: Copy, st: dict) -> list[dict]:
    hook = "Think cheap hosting stays cheap? That's the myth."
    real = "Reality: at typical hosts, renewal prices often increase." if c.typical_renewal else \
        "Reality: the intro price is rarely the price you keep."
    expl = f"{c.brand} plans renew at the listed price, with {_feature_phrase(c)} included."
    proof = (f"{c.short_product.capitalize()} from {c.spoken_price}, the same every time you renew." if c.renewal else
             f"{c.short_product.capitalize()} from {c.spoken_price}.")
    proof_blocks = [_price_block(c, proof, "from", c.product)]
    if c.use_plans_block():
        proof_blocks = [_plans_block(c, proof, c.amt)]
    if c.renewal:
        proof_blocks.append({"type": "flat-line", "title": f"Your {c.brand} bill", "at": _w(proof, "same", -0.1),
                             "drawEnd": _w(proof, "renew", 0.35),
                             "points": [{"label": f"Year {i}", "value": f"₹{c.amt}{c.per}"} for i in (1, 2, 3)]})
    return [
        S("myth", "hook", hook, [{"type": "hook-tag", "label": "MYTH", "text": "Cheap stays cheap", "sub": "…right?",
                                  "at": _w(hook, "cheap", -0.1)},
                                 {"type": "headline", "size": "l", "words": "That's the myth.", "tones": {"myth.": "danger"},
                                  "strike": {"word": 2, "at": _w(hook, "myth", 0.3), "tone": "danger"}}], transition="fade",
          extra="Here's what really happens."),
        S("reality", "problem", real, [{"type": "pill", "text": "REALITY", "tone": "danger", "stamp": True, "at": _w(real, "Reality")},
                                       {"type": "compare-rows", "rows": [{"label": "Intro price", "value": "Low", "at": _w(real, "typical")},
                                                                         {"label": "Renewal", "value": "Often increases" if c.typical_renewal else "Higher",
                                                                          "at": _w(real, "renewal" if c.typical_renewal else "price")}],
                                        "badge": {"text": "Typical hosts", "tone": "danger", "at": _w(real, "often" if c.typical_renewal else "keep")}}],
          mood="danger", extra="The intro price is just the start."),
        S("explain", "point", expl, [{"type": "logo", "variant": "onDark", "width": 640, "at": _w(expl, c.brand.split()[0])},
                                     _feature_checklist(c, expl, 3)], brandBar=False, mood="brand",
          extra="Plus free migration, handled for you."),
        S("proof", "resolution", proof, proof_blocks[:3], brandBar=True, extra="Year one, year two, year three." if c.renewal else None),
        _cta_scene(c, st["cta"], "Your site, priced honestly."),
    ]


def _p_before_after(c: Copy, st: dict) -> list[dict]:
    before = "Before: a blank screen and a setup you don't understand."
    cost = "Plus a renewal bill that often goes up." if c.typical_renewal else "Plus add-ons you never asked for."
    switch = f"After: {c.brand}."
    after = ("Your domain, WordPress installed in one click, LiteSpeed Cache switched on." if c.is_wp else
             "Your domain, live on NVMe and LiteSpeed, free SSL switched on.")
    price = (f"Just {c.spoken_price}, and the same price when you renew." if c.renewal else f"Just {c.spoken_price}.")
    rows = {"type": "compare-rows", "rows": [{"label": "Before · renewal", "value": "Often increases" if c.typical_renewal else "Add-ons",
                                              "at": _w(price, "Just")},
                                             {"label": "After · renewal", "value": f"₹{c.amt}{c.per}", "at": _w(price, "same" if c.renewal else c.amt)}]}
    if c.renewal:
        rows["badge"] = {"text": "Same price", "tone": "success", "at": _w(price, "renew", 0.3)}
    return [
        S("before", "hook", before, [{"type": "headline", "size": "xl", "words": "Before:", "tones": {"Before:": "danger"}},
                                     {"type": "browser", "url": "your-website.in", "at": _w(before, "blank", -0.1),
                                      "loadUntil": _w(before, "understand"), "stallAt": _w(before, "setup")}], mood="danger", transition="fade",
          extra="Hours of tutorials, and still nothing live."),
        S("cost", "problem", cost, [{"type": "hook-tag", "label": "RENEWAL", "text": "Often increases" if c.typical_renewal else "Add-ons",
                                     "sub": "at typical hosts", "at": _w(cost, "renewal" if c.typical_renewal else "add-ons", -0.1)}], mood="danger"),
        S("switch", "turn", switch, [{"type": "pill", "text": "AFTER", "tone": "success", "stamp": True, "at": _w(switch, "After")},
                                     {"type": "logo", "variant": "onDark", "width": 800, "at": _w(switch, c.brand.split()[0])}], mood="brand",
          extra="WordPress hosting, tuned to run fast." if c.is_wp else "Fast hosting, priced honestly."),
        S("after", "journey", after, [
            {"type": "domain-input", "title": "Your domain", "domain": "yourbrand.in", "typeAt": _w(after, "domain", 0.05),
             "availableText": "is available",
             "button": {"idle": "Install", "busy": "Installing…", "done": "Live", "clickAt": _w(after, "installed" if c.is_wp else "live"),
                        "doneAt": _w(after, "switched", 0.2)}},
            _feature_checklist(c, after, 3)], brandBar=True, layout="split", splitAt=1, extra="Free SSL and daily backups, included."),
        S("after-price", "resolution", price, [rows], brandBar=True, extra="No surprises." if c.renewal else None),
        _cta_scene(c, st["cta"], "Your first website starts here."),
    ]


def _p_fbp(c: Copy, st: dict) -> list[dict]:
    hook = "One click. WordPress, installed." if c.is_wp else "NVMe. LiteSpeed. Ready."
    feat = (f"{c.brand} installs WordPress in one click, with LiteSpeed Cache and AccelerateWP." if c.is_wp else
            f"{c.brand} runs your site on NVMe storage and LiteSpeed servers.")
    ben = "So your first site goes live in minutes, with free SSL and daily backups."
    proof = (f"From {c.spoken_price}, same price on renewal." if c.renewal else f"From {c.spoken_price}.")
    feat_items = [{"text": "One-click install" if c.is_wp else "NVMe storage", "icon": "zap", "at": _w(feat, "one" if c.is_wp else "NVMe")},
                  {"text": "LiteSpeed Cache" if c.is_wp else "LiteSpeed servers", "icon": "server", "at": _w(feat, "LiteSpeed")}]
    if c.is_wp:
        feat_items.append({"text": "AccelerateWP", "icon": "arrowUp", "at": _w(feat, "AccelerateWP")})
    proof_blocks = [_price_block(c, proof, "From", f"{c.short_product.capitalize()} · from")]
    if c.renewal:
        proof_blocks.append(_renewal_rows(c, proof, "From", "renewal"))
    return [
        S("hook", "hook", hook, [{"type": "headline", "size": "xl", "words": hook.split(".")[0] + ".",
                                  "tones": {hook.split(".")[0].split()[-1] + ".": "brand"}},
                                 {"type": "pill", "text": "WordPress, installed" if c.is_wp else "Ready to launch", "tone": "brand",
                                  "icon": "zap", "at": _w(hook, hook.split()[-1].strip("."), -0.1)}], transition="fade",
          extra="That's how your first website should start."),
        S("feature", "point", feat, [{"type": "checklist", "items": feat_items}], brandBar=True,
          extra="Built specifically for WordPress, not bolted on." if c.is_wp else None),
        S("benefit", "example", ben, [{"type": "browser", "url": "your-website.in", "at": _w(ben, "first", -0.1),
                                       "loadUntil": _w(ben, "minutes"), "tag": {"text": "Live", "at": _w(ben, "live")}},
                                      {"type": "checklist", "items": [{"text": "Free SSL", "icon": "lock", "at": _w(ben, "SSL")},
                                                                      {"text": "Daily backups", "icon": "cloud", "at": _w(ben, "backups")}]}],
          brandBar=True, layout="split", splitAt=1, extra="And free migration, handled for you."),
        S("proof", "resolution", proof, proof_blocks, brandBar=True, extra="Every billing cycle, no increase later." if c.renewal else None),
        _cta_scene(c, st["cta"], "Your first website starts here."),
    ]


def _p_pdt(c: Copy, st: dict) -> list[dict]:
    prob = "Your website idea is stuck at step one."
    strug = ("Hosting panels assume you're an expert, and renewal prices often go up." if c.typical_renewal else
             "Hosting panels assume you're an expert.")
    disc = f"Then you find {c.brand} {c.short_product}."
    trans = ("Type your domain, install WordPress in one click, and you're live in minutes." if c.is_wp else
             "Type your domain, and you're live in minutes on NVMe and LiteSpeed.")
    res = (f"{c.spoken_price.capitalize()}, and it stays that way when you renew." if c.renewal else f"From {c.spoken_price}.")
    res_blocks = [_price_block(c, res, c.amt, c.product)]
    if c.renewal:
        res_blocks.insert(0, {"type": "flat-line", "title": f"Your {c.brand} bill", "at": _w(res, "stays", -0.1),
                              "drawEnd": _w(res, "renew", 0.35),
                              "points": [{"label": f"Year {i}", "value": f"₹{c.amt}{c.per}"} for i in (1, 2, 3)]})
        res_blocks[1]["at"] = "@start+0.1"
    return [
        S("stuck", "hook", prob, [{"type": "headline", "size": "l", "words": "Stuck at step one?", "tones": {"one?": "danger"}},
                                  {"type": "browser", "url": "your-website.in", "at": _w(prob, "stuck", -0.1),
                                   "loadUntil": _w(prob, "one", 0.6), "stallAt": _w(prob, "step")}], mood="danger", transition="fade",
          extra="Every tutorial assumes you already know hosting."),
        S("struggle", "problem", strug, [{"type": "compare-rows", "rows": [{"label": "Panels", "value": "Expert-only", "at": _w(strug, "expert")}] +
                                          ([{"label": "Renewal", "value": "Often increases", "at": _w(strug, "renewal")}] if c.typical_renewal else [])}],
          mood="danger", extra="So the idea waits."),
        S("discovery", "turn", disc, [{"type": "logo", "variant": "onDark", "width": 820, "at": _w(disc, c.brand.split()[0])},
                                      {"type": "pill", "text": c.product, "tone": "brand", "icon": "server",
                                       "at": _w(disc, c.short_product.split()[0], -0.05)}], mood="brand",
          extra="WordPress, tuned to run fast." if c.is_wp else "Fast hosting, priced honestly."),
        S("transform", "journey", trans, [
            {"type": "domain-input", "title": "Find your domain", "domain": "yourbrand.in", "typeAt": _w(trans, "Type", 0.1),
             "availableText": "is available",
             "button": {"idle": "Install" if c.is_wp else "Launch", "busy": "Installing…" if c.is_wp else "Launching…",
                        "done": "You're live", "clickAt": _w(trans, "install" if c.is_wp else "live"), "doneAt": _w(trans, "minutes", 0.2)}},
            _feature_checklist(c, trans, 2)], brandBar=True, layout="split", splitAt=1, extra="Free SSL and daily backups come included."),
        S("result", "resolution", res, res_blocks, brandBar=True, extra="No surprises later." if c.renewal else None),
        _cta_scene(c, st["cta"], "Your website starts here."),
    ]


def _p_tutorial(c: Copy, st: dict) -> list[dict]:
    hook = f"Launch a {'WordPress ' if c.is_wp else ''}site in three steps."
    s1 = "Step one: pick a plan."
    s2 = "Step two: type your domain."
    s3 = ("Step three: install WordPress in one click, with free SSL and daily backups." if c.is_wp else
          "Step three: go live, with free SSL and daily backups.")
    res = (f"Live, from {c.spoken_price}, same price on renewal." if c.renewal else f"Live, from {c.spoken_price}.")
    s1_blocks = [_plans_block(c, s1, "plan")] if c.use_plans_block() else \
        [{"type": "text", "text": "Pick your plan", "size": "l"}, {"type": "pill", "text": c.product, "tone": "brand", "icon": "server",
                                                                   "at": _w(s1, "plan")}]
    res_blocks = [_price_block(c, res, "from", f"{c.short_product.capitalize()} · from")]
    if c.renewal:
        res_blocks.append(_renewal_rows(c, res, "from", "renewal"))
    return [
        S("promise", "hook", hook, [{"type": "headline", "size": "xl", "words": "Three steps.", "tones": {"steps.": "brand"}},
                                    {"type": "text", "text": hook.rstrip("."), "size": "m", "tone": "muted", "at": _w(hook, "Launch")}],
          transition="fade", extra="No experience needed."),
        S("step-1", "journey", s1, s1_blocks, brandBar=True, extra=f"{c.product}, built for {'WordPress' if c.is_wp else 'your site'}."),
        S("step-2", "journey", s2, [{"type": "domain-input", "title": "Step 2 · your domain", "domain": "yourbrand.in",
                                     "typeAt": _w(s2, "type", 0.1), "availableText": "is available",
                                     "button": {"idle": "Continue", "busy": "Checking…", "done": "Yours", "clickAt": "@speech_end-0.1",
                                                "doneAt": "@speech_end+0.3"}}], brandBar=True, extra="Pick a name that fits your idea."),
        S("step-3", "example", s3, [_feature_checklist(c, s3, 3)], brandBar=True, extra="LiteSpeed Cache is already on." if c.is_wp else None),
        S("result", "resolution", res, res_blocks, brandBar=True, extra="Every billing cycle." if c.renewal else None),
        _cta_scene(c, st["cta"], "Your first website starts here."),
    ]


TEMPLATES = {"hook-problem-solution-demo-cta": _p_hpsdc, "myth-reality-explanation": _p_myth, "before-after": _p_before_after,
             "feature-benefit-proof": _p_fbp, "problem-discovery-transformation": _p_pdt, "tutorial-demo-result": _p_tutorial}


# ---------------------------------------------------------------------------------------------
EXTRA_DROP_ORDER = ["cta", "hook", "myth", "promise", "before", "stuck", "turn", "switch", "discovery", "step-2", "step-1"]


def fit_duration(scenes: list[dict], target_s: float, wps: float = 2.6, gap: float = 0.2, pad: float = 0.5) -> list[dict]:
    """Append optional sentences, then drop them (least important first) until the estimate is <= target."""
    est = lambda ss: sum(word_count(s["narration"] + " " + s.get("_extra", "")) for s in ss) / wps + gap * len(ss) + pad
    order = sorted([s for s in scenes if s.get("_extra")],
                   key=lambda s: EXTRA_DROP_ORDER.index(s["id"]) if s["id"] in EXTRA_DROP_ORDER else 99)
    while order and est(scenes) > target_s * 1.03:
        order.pop(0).pop("_extra")
    for s in scenes:
        if s.get("_extra"):
            s["narration"] = f"{s['narration']} {s.pop('_extra')}"
    return scenes


def template_scenes(brief: dict, fb: FactBase, pattern_id: str, cta_style: str | None = None) -> list[dict]:
    st = dict(STYLE[pattern_id])
    if cta_style:
        st["cta"] = cta_style
    return fit_duration(TEMPLATES[pattern_id](Copy(brief, fb), st), brief.get("duration_seconds", 35))


def word_count(text: str) -> int:
    return len([t for t in text.split() if re.search(r"\w", t)])


def template_concept(brief: dict, fb: FactBase, pattern_id: str, idx: int = 1) -> dict:
    st = STYLE[pattern_id]
    scenes = template_scenes(brief, fb, pattern_id)
    words = sum(word_count(s["narration"]) for s in scenes)
    blocks = []
    for s in scenes:
        for b in s["blocks"]:
            if b["type"] not in blocks:
                blocks.append(b["type"])
    have, missing = coverage(pattern_id, brief.get("requirements", []))
    c = Copy(brief, fb)
    return {
        "id": f"concept-{idx}", "name": st["name"], "pattern": pattern_id, "pattern_name": PATTERNS[pattern_id]["name"],
        "hook": scenes[0]["narration"], "hook_style": st["hook_style"],
        "logline": f"{PATTERNS[pattern_id]['name']} for {brief.get('audience') or 'the audience'}: "
                   f"{' → '.join(b['beat'] for b in PATTERNS[pattern_id]['beats'])}.",
        "beats": [{"purpose": s["purpose"], "idea": s["narration"]} for s in scenes],
        "visual_approach": {"hero_blocks": blocks, "description": f"{st['animation']} built from {', '.join(blocks[:5])}"},
        "pacing": {"words_per_second": st["wps"], "scene_count": len(scenes), "target_words": words},
        "animation_style": st["animation"], "music_mood": st["music"],
        "cta_treatment": {"style": st["cta"], "text": f"{c.cta} at {c.domain}"},
        "requirements_covered": have, "requirements_missing": missing, "source": "template",
    }


def choose_patterns(brief: dict, n: int = 3) -> list[str]:
    """Top-ranked patterns, skipping ones whose hero blocks would nearly duplicate an earlier pick."""
    return rank_patterns(brief)[:n] if n <= 3 else rank_patterns(brief)[:n]


def template_draft(brief: dict, fb: FactBase, concept: dict) -> dict:
    pid = concept["pattern"]
    cta = (concept.get("cta_treatment") or {}).get("style")
    scenes = template_scenes(brief, fb, pid, cta if cta in ("url-click", "callback-question", "logo-lockup", "button-press", "offer-stamp") else None)
    c = Copy(brief, fb)
    return {"title": f"{brief['brand']} — {concept.get('name', PATTERNS[pid]['name'])}", "structure": structure_for(pid),
            "scenes": scenes, "publishing": template_publishing(brief, fb, c)}


def template_publishing(brief: dict, fb: FactBase, c: Copy | None = None) -> dict:
    c = c or Copy(brief, fb)
    price = f" from ₹{c.amt}{c.per}" if c.amount is not None else ""
    title = f"{c.product}{price}" + (" — same price on renewal" if c.renewal else "") + f" | {c.brand}"
    feats = ", ".join(f[0] for f in c.features[:4])
    desc = (f"{c.product} by {c.brand}: {feats}." + (" Every plan renews at the price you signed up for." if c.renewal else "") +
            f"\nhttps://{c.domain}")
    tags = ["#webhosting", "#WordPress" if c.is_wp else "#hosting", "#India", "#" + re.sub(r"\W", "", c.brand)]
    if c.is_wp:
        tags.insert(2, "#WordPressHosting")
    return {"title": title[:100], "description": desc, "hashtags": tags}
