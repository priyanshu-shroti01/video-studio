"""Suggested facts: read a brand's own website pages and propose CANDIDATE facts that a person confirms.

    knowledge/<brand>/candidates.json    proposals, every one status NEEDS_REVIEW (never facts.json)

What is proposed (deterministically, from the visible page text only):
  * prices: currency + amount (+ period / per-seat / "billed …"), with the plan name from the nearest heading
    or plan-card title before it; struck-through (old) prices and "save ₹X" / "$X off" amounts are skipped;
  * numeric features: storage, websites, bandwidth, RAM, CPU cores, e-mail accounts, databases, users, projects;
  * claims: N-day money-back guarantee, uptime %, free SSL, free domain, backups, 24/7 support, free
    migration, N-day free trial;
  * the site URL (company.url, from the page source like the hand-written facts).

Every candidate's `excerpt` is a verbatim slice of `facts.page_text(page)` (or of the normalised page source for
`page-data`), so the existing `facts.refresh()` check finds it. Values are parsed from the same text. An
optional local LLM may only re-word the `claim`; values and excerpts never come from a model.

A candidate becomes a fact only through `confirm_candidate`: a named reviewer, an explicit confirm, and a
fresh re-check (the same `refresh()` logic) that the excerpt is still on the page. `reject_candidate` removes it
and remembers the rejection so a later extraction does not propose it again. Both are written to the audit log.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
from pathlib import Path

from .errors import ConfigError, NotFound, PipelineError, StateError
from .intelligence import facts as F
from .paths import atomic_write_json

MAX_PAGES = 6                 # polite: a handful of the brand's own pages, one GET each
DELAY_S = 0.5                 # pause between page fetches
MAX_PER_PAGE = 60
PLAN_WINDOW = 260             # how far (characters of page text) a plan title may be before its price
LOCK = threading.Lock()       # candidates.json / facts.json read-modify-write

CURRENCY = {"₹": "INR", "rs": "INR", "inr": "INR", "$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR",
            "£": "GBP", "gbp": "GBP"}
NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
PRICE = re.compile(r"(?<![A-Za-z])(₹|Rs\.?|INR|US\$|USD|\$|€|EUR|£|GBP)\s?" + NUM + r"(?![\d.,]*\s?%)(?![\w])", re.I)
PERIOD = re.compile(r"\s?(?:/\s?|per\s|a\s|an\s)(?:(user|seat|member)\s?(?:/\s?|per\s|a\s|an\s))?"
                    r"(mo|mon|month|mth|yr|year|annum|week|wk)\b|\s?(?:/\s?|per\s)(user|seat|member)\b", re.I)
BILLED = re.compile(r"billed\s(monthly|annually|yearly|quarterly|every\s(?:\d+\s)?(?:months?|years?))", re.I)
NOT_A_PRICE_AFTER = re.compile(r"\s?(?:off|discount|credit|cashback|back|savings?)\b", re.I)
NOT_A_PRICE_BEFORE = re.compile(r"(?:save|saving|get|off|discount|worth)\s?$", re.I)
TLD_BEFORE = re.compile(r"(?:^|\s)(\.[a-z]{2,12})\s?$")          # ".com ₹1,169/yr": a domain price
RENEW_BEFORE = re.compile(r"renews?(?:\sat)?\s?$", re.I)
FROM_BEFORE = re.compile(r"(?:from|starting at|starts at|as low as|only)\s?$", re.I)
PERIOD_WORD = {"mo": "month", "mon": "month", "month": "month", "mth": "month", "yr": "year", "year": "year",
               "annum": "year", "week": "week", "wk": "week"}
BILLING_WORD = {"monthly": "monthly", "annually": "annual", "yearly": "annual", "quarterly": "quarterly"}
GENERIC_HEADINGS = re.compile(r"^(?:pricing|prices?|plans?|our plans|all plans|features?|faqs?|most popular|popular|"
                              r"best value|recommended|compare(?: plans)?|choose (?:a|your) plan|monthly|yearly|annually|"
                              r"new|sale|offer|limited offer|save \d+%?)$", re.I)

# numeric features: (key, category, pattern, value builder). Label-first patterns come first ("Storage10 GB NVMe").
_U = r"(unlimited|unmetered|" + NUM + r")"


def _num(s: str) -> float | int:
    v = float(s.replace(",", ""))
    return int(v) if v.is_integer() else v


def _count(s: str):
    return s.lower() if s.lower() in ("unlimited", "unmetered") else _num(s)


def _gb(m) -> dict:
    return {f"storage_{m[2].lower()}": _num(m[1]), **({"type": m[3]} if m[3] else {})}


def _pl(n, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


FEATURES = [   # (kind, category, pattern, value, wording of the value)
    ("storage", "spec", re.compile(r"(?:storage|disk(?: space)?)\s?:?\s?" + NUM + r"\s?(GB|TB)\b(?:\s(NVMe|SSD))?", re.I), _gb,
     lambda v: " ".join(str(x) for x in (v.get("storage_gb"), "GB") if v.get("storage_gb") is not None)
               + " ".join(str(x) for x in (v.get("storage_tb"), "TB") if v.get("storage_tb") is not None)
               + (f" {v['type']}" if "type" in v else "") + " storage"),
    ("storage", "spec", re.compile(NUM + r"\s?(GB|TB)\s(?:(NVMe|SSD)\s)?(?:SSD\s)?(?:storage|disk(?: space)?|space)\b", re.I), _gb, None),
    ("bandwidth", "spec", re.compile(r"bandwidth\s?:?\s?(unlimited|unmetered|" + NUM + r"\s?(?:GB|TB))\b", re.I),
     lambda m: {"bandwidth": m[1].lower() if not m[2] else m[1]}, lambda v: f"{v['bandwidth']} bandwidth"),
    ("bandwidth", "spec", re.compile(r"(unlimited|unmetered|" + NUM + r"\s?(?:GB|TB))\s(?:monthly\s)?bandwidth\b", re.I),
     lambda m: {"bandwidth": m[1].lower() if not m[2] else m[1]}, None),
    ("ram", "spec", re.compile(r"\bRAM\s?:?\s?" + NUM + r"\s?GB\b", re.I), lambda m: {"ram_gb": _num(m[1])},
     lambda v: f"{v['ram_gb']} GB RAM"),
    ("ram", "spec", re.compile(NUM + r"\s?GB\s(?:of\s)?(?:RAM|memory)\b", re.I), lambda m: {"ram_gb": _num(m[1])}, None),
    ("cpu", "spec", re.compile(r"\bv?CPU\s?:?\s?" + NUM + r"\s?(?:v?CPU\s)?cores?\b", re.I), lambda m: {"cpu_cores": _num(m[1])},
     lambda v: _pl(v["cpu_cores"], "CPU core")),
    ("cpu", "spec", re.compile(NUM + r"\s(?:v?CPU\s)?cores?\b", re.I), lambda m: {"cpu_cores": _num(m[1])}, None),
    ("websites", "spec", re.compile(r"\bwebsites?\s?:?\s?" + _U + r"\s(?:(?:WordPress|WP)\s)?(?:websites?|sites?)\b", re.I),
     lambda m: {"websites": _count(m[1])}, lambda v: _pl(v["websites"], "website")),
    ("websites", "spec", re.compile(r"\b" + _U + r"\s(?:(?:WordPress|WP)\s)?(?:websites?|sites?)\b", re.I),
     lambda m: {"websites": _count(m[1])}, None),
    ("email", "spec", re.compile(r"\b" + _U + r"\s(?:e-?mail accounts?|mailboxes|e-?mail addresses)\b", re.I),
     lambda m: {"email_accounts": _count(m[1])}, lambda v: _pl(v["email_accounts"], "e-mail account")),
    ("databases", "spec", re.compile(r"\b" + _U + r"\s(?:MySQL\s)?databases?\b", re.I), lambda m: {"databases": _count(m[1])},
     lambda v: _pl(v["databases"], "database")),
    ("users", "spec", re.compile(r"\b" + _U + r"\s(?:users?|seats?|team members?)\b", re.I), lambda m: {"users": _count(m[1])},
     lambda v: _pl(v["users"], "user")),
    ("projects", "spec", re.compile(r"\b" + _U + r"\sprojects?\b", re.I), lambda m: {"projects": _count(m[1])},
     lambda v: _pl(v["projects"], "project")),
]
WORDING = {k: w for k, _, _, _, w in FEATURES if w}
CLAIMS = [
    ("money_back", "policy", re.compile(r"\b(\d{1,3})[- ]days?\s(?:\w+\s)?money[- ]back(?:\sguarantee)?", re.I),
     lambda m: {"days": int(m[1])}, lambda m: f"{m[1]}-day money-back guarantee"),
    ("money_back", "policy", re.compile(r"\bmoney[- ]back guarantee", re.I),
     lambda m: {"money_back": True}, lambda m: "Money-back guarantee"),
    ("uptime", "policy", re.compile(NUM + r"\s?%\s(?:network\s|server\s)?uptime(?:\s(guarantee|target|sla|commitment))?", re.I),
     lambda m: {"uptime_pct": _num(m[1]), **({"kind": m[2].lower()} if m[2] else {})}, lambda m: f"{m[1]}% uptime" + (f" {m[2].lower()}" if m[2] else "")),
    ("free_ssl", "feature", re.compile(r"\bfree\s(?:\w+\s)?SSL(?:\scertificates?)?|\bSSL(?:\scertificates?)?\sincluded", re.I),
     lambda m: {"ssl": "free"}, lambda m: "Free SSL certificate"),
    ("free_domain", "offer", re.compile(r"\bfree\s(?:\.[a-z]{2,6}\s(?:or\s\.[a-z]{2,6}\s)?)?domain(?:\sname)?"
                                        r"(?:\s(?:for|with)\s(?:the\s)?(?:first\s)?(?:1\s)?year)?", re.I),
     lambda m: {"free_domain": True, **({"first_year_only": True} if "year" in m[0].lower() else {})}, lambda m: m[0][0].upper() + m[0][1:]),
    ("backups", "feature", re.compile(r"\b(daily|weekly|automatic|automated|free)(?:\s(?:and\s)?(?:daily|weekly|automatic|automated|off-?site))?\sbackups?", re.I),
     lambda m: {"backups": m[0].lower().rsplit(" ", 1)[0]}, lambda m: m[0][0].upper() + m[0][1:]),
    ("support_247", "policy", re.compile(r"\b24\s?/\s?7(?:\s\w+)?\ssupport|\b24x7(?:\s\w+)?\ssupport", re.I),
     lambda m: {"support": "24/7"}, lambda m: m[0][0].upper() + m[0][1:]),
    ("free_migration", "policy", re.compile(r"\bfree\s(?:\w+\s)?migrations?\b", re.I),
     lambda m: {"migration": "free"}, lambda m: m[0][0].upper() + m[0][1:]),
    ("free_trial", "offer", re.compile(r"\b(\d{1,3})[- ]days?\sfree\strial|\bfree\sfor\s(\d{1,3})\sdays\b", re.I),
     lambda m: {"trial_days": int(m[1] or m[2])}, lambda m: f"{m[1] or m[2]}-day free trial"),
]
TITLE_CLASS = re.compile(r"(?:plan|package|tier|card|pricing|product)[-_]?(?:name|title|heading)|^(?:title|name)$", re.I)
VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area", "col", "embed", "param", "track"}


# ---- page text with structure (same text as facts.page_text) -------------------------------------------------
class _Scan(F._Text):
    """facts._Text (the verification text) plus, for every data chunk, whether it sits in a heading/plan title
    or in a struck-through element. The text itself is produced exactly like facts.page_text."""

    def __init__(self):
        super().__init__()
        self.stack: list[tuple[str, bool, bool]] = []
        self.chunks: list[tuple[str, bool, bool]] = []

    def handle_starttag(self, t, a):
        super().handle_starttag(t, a)
        if t in VOID:
            return
        cls = " ".join(v or "" for k, v in a if k in ("class", "id"))
        head = bool(re.fullmatch(r"h[2-6]", t)) or any(TITLE_CLASS.search(c) for c in cls.split())
        strike = t in ("del", "s", "strike")
        ph, ps = (self.stack[-1][1], self.stack[-1][2]) if self.stack else (False, False)
        self.stack.append((t, head or ph, strike or ps))

    def handle_endtag(self, t):
        super().handle_endtag(t)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == t:
                del self.stack[i:]
                break

    def handle_data(self, d):
        super().handle_data(d)
        if not self.skip and d.strip():
            h, s = (self.stack[-1][1], self.stack[-1][2]) if self.stack else (False, False)
            self.chunks.append((d, h, s))


class Page:
    def __init__(self, html: str, url: str, key: str):
        self.url, self.key = url, key
        sc = _Scan()
        sc.feed(html)
        self.text = F.page_text(html)
        self.raw = F._norm(html.replace('\\"', '"'))            # what refresh() searches for page-data facts
        self.headings: list[tuple[int, int, str]] = []
        self.struck: list[tuple[int, int]] = []
        self.blocks: list[tuple[int, int]] = []
        cur, head = 0, None
        for d, h, s in sc.chunks:                                  # chunks appear in the text in order
            nd = F._norm(d)
            pos = self.text.find(nd, cur)
            if pos < 0:
                continue
            end = pos + len(nd)
            if s:
                self.struck.append((pos, end))
            if h and head and pos <= head[1] + 1:
                head = (head[0], end)
            elif h:
                if head:
                    self.headings.append((*head, self.text[head[0]:head[1]]))
                head = (pos, end)
            elif head:
                self.headings.append((*head, self.text[head[0]:head[1]])); head = None
            cur = end
        if head:
            self.headings.append((*head, self.text[head[0]:head[1]]))
        cur = 0
        for line in "".join(sc.out).split("\n"):                   # block-level lines, as page_text builds them
            nl = F._norm(line)
            if not nl:
                continue
            pos = self.text.find(nl, cur)
            if pos >= 0:
                self.blocks.append((pos, pos + len(nl)))
                cur = pos + len(nl)

    def block_at(self, i: int) -> tuple[int, int]:
        return next(((a, b) for a, b in self.blocks if a <= i < b), (i, i))

    def plan_before(self, i: int, allowed: set[str] | None = None) -> tuple[int, str] | None:
        for a, b, h in reversed(self.headings):
            if b > i:
                continue
            if i - a > PLAN_WINDOW:
                return None
            if allowed is not None:
                return (a, h) if h in allowed else None
            if _plan_like(h):
                return a, h
            return None
        return None

    def window(self, a: int, b: int, pad: int = 70) -> tuple[int, int]:
        """The block holding [a, b) if it is short, else a word-aligned window around it."""
        ba, bb = self.block_at(a)
        if ba <= a and bb >= b and bb - ba <= 160:
            return ba, bb
        s, e = max(0, a - pad), min(len(self.text), b + pad)
        if s > 0:                                                  # snap to whole words
            sp = self.text.find(" ", s, a)
            s = sp + 1 if sp != -1 else a
        if e < len(self.text):
            sp = self.text.rfind(" ", b, e)
            e = sp if sp != -1 else b
        return s, e


def _plan_like(h: str) -> bool:
    return (0 < len(h) <= 40 and len(h.split()) <= 4 and "?" not in h and ". " not in h and not h.endswith(".") and not PRICE.search(h)
            and not GENERIC_HEADINGS.match(h.strip(" :!.")) and bool(re.search(r"[A-Za-z]", h)))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:30] or "x"


def _product(key: str) -> str:
    return "all" if re.fullmatch(r"home|pric\w*|plans?|offers?|features?", key or "home") else key


# ---- extraction ------------------------------------------------------------------------------------------
def analyse(html: str, url: str, key: str = "home") -> list[dict]:
    """Candidates found in one page (pure: no network, no files)."""
    pg = Page(html, url, key)
    t, out, product = pg.text, [], _product(key)

    def add(kind, category, plan, claim, value, a, b, ha, hb, source_kind="visible-text", prod=None):
        hay = pg.raw if source_kind == "page-data" else t
        excerpt = hay[a:b].strip()
        if not excerpt or F._norm(excerpt) not in hay:
            return
        rel = excerpt.find(hay[ha:hb])
        out.append({"kind": kind, "category": category, "product": prod or ("company" if category == "url" else product),
                    "plan": plan, "claim": claim, "value": value, "keywords": [], "source_url": url,
                    "source_kind": source_kind, "excerpt": excerpt, "match": hay[ha:hb],
                    "highlight": [rel, rel + (hb - ha)] if rel >= 0 else None, "volatile": False})

    taken: list[tuple[int, int]] = []
    plans: set[str] = set()
    tld = None                                    # (".com", start, end of its first price) for "Renews ₹…" after it
    for m in PRICE.finditer(t):
        a, b = m.span()
        if any(sa < b and a < sb for sa, sb in pg.struck) or NOT_A_PRICE_BEFORE.search(t[max(0, a - 12):a]) \
                or NOT_A_PRICE_AFTER.match(t, b):
            continue
        amount = _num(m[2])
        cur = CURRENCY.get(m[1].lower().rstrip("."), "?")
        value: dict = {"amount": amount, "currency": cur}
        end = b
        pm = PERIOD.match(t, b)
        unit = None
        if pm:
            unit = (pm[1] or pm[3] or "").lower() or None
            if pm[2]:
                value["period"] = PERIOD_WORD[pm[2].lower()]
            end = pm.end()
        if unit:
            value["per"] = unit
        nxt = PRICE.search(t, end)
        bm = BILLED.search(t, end, min(len(t), end + 60))
        if bm and (not nxt or bm.start() < nxt.start()):
            w = bm[1].lower()
            value["billing"] = BILLING_WORD.get(w, w)
            value.setdefault("period", {"monthly": "month", "annual": "year"}.get(value["billing"], value.get("period")))
            if value.get("period") is None:
                value.pop("period")
            end = bm.end()
        be = pg.block_at(max(end - 1, a))[1]
        if end < be <= end + 40 and not PRICE.search(t, end, be):
            end = be
        disp = re.sub(r"(?<=[₹$€£])\s", "", t[a:b]) + (re.sub(r"\s*/\s*", "/", pm[0]) if pm else "")
        billing = f", billed {bm[1].lower()}" if bm and "billing" in value else ""
        renew = RENEW_BEFORE.search(t[max(0, a - 12):a])
        tm = TLD_BEFORE.search(t[max(0, a - 16):a])
        if tm:
            tld = (tm[1], a - (len(t[max(0, a - 16):a]) - tm.start(1)), end)
        elif not (renew and tld and a - tld[2] <= 12):
            tld = None
        if tld:                                   # domain registration / renewal price, labelled by its TLD
            value["domain_tld"] = tld[0]
            if renew:
                value["renewal"] = True
            claim = f"{tld[0]} domain {'renews at' if renew else 'costs'} {disp}"
            add("domain_price", "price", None, claim, value, tld[1], b if not pm else pm.end(), a, pm.end() if pm else b,
                prod="domains")
            taken.append((a, end))
            continue
        plan = pg.plan_before(a)
        start = plan[0] if plan else pg.window(a, end)[0]
        if plan:
            plans.add(plan[1])
        if renew:
            value["renewal"] = True
            claim = f"{plan[1]} plan renews at {disp}{billing}" if plan else f"Renews at {disp}{billing}"
        elif FROM_BEFORE.search(t[max(0, a - 14):a]):
            value["from"] = True
            claim = f"{plan[1]} plan starts from {disp}{billing}" if plan else f"Prices start from {disp}{billing}"
        else:
            claim = f"{plan[1]} plan costs {disp}{billing}" if plan else f"Price shown on the page: {disp}{billing}"
        add("price", "price", plan[1] if plan else None, claim, value, start, end, a, pm.end() if pm else b)
        taken.append((a, end))

    def overl(a, b):
        return any(sa < b and a < sb for sa, sb in taken)
    for key_, category, rx, val, _w in FEATURES:
        for m in rx.finditer(t):
            a, b = m.span()
            if overl(a, b):
                continue
            plan = pg.plan_before(a, plans)
            s, e = pg.window(a, b)
            v = val(m)
            words = WORDING[key_](v)
            claim = f"{plan[1]} plan includes {words}" if plan else f"Includes {words}"
            hb = max(m.end(1), m.end(2) if m.re.groups >= 2 and m[2] else 0)          # highlight the number (and its unit)
            add(key_, category, plan[1] if plan else None, claim, v, s, e, m.start(1), hb)
            taken.append((a, b))
    for key_, category, rx, val, words in CLAIMS:
        for m in rx.finditer(t):
            a, b = m.span()
            if overl(a, b):
                continue
            plan = pg.plan_before(a, plans)
            s, e = pg.window(a, b)
            claim = words(m) + (f" ({plan[1]} plan)" if plan else "")
            add(key_, category, plan[1] if plan else None, claim, val(m), s, e, a, b)
            taken.append((a, b))
    return out[:MAX_PER_PAGE]


def site_url_candidate(html: str, site: str) -> dict | None:
    """company.url: the site's own address as it appears in the page source (or its visible text)."""
    u = urllib.parse.urlparse(site)
    domain = u.netloc.removeprefix("www.")
    if not domain:
        return None
    raw = F._norm(html.replace('\\"', '"'))
    text = F.page_text(html)
    for cand, kind, hay in ((f"https://{u.netloc}", "page-data", raw), (domain, "visible-text", text)):
        i = hay.find(cand)
        if i >= 0:
            return {"kind": "url", "category": "url", "product": "company", "plan": None,
                    "claim": f"The website is {domain}", "value": {"domain": domain}, "keywords": [],
                    "source_url": site, "source_kind": kind, "excerpt": cand, "match": cand,
                    "highlight": [0, len(cand)], "volatile": False}
    return None


def _as_text(r) -> str:
    """Accept brand_init's fetch ((bytes, content-type)), bytes or str."""
    if isinstance(r, tuple):
        r = r[0]
    return r.decode("utf-8", "replace") if isinstance(r, (bytes, bytearray)) else str(r)


def _order(pages: dict[str, str]) -> list[tuple[str, str]]:
    items = list(pages.items())
    def rank(kv):
        k = kv[0] + " " + urllib.parse.urlparse(kv[1]).path
        return (0 if re.search(r"pric|plan", k, re.I) else 1 if kv[0] == "home" else
                2 if re.search(r"hosting|product|feature|offer|package|service|shop|store", k, re.I) else 3)
    return sorted(items, key=rank)


def _fid(c: dict) -> str:
    parts = [] if c["product"] in ("all", "company") else [_slug(c["product"])]
    if c["category"] == "url":
        return "company.url"
    if c["plan"]:
        parts.append(_slug(c["plan"]))
    if c["kind"] == "domain_price":
        return f"domain.{_slug(c['value']['domain_tld'])}.price." + ("renewal" if c["value"].get("renewal") else "first_year")
    if c["category"] == "price" and c["value"].get("from"):
        parts.append("from_price")
    elif c["category"] == "price" and c["value"].get("renewal"):
        parts += ["price", "renewal"]
    elif c["category"] == "price":
        v = c["value"]
        parts += ["price", {"month": "monthly", "year": "annual", "week": "weekly"}.get(v.get("period", ""), "once")
                  if v.get("period") else "shown"]
    else:
        parts += [{"policy": "policy", "offer": "offer", "feature": "platform", "spec": "spec"}.get(c["category"], "")
                  if not c["plan"] and c["product"] == "all" else "", c["kind"]]
    return ".".join(p for p in parts if p)


def _cid(c: dict) -> str:
    return "c" + hashlib.sha1(f"{c['source_url']}\n{c['source_kind']}\n{c['excerpt']}\n{c['kind']}\n"
                              f"{json.dumps(c['value'], sort_keys=True)}".encode()).hexdigest()[:11]


def extract(pages: dict[str, str], *, site: str, fetch, max_pages: int = MAX_PAGES, delay: float = DELAY_S,
            prefetched: dict[str, str | bytes] | None = None, existing: list[dict] | None = None,
            rejected: list[dict] | None = None, sleep=time.sleep) -> dict:
    """Fetch up to `max_pages` of `pages` (name -> URL) politely and return candidates (deduplicated, minus
    anything already in facts.json or rejected before). `fetch(url)` is injectable for offline tests."""
    prefetched = dict(prefetched or {})
    known = {(f.get("source_url"), F._norm(f.get("excerpt", ""))) for f in (existing or [])}
    known |= {(r.get("source_url"), F._norm(r.get("excerpt", ""))) for r in (rejected or [])}
    known_vals = {(f.get("category"), f.get("plan"), json.dumps(f.get("value"), sort_keys=True)) for f in existing or []}
    ids = {f.get("id") for f in existing or []}
    out, seen, errors, read, fetched = [], set(), {}, [], 0
    for key, url in _order(pages)[:max_pages]:
        try:
            if url in prefetched:
                html = _as_text(prefetched[url])
            else:
                if fetched and delay:
                    sleep(delay)
                fetched += 1
                html = _as_text(fetch(url))
        except Exception as e:  # noqa: BLE001 - reported per page
            errors[url] = str(e) or type(e).__name__
            continue
        read.append(url)
        found = analyse(html, url, key)
        if key == "home" or url.rstrip("/") == site.rstrip("/"):
            u = site_url_candidate(html, url)
            if u:
                found.insert(0, u)
        for c in found:
            dedup = (c["category"], c["plan"], json.dumps(c["value"], sort_keys=True))
            if dedup in seen or dedup in known_vals or (c["source_url"], F._norm(c["excerpt"])) in known:
                continue
            seen.add(dedup)
            fid, n = _fid(c), 2
            base = fid
            while fid in ids:
                fid, n = f"{base}-{n}", n + 1
            ids.add(fid)
            out.append({"candidate_id": _cid(c), "id": fid, **{k: v for k, v in c.items() if k != "kind"},
                        "kind": c["kind"], "status": "NEEDS_REVIEW", "extracted_by": "rules"})
    return {"candidates": out, "pages_read": read, "fetch_errors": errors}


def suggest_wording(cands: list[dict], provider) -> int:
    """Optional: the local LLM re-words `claim` only. A suggestion is kept only if every number in it appears in
    the excerpt; values and excerpts are never touched. Returns how many claims were re-worded."""
    if not cands or provider is None or not provider.available()[0]:
        return 0
    schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
        "type": "object", "required": ["candidate_id", "claim"],
        "properties": {"candidate_id": {"type": "string"}, "claim": {"type": "string"}}}}}}
    rows = [{"candidate_id": c["candidate_id"], "claim": c["claim"], "excerpt": c["excerpt"]} for c in cands[:40]]
    try:
        res = provider.generate_json(system="Rewrite each claim as one short, plain sentence that says only what the "
                                            "excerpt says. Do not add numbers, plans or promises that are not in the excerpt.",
                                     messages=[{"role": "user", "content": json.dumps(rows, ensure_ascii=False)}],
                                     schema=schema, task="fact-wording", temperature=0.2, max_tokens=1500)
    except Exception:  # noqa: BLE001 - wording is optional
        return 0
    by = {c["candidate_id"]: c for c in cands}
    n = 0
    for it in (res.data or {}).get("items", []):
        c = by.get(it.get("candidate_id"))
        w = str(it.get("claim", "")).strip()
        if not c or not w or len(w) > 200:
            continue
        if all(x in c["excerpt"].replace(",", "") for x in re.findall(r"\d+(?:\.\d+)?", w.replace(",", ""))):
            c["claim_rule"], c["claim"], c["claim_by"] = c["claim"], w, f"llm:{getattr(provider, 'model', '')}"
            n += 1
    return n


# ---- storage -----------------------------------------------------------------------------------------------
def candidates_path(bid: str) -> Path:
    return F.KNOWLEDGE_DIR / bid / "candidates.json"


def _facts_path(bid: str) -> Path:
    return F.KNOWLEDGE_DIR / bid / "facts.json"


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_candidates(bid: str) -> dict:
    d = _read(candidates_path(bid)) or {}
    return {"brand": bid, "extracted_at": d.get("extracted_at"), "pages_read": d.get("pages_read", []),
            "fetch_errors": d.get("fetch_errors", {}), "candidates": d.get("candidates", []),
            "rejected": d.get("rejected", [])}


def extract_for_brand(bid: str, *, fetch=None, max_pages: int = MAX_PAGES, delay: float = DELAY_S,
                      prefetched: dict | None = None, provider=None) -> dict:
    """Read the brand's candidate pages (facts.json `pages`, found by brand init) and write candidates.json.
    Replaces the pending proposals; keeps the rejection list; never touches facts.json."""
    from . import brand_init
    fd = _read(_facts_path(bid))
    if fd is None:
        raise ConfigError(f"knowledge/{bid}/facts.json is missing: add the website first")
    site = fd.get("site") or ""
    pages = fd.get("pages") or ({"home": site} if site else {})
    if not pages:
        raise StateError(f"knowledge/{bid}/facts.json lists no pages to read")
    old = load_candidates(bid)
    res = extract(pages, site=site, fetch=fetch or brand_init._get, max_pages=max_pages, delay=delay,
                  prefetched=prefetched, existing=fd.get("facts", []), rejected=old["rejected"])
    reworded = suggest_wording(res["candidates"], provider) if provider is not None else 0
    doc = {"$comment": "SUGGESTED facts found on the website. None is verified: a person confirms each one in the Studio "
                       "(Websites → Suggested facts), which re-checks the excerpt on the page and then moves it into facts.json.",
           "brand": bid, "site": site, "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "pages_read": res["pages_read"], "fetch_errors": res["fetch_errors"], "candidates": res["candidates"],
           "rejected": old["rejected"]}
    with LOCK:
        atomic_write_json(candidates_path(bid), doc)
    return {"brand": bid, "count": len(res["candidates"]), "pages_read": res["pages_read"],
            "fetch_errors": res["fetch_errors"], "reworded": reworded, "file": f"knowledge/{bid}/candidates.json"}


class BadInput(PipelineError):
    code, exit_code = "BAD_REQUEST", 2


def confirm_candidate(bid: str, candidate_id: str, reviewer: str, *, confirm: bool, note: str = "",
                      fetcher=None, lock=None) -> dict:
    """A PERSON confirms a suggestion ("I checked this on the website"). The excerpt is re-checked on its page with
    facts.refresh(); only then is the fact appended to facts.json (status verified, verified_by, human_checks)."""
    from .jobs import Registry
    if confirm is not True:
        raise BadInput("confirming needs {\"confirm\": true} (tick \"I checked this on the website\")")
    if not (reviewer or "").strip():
        raise BadInput("a reviewer name is required")
    reviewer = reviewer.strip()
    c = next((x for x in load_candidates(bid)["candidates"] if x.get("candidate_id") == candidate_id), None)
    if c is None:
        raise NotFound(f"no suggested fact {candidate_id!r} for {bid}")
    probe = {k: c[k] for k in ("id", "source_url", "source_kind", "excerpt")}
    rep = F.refresh(F.FactBase(bid, bid, "", "", [probe], []), fetcher=fetcher or F.fetch)
    if rep["fetch_errors"]:
        raise StateError(f"could not read {c['source_url']} to re-check it: {next(iter(rep['fetch_errors'].values()))}")
    if rep["verified"] != 1:
        raise StateError("the exact text is no longer on the page, so it cannot become a fact; re-run "
                         "\"Find facts on the website\" or reject it")
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    check = {"reviewer": reviewer, "checked_at": at, "note": note, "source_url": c["source_url"],
             "via": "studio: suggested fact, \"I checked this on the website\" (excerpt re-checked on the page)"}
    with lock or LOCK:
        fd = _read(_facts_path(bid))
        if fd is None:
            raise NotFound(f"knowledge/{bid}/facts.json is missing or unreadable")
        cd = _read(candidates_path(bid)) or {}
        if not any(x.get("candidate_id") == candidate_id for x in cd.get("candidates", [])):
            raise NotFound(f"no suggested fact {candidate_id!r} for {bid}")
        ids = {f.get("id") for f in fd.get("facts", [])}
        fid, n = c["id"], 2
        while fid in ids:
            fid, n = f"{c['id']}-{n}", n + 1
        fact = {"id": fid, "category": c["category"], "product": c["product"], "plan": c.get("plan"), "claim": c["claim"],
                "value": c["value"], "keywords": c.get("keywords", []), "source_url": c["source_url"],
                "source_kind": c["source_kind"], "fetched_at": rep["checked_at"], "excerpt": c["excerpt"],
                "volatile": bool(c.get("volatile")), "status": "verified", "verified_by": {"reviewer": reviewer, "at": at},
                "human_checks": [check], "origin": {"candidate": candidate_id, "extracted_by": c.get("extracted_by", "rules")}}
        fd.setdefault("facts", []).append(fact)
        if not fd.get("fetched_at"):
            fd["fetched_at"] = rep["checked_at"]
        cd["candidates"] = [x for x in cd.get("candidates", []) if x.get("candidate_id") != candidate_id]
        atomic_write_json(_facts_path(bid), fd)
        atomic_write_json(candidates_path(bid), cd)
    Registry().audit(reviewer, "facts.candidate-confirm", f"{bid}:{fid}",
                     {"candidate": candidate_id, "note": note, "source_url": c["source_url"], "excerpt": c["excerpt"]})
    return {"brand": bid, "candidate": candidate_id, "fact": fid, "status": "verified", "check": check}


def reject_candidate(bid: str, candidate_id: str, reviewer: str, note: str = "", lock=None) -> dict:
    """Remove a suggestion (with an audit entry). It is remembered so a later extraction does not propose it again."""
    from .jobs import Registry
    if not (reviewer or "").strip():
        raise BadInput("a reviewer name is required")
    reviewer = reviewer.strip()
    with lock or LOCK:
        cd = _read(candidates_path(bid)) or {}
        c = next((x for x in cd.get("candidates", []) if x.get("candidate_id") == candidate_id), None)
        if c is None:
            raise NotFound(f"no suggested fact {candidate_id!r} for {bid}")
        cd["candidates"] = [x for x in cd["candidates"] if x.get("candidate_id") != candidate_id]
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cd.setdefault("rejected", []).append({"candidate_id": candidate_id, "id": c.get("id"), "claim": c.get("claim"),
                                              "source_url": c.get("source_url"), "excerpt": c.get("excerpt"),
                                              "reviewer": reviewer, "at": at, "note": note})
        atomic_write_json(candidates_path(bid), cd)
    Registry().audit(reviewer, "facts.candidate-reject", f"{bid}:{c.get('id')}",
                     {"candidate": candidate_id, "note": note, "source_url": c.get("source_url"), "excerpt": c.get("excerpt")})
    return {"brand": bid, "candidate": candidate_id, "status": "rejected"}


__all__ = ["analyse", "extract", "extract_for_brand", "load_candidates", "confirm_candidate", "reject_candidate",
           "suggest_wording", "candidates_path"]
