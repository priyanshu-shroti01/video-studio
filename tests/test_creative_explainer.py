"""Explainer style in the hybrid creative engine (pipeline/creative/explain.py): the myth / steps / proof blueprint for
the software and web-hosting packs, the storyboard HUD it composes, caption tones, fact-bound proofs and the endings."""
import copy
import re

import pytest

from pipeline.creative import build_storyboard, generate_concepts
from pipeline.creative.explain import ORDINALS, hud_step_report, step_copies
from pipeline.creative.rules import MAX_EMPTY_OPEN, check_rules, failed, sync_report
from pipeline.intelligence.facts import load_facts
from pipeline.storyboard import validate_storyboard

VS = {"brand": "Video Studio", "product": "Video Studio", "audience": "Marketers and founders", "goal": "launch",
      "tone": "direct, myth-busting", "cta": "Explore the code", "format": "short", "duration_seconds": 33,
      "request": "An explainer: a myth crossed out, three steps on a step header, the QA score on a gauge, the cost line."}
WP = {"brand": "Shroti Host", "product": "WordPress Hosting", "price": "₹69/month", "audience": "Website beginners",
      "format": "short", "duration_seconds": 33, "goal": "Conversions", "cta": "Get Started", "tone": "direct",
      "request": "An explainer Short: a myth crossed out, three steps on a step header, a proof on a gauge, the price."}


def _explainer(brief, facts=None, provider="none"):
    res = generate_concepts(brief, provider=provider, facts=facts)
    c = next((c for c in res["concepts"] if c["blueprint"] == "explainer-steps"), None)
    assert c is not None, res["rejected"]
    sb, _, rep = build_storyboard(res["brief"], c, provider=provider, facts=facts)
    return res, c, sb, rep


@pytest.fixture(scope="module")
def vs():
    return _explainer(VS)


@pytest.fixture(scope="module")
def wp():
    return _explainer(WP)


@pytest.mark.parametrize("which", ["vs", "wp"])
def test_explainer_is_offered_first_and_passes_every_rule(which, request):
    res, c, sb, rep = request.getfixturevalue(which)
    assert res["concepts"][0]["id"] == c["id"]                     # the brief asks for an explainer: ranked first
    assert c["hud"] == "steps" and not failed(c["rules"])
    assert not failed(rep["rules"]) and rep["review"]["status"] == "READY_FOR_HUMAN_REVIEW", rep["review"]["reasons"]
    assert {r["id"] for r in rep["rules"]} >= {"hud-steps", "labels-bound", "sync-gaps", "scene-opens", "sync-numbers",
                                               "variety", "hero-every-scene", "no-repeat-hero"}
    errs, _ = validate_storyboard(sb)
    assert errs == []
    purposes = [s["purpose"] for s in sb["scenes"]]
    assert purposes[0] == "hook" and purposes[1] == "turn" and purposes[-1] == "cta"


@pytest.mark.parametrize("which", ["vs", "wp"])
def test_hud_header_and_chips_follow_the_step_scenes(which, request):
    _, _, sb, _ = request.getfixturevalue(which)
    els = {e["id"]: e for e in sb["hud"]["elements"]}
    assert els["step"]["kind"] == "header" and els["terms"]["kind"] == "chips"
    steps = [(k, s) for k, s in enumerate(sb["scenes"]) if any(e["target"] == "step" and e["op"] in ("show", "advance")
                                                              for e in s.get("hud", []))]
    assert len(steps) == len(els["step"]["steps"]) == 3
    ops = [next(e["op"] for e in s["hud"] if e["target"] == "step") for _, s in steps]
    assert ops == ["show", "advance", "advance"]
    for n, (_, s) in enumerate(steps):
        assert s["narration"].startswith(f"Step {ORDINALS[n]}")    # "{step}" was filled with the ordinal
        chip = [e for e in s["hud"] if e["target"] == "terms"]
        assert len(chip) == 1 and chip[0]["op"] == "add"
        assert re.fullmatch(r"@word:[^+\-]+", chip[0]["at"])       # on the word itself: the chip makes it a caption term
    nxt = sb["scenes"][steps[-1][0] + 1]
    assert {(e["target"], e["op"]) for e in nxt["hud"]} == {("step", "hide"), ("terms", "hide")}
    assert "hud" not in sb["scenes"][-1]
    assert hud_step_report(sb) == []


@pytest.mark.parametrize("which", ["vs", "wp"])
def test_myth_is_crossed_and_stamped_in_danger_and_the_proof_in_success(which, request):
    _, _, sb, _ = request.getfixturevalue(which)
    myth = sb["scenes"][0]
    assert [b["type"] for b in myth["blocks"]] == ["headline", "verdict"]
    assert myth["blocks"][1].get("tone", "danger") == "danger"
    cross = [e for e in myth["effects"] if e["type"] == "annotate"]
    assert cross and cross[0]["kind"] == "cross" and cross[0]["target"] == 0
    assert set(myth["captionTones"].values()) == {"danger"}
    proof = next(s for s in sb["scenes"] if any(b["type"] == "gauge" for b in s["blocks"]))
    verdict = next(b for b in proof["blocks"] if b["type"] == "verdict")
    assert verdict["tone"] == "success" and verdict["mark"] == "check"
    assert "success" in proof["captionTones"].values()


def test_gauge_values_come_from_the_facts(vs, wp):
    qa = load_facts("videostudio").by_id("evidence.qa")["value"]
    up = load_facts("shrotihost").by_id("policy.uptime_target")["value"]
    for (_, _, sb, _), want in ((vs, qa["checks"]), (wp, up["uptime_pct"])):
        g = next(b for s in sb["scenes"] for b in s["blocks"] if b["type"] == "gauge")
        assert [k["value"] for k in g["keys"]] == [want]
        assert g["keys"][0]["at"].startswith("@word:")               # the readout lands on the spoken number


@pytest.mark.parametrize("which", ["vs", "wp"])
def test_every_scene_opens_on_content(which, request):
    _, _, sb, _ = request.getfixturevalue(which)
    sy = sync_report(sb)
    assert all(r["opens_empty_s"] <= MAX_EMPTY_OPEN for r in sy["scenes"]), sy["open_violations"]
    assert sy["gap_violations"] == [] and sy["number_violations"] == []
    bds = [s["backdrop"] for s in sb["scenes"]]
    assert not any(a == "light" and b == "deep" for a, b in zip(bds, bds[1:]))


def test_a_flexible_brief_gets_a_poll_before_the_outro():
    _, c, sb, rep = _explainer({**VS, "duration_seconds": 45, "duration_flexible": True})
    assert c["templates"][-2:] == ["cta-poll", "cta-outro"] and not failed(rep["rules"])
    poll = next(b for b in sb["scenes"][-2]["blocks"] if b["type"] == "poll")
    narr = sb["scenes"][-2]["narration"].lower()
    assert all(o["text"].lower() in narr for o in poll["options"]) and "pick" not in poll   # no invented votes


def test_the_brief_chooses_the_ending():
    _, c, sb, rep = _explainer({**WP, "duration_seconds": 45, "duration_flexible": True, "ending": "comment"})
    assert c["templates"][-2] == "cta-comment-keyword" and not failed(rep["rules"])
    cc = next(b for b in sb["scenes"][-2]["blocks"] if b["type"] == "comment-cta")
    assert cc["keyword"].lower() in sb["scenes"][-2]["narration"].lower()


def test_next_episode_only_when_the_brief_names_it():
    _, c, _, _ = _explainer({**VS, "duration_seconds": 45, "duration_flexible": True, "ending": "next-episode"})
    assert "cta-next-episode" not in c["templates"]                 # nothing about a next part is promised
    nx = {"label": "Part 2", "title": "The storyboard, up close"}
    _, c, sb, rep = _explainer({**VS, "duration_seconds": 45, "duration_flexible": True, "ending": "next-episode",
                                "next_episode": nx})
    assert c["templates"][-2] == "cta-next-episode" and not failed(rep["rules"])
    ne = next(b for b in sb["scenes"][-2]["blocks"] if b["type"] == "next-episode")
    assert (ne["label"], ne["title"]) == (nx["label"], nx["title"])


def test_a_duration_fact_becomes_a_countdown_when_there_is_no_uptime_fact():
    fb = copy.deepcopy(load_facts("shrotihost"))
    fb.facts = [f for f in fb.facts if f["id"] != "policy.uptime_target"]
    _, c, sb, rep = _explainer(WP, facts=fb)
    assert "step-refund-countdown" in c["templates"] and not failed(rep["rules"])
    cd = next(b for s in sb["scenes"] for b in s["blocks"] if b["type"] == "countdown")
    assert cd["from"] == fb.by_id("policy.money_back")["value"]["days"]


def test_endings_ask_and_never_promise():
    from pipeline.creative.industries import get_pack
    lines = []
    for pid in ("software", "web-hosting"):
        bank = get_pack(pid).bank
        for t in ("cta-poll", "cta-comment-keyword", "cta-next-episode"):
            lines += [v["narration"] for fam in bank.get(t, {}).values() for v in fam]
    assert lines
    for line in lines:
        assert not re.search(r"\b(dm|we'll|we will|send you|link in|free download|giveaway)\b", line, re.I), line


def test_hud_rule_and_labels_catch_a_broken_header(vs):
    _, _, sb, rep = vs
    bad = copy.deepcopy(sb)
    bad["hud"]["elements"][0]["steps"].append("Publish")            # a step with no scene
    assert any("header steps" in p for p in hud_step_report(bad))
    labels = dict(rep["labels"])
    bad = copy.deepcopy(sb)
    ev = next(e for s in bad["scenes"] for e in s.get("hud", []) if e["op"] == "add")
    ev["text"] = "Magic"                                            # not a bound label
    rules = {r["id"]: r for r in check_rules(bad, labels=labels)}
    assert rules["labels-bound"]["status"] == "FAIL" and "Magic" in rules["labels-bound"]["detail"]
    bad = copy.deepcopy(sb)
    for s in bad["scenes"]:
        kept = [e for e in s.pop("hud", []) if e["op"] != "hide"]
        if kept:
            s["hud"] = kept
    assert "the step header is still on screen in the CTA scenes" in hud_step_report(bad)


def test_step_ordinals_follow_the_step_scenes():
    plan = [{"scene": "a"}, {"scene": "b"}, {"scene": "c"}]
    out = step_copies(plan, {"a": {"narration": "Meet it."}, "b": {"narration": "Step {step}: x."},
                             "c": {"narration": "Step {step}: y."}})
    assert [out[k]["narration"] for k in "abc"] == ["Meet it.", "Step one: x.", "Step two: y."]


def test_brief_schema_accepts_the_explainer_options():
    from pipeline.errors import ConfigError
    from pipeline.intelligence.brief import parse_brief
    b, _ = parse_brief({**VS, "ending": "poll", "next_episode": {"label": "Part 2", "title": "Up close"}})
    assert b["ending"] == "poll"
    with pytest.raises(ConfigError):
        parse_brief({**VS, "ending": "giveaway"})
    with pytest.raises(ConfigError):
        parse_brief({**VS, "next_episode": {"label": "Part 2"}})
