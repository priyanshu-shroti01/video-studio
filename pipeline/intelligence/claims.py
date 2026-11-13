"""Claim extraction + verification over narration, every block field, concept text and publishing metadata.

Every factual-looking span becomes a claim and is matched against the verified fact base:

  price        "₹49/mo", "49 rupees a month", plans/price blocks   -> amount + period + product + plan must match
  percent      "40%", "99.9 percent"                               -> must appear in a fact (context-checked)
  quantity     "50 GB", "5 websites", "7-day"                       -> (number, unit) must appear in a fact
  multiplier   "3×", "triple", "10x faster"                         -> must appear in a fact (almost never)
  number       any other number                                    -> must appear in a fact
  plan         "Grow plan", plans-block names                       -> plan must exist
  domain/email "shrotihost.in"                                      -> brand domain; placeholders are ILLUSTRATIVE
  risky        fastest/best/#1/guaranteed/unlimited/customers/award/discount/...  -> must be covered by a fact keyword
  feature      phrases that match a fact keyword                    -> VERIFIED with that fact id (annotation)

Status: VERIFIED (fact ids) | NEEDS_REVIEW (blocking; reason, origin brief|generated) | ILLUSTRATIVE (placeholder UI text)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .facts import FactBase

VERIFIED, NEEDS_REVIEW, ILLUSTRATIVE = "VERIFIED", "NEEDS_REVIEW", "ILLUSTRATIVE"

# ---- spelled numbers -> digits (n >= 2 so "one-click" / "one site" stay words) ------------------------
_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _spell(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        t, o = divmod(n, 10)
        return [_TENS[t]] if o == 0 else [f"{_TENS[t]}-{_ONES[o]}", f"{_TENS[t]} {_ONES[o]}"]
    h, r = divmod(n, 100)
    if r == 0:
        return [f"{_ONES[h]} hundred"]
    return [f"{_ONES[h]} hundred {x}" for x in _spell(r)] + [f"{_ONES[h]} hundred and {x}" for x in _spell(r)]


_NUMWORDS = {w: n for n in range(2, 1000) for w in _spell(n)}
_NUMWORD_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _NUMWORDS), key=len, reverse=True)) + r")\b", re.I)


def normalize_numbers(text: str) -> str:
    return _NUMWORD_RE.sub(lambda m: str(_NUMWORDS[m.group(1).lower()]), text)


# ---- patterns -------------------------------------------------------------------------------------------
NUM = r"\d[\d,]*(?:\.\d+)?"
PERIOD = r"(?:\s*(?:/|per|a|an|every)\s*(mo|month|yr|year|annum)\b|\s*(monthly|yearly|annually))?"
RE_PRICE = [
    re.compile(rf"(?:₹|rs\.?\s?|inr\s?)\s*({NUM})(?:\s*(?:rupees|/-))?{PERIOD}", re.I),
    re.compile(rf"\b({NUM})\s*(?:rupees|rs\b\.?|inr\b){PERIOD}", re.I),
    re.compile(rf"(?:\$|usd\s?|€|eur\s?)\s*({NUM}){PERIOD}", re.I),
]
RE_PERCENT = re.compile(rf"({NUM})\s*(%|percent\b|per cent\b)", re.I)
UNITS = {
    "gb": "gb", "gigabytes": "gb", "gigabyte": "gb", "tb": "tb", "mb/s": "mb/s", "core": "core", "cores": "core",
    "website": "website", "websites": "website", "site": "website", "sites": "website", "mailbox": "mailbox",
    "mailboxes": "mailbox", "accounts": "mailbox", "day": "day", "days": "day", "hour": "hour", "hours": "hour",
    "minute": "minute", "minutes": "minute", "second": "second", "seconds": "second", "year": "year", "years": "year",
    "month": "month", "months": "month", "customer": "customer", "customers": "customer", "client": "customer",
    "clients": "customer", "user": "customer", "users": "customer", "review": "review", "reviews": "review",
    "star": "star", "stars": "star", "plan": "plan", "plans": "plan", "step": "step", "steps": "step", "click": "click",
    "clicks": "click", "domains": "domain", "domain": "domain", "servers": "server", "countries": "country",
}
RE_QTY = re.compile(rf"({NUM})\s*(?:-\s*)?(" + "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True)) + r")\b", re.I)
RE_MULT = re.compile(rf"({NUM})\s*[x×](?![\w])|\b(double|triple|twice|thrice|quadruple|tenfold)\b", re.I)
RE_NUMBER = re.compile(rf"(?<![\w/]){NUM}(?![\w/])")
RE_DOMAIN = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+(?:in|com|org|net|co|io|xyz|online|shop|dev|app|ai))(?:/[\w/.-]*)?\b", re.I)
RE_LABEL_NUM = re.compile(r"\b(?:year|step|day|week|month|scene|part|tip)\s+\d{1,2}\b", re.I)
RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
RE_PLAN_MENTION = re.compile(r"\b((?:[A-Z][\w+-]*\s){0,2}[A-Z][\w+-]*)\s+(?:plan|tier)\b")
RE_FROM = re.compile(r"(from|starting at|starts at|start at|as low as|only|just)\s*(?:just\s*)?$", re.I)
PLACEHOLDER = re.compile(r"your|example|mysite|yoursite|brand\.|domain\.|demo|acme|sample", re.I)

RISKY = [
    r"fastest", r"quickest", r"best", r"#\s?1\b", r"number one", r"no\.\s?1", r"cheapest", r"lowest", r"most affordable",
    r"top[- ]rated", r"leading", r"world[- ]class", r"unbeatable", r"guarantee[ds]?", r"100\s?%", r"zero downtime",
    r"no downtime", r"never (?:goes )?down", r"always online", r"forever", r"lifetime", r"customers", r"clients",
    r"trusted by", r"happy", r"rated", r"stars?", r"reviews?", r"awards?", r"award-winning", r"certified", r"certification",
    r"\biso\b", r"gdpr", r"pci", r"compliant", r"faster", r"fast", r"speed", r"blazing", r"lightning", r"instant(?:ly)?",
    r"in seconds", r"load time", r"discount", r"% off", r"\boff\b", r"\bsale\b", r"\bdeal\b", r"coupon", r"promo",
    r"limited[- ]time", r"today only", r"hurry", r"unlimited", r"free\b", r"uptime", r"secure", r"security",
    r"protected", r"backups?", r"migration", r"support", r"renewal", r"renews?", r"hidden", r"hikes?",
    r"built for", r"designed for", r"perfect for", r"made for", r"ideal for", r"affordable", r"trusted", r"reliable",
    r"cloudflare", r"woocommerce", r"google", r"aws", r"cpanel", r"ssl", r"nvme", r"litespeed", r"ssd", r"managed",
]
RE_RISKY = re.compile(r"(?<![\w-])(" + "|".join(RISKY) + r")(?![\w-])", re.I)


@dataclass
class Claim:
    text: str
    kind: str
    scope: str
    status: str = NEEDS_REVIEW
    fact_ids: list[str] = field(default_factory=list)
    reason: str = ""
    origin: str = "generated"
    value: dict | None = None

    def as_dict(self) -> dict:
        d = {"text": self.text, "kind": self.kind, "scope": self.scope, "status": self.status, "fact_ids": self.fact_ids,
             "origin": self.origin}
        if self.reason:
            d["reason"] = self.reason
        if self.value:
            d["value"] = self.value
        return d


def _unit_pairs(text: str) -> set[tuple[float, str]]:
    t = normalize_numbers(text.lower())
    out = set()
    for m in RE_QTY.finditer(t):
        out.add((float(m.group(1).replace(",", "")), UNITS[m.group(2).lower()]))
    return out


def _numbers(text: str) -> set[float]:
    return {float(x.replace(",", "")) for x in RE_NUMBER.findall(normalize_numbers(text))}


class Verifier:
    def __init__(self, facts: FactBase, brief: dict | None = None):
        self.fb, self.brief = facts, brief or {}
        self.kw = [(normalize_numbers(k), fid) for k, fid in facts.keyword_index()]
        self.plans = facts.plan_names()
        self.sig_units = {f["id"]: _unit_pairs(f["excerpt"] + " " + f["claim"]) for f in facts.facts}
        self.sig_nums = {f["id"]: _numbers(f["excerpt"] + " " + f["claim"] + " " + _flat(f.get("value"))) for f in facts.facts}
        bp = self.brief.get("price_parsed") or {}
        self.brief_amount = bp.get("amount")
        self.brief_text = " ".join(str(self.brief.get(k, "")) for k in ("product", "price", "request", "cta", "audience")).lower()
        self.brief_product = _product_of(self.brief.get("product", ""))
        self.brief_price_ok = True
        if self.brief_amount is not None:
            probe = Claim("brief", "price", "brief")
            bp = self.brief["price_parsed"]
            self.check_price(probe, float(bp["amount"]), bp.get("period"), self.brief.get("product", ""), "", "")
            self.brief_price_ok = probe.status == VERIFIED

    # -- helpers --------------------------------------------------------------------------
    def _plan_in(self, text: str) -> str | None:
        for p in self.plans:
            if re.search(rf"(?<![\w-]){re.escape(p)}(?![\w-])", text, re.I):
                if " " in p or re.search(rf"{re.escape(p)}\s+(plan|tier)|(plan|tier)\s*[:\-]?\s*{re.escape(p)}", text, re.I) \
                        or re.search(rf"^{re.escape(p)}\b", text.strip()):
                    return p
        return None

    def _product_ctx(self, scope_text: str, context: str) -> str | None:
        for t in (scope_text, context):
            p = _product_of(t)
            if p:
                return p
        return self.brief_product

    # -- verification ---------------------------------------------------------------------
    def check_price(self, c: Claim, amount: float, period: str | None, scope_text: str, context: str, prefix: str) -> None:
        plan = self._plan_in(scope_text)
        product = "wordpress" if plan and plan.startswith("WP ") else ("shared" if plan else self._product_ctx(scope_text, context))
        c.value = {"amount": amount, "period": period, "product": product, "plan": plan}
        cands = []
        for f in self.fb.prices():
            v = f["value"]
            amts = {("month", v.get("amount"))} if v.get("period", "month") == "month" else {("year", v.get("amount"))}
            for cyc, a in (v.get("cycles") or {}).items():
                amts.add(("year" if cyc == "annual" else "6months" if cyc == "semiAnnual" else "month", a))
            if any(a == amount and (period is None or p == period) for p, a in amts):
                cands.append(f)
        strict = [f for f in cands if (product is None or f.get("product") in (product, "all")) and (plan is None or f.get("plan") == plan)]
        is_brief = self.brief_amount is not None and float(amount) == float(self.brief_amount)
        c.origin = "brief" if is_brief else "generated"
        if strict and not is_brief and not getattr(self, "brief_price_ok", True) and product and product == self.brief_product:
            c.status, c.fact_ids = NEEDS_REVIEW, [f["id"] for f in strict]
            c.reason = (f"₹{_n(amount)} is a real {product} price, but it contradicts the brief's price "
                        f"({self.brief.get('price')}) used in this video; show one consistent price")
            return
        if strict:
            if RE_FROM.search(prefix) and not any(f["id"].endswith("from_price") for f in strict):
                lowest = min((f for f in self.fb.prices() if f.get("product") == product and f["value"].get("period") == "month"),
                             key=lambda f: f["value"]["amount"], default=None)
                if lowest and lowest["value"]["amount"] != amount:
                    c.status, c.reason = NEEDS_REVIEW, f"'{prefix.strip()} ₹{_n(amount)}' implies a starting price; the lowest is {lowest['claim']}"
                    c.fact_ids = [lowest["id"]]
                    return
            c.status, c.fact_ids = VERIFIED, [f["id"] for f in strict]
            return
        c.status = NEEDS_REVIEW
        if cands:
            c.fact_ids = [f["id"] for f in cands]
            c.reason = f"₹{_n(amount)} exists only as: {'; '.join(f['claim'] for f in cands[:2])} (not {plan or product or 'this product'})"
        else:
            near = sorted((f for f in self.fb.prices() if product is None or f.get("product") == product),
                          key=lambda f: abs(f["value"].get("amount", 0) - amount))[:2]
            c.fact_ids = [f["id"] for f in near]
            c.reason = (f"no {product or ''} price of ₹{_n(amount)}{'/' + period if period else ''} on {self.fb.site or 'the site'}; "
                        f"closest: {'; '.join(f['claim'] for f in near)}").replace("  ", " ")
            coupon = next((f for f in self.fb.facts if f["id"].startswith("offer.coupon")
                           and "percent_off" in (f.get("value") or {})), None)     # the brand's coupon fact, any brand
            if coupon:
                pct = coupon["value"]["percent_off"]
                for f in near:
                    if abs(f["value"].get("amount", 0) * (100 - pct) / 100 - amount) < 0.01:
                        c.reason += f". Equals the {pct}% coupon price of {f.get('plan')} (first payment only; must be stated)"
        if is_brief:
            c.reason += " — supplied by the brief: owner must confirm before publishing"

    def check_numeric(self, c: Claim, pairs: set | None, nums: set | None, product: str | None) -> None:
        hits = []
        for f in self.fb.facts:
            if product and f.get("product") not in (product, "all", "company") and c.kind != "number":
                continue
            if pairs and pairs & self.sig_units[f["id"]]:
                hits.append(f["id"])
            elif nums and nums <= self.sig_nums[f["id"]] and not pairs:
                hits.append(f["id"])
        if hits:
            c.status, c.fact_ids = VERIFIED, hits[:4]
        else:
            c.status, c.reason = NEEDS_REVIEW, f"'{c.text}' is not stated on {self.fb.site or 'the site'}"

    def verify_text(self, text: str, scope: str, context: str = "") -> list[Claim]:
        if not text or not str(text).strip():
            return []
        raw = str(text)
        t = normalize_numbers(raw)
        low = t.lower()
        taken: list[tuple[int, int]] = []
        out: list[Claim] = []

        def free(a, b):
            return not any(a < y and x < b for x, y in taken)

        def take(a, b):
            taken.append((a, b))

        for m in RE_LABEL_NUM.finditer(t):   # "Year 1", "Step 2": labels, not claims
            take(*m.span())
        for m in RE_EMAIL.finditer(t):
            c = Claim(m.group(0), "email", scope)
            f = next((f for f in self.fb.facts if f["category"] == "contact" and m.group(0).lower() in f["excerpt"].lower()), None)
            c.status, c.fact_ids = (VERIFIED, [f["id"]]) if f else (NEEDS_REVIEW, [])
            c.reason = "" if f else "email address not on the site"
            out.append(c); take(*m.span())
        for m in RE_DOMAIN.finditer(t):
            if not free(*m.span()):
                continue
            d = m.group(1).lower()
            c = Claim(m.group(0), "domain", scope)
            if d.endswith(self.fb.domain()) and self.fb.domain():
                c.status, c.fact_ids = VERIFIED, ["company.url"]
            elif PLACEHOLDER.search(d):
                c.status, c.reason = ILLUSTRATIVE, "placeholder domain in UI mock-up"
            else:
                c.reason = "domain is not the brand's site"
            out.append(c); take(*m.span())
        for rx in RE_PRICE:
            for m in rx.finditer(t):
                if not free(*m.span()):
                    continue
                amount = float(m.group(1).replace(",", ""))
                per = (m.group(2) or m.group(3) or "").lower()
                period = "month" if per in ("mo", "month", "monthly") else "year" if per in ("yr", "year", "annum", "yearly", "annually") else None
                c = Claim(m.group(0).strip(), "price", scope)
                self.check_price(c, amount, period, t, context, t[max(0, m.start() - 20):m.start()])
                out.append(c); take(*m.span())
        for m in RE_PERCENT.finditer(t):
            if not free(*m.span()):
                continue
            c = Claim(m.group(0), "percent", scope)
            v = float(m.group(1).replace(",", ""))
            self.check_numeric(c, None, {v}, None)
            if c.status == VERIFIED and v == 99.9 and re.search(r"guarantee", low):
                c.status, c.reason = NEEDS_REVIEW, "the site states a 99.9% uptime TARGET, not a guarantee"
            if c.status == VERIFIED and any(i.startswith("offer.coupon") for i in c.fact_ids) \
                    and not re.search(r"first|code|new customer", low + " " + context.lower()):
                c.reason = "coupon: state the conditions (first payment, new customers, the code)"
            out.append(c); take(*m.span())
        for m in RE_MULT.finditer(t):
            if not free(*m.span()):
                continue
            c = Claim(m.group(0), "multiplier", scope)
            hit = [f["id"] for f in self.fb.facts if m.group(1) and re.search(rf"\b{re.escape(m.group(1))}\s*[x×]", f["excerpt"], re.I)]
            c.status, c.fact_ids = (VERIFIED, hit) if hit else (NEEDS_REVIEW, [])
            c.reason = "" if hit else "comparative multiplier is not supported by any fact (competitor claims need a source)"
            out.append(c); take(*m.span())
        product = self._product_ctx(t, context)
        for m in RE_QTY.finditer(t):
            if not free(*m.span()):
                continue
            unit = UNITS[m.group(2).lower()]
            if unit in ("step", "click", "plan"):
                take(*m.span()); continue  # narrative counts ("3 steps"), not product claims
            c = Claim(m.group(0), "quantity", scope)
            self.check_numeric(c, {(float(m.group(1).replace(",", "")), unit)}, None, product)
            out.append(c); take(*m.span())
        for kw, fid in self.kw:
            for m in re.finditer(rf"(?<![\w-]){re.escape(kw)}(?![\w-])", low):
                if any(ch.isdigit() for ch in kw) and free(*m.span()):
                    out.append(Claim(t[m.start():m.end()], "feature", scope, VERIFIED, [fid])); take(*m.span())
        for m in RE_NUMBER.finditer(t):
            if not free(*m.span()):
                continue
            c = Claim(m.group(0), "number", scope)
            self.check_numeric(c, None, {float(m.group(0).replace(",", ""))}, None)
            out.append(c); take(*m.span())
        # plans
        for m in RE_PLAN_MENTION.finditer(t):
            name = m.group(1).strip()
            name = next((p for p in self.plans if name.lower().endswith(p.lower())), name)
            c = Claim(m.group(0), "plan", scope)
            f = next((f for f in self.fb.facts if f.get("plan") == name and f["category"] == "price"), None)
            c.status, c.fact_ids = (VERIFIED, [f["id"]]) if f else (NEEDS_REVIEW, [])
            c.reason = "" if f else f"plan {name!r} does not exist on the site"
            if f or name.lower() not in ("the", "this", "your", "a", "our", "every"):
                out.append(c)
        # feature keywords (annotations) + risky terms that need cover
        cover: list[tuple[int, int, str]] = []
        for kw, fid in self.kw:
            for m in re.finditer(rf"(?<![\w-]){re.escape(kw)}(?![\w-])", low):
                f = self.fb.by_id(fid)
                if f and f.get("product") not in (None, "all", "company") and product and f.get("product") != product \
                        and not any(f2 for k2, f2 in self.kw if k2 == kw and (self.fb.by_id(f2) or {}).get("product") in (product, "all")):
                    continue
                cover.append((m.start(), m.end(), fid))
        seen = set()
        for a, b, fid in sorted(cover, key=lambda x: (x[0], -(x[1] - x[0]))):
            if any(a >= x and b <= y and (x, y) != (a, b) for x, y, _ in cover) or (a, b) in seen:
                continue
            seen.add((a, b))
            out.append(Claim(t[a:b], "feature", scope, VERIFIED, [fid]))
        for m in RE_RISKY.finditer(low):
            a, b = m.span()
            if any(x <= a and b <= y for x, y, _ in cover) or not free(a, b):
                continue
            c = Claim(t[a:b], "risky", scope)
            c.reason = f"'{t[a:b]}' needs a source on {self.fb.site or 'the site'} (performance/guarantee/offer/social-proof claim)"
            if t[a:b].lower() in self.brief_text:
                c.origin = "brief"
            out.append(c)
        for c in out:
            if c.origin == "generated" and c.kind != "price" and c.text.lower() in self.brief_text:
                c.origin = "brief"
        return out


def _flat(v) -> str:
    if isinstance(v, dict):
        return " ".join(_flat(x) for x in v.values())
    if isinstance(v, list):
        return " ".join(_flat(x) for x in v)
    return str(v) if v is not None else ""


def _n(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}"


def _product_of(text: str) -> str | None:
    t = (text or "").lower()
    if re.search(r"wordpress|\bwp\b|woocommerce", t):
        return "wordpress"
    if re.search(r"shared hosting|\b(launch|grow|turbo|infinity) plan", t):
        return "shared"
    return None


# ---- walking storyboards / concepts / publishing --------------------------------------------------------
def block_texts(b: dict) -> list[tuple[str, str]]:
    """(field path, text) pairs worth checking in a block. Structured fields are rendered as text."""
    ty, out = b.get("type"), []

    def add(path, *parts):
        s = " ".join(str(p) for p in parts if p not in (None, ""))
        if s.strip():
            out.append((path, s))

    if ty == "headline":
        add("words", b["words"] if isinstance(b.get("words"), str) else " ".join(w.get("text", "") for w in b.get("words", [])))
    elif ty in ("text", "pill"):
        add("text", b.get("text"))
    elif ty == "price":
        cur = b.get("currency", "₹")
        add("price", b.get("label"), f"{cur}{b.get('amount')}{b.get('period', '')}", b.get("note"))
    elif ty == "checklist":
        for i, it in enumerate(b.get("items", [])):
            add(f"items[{i}]", it.get("text"))
    elif ty == "bars":
        add("title", b.get("title"))
        for i, it in enumerate(b.get("bars", [])):
            add(f"bars[{i}]", it.get("label"))
        if b.get("badge"):
            add("badge", b["badge"].get("text"))
    elif ty == "compare-rows":
        for i, r in enumerate(b.get("rows", [])):
            add(f"rows[{i}]", r.get("label"), "—", r.get("value"))
        if b.get("badge"):
            add("badge", b["badge"].get("text"))
    elif ty == "plans":
        for i, p in enumerate(b.get("plans", [])):
            add(f"plans[{i}]", f"{p.get('name')} plan", f"{p.get('price', '')}{p.get('period', '')}", p.get("detail"), p.get("badge"))
    elif ty == "domain-input":
        add("title", b.get("title")); add("domain", b.get("domain")); add("availableText", b.get("availableText"))
        for k, v in (b.get("button") or {}).items():
            if isinstance(v, str) and not v.startswith("@"):
                add(f"button.{k}", v)
    elif ty == "browser":
        add("url", b.get("url"))
        if b.get("tag"):
            add("tag", b["tag"].get("text"))
    elif ty == "hook-tag":
        add("hook-tag", b.get("label"), b.get("text"), b.get("sub"))
    elif ty == "flat-line":
        add("title", b.get("title"))
        for i, p in enumerate(b.get("points", [])):
            add(f"points[{i}]", p.get("label"), p.get("value"))
    elif ty == "cta":
        add("text", b.get("text")); add("url", b.get("url")); add("sub", b.get("sub"))
    return out


def block_texts_all(blocks: list[dict]) -> list[tuple[str, str]]:
    return [x for b in blocks for x in block_texts(b)]


def verify_storyboard(sb: dict, facts: FactBase, brief: dict | None = None, publishing: dict | None = None) -> dict:
    v = Verifier(facts, brief)
    claims: list[Claim] = []
    for i, sc in enumerate(sb.get("scenes", [])):
        p = f"scenes[{i}]({sc.get('id')})"
        ctx = sc.get("narration", "")
        claims += v.verify_text(sc.get("narration", ""), f"{p}.narration", ctx)
        for j, b in enumerate(sc.get("blocks", [])):
            for path, text in block_texts(b):
                claims += v.verify_text(text, f"{p}.blocks[{j}]:{b.get('type')}.{path}", ctx)
    if sb.get("title"):
        claims += v.verify_text(sb["title"], "storyboard.title")
    for k in ("title", "description"):
        if publishing and publishing.get(k):
            claims += v.verify_text(publishing[k], f"publishing.{k}")
    if publishing and publishing.get("hashtags"):
        claims += v.verify_text(" ".join(h.lstrip("#") for h in publishing["hashtags"]), "publishing.hashtags")
    return summarize(claims, facts, brief)


def verify_brief(brief: dict, facts: FactBase) -> dict:
    v = Verifier(facts, brief)
    claims = []
    if brief.get("price"):
        claims += v.verify_text(f"{brief['product']} at {brief['price']}", "brief.price", brief.get("product", ""))
    for c in claims:
        c.origin = "brief"
    return summarize(claims, facts, brief)


def verify_concept(concept: dict, facts: FactBase, brief: dict | None = None) -> dict:
    v = Verifier(facts, brief)
    claims = []
    for k in ("hook", "logline", "title"):
        if concept.get(k):
            claims += v.verify_text(concept[k], f"concept.{k}", concept.get("logline", ""))
    cta = concept.get("cta_treatment", {})
    if cta.get("text"):
        claims += v.verify_text(cta["text"], "concept.cta_treatment.text")
    for i, bt in enumerate(concept.get("beats", [])):
        claims += v.verify_text(bt.get("idea", ""), f"concept.beats[{i}]")
    return summarize(claims, facts, brief)


def summarize(claims: list[Claim], facts: FactBase, brief: dict | None) -> dict:
    nr = [c for c in claims if c.status == NEEDS_REVIEW]
    return {
        "facts_file": str(facts.path) if facts.path else None,
        "facts_fetched_at": facts.fetched_at,
        "summary": {"total": len(claims), "verified": sum(c.status == VERIFIED for c in claims), "needs_review": len(nr),
                    "illustrative": sum(c.status == ILLUSTRATIVE for c in claims),
                    "needs_review_from_brief": sum(c.origin == "brief" for c in nr),
                    "needs_review_generated": sum(c.origin == "generated" for c in nr)},
        "blocking": bool(nr),
        "needs_review": [c.as_dict() for c in nr],
        "claims": [c.as_dict() for c in claims],
    }
