"""Product resolution and price discipline (generic; the industry pack says which product families exist and
which fact ids carry the gated statements).

The brief's price is NOT trusted. The product family comes from the brief's product name (pack rules), its
plans are read from the verified fact base, and the plan the video features is the plan whose verified price
matches the brief. When the brief's price matches no verified plan, the family's verified starting plan is used
instead and the mismatch is reported (the brief price is never rendered). Renewal / money-back / comparison
statements are only unlocked by an explicit fact that applies to the product."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..intelligence.facts import FactBase

CURRENCIES = {"INR": ("₹", "rupees"), "USD": ("$", "dollars"), "EUR": ("€", "euros"), "GBP": ("£", "pounds")}


def money(n, symbol: str) -> str:
    n = int(n) if float(n).is_integer() else n
    return f"{symbol}{n:,}"


@dataclass
class Plan:
    name: str
    product: str
    monthly: int | None = None
    semi: int | None = None
    annual: int | None = None
    storage_gb: int | None = None
    websites: int | None = None
    cpu: str | None = None
    ram: str | None = None
    badge: str | None = None
    currency: str = "INR"
    facts: dict[str, str] = field(default_factory=dict)   # field -> fact id

    def price(self, period: str) -> int | None:
        return {"month": self.monthly, "6months": self.semi, "year": self.annual}.get(period)


def plans_for(fb: FactBase, product: str) -> list[Plan]:
    """Plans of a fact-base product, from the fact schema (price / cycles / spec values)."""
    by: dict[str, Plan] = {}
    for f in fb.facts:
        if f.get("product") != product or not f.get("plan"):
            continue
        p = by.setdefault(f["plan"], Plan(f["plan"], product))
        v, fid = f["value"], f["id"]
        if f["category"] == "price":
            p.currency = v.get("currency", p.currency)
            if v.get("cycles"):
                cyc = v["cycles"]
                if cyc.get("semiAnnual"):
                    p.semi, p.facts["semi"] = cyc["semiAnnual"], fid
                if cyc.get("annual"):
                    p.annual, p.facts["annual"] = cyc["annual"], fid
            elif v.get("period") == "month" and not fid.endswith("from_price"):
                p.monthly, p.facts["monthly"] = v["amount"], fid
            elif v.get("period") == "year":
                p.annual, p.facts["annual"] = v["amount"], fid
        elif "storage_gb" in v:
            p.storage_gb, p.facts["storage"] = v["storage_gb"], fid
        elif "websites" in v:
            p.websites, p.facts["websites"] = v["websites"], fid
        elif "cpu" in v:
            p.cpu, p.ram, p.facts["cpu_ram"] = v.get("cpu"), v.get("ram"), fid
        elif v.get("badge"):
            p.badge, p.facts["badge"] = v["badge"], fid
    return sorted((p for p in by.values() if p.monthly is not None), key=lambda p: p.monthly)


@dataclass
class ProductFacts:
    family: str
    family_label: str
    family_icon: str
    brand: str
    domain: str
    plans: list[Plan]
    featured: Plan
    period: str                 # "month" | "year"
    price: int
    price_fact: str
    brief_price: dict | None
    mismatch: dict | None
    allow: dict[str, bool]      # fact-gated statements (roles from the pack)
    tagline: str
    tagline_fact: str | None
    cta: str
    currency_symbol: str
    currency_word: str
    placeholder_domain: str
    fact_ids: dict[str, str]    # role -> fact id (pack)
    url_cue: str
    name_cue: str
    display_url: str = ""       # what CTA buttons show (e.g. a repository path); defaults to the domain
    media: dict = None          # brand media clips (brand.json creative.footage): {clip id: {asset, title, frame, beats...}}
    spoken: dict = None         # unpriced packs: {"<role>_spoken": text} from a fact's value.spoken (e.g. a count, as said)

    @property
    def per_short(self) -> str:
        return "/mo" if self.period == "month" else "/yr"

    @property
    def second(self) -> Plan | None:
        """The next plan up (shown next to the featured plan in comparisons)."""
        i = self.plans.index(self.featured) if self.featured in self.plans else -1
        return self.plans[i + 1] if 0 <= i < len(self.plans) - 1 else (self.plans[i - 1] if i > 0 else None)

    def money(self, n) -> str:
        return money(n, self.currency_symbol)

    def bound(self) -> dict:
        """Placeholder values for copy (the ONLY numbers copy may contain)."""
        if self.featured is None:              # unpriced product: no plan or price placeholders
            cta = self.cta.strip().rstrip(".!")
            return {"brand": self.brand, "domain": self.domain, "cta": cta, "cta_spoken": cta[:1].upper() + cta[1:].lower(),
                    "product_label": self.family_label, **(self.spoken or {})}
        p, s = self.featured, self.second
        cta = self.cta.strip().rstrip(".!")
        return {
            "brand": self.brand, "domain": self.domain, "cta": cta, "cta_spoken": cta[:1].upper() + cta[1:].lower(),
            "plan": p.name, "price": self.price, "monthly": p.monthly, "semi": p.semi, "annual": p.annual,
            "storage": p.storage_gb, "websites": p.websites,
            "plan2": s.name if s else p.name, "price2": (s.monthly if self.period == "month" else s.annual) if s else self.price,
            "storage2": s.storage_gb if s else p.storage_gb, "websites2": s.websites if s else p.websites,
            "period_word": "a month" if self.period == "month" else "a year", "currency_word": self.currency_word,
            "product_label": self.family_label,
        }

    def report(self) -> dict:
        if self.featured is None:
            return {"family": self.family, "priced": False, "allow": self.allow}
        return {"family": self.family, "plan": self.featured.name, "price": self.price, "period": self.period,
                "display": f"{self.money(self.price)}{self.per_short}", "fact_id": self.price_fact,
                "brief_price": (self.brief_price or {}).get("text"), "mismatch": self.mismatch,
                "plans": [{"name": p.name, "monthly": p.monthly, "semi": p.semi, "annual": p.annual,
                           "storage_gb": p.storage_gb, "badge": p.badge} for p in self.plans],
                "allow": self.allow}


def resolve_product(brief: dict, fb: FactBase, brand, pack) -> ProductFacts:
    fam = pack.family_of(brief.get("product", ""))
    if not getattr(pack, "priced", True):
        applies0 = {fam.get("product"), "all", "company"}

        def ok0(role: str) -> bool:
            f = fb.by_id(pack.fact_ids[role]) if pack.fact_ids.get(role) else None
            return bool(f) and f.get("product") in applies0
        tag, tag_fact = brand.tagline(fam["id"], fb)
        spoken = {}
        for role, fid in pack.fact_ids.items():          # numbers copy may SAY come from the fact, never from the bank
            v = (fb.by_id(fid) or {}).get("value")
            if ok0(role) and isinstance(v, dict) and isinstance(v.get("spoken"), str):
                spoken[f"{role}_spoken"] = v["spoken"]
        return ProductFacts(family=fam["id"], family_label=fam["label"], family_icon=fam.get("icon", "star"), brand=brand.name,
                            domain=brand.domain, plans=[], featured=None, period="month", price=None, price_fact=None,
                            brief_price=None, mismatch=None, allow={r: ok0(r) for r in pack.gated_roles}, tagline=tag,
                            tagline_fact=tag_fact, cta=brief.get("cta") or brand.cta, currency_symbol="", currency_word="",
                            placeholder_domain=brand.placeholder_domain, fact_ids=dict(pack.fact_ids), url_cue=brand.url_cue,
                            name_cue=brand.name_cue, display_url=brand.extra.get("displayUrl") or brand.domain,
                            media=dict(brand.extra.get("footage") or {}), spoken=spoken)
    plans = fam["plans"](fb) if callable(fam.get("plans")) else plans_for(fb, fam["product"])
    if not plans:
        raise ValueError(f"no verified plans for {fam['id']!r} in {fb.path}: cannot build a priced video")
    bp = brief.get("price_parsed")
    featured, period, mismatch = None, None, None
    if bp:
        per = bp.get("period", "month")
        for p in plans:
            if p.price(per) is not None and float(p.price(per)) == float(bp["amount"]):
                featured, period = p, per
                break
    cur = CURRENCIES.get(plans[0].currency, ("", plans[0].currency))
    if featured is None:
        featured = plans[0]
        period = fam.get("period", "month")
        if bp:
            price = featured.price(period)
            known = [m for m in fb.not_found if str(bp["amount"]) in m.get("claim", "")]
            mismatch = {"brief_price": bp.get("text") or f"{bp['amount']}/{bp.get('period', 'month')}",
                        "brief_amount": bp["amount"], "used_price": f"{money(price, cur[0])}{'/mo' if period == 'month' else '/yr'}",
                        "used_amount": price, "plan": featured.name,
                        "fact_id": featured.facts["monthly" if period == "month" else "annual"],
                        "reason": f"no verified {fam['id']} plan costs {bp.get('text') or bp['amount']}; the video shows the "
                                  f"verified {featured.name} price instead and never renders the brief price",
                        "known_finding": known[0]["finding"] if known else None}
    price = featured.price(period)
    price_fact = featured.facts["monthly" if period == "month" else "annual"]
    applies = {fam["product"], "all", "company"} if fam.get("product") else {"all", "company"}

    def ok(role: str) -> bool:
        f = fb.by_id(pack.fact_ids[role]) if pack.fact_ids.get(role) else None
        return bool(f) and f.get("product") in applies

    allow = {r: ok(r) for r in pack.gated_roles}
    offer = fb.by_id(pack.fact_ids.get("free_domain", "")) if pack.fact_ids.get("free_domain") else None
    allow["free_domain"] = bool(offer) and featured.name in offer.get("value", {}).get("plans", [])
    tag, tag_fact = brand.tagline(fam["id"], fb)
    return ProductFacts(family=fam["id"], family_label=fam["label"], family_icon=fam.get("icon", "star"), brand=brand.name,
                        domain=brand.domain, plans=plans, featured=featured, period=period, price=price, price_fact=price_fact,
                        brief_price=bp, mismatch=mismatch, allow=allow, tagline=tag, tagline_fact=tag_fact,
                        cta=brief.get("cta") or brand.cta, currency_symbol=cur[0], currency_word=cur[1],
                        placeholder_domain=brand.placeholder_domain, fact_ids=dict(pack.fact_ids), url_cue=brand.url_cue,
                        name_cue=brand.name_cue, display_url=brand.extra.get("displayUrl") or brand.domain,
                        media=dict(brand.extra.get("footage") or {}))


def trusted_brief(brief: dict, pf: ProductFacts) -> dict:
    """The brief as the claim verifier should see it: the untrusted brief price replaced by the verified one
    (otherwise every real price would be flagged as 'contradicting the brief')."""
    b = dict(brief)
    if pf.featured is None:                    # unpriced: nothing to substitute
        return b
    b["price"] = f"{pf.currency_symbol}{pf.price}/{pf.period}"
    b["price_parsed"] = {"amount": pf.price, "currency": pf.featured.currency, "period": pf.period, "text": b["price"]}
    if pf.mismatch and b.get("request"):
        b["request"] = b["request"].replace(str(pf.mismatch["brief_price"]), b["price"])
    return b
