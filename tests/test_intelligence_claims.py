"""Brief schema + claim extraction/verification (fact discipline)."""
import pytest

from pipeline.errors import ConfigError
from pipeline.intelligence.brief import parse_brief, parse_price
from pipeline.intelligence.claims import ILLUSTRATIVE, NEEDS_REVIEW, VERIFIED, Verifier, verify_brief, verify_storyboard
from pipeline.intelligence.facts import FactBase, load_facts

DEMO = {"brand": "Shroti Host", "product": "WordPress Hosting", "price": "₹39/month", "audience": "Website beginners",
        "format": "short", "duration_seconds": 35, "goal": "Conversions", "cta": "Get Started"}
REQ = ("Create a 35-second premium YouTube Short promoting Shroti Host WordPress Hosting at ₹39/month. Target beginners. "
       "Show a compelling problem, a product demonstration, an animated pricing comparison and a strong CTA.")


def _fact(id, cat, claim, value, excerpt, product="all", plan=None, keywords=()):
    return {"id": id, "category": cat, "product": product, "plan": plan, "claim": claim, "value": value, "keywords": list(keywords),
            "source_url": "https://example.test/", "source_kind": "visible-text", "fetched_at": "2026-11-13T00:00:00Z", "excerpt": excerpt}


@pytest.fixture
def fb():
    return FactBase("acme", "Acme Host", "https://acmehost.in", "2026-11-13", [
        _fact("p.basic", "price", "Basic costs ₹49/month", {"amount": 49, "period": "month"}, "Basic ₹49 Billed monthly", "shared", "Basic"),
        _fact("p.wp", "price", "WP Lite costs ₹69/month", {"amount": 69, "period": "month"}, "WP Lite ₹69 Billed monthly", "wordpress", "WP Lite"),
        _fact("s.basic", "spec", "Basic has 10 GB NVMe", {"storage_gb": 10}, "Storage10 GB NVMe", "shared", "Basic"),
        _fact("f.ssl", "feature", "Free SSL", {}, "Free SSL Certificate", keywords=["free ssl", "ssl"]),
        _fact("pol.up", "policy", "99.9% uptime target", {"uptime_pct": 99.9}, "99.9% uptime target", keywords=["uptime"]),
        _fact("url", "url", "site", {"domain": "acmehost.in"}, "https://acmehost.in", "company", keywords=["acmehost.in"]),
    ], [])


def test_brief_schema_and_requirements():
    b, w = parse_brief(DEMO, REQ)
    assert b["requirements"] == ["problem", "demonstration", "pricing-comparison", "cta"]
    assert b["price_parsed"] == {"amount": 39, "currency": "INR", "period": "month", "text": "₹39/month"}
    assert b["brand_id"] == "shrotihost" and b["platform"] == "youtube-shorts" and "premium" in b["tone"]
    assert w == []
    with pytest.raises(ConfigError):
        parse_brief({"product": "x"})                       # brand missing
    with pytest.raises(ConfigError):
        parse_brief({**DEMO, "format": "square"})           # bad enum
    with pytest.raises(ConfigError):
        parse_brief({**DEMO, "duration_seconds": 5})        # below minimum
    with pytest.raises(ConfigError):
        parse_brief({**DEMO, "surprise": 1})                # unknown field
    _, w = parse_brief({**DEMO, "duration_seconds": 40}, REQ)
    assert any("35s" in x for x in w)
    assert parse_price("49 rupees a year")["period"] == "year"


def test_invented_price_needs_review(fb):
    v = Verifier(fb, None)
    [c] = [x for x in v.verify_text("Hosting from just ₹29/mo.", "s.narration") if x.kind == "price"]
    assert c.status == NEEDS_REVIEW and c.origin == "generated" and "closest" in c.reason
    [ok] = [x for x in v.verify_text("Basic plan at 49 rupees a month", "s") if x.kind == "price"]
    assert ok.status == VERIFIED and ok.fact_ids == ["p.basic"]


def test_spelled_price_and_product_mismatch(fb):
    v = Verifier(fb, None)
    [c] = [x for x in v.verify_text("WordPress hosting for forty-nine rupees a month", "s") if x.kind == "price"]
    assert c.status == NEEDS_REVIEW and "not" in c.reason        # ₹49 exists, but only as a shared plan price
    [ok] = [x for x in v.verify_text("WordPress hosting for sixty-nine rupees a month", "s") if x.kind == "price"]
    assert ok.status == VERIFIED


def test_brief_price_not_on_site_is_flagged_as_brief(fb):
    b, _ = parse_brief({**DEMO, "brand": "Acme Host", "price": "₹39/month"})
    rep = verify_brief(b, fb)
    assert rep["blocking"] and rep["needs_review"][0]["origin"] == "brief"
    assert "owner must confirm" in rep["needs_review"][0]["reason"]


def test_multiplier_guarantee_superlative_and_domains(fb):
    v = Verifier(fb, None)
    cs = v.verify_text("Other hosts triple the price. We're the fastest, with a 99.9% uptime guarantee. Visit acmehost.in or yourbrand.in",
                       "s")
    st = {c.text.lower(): c.status for c in cs}
    assert st["triple"] == NEEDS_REVIEW
    assert st["fastest"] == NEEDS_REVIEW
    assert st["99.9%"] == NEEDS_REVIEW                       # site says target, not guarantee
    assert st["acmehost.in"] == VERIFIED and st["yourbrand.in"] == ILLUSTRATIVE
    assert all(c.status == VERIFIED for c in v.verify_text("Free SSL on every plan", "s"))


def test_unknown_plan_and_spec(fb):
    v = Verifier(fb, None)
    cs = v.verify_text("Pick the Pro plan with 500 GB NVMe", "s")
    assert {c.kind: c.status for c in cs}["plan"] == NEEDS_REVIEW
    assert {c.kind: c.status for c in cs}["quantity"] == NEEDS_REVIEW
    assert {c.kind: c.status for c in v.verify_text("Basic plan: 10 GB NVMe", "s")}["quantity"] == VERIFIED


def test_block_fields_are_checked(fb):
    sb = {"scenes": [{"id": "a", "purpose": "hook", "narration": "Hello.", "blocks": [
        {"type": "plans", "plans": [{"name": "Basic", "price": "₹49", "period": "/mo"}, {"name": "Mega", "price": "₹999", "period": "/mo"}]},
        {"type": "price", "currency": "₹", "amount": 19, "period": "/mo"},
        {"type": "compare-rows", "rows": [{"label": "Speed", "value": "10x faster", "at": 0}]}]}]}
    rep = verify_storyboard(sb, fb)
    bad = {c["text"] for c in rep["needs_review"]}
    assert {"₹999/mo", "₹19/mo", "10x"} <= bad and "Mega plan" in bad
    assert rep["blocking"]


def test_real_fact_base_has_no_39_rupee_wordpress_price():
    fb = load_facts("shrotihost")
    assert len(fb.facts) >= 40
    assert all(f["excerpt"] and f["source_url"].startswith("https://shrotihost.in") and f["fetched_at"] for f in fb.facts)
    assert not any(f["category"] == "price" and f["value"].get("amount") == 39 for f in fb.facts)
    assert fb.not_found and "₹39" in fb.not_found[0]["claim"]
    b, _ = parse_brief(DEMO, REQ)
    rep = verify_brief(b, fb)
    assert rep["blocking"] and rep["needs_review"][0]["kind"] == "price"
    assert "wp.starter.price.monthly" in rep["needs_review"][0]["fact_ids"]
