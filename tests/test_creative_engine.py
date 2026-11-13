"""Hybrid creative engine (pipeline/creative): concepts, storyboards, price discipline, LLM copy gate, brand neutrality."""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from pipeline.creative import build_storyboard, generate_concepts
from pipeline.creative.rules import validate_fields
from pipeline.errors import ConfigError
from pipeline.intelligence.facts import load_facts
from pipeline.intelligence.providers import MockProvider
from pipeline.paths import ROOT
from pipeline.storyboard import validate_storyboard

BRIEF = {"brand": "Shroti Host", "product": "WordPress Hosting", "price": "₹39/month", "audience": "Website beginners",
         "format": "short", "duration_seconds": 35, "goal": "Conversions", "cta": "Get Started",
         "request": "Create a 35-second premium YouTube Short promoting WordPress Hosting at ₹39/month. Target beginners. "
                    "Show a compelling problem, a product demonstration, an animated pricing comparison and a strong CTA."}


@pytest.fixture(scope="module")
def wp():
    return generate_concepts(dict(BRIEF), provider="none")


def _texts(sb) -> str:
    return json.dumps(sb, ensure_ascii=False)


def test_three_genuinely_different_concepts(wp):
    cs = wp["concepts"]
    assert len(cs) == 3
    for key in ("pattern", "hook_template", "demo_template", "pricing_template"):
        assert len({c[key] for c in cs}) == 3, key
    assert len({tuple(c["visual_approach"]["backdrop_rhythm"]) for c in cs}) == 3
    assert len({c["pacing"]["label"] for c in cs}) == 3
    assert all(p["ok"] and p["template_jaccard"] <= 0.6 for p in wp["distinctness"])
    for c in cs:
        assert all(r["status"] in ("PASS", "SKIP", "WARN") for r in c["rules"]), [r for r in c["rules"] if r["status"] == "FAIL"]


@pytest.mark.parametrize("provider", ["none", "mock"])
def test_every_concept_builds_a_valid_storyboard(wp, provider):
    for c in wp["concepts"]:
        sb, project, rep = build_storyboard(wp["brief"], c, provider=provider)
        errs, _ = validate_storyboard(sb)
        assert errs == [] and validate_fields(sb) == []
        bad = [r for r in rep["rules"] if r["status"] == "FAIL"]
        assert not bad, bad
        assert rep["claims"]["needs_review"] == []
        assert 5 <= len(sb["scenes"]) <= 7
        assert all(s.get("backdrop") for s in sb["scenes"])
        assert rep["creative_plan"]["music"]["mood"] in ("cinematic", "corporate", "technology", "energetic", "minimal",
                                                          "educational", "calm", "promotional")
        assert set(rep["copy_sources"]) == {s["id"] for s in sb["scenes"]}
        assert {"verified", "needs_review"} <= set(rep["claims"]) and {"status", "blocking", "reasons"} <= set(rep["review"])


def test_brief_price_mismatch_uses_verified_price(wp):
    m = wp["price"]["mismatch"]
    assert m["brief_amount"] == 39 and m["used_amount"] == 69 and m["plan"] == "WP Starter"
    assert m["fact_id"] == "wp.starter.price.monthly"
    sb, _, rep = build_storyboard(wp["brief"], wp["concepts"][0], provider="none")
    nums = {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", _texts(sb))}
    assert 39 not in nums and 69 in nums
    assert rep["review"]["blocking"] and "₹39/month" in rep["review"]["reasons"][0] and "₹69/mo" in rep["review"]["reasons"][0]
    assert all(c.get("rendered") is False for c in rep["brief_claims"]["needs_review"])
    assert any(r["id"] == "brief-price-not-rendered" and r["status"] == "PASS" for r in rep["rules"])


def test_matching_brief_price_selects_that_plan():
    res = generate_concepts({**BRIEF, "price": "₹119/month"}, provider="none")
    assert res["price"]["plan"] == "WP Business" and res["price"]["mismatch"] is None
    sb, _, rep = build_storyboard(res["brief"], res["concepts"][0], provider="none")
    assert not rep["review"]["blocking"], rep["review"]["reasons"]


@pytest.mark.parametrize("product", ["Shared Hosting", "Domains"])
def test_other_product_families(product):
    res = generate_concepts({**BRIEF, "product": product, "price": None}, provider="none")
    assert len(res["concepts"]) == 3
    sb, _, rep = build_storyboard(res["brief"], res["concepts"][0], provider="none")
    assert not [r for r in rep["rules"] if r["status"] == "FAIL"]
    assert rep["review"]["status"] == "READY_FOR_HUMAN_REVIEW"


def test_llm_invented_labels_and_prices_fall_back_to_bank(wp):
    c = wp["concepts"][0]
    ids = [sp["scene"] for sp in c["scene_plan"]]
    hook, problem, turn, demo, price, cta = ids
    # a valid model line. At the measured voice rate (WPS 2.33) ", with a seven-day money-back guarantee." leaves 2.43 s
    # of speech after the pill's cue word "seven" (over the 2.4 s design gap); a shorter tail keeps the line in sync.
    good_cta = "Get started now at shrotihost.in. Seven days, or your money back."
    script = [{
        hook: {"narration": "Browser: 39 rupees. Beginner pain is real, so stop paying more today."},
        problem: {"narration": "Setting up WordPress by hand means config files, database errors, and a lost weekend.",
                  "headline": "Beginner pain", "pill": "Beginner pain"},
        turn: {"narration": "This is Shroti Host: seamless WordPress hosting, tuned to run fast.",
               "headline": "seamless WordPress hosting, tuned to run fast."},
        demo: {"narration": "One click installs WordPress, a theme, plugins, SSL and LiteSpeed Cache. Renewal stays the same. Live."},
        price: {"narration": "WP Starter is 39 rupees a month, with free SSL, daily backups, and the same price on renewal."},
        cta: {"narration": good_cta},
    }]
    prov = MockProvider(script=script)
    sb, _, rep = build_storyboard(wp["brief"], c, provider=prov)
    src = rep["copy_sources"]
    assert src[hook]["narration"] == "bank" and any("39" in r for r in src[hook]["reasons"])
    assert src[problem]["narration"] == "bank" and any("not spoken verbatim" in r for r in src[problem]["reasons"])
    assert any("extra fields ['pill']" in r for r in src[problem]["reasons"])
    assert src[turn]["narration"] == "bank" and any("seamless" in r for r in src[turn]["reasons"])
    assert src[price]["narration"] == "bank" and any("39" in r for r in src[price]["reasons"])
    assert src[cta]["narration"] == "llm"
    text = _texts(sb)
    assert "Beginner pain" not in text and "Browser: 39" not in text and "seamless" not in text
    assert sb["scenes"][-1]["narration"] == good_cta
    assert not [r for r in rep["rules"] if r["status"] == "FAIL"]


def test_llm_line_that_drops_a_beat_word_is_rejected(wp):
    c = wp["concepts"][0]
    demo = c["scene_plan"][3]["scene"]
    assert c["scene_plan"][3]["template"] == "demo-install-flow"
    script = [{demo: {"narration": "Press one button and the whole website builds itself, neatly, while you make tea. Done."}}]
    _, _, rep = build_storyboard(wp["brief"], c, provider=MockProvider(script=script))
    assert rep["copy_sources"][demo]["narration"] == "bank"
    assert any("beats lose their spoken word" in r for r in rep["copy_sources"][demo]["reasons"])


def test_llm_hook_choice_is_recorded():
    res = generate_concepts(dict(BRIEF), provider="mock")
    assert any(c["hook_choice"]["source"] == "llm" for c in res["concepts"])
    for c in res["concepts"]:
        assert c["hook_variant"] in {h["id"] for h in c["hook_options"]}


def test_renewal_statements_need_the_fact():
    fb = load_facts("shrotihost")
    drop = {"policy.same_renewal", "comparison.typical_renewal"}
    fb2 = dataclasses.replace(fb, facts=[f for f in fb.facts if f["id"] not in drop])
    res = generate_concepts(dict(BRIEF), provider="none", facts=fb2)
    assert res["concepts"]
    for c in res["concepts"]:
        assert "problem-renewal-compare" not in c["templates"] and "price-counter-flat" not in c["templates"]
        sb, _, rep = build_storyboard(res["brief"], c, provider="none", facts=fb2)
        assert not re.search(r"renew", _texts(sb), re.I)


def test_outputs_written(tmp_path, wp):
    out = tmp_path / "eval"
    res = generate_concepts(dict(BRIEF), provider="none", out_dir=out)
    _, _, rep = build_storyboard(res["brief"], res["concepts"][1], provider="none", out_dir=out)
    for f in ("concepts.json", "concepts.md", "claims.json", "review.json", "creative-plan.json", "rules.json",
              "copy-sources.json", "storyboard-preview.md"):
        assert (out / f).exists(), f
    assert "Brief price not verified" in (out / "concepts.md").read_text()


def test_storyboard_resolves_on_the_real_timeline(wp):
    from pipeline.config import deep_merge, load_preset, load_theme
    from pipeline.timeline import build_timeline, estimated_timing
    for c in wp["concepts"]:
        sb, project, _ = build_storyboard(wp["brief"], c, provider="none")
        cfg = deep_merge(load_preset("shorts"), {k: v for k, v in project.items() if k != "$comment"})
        cfg["theme"] = load_theme("shrotihost")
        tl = build_timeline(cfg, estimated_timing(sb))
        assert tl.warnings == []
        for sc in tl.props["short"]["scenes"]:
            for b in sc["blocks"]:
                assert isinstance(b["at"], (int, float))


# ---- brand neutrality -----------------------------------------------------------------------------------
def test_no_brand_literals_in_creative_code():
    hits = []
    for p in (ROOT / "pipeline" / "creative").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"shroti|rupee|₹\d", line, re.I) and not line.startswith("CURRENCIES = "):   # ISO currency table is generic
                hits.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
    assert hits == []


def test_brand_must_be_known_and_opted_in():
    with pytest.raises(ConfigError, match="brand profile"):
        generate_concepts({**BRIEF, "brand": "Nobody Hosting Co"}, provider="none")
    with pytest.raises(ConfigError, match="creative.industry"):
        generate_concepts({**BRIEF, "brand": "ACME Demo", "brand_id": "acme-demo"}, provider="none")
    from pipeline.creative.brand import load_brand
    with pytest.raises(ConfigError, match="no brand"):
        load_brand(None, load_facts("shrotihost"))


def test_brand_values_come_from_the_profile():
    prof = json.loads((ROOT / "brands" / "shrotihost" / "brand.json").read_text())
    from pipeline.creative.brand import load_brand
    br = load_brand("shrotihost", load_facts("shrotihost"))
    assert br.industry == prof["creative"]["industry"] and br.url_cue == br.domain.split(".")[0]
    assert set(prof["creative"]["banned"]) <= set(br.banned)
