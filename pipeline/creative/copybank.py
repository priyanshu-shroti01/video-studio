"""Copy bank machinery + the GENERIC copy layer. Industry copy lives in the industry pack
(pipeline/creative/industries/<pack>.py, BANK) and takes precedence; brand values (name, domain, CTA, tagline,
banned words) come from brands/<id>/brand.json and facts. The bank is the deterministic fallback for every
copy slot and the style reference the LLM copy assistant is shown.

House style: confident, concrete, second person; short sentences; name the real thing on screen (cPanel,
LiteSpeed, Imunify360) instead of adjectives; numbers only through placeholders bound to verified facts
({price}, {annual}, {storage}...); no clichés, no superlatives, no guarantees except the site's own 7-day
money-back guarantee. Every line contains the cue words its template animates on, so picture and voice stay
in sync. Length: the estimators use the measured local-voice rate (anchors.WPS = 2.33 words/s), so a 30–35 s
video has room for about 62–70 words; keep a tight variant for every template.

Entry: {"id", "narration", "headline"? (on-screen phrase, must be spoken verbatim), "emphasis"?, "needs"?
(product flags that must be true: renewal, typical_backups, money_back, lowest, plan2_popular, annual, semi,
free_domain), "tags"?}. Keys: template id -> family ("wordpress" | "shared" | "domains" | "*") -> variants."""
from __future__ import annotations

import re

from .product import ProductFacts

BANNED = [
    "tech skills", "technical skills", "no coding", "no code needed", "game-changer", "game changer", "seamless", "seamlessly",
    "revolutionary", "revolutionize", "unlock", "supercharge", "elevate", "next level", "next-level", "cutting-edge",
    "cutting edge", "world-class", "world class", "in today's", "look no further", "say goodbye", "hassle-free", "hassle free",
    "effortless", "effortlessly", "skyrocket", "empower", "unleash", "best-in-class", "one-stop", "dive in", "magic", "blazing",
    "lightning", "fastest", "cheapest", "best", "#1", "number one", "unbeatable", "guaranteed", "100%", "forever", "lifetime",
    "zero downtime", "never goes down", "limited time", "hurry", "act now", "unlimited", "secret", "hack", "insane", "amazing",
    "incredible", "awesome", "ultimate solution", "peace of mind", "worry-free", "robust", "leverage", "synergy", "beginner pain",
]

GENERIC_BANK: dict[str, dict[str, list[dict]]] = {
    # generic fallback copy for the generic templates; an industry pack's copy takes precedence
    "hook-kinetic-spotlight": {"*": [
        {"id": "properly", "narration": "You know what you need. Here is {product_label}, done properly.", "tags": ["promise"]},
        {"id": "choosing", "narration": "Choosing {product_label}? Start with what you actually get.", "tags": ["question"]},
    ]},
    "turn-logo-sting": {"*": [
        {"id": "meet", "narration": "Meet {brand}: {product_label}, made simple and clear.", "headline": "{product_label}, made simple and clear."},
    ]},
    "price-plan-card": {"*": [
        {"id": "plain", "narration": "{plan} is {price} {currency_word} {period_word}, with every feature on this card included."},
        {"id": "short", "narration": "{plan}: {price} {currency_word} {period_word}. Everything on this card is included."},
    ]},
    "price-plans-lineup": {"*": [
        {"id": "fits", "narration": "{plan} is {price} {currency_word} {period_word}. Pick the plan that fits you."},
    ]},
    "price-compare-cycles": {"*": [
        {"id": "matrix", "narration": "{plan} is {price} {currency_word} {period_word}. Bigger plans add more room as you grow."},
    ]},
    "price-counter-flat": {"*": [
        {"id": "renews", "narration": "{plan} is {price} {currency_word} {period_word}, and it renews at {price} again.", "needs": ["renewal"]},
    ]},
    "cta-outro": {"*": [
        {"id": "ready", "narration": "Ready when you are. {cta_spoken} at {domain}."},
    ]},
    "cta-logo-lockup": {"*": [
        {"id": "brand", "narration": "{brand}. {cta_spoken} today at {domain}."},
        {"id": "ready", "narration": "Ready when you are. {cta_spoken} at {domain}."},
    ]},
}


def flags(pf: ProductFacts) -> dict[str, bool]:
    p, s = pf.featured, pf.second
    if p is None:                              # unpriced product: only the fact-gated roles
        return {**pf.allow, "domains": False, "not_domains": True}
    return {**pf.allow, "lowest": bool(pf.plans) and pf.featured is pf.plans[0], "plan2_popular": bool(s and s.badge),
            "annual": bool(p.annual), "no_annual": not p.annual, "semi": bool(p.semi), "domains": pf.family == "domains",
            "not_domains": pf.family != "domains"}


def fill(text: str, values: dict) -> str:
    def rep(m):
        v = values.get(m.group(1))
        if v is None:
            raise KeyError(m.group(1))
        return str(v)
    return re.sub(r"\{(\w+)\}", rep, text)


def raw_variants(template_id: str, family: str, pack) -> list[dict]:
    for bank in (pack.bank, GENERIC_BANK):
        fams = bank.get(template_id, {})
        raw = fams.get(family) or fams.get("*")
        if raw:
            return raw
    return []


def variants(template_id: str, pf: ProductFacts, pack) -> list[dict]:
    """Copy variants usable for this product (pack copy first, then generic; needs satisfied, placeholders filled)."""
    fl, vals = flags(pf), pf.bound()
    out = []
    for v in raw_variants(template_id, pf.family, pack):
        if not all(fl.get(n, False) for n in v.get("needs", [])) or pack.unbacked_terms(v["narration"], pf.allow):
            continue
        try:
            d = {**v, "narration": fill(v["narration"], vals)}
            if v.get("headline"):
                d["headline"] = fill(v["headline"], vals)
        except KeyError:
            continue
        out.append(d)
    return out


def banned_hits(text: str, extra: list[str] | None = None) -> list[str]:
    low = text.lower()
    return [b for b in BANNED + list(extra or []) if re.search(rf"(?<![\w-]){re.escape(b.lower())}(?![\w-])", low)]


def word_count(text: str) -> int:
    return len([t for t in text.split() if re.search(r"\w", t)])
