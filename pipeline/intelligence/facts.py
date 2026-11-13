"""Verified brand facts (knowledge/<brand>/facts.json) and a re-check against the live public site.

A fact is only usable if its verbatim excerpt was found on its source page. `refresh()` re-fetches the
pages (plain GET with a normal browser User-Agent; nothing about the project is sent), re-checks every
excerpt and reports facts that disappeared, plus whether brief-supplied claims (e.g. a price) appear."""
from __future__ import annotations

import html.parser
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigError
from ..paths import ROOT

KNOWLEDGE_DIR = ROOT / "knowledge"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")


@dataclass
class FactBase:
    brand_id: str
    brand_name: str
    site: str
    fetched_at: str
    facts: list[dict]
    not_found: list[dict]
    path: Path | None = None

    def by_id(self, fid: str) -> dict | None:
        return next((f for f in self.facts if f["id"] == fid), None)

    def prices(self) -> list[dict]:
        return [f for f in self.facts if f["category"] == "price"]

    def plan_names(self) -> list[str]:
        return sorted({f["plan"] for f in self.facts if f.get("plan")}, key=len, reverse=True)

    def domain(self) -> str:
        f = self.by_id("company.url")
        return f["value"]["domain"] if f else re.sub(r"^https?://", "", self.site).strip("/")

    def keyword_index(self) -> list[tuple[str, str]]:
        """(lowercase phrase, fact id), longest phrases first."""
        idx = [(k.lower(), f["id"]) for f in self.facts for k in f.get("keywords", [])]
        return sorted(idx, key=lambda x: -len(x[0]))

    def for_prompt(self, product_hint: str = "", limit: int = 60) -> str:
        """Compact fact sheet for an LLM prompt: id + claim, product-relevant first."""
        wp = "wordpress" in product_hint.lower()
        def rel(f):
            p = f.get("product", "all")
            return 0 if (wp and p == "wordpress") or (not wp and p == "shared") else 1 if p in ("all", "company") else 2
        fs = sorted(self.facts, key=lambda f: (rel(f), f["category"] != "price"))
        return "\n".join(f"- [{f['id']}] {f['claim']}" for f in fs[:limit])


def load_facts(brand_id: str, path: str | Path | None = None) -> FactBase:
    p = Path(path) if path else KNOWLEDGE_DIR / brand_id / "facts.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"no verified facts for brand {brand_id!r} ({p}); every claim will be NEEDS_REVIEW") from e
    return FactBase(d.get("brand", brand_id), d.get("brand_name", brand_id), d.get("site", ""), d.get("fetched_at", ""),
                    d.get("facts", []), d.get("not_found", []), p)


def empty_facts(brand_id: str, brand_name: str) -> FactBase:
    return FactBase(brand_id, brand_name, "", "", [], [], None)


# ---------------------------------------------------------------------------------------------
class _Text(html.parser.HTMLParser):
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br", "section", "span", "button", "a", "td", "th"}

    def __init__(self):
        super().__init__(); self.out: list[str] = []; self.skip = 0

    def handle_starttag(self, t, a):
        if t in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if t in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, t):
        if t in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def page_text(html: str) -> str:
    p = _Text(); p.feed(html)
    return _norm(" ".join(x.strip() for x in "".join(p.out).split("\n") if x.strip()))


REPO_PREFIX = "repo:"      # local evidence, e.g. "repo:docs/reports/X.md" or a job's QA report (not yet public)


def read_repo_source(url: str) -> str:
    """Text of a repository file named by a `repo:` source. Paths must stay inside the repository."""
    p = (ROOT / url[len(REPO_PREFIX):]).resolve()
    if ROOT.resolve() not in p.parents:
        raise ValueError(f"source outside the repository: {url}")
    return p.read_text(encoding="utf-8")


def fetch(url: str, timeout: float = 45.0) -> str:
    if url.startswith(REPO_PREFIX):
        return read_repo_source(url)
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml",
                                               "Accept-Language": "en-IN,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - public brand site, fixed URLs from facts.json
        return r.read().decode("utf-8", errors="replace")


def refresh(fb: FactBase, *, claims: list[str] | None = None, out_dir: Path | None = None, fetcher=fetch) -> dict:
    """Re-fetch every source page, re-verify each excerpt, and search for extra claim strings (e.g. '₹39').
    Returns a report; does not modify facts.json (a human decides)."""
    urls = sorted({f["source_url"] for f in fb.facts})
    pages, errors = {}, {}
    for u in urls:
        try:
            raw = fetcher(u)
            pages[u] = {"text": page_text(raw), "raw": _norm(raw.replace('\\"', '"'))}
        except Exception as e:  # noqa: BLE001 - reported per URL
            errors[u] = str(e)
    ok, stale, unchecked = [], [], []
    for f in fb.facts:
        pg = pages.get(f["source_url"])
        if pg is None:
            unchecked.append(f["id"]); continue
        hay = pg["raw"] if f.get("source_kind") == "page-data" else pg["text"]
        (ok if _norm(f["excerpt"]) in hay else stale).append(f["id"])
    found = {}
    for c in claims or []:
        hits = [u for u, pg in pages.items() if c in pg["text"]]
        found[c] = hits
    rep = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pages": urls, "fetch_errors": errors,
           "verified": len(ok), "stale": stale, "unchecked": unchecked, "claim_search": found,
           "status": "OK" if not stale and not errors else "NEEDS_REVIEW"}
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        Path(out_dir, "facts-refresh.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep
