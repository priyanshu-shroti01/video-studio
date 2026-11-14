"""Suggested facts (pipeline/fact_extract.py): deterministic candidates from saved pages, verbatim excerpts that
the existing refresh() finds, nothing verified automatically, and the human confirm / reject flow. Offline."""
import json
import shutil
import uuid
from pathlib import Path

import pytest

from pipeline import fact_extract as X
from pipeline.errors import NotFound, PipelineError, StateError
from pipeline.intelligence import facts as F

SITES = Path(__file__).parent / "fixtures" / "sites"
DESI = {"https://desihost.example/": "desi-hosting-home.html", "https://desihost.example/hosting": "desi-hosting-plans.html"}
SAAS = {"https://flowboard.example/pricing": "saas-pricing.html"}


def page(name: str) -> str:
    return (SITES / name).read_text(encoding="utf-8")


def fetcher(mapping: dict, log: list | None = None):
    def f(url, timeout=30.0):
        if log is not None:
            log.append(url)
        if url not in mapping:
            raise OSError(f"404 {url}")
        return page(mapping[url]).encode(), "text/html"          # brand_init's (bytes, content-type) shape
    return f


def by(cands, **kw):
    return [c for c in cands if all(c.get(k) == v for k, v in kw.items())]


@pytest.fixture
def desi():
    return X.extract({"home": "https://desihost.example/", "hosting": "https://desihost.example/hosting"},
                     site="https://desihost.example/", fetch=fetcher(DESI), delay=0)["candidates"]


@pytest.fixture
def saas():
    return X.extract({"pricing": "https://flowboard.example/pricing"}, site="https://flowboard.example/",
                     fetch=fetcher(SAAS), delay=0)["candidates"]


# ---- extraction ------------------------------------------------------------------------------------------
def test_rupee_plan_prices_with_plan_names_period_and_billing(desi):
    prices = {c["plan"]: c for c in by(desi, category="price") if c["plan"]}
    assert set(prices) == {"Starter", "Business"}
    assert prices["Starter"]["value"] == {"amount": 69, "currency": "INR", "period": "month", "billing": "monthly"}
    assert prices["Business"]["value"] == {"amount": 1499, "currency": "INR", "period": "year", "billing": "annual"}
    assert prices["Starter"]["id"] == "hosting.starter.price.monthly" and prices["Starter"]["product"] == "hosting"
    assert prices["Starter"]["excerpt"].startswith("Starter ") and "Billed monthly" in prices["Starter"]["excerpt"]
    frm = by(desi, id="from_price")[0]
    assert frm["value"] == {"amount": 69, "currency": "INR", "period": "month", "from": True}
    assert frm["claim"] == "Prices start from ₹69/mo"
    amounts = {c["value"]["amount"] for c in by(desi, category="price")}
    assert 149 not in amounts            # struck-through old price
    assert 500 not in amounts            # "Save ₹500" is not a price
    assert 5 not in amounts              # JS-only data in <script> is never read


def test_rupee_specs_and_claims(desi):
    vals = {(c["plan"], c["kind"]): c["value"] for c in desi}
    assert vals[("Starter", "storage")] == {"storage_gb": 10, "type": "NVMe"}
    assert vals[("Business", "storage")] == {"storage_gb": 50, "type": "NVMe"}
    assert vals[("Starter", "websites")] == {"websites": 1} and vals[("Business", "websites")] == {"websites": 5}
    assert vals[("Starter", "bandwidth")] == {"bandwidth": "unmetered"} and vals[("Business", "ram")] == {"ram_gb": 2}
    assert vals[("Business", "free_domain")] == {"free_domain": True, "first_year_only": True}
    assert vals[(None, "money_back")] == {"days": 30}
    assert vals[(None, "uptime")] == {"uptime_pct": 99.9, "kind": "guarantee"}
    assert vals[(None, "free_ssl")] == {"ssl": "free"} and vals[(None, "backups")] == {"backups": "daily"}
    assert vals[(None, "support_247")] == {"support": "24/7"}
    url = by(desi, id="company.url")[0]
    assert url["value"] == {"domain": "desihost.example"} and url["source_kind"] == "page-data"
    assert not any(c["plan"] == "Web hosting that just works" for c in desi)   # the page's h1 is not a plan


def test_domain_prices_are_labelled_by_their_tld(desi):
    first, renew = by(desi, id="domain.in.price.first_year")[0], by(desi, id="domain.in.price.renewal")[0]
    assert first["value"] == {"amount": 699, "currency": "INR", "period": "year", "domain_tld": ".in"}
    assert renew["value"] == {"amount": 899, "currency": "INR", "period": "year", "domain_tld": ".in", "renewal": True}
    assert renew["excerpt"] == ".in ₹699/yr Renews ₹899/yr" and renew["match"] == "₹899/yr" and renew["product"] == "domains"


def test_dollar_saas_pricing(saas):
    p = {c["plan"]: c["value"] for c in by(saas, category="price")}
    assert p == {"Basic": {"amount": 9.99, "currency": "USD", "period": "month"},
                 "Team": {"amount": 12, "currency": "USD", "period": "month", "per": "user", "billing": "annual"}}
    assert "Enterprise" not in p                                     # "Contact sales" has no price
    vals = {(c["plan"], c["kind"]): c["value"] for c in saas}
    assert vals[("Basic", "projects")] == {"projects": 5} and vals[("Team", "projects")] == {"projects": "unlimited"}
    assert vals[("Basic", "users")] == {"users": 2} and vals[("Team", "storage")] == {"storage_gb": 100}
    assert vals[(None, "free_trial")] == {"trial_days": 14}
    assert not any(c["value"].get("amount") in (20, 99) for c in saas)  # "$20 off" and a data-attribute price


def test_excerpts_are_verbatim_and_pass_refresh(desi, saas):
    for cands, mapping in ((desi, DESI), (saas, SAAS)):
        fb = F.FactBase("t", "T", "", "", [{k: c[k] for k in ("id", "source_url", "source_kind", "excerpt")} for c in cands], [])
        rep = F.refresh(fb, fetcher=lambda u, m=mapping: page(m[u]))
        assert rep["stale"] == [] and rep["verified"] == len(cands) and rep["status"] == "OK", rep
        for c in cands:
            a, b = c["highlight"]
            assert c["excerpt"][a:b] == c["match"] and c["match"]
            if c["category"] in ("price", "spec") and not isinstance(next(iter(c["value"].values())), str):
                assert any(ch.isdigit() for ch in c["match"]), c          # the number is what is highlighted


def test_nothing_is_ever_verified(desi, saas):
    for c in desi + saas:
        assert c["status"] == "NEEDS_REVIEW" and "verified_by" not in c and "human_checks" not in c
        assert c["candidate_id"].startswith("c") and c["id"] and c["claim"] and c["source_url"].startswith("https://")
    assert len({c["candidate_id"] for c in desi}) == len(desi) and len({c["id"] for c in desi}) == len(desi)


def test_fetching_is_polite_and_limited():
    log, sleeps = [], []
    pages = {"home": "https://desihost.example/", **{f"p{i}": f"https://desihost.example/p{i}" for i in range(9)},
             "hosting": "https://desihost.example/hosting"}
    res = X.extract(pages, site="https://desihost.example/", fetch=fetcher(DESI, log), max_pages=3, delay=0.25,
                    sleep=sleeps.append, prefetched={"https://desihost.example/": page(DESI["https://desihost.example/"])})
    assert len(log) + 1 <= 3 and "https://desihost.example/" not in log       # home came from the prefetch
    assert log[0] == "https://desihost.example/hosting"                       # pricing-like pages first
    assert sleeps == [0.25] * (len(log) - 1)
    assert set(res["fetch_errors"]) == set(log) - {"https://desihost.example/hosting"}


# ---- storage, confirm, reject -----------------------------------------------------------------------------
@pytest.fixture
def kb(tmp_path, monkeypatch, registry):
    monkeypatch.setattr(F, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    bid = "zzfx"
    d = tmp_path / "knowledge" / bid
    d.mkdir(parents=True)
    facts = {"brand": bid, "brand_name": "DesiHost", "site": "https://desihost.example/", "fetched_at": "",
             "pages": {"home": "https://desihost.example/", "hosting": "https://desihost.example/hosting"},
             "facts": [], "not_found": []}
    (d / "facts.json").write_text(json.dumps(facts))
    return bid, d


def test_extract_for_brand_writes_candidates_not_facts(kb):
    bid, d = kb
    before = (d / "facts.json").read_text()
    r = X.extract_for_brand(bid, fetch=fetcher(DESI), delay=0)
    assert r["count"] > 10 and r["file"] == f"knowledge/{bid}/candidates.json"
    assert (d / "facts.json").read_text() == before
    doc = json.loads((d / "candidates.json").read_text())
    assert all(c["status"] == "NEEDS_REVIEW" for c in doc["candidates"]) and doc["rejected"] == []


def _starter(bid):
    return next(c for c in X.load_candidates(bid)["candidates"] if c["id"] == "hosting.starter.price.monthly")


def test_confirm_needs_a_person_and_a_fresh_recheck(kb):
    bid, d = kb
    X.extract_for_brand(bid, fetch=fetcher(DESI), delay=0)
    c = _starter(bid)
    live = lambda u: page(DESI[u])                                    # noqa: E731
    with pytest.raises(PipelineError):
        X.confirm_candidate(bid, c["candidate_id"], "Priyanshu", confirm=False, fetcher=live)
    with pytest.raises(PipelineError):
        X.confirm_candidate(bid, c["candidate_id"], "  ", confirm=True, fetcher=live)
    with pytest.raises(NotFound):
        X.confirm_candidate(bid, "cnope", "Priyanshu", confirm=True, fetcher=live)
    changed = lambda u: page(DESI[u]).replace(">69<", ">79<")         # noqa: E731 - the price changed on the site
    with pytest.raises(StateError, match="no longer on the page"):
        X.confirm_candidate(bid, c["candidate_id"], "Priyanshu", confirm=True, fetcher=changed)
    assert json.loads((d / "facts.json").read_text())["facts"] == []

    r = X.confirm_candidate(bid, c["candidate_id"], "Priyanshu", confirm=True, note="seen on /hosting", fetcher=live)
    assert r["fact"] == "hosting.starter.price.monthly" and r["status"] == "verified"
    fact = json.loads((d / "facts.json").read_text())["facts"][0]
    assert fact["excerpt"] == c["excerpt"] and fact["value"] == c["value"] and fact["verified_by"]["reviewer"] == "Priyanshu"
    assert fact["human_checks"][0]["note"] == "seen on /hosting" and fact["origin"]["candidate"] == c["candidate_id"]
    assert not any(x["candidate_id"] == c["candidate_id"] for x in X.load_candidates(bid)["candidates"])
    fb = F.load_facts(bid, d / "facts.json")
    assert F.refresh(fb, fetcher=live)["verified"] == 1                  # the existing re-check agrees
    from pipeline.jobs import Registry
    with Registry().conn() as con:
        rows = con.execute("SELECT actor, action, subject FROM audit_log WHERE action LIKE 'facts.candidate%'").fetchall()
    assert [tuple(x) for x in rows] == [("Priyanshu", "facts.candidate-confirm", f"{bid}:hosting.starter.price.monthly")]
    X.extract_for_brand(bid, fetch=fetcher(DESI), delay=0)               # already a fact: not suggested again
    assert not any(x["id"].startswith("hosting.starter.price") for x in X.load_candidates(bid)["candidates"])


def test_reject_removes_and_is_remembered(kb):
    bid, d = kb
    X.extract_for_brand(bid, fetch=fetcher(DESI), delay=0)
    c = _starter(bid)
    with pytest.raises(PipelineError):
        X.reject_candidate(bid, c["candidate_id"], "")
    r = X.reject_candidate(bid, c["candidate_id"], "Priyanshu", "wrong plan")
    assert r["status"] == "rejected"
    doc = X.load_candidates(bid)
    assert not any(x["candidate_id"] == c["candidate_id"] for x in doc["candidates"])
    assert doc["rejected"][0]["reviewer"] == "Priyanshu" and doc["rejected"][0]["note"] == "wrong plan"
    with pytest.raises(NotFound):
        X.reject_candidate(bid, c["candidate_id"], "Priyanshu")
    X.extract_for_brand(bid, fetch=fetcher(DESI), delay=0)
    assert not any(x["candidate_id"] == c["candidate_id"] for x in X.load_candidates(bid)["candidates"])
    assert json.loads((d / "facts.json").read_text())["facts"] == []
    from pipeline.jobs import Registry
    with Registry().conn() as con:
        rows = con.execute("SELECT actor, action FROM audit_log WHERE action='facts.candidate-reject'").fetchall()
    assert [tuple(x) for x in rows] == [("Priyanshu", "facts.candidate-reject")]


def test_llm_may_only_reword_claims(desi):
    from pipeline.intelligence.providers import MockProvider
    a, b = desi[1], desi[2]
    va, ea = json.dumps(a["value"]), a["excerpt"]
    script = [{"items": [{"candidate_id": a["candidate_id"], "claim": "Plans start at ₹69 a month"},
                         {"candidate_id": b["candidate_id"], "claim": "Refunds within 45 days"}]}]   # 45: not on the page
    n = X.suggest_wording(desi, MockProvider(script=script))
    assert n == 1 and a["claim"] == "Plans start at ₹69 a month" and a["claim_by"].startswith("llm:")
    assert json.dumps(a["value"]) == va and a["excerpt"] == ea and a["status"] == "NEEDS_REVIEW"
    assert "45" not in b["claim"]


def test_brand_init_proposes_candidates_but_no_facts():
    from pipeline import brand_init as BI
    from pipeline.paths import ROOT
    bid = f"zzfx{uuid.uuid4().hex[:6]}"
    home = page(DESI["https://desihost.example/"]).encode()
    try:
        r = BI.init_brand(bid, "https://desihost.example", industry="web-hosting",
                          fetch=lambda u, timeout=30.0: (home, "text/html") if u.endswith(".example/") else
                          (page("desi-hosting-plans.html").encode(), "text/html"))
        assert r["suggested_facts"] > 5
        k = ROOT / "knowledge" / bid
        assert json.loads((k / "facts.json").read_text())["facts"] == []
        cands = json.loads((k / "candidates.json").read_text())["candidates"]
        assert any(c["id"] == "hosting.starter.price.monthly" for c in cands)
        assert all(c["status"] == "NEEDS_REVIEW" for c in cands)
    finally:
        for d in (ROOT / "brands" / bid, ROOT / "public/brands" / bid, ROOT / "knowledge" / bid):
            shutil.rmtree(d, ignore_errors=True)
