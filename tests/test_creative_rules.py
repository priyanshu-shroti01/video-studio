"""Creative rules (pipeline/creative/rules.py): composition, demo/pricing, anchoring and sync are enforced."""
from __future__ import annotations

import copy

import pytest

from pipeline.creative import build_storyboard, generate_concepts
from pipeline.creative.copybank import word_count
from pipeline.creative.director import build_scene, studio
from pipeline.creative.rules import check_rules, sync_report
from pipeline.creative.claims_v2 import verify
from pipeline.creative.templates import Ctx
from pipeline.intelligence.brief import parse_brief
from pipeline.intelligence.facts import load_facts

BRIEF = {"brand": "Shroti Host", "product": "WordPress Hosting", "format": "short", "duration_seconds": 35, "cta": "Get Started"}


@pytest.fixture(scope="module")
def good():
    res = generate_concepts(dict(BRIEF), provider="none")
    sb, _, rep = build_storyboard(res["brief"], res["concepts"][0], provider="none")
    return sb


def status(sb, rid):
    return {r["id"]: r["status"] for r in check_rules(sb)}[rid]


def test_good_storyboard_passes_all(good):
    # advisory WARN is allowed only for scene openings (graded rule); everything else must PASS
    off = [r for r in check_rules(good) if r["status"] != "PASS" and not (r["id"] == "scene-opens" and r["status"] == "WARN")]
    assert not off, off


def test_empty_scene_is_rejected(good):
    sb = copy.deepcopy(good)
    sb["scenes"][1]["blocks"] = [{"type": "headline", "size": "l", "words": "a lost weekend", "at": "@word:lost"}]
    assert status(sb, "hero-every-scene") == "FAIL"


def test_low_density_is_rejected(good):
    sb = copy.deepcopy(good)
    for s in sb["scenes"]:
        s["blocks"] = s["blocks"][:1]
    assert status(sb, "density") == "FAIL"


def test_repetition_is_rejected(good):
    sb = copy.deepcopy(good)
    sb["scenes"][2]["backdrop"] = sb["scenes"][1]["backdrop"]
    assert status(sb, "no-repeat-backdrop") == "FAIL"
    sb = copy.deepcopy(good)
    sb["scenes"][2]["blocks"] = copy.deepcopy(sb["scenes"][1]["blocks"])
    sb["scenes"][2]["narration"] = sb["scenes"][1]["narration"]
    assert status(sb, "no-repeat-hero") == "FAIL"


def test_missing_demo_is_rejected_and_a_loading_browser_does_not_count(good):
    sb = copy.deepcopy(good)
    demo = next(s for s in sb["scenes"] if any(b["type"] == "install-flow" for b in s["blocks"]))
    w = demo["narration"].split()[0]
    demo["blocks"] = [{"type": "browser", "url": "your-website.in", "at": f"@word:{w}", "loadUntil": f"@word:{w}+2"},
                      {"type": "pill", "text": "Loading", "tone": "brand", "at": f"@word:{w}"}]
    assert status(sb, "product-demo") == "FAIL"


def test_missing_pricing_is_rejected(good):
    sb = copy.deepcopy(good)
    sc = next(s for s in sb["scenes"] if any(b["type"] == "plan-card" for b in s["blocks"]))
    sc["blocks"] = [b for b in sc["blocks"] if b["type"] != "plan-card"] + [
        {"type": "checklist", "items": [{"text": "Free SSL", "at": "@word:SSL"}, {"text": "Daily backups", "at": "@word:daily"}],
         "at": "@word:SSL"}]
    assert status(sb, "pricing") == "FAIL"


def test_scene_start_anchors_are_rejected(good):
    sb = copy.deepcopy(good)
    sb["scenes"][0]["blocks"][0]["at"] = "@start+0.3"
    assert status(sb, "beats-on-words") == "FAIL"


def test_price_shown_before_it_is_spoken_is_rejected(good):
    sb = copy.deepcopy(good)
    sc = next(s for s in sb["scenes"] if any(b["type"] == "plan-card" for b in s["blocks"]))
    card = next(b for b in sc["blocks"] if b["type"] == "plan-card")
    card["at"] = "@word:" + sc["narration"].split()[0]       # card (with ₹69) at the first word, before "69"
    rep = sync_report(sb)
    assert rep["number_violations"] and status(sb, "sync-numbers") == "FAIL"


def test_long_silent_stretch_is_rejected(good):
    sb = copy.deepcopy(good)
    sc = next(s for s in sb["scenes"] if any(b["type"] == "install-flow" for b in s["blocks"]))
    flow = next(b for b in sc["blocks"] if b["type"] == "install-flow")
    first = sc["narration"].split()[0]
    for st in flow["steps"]:
        st["at"] = f"@word:{first}"
    flow["doneAt"] = f"@word:{first}+0.2"
    sc["blocks"] = [flow]
    assert status(sb, "sync-gaps") == "FAIL"


def test_invented_label_is_rejected(good):
    sb = copy.deepcopy(good)
    from pipeline.creative.director import compose
    res = generate_concepts(dict(BRIEF), provider="none")
    st = studio(res["brief"], load_facts("shrotihost"))
    c = res["concepts"][0]
    from pipeline.creative.api import _bank_copies
    sb, ctx, _ = compose(c, st, _bank_copies(c, st))
    sb["scenes"][0]["blocks"][0]["text"] = "Beginner pain"
    rules = {r["id"]: r for r in check_rules(sb, labels=ctx.labels)}
    assert rules["labels-bound"]["status"] == "FAIL" and "Beginner pain" in rules["labels-bound"]["detail"]


@pytest.mark.parametrize("product", ["WordPress Hosting", "Shared Hosting", "Domains"])
def test_every_bank_line_is_in_budget_in_sync_and_verified(product):
    """The professional copy bank itself: every variant x template x family."""
    b, _ = parse_brief({"brand": "Shroti Host", "product": product})
    fb = load_facts("shrotihost")
    st = studio(b, fb)
    n = 0
    for t in st.lib.values():
        if not t.available(st.pf):
            continue
        for v in st.variants(t.id):
            n += 1
            assert t.words[0] <= word_count(v["narration"]) <= t.words[1], (t.id, v["id"])
            sc, _ = build_scene(t, t.role, "s1", v, Ctx(st.pf, fb, st.pack), t.backdrops[0])
            sy = sync_report({"scenes": [sc]})
            assert not sy["gap_violations"] and not sy["number_violations"], (t.id, v["id"], sy)
            cl = verify({"scenes": [sc]}, fb, st.tb)
            assert cl["needs_review"] == [], (t.id, v["id"], cl["needs_review"])
    assert n >= 30


def test_template_catalogue():
    b, _ = parse_brief({"brand": "Shroti Host", "product": "WordPress Hosting"})
    st = studio(b, load_facts("shrotihost"))
    assert len(st.lib) >= 18
    generic = {t.id for t in st.lib.values() if t.generic}
    assert {"hook-kinetic-spotlight", "price-plan-card", "proof-feature-checklist", "cta-outro"} <= generic
    assert {"demo-install-flow", "proof-server-stack", "demo-domain-search"} <= set(st.lib) - generic
    heroes = {t.hero for t in st.lib.values()}
    assert {"plan-card", "install-flow", "server-stack", "logo-sting", "domain-input", "dashboard", "outro", "kinetic-text"} <= heroes
