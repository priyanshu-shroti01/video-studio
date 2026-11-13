"""Unpriced industry packs, brief-driven duration windows and the software pack (launch films / product demos)."""
import pytest

from pipeline.creative.rules import DURATION, SCENES, SHORTS_MAX, windows


def test_shorts_keep_the_classic_window():
    for d in (25, 30, 33, 35, 40):
        assert windows({"duration_seconds": d}) == (DURATION, SCENES)
    assert windows({}) == (DURATION, SCENES)


def test_longer_and_flexible_briefs_get_their_own_window():
    (lo, hi), (s_lo, s_hi) = windows({"duration_seconds": 80})
    assert lo < 80 < hi and s_hi >= 9
    (lo, hi), (_, s_hi) = windows({"duration_seconds": 80, "duration_flexible": True})
    assert lo <= 48 and hi == SHORTS_MAX < 180 and s_hi >= 10      # stays a YouTube Short


def test_brief_schema_accepts_flexible_length_and_formats():
    from pipeline.intelligence.brief import parse_brief
    b, _ = parse_brief({"brand": "Video Studio", "product": "Video Studio", "duration_seconds": 80, "duration_flexible": True,
                        "formats": ["short", "landscape"]})
    assert b["duration_flexible"] is True and b["formats"] == ["short", "landscape"]


def _studio(brief=None):
    from pipeline.creative.director import studio
    from pipeline.intelligence.facts import load_facts
    b = {"brand": "Video Studio", "brand_id": "videostudio", "product": "Video Studio", "duration_seconds": 80,
         "duration_flexible": True, "cta": "Explore the code", **(brief or {})}
    return studio(b, load_facts("videostudio"))


def test_unpriced_product_has_no_plan_and_safe_placeholders():
    st = _studio()
    pf = st.pf
    assert st.pack.id == "software" and st.pack.priced is False
    assert pf.featured is None and pf.plans == [] and pf.price is None
    vals = pf.bound()
    assert vals["brand"] == "Video Studio" and "price" not in vals
    assert pf.display_url == "github.com/priyanshu-shroti01/video-studio" and pf.url_cue == "github"


def test_pricing_rule_forbids_prices_for_unpriced_products():
    from pipeline.creative.rules import check_rules
    st = _studio()
    sb = {"scenes": [{"id": "s1", "purpose": "hook", "narration": "It costs 99 a month.", "backdrop": "glow",
                      "blocks": [{"type": "price", "amount": 99, "currency": "$", "at": "@word:costs"}]}]}
    rule = next(r for r in check_rules(sb, pf=st.pf) if r["id"] == "pricing")
    assert rule["status"] == "FAIL"


def test_software_pack_copy_is_brand_neutral():
    from pipeline.creative.industries import software
    text = str(software.BANK) + str([t.describe for t in software.TEMPLATES])
    assert "Video Studio" not in text and "Shroti" not in text and "github.com" not in text.lower()


def test_footage_templates_need_the_recording_on_disk(tmp_path):
    from pipeline.creative.industries.software import clip
    st = _studio()
    pf = st.pf
    assert clip("app-tour")(pf)                                   # recorded clip exists
    pf.media = {**pf.media, "ghost": {"asset": "brands/videostudio/footage/does-not-exist.mp4"}}
    assert not clip("ghost")(pf)


def test_software_concepts_are_three_distinct_rule_passing_films():
    from pipeline.creative import generate_concepts
    brief = {"brand": "Video Studio", "brand_id": "videostudio", "product": "Video Studio", "duration_seconds": 80,
             "duration_flexible": True, "cta": "Explore the code", "audience": "Developers, creators and product teams",
             "goal": "launch", "format": "short"}
    res = generate_concepts(brief, provider="none")
    assert len(res["concepts"]) == 3, res.get("rejected")
    d = res["distinctness"]
    assert all(x["ok"] for x in (d if isinstance(d, list) else d.get("pairs", [])))
    for c in res["concepts"]:
        assert c["pricing_template"] is None
        assert not [r for r in c["rules"] if r["status"] == "FAIL"]


def test_footage_scenes_split_for_landscape():
    from pipeline.creative.director import FOOTAGE_SPLIT, footage_split
    f, t = {"type": "footage", "asset": "x.mp4"}, {"type": "pill", "text": "t"}
    assert footage_split([f, t]) == {"layout": "split", "splitAt": 1, "splitRatio": FOOTAGE_SPLIT}
    assert footage_split([t, f])["splitRatio"] == round(1 - FOOTAGE_SPLIT, 2)       # message left, recording right
    assert footage_split([f]) == {} and footage_split([t, t]) == {} and footage_split([f, t, t]) == {}



def test_schema_accepts_split_ratio_in_range_only():
    from pipeline.storyboard import validate_storyboard
    sc = {"id": "s1", "purpose": "hook", "narration": "Look at this.", "layout": "split", "splitAt": 1,
          "blocks": [{"type": "kinetic-text", "text": "Look", "at": "@word:Look"}, {"type": "pill", "text": "this", "at": "@word:this"}]}
    ok, _ = validate_storyboard({"scenes": [{**sc, "splitRatio": 0.66}]})
    bad, _ = validate_storyboard({"scenes": [{**sc, "splitRatio": 0.9}]})
    assert not [e for e in ok if "splitRatio" in e] and [e for e in bad if "splitRatio" in e]


def test_repo_sources_are_read_locally_and_cannot_escape(tmp_path):
    from pipeline.intelligence.facts import fetch
    assert "Self-launch film" in fetch("repo:docs/reports/SELF_LAUNCH_AUDIT.md")
    with pytest.raises(ValueError):
        fetch("repo:../outside.txt")


def test_rules_reject_a_scene_that_opens_on_an_empty_backdrop():
    """Iteration 2 of the launch film opened its QA scene with ~1 s of bare dark backdrop (QA: black frames)."""
    from pipeline.creative.rules import check_rules
    words = "Then it checks every single thing it made before the work is shown".split()
    late = {"scenes": [{"id": "s1", "purpose": "point", "narration": " ".join(words), "backdrop": "deep",
                        "blocks": [{"type": "pill", "text": "work", "tone": "success", "at": "@word:work"}]}]}
    rule = next(r for r in check_rules(late) if r["id"] == "scene-opens")
    assert rule["status"] == "FAIL" and "nothing on screen" in rule["detail"]        # > 2 s: rejected
    late["scenes"][0]["blocks"][0]["at"] = "@word:single"                               # ~1.1 s: reported only
    assert next(r for r in check_rules(late) if r["id"] == "scene-opens")["status"] == "WARN"
    late["scenes"][0]["blocks"][0]["at"] = "@word:Then-0.05"
    assert next(r for r in check_rules(late) if r["id"] == "scene-opens")["status"] == "PASS"


def test_a_checklist_counts_as_visible_only_from_its_first_item():
    from pipeline.creative.rules import _first_visible
    assert _first_visible({"type": "checklist", "at": 1.0, "items": [{"at": 3.0}, {"at": 4.0}]}) == 3.0
    assert _first_visible({"type": "pill", "at": 1.0}) == 1.0
    assert _first_visible({"type": "pill", "at": "@word:x"}) is None


def test_create_production_rejects_an_invalid_brief_before_creating_anything(registry, tmp_path, monkeypatch):
    import pipeline.productions as P
    from pipeline import api
    from pipeline.errors import ConfigError
    pdir = tmp_path / "productions"
    pdir.mkdir()
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", pdir)
    with pytest.raises(ConfigError):
        api.create_production("videostudio", {"brand": "Video Studio", "product": "Video Studio", "voice": {"voice": "x"}})
    assert not any(pdir.iterdir())
