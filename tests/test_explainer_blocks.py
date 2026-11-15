"""v3 explainer blocks (pipeline/explainer.py): validation, `@word:` anchors, the numbers rule, sound cues, the verdict-tint
photosensitivity budget, hero visuals and the fixture storyboard that the engine fixtures are built from."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pipeline import effects as FX
from pipeline import explainer as XB
from pipeline.contract import BLOCK_TYPES, CONTRACT_VERSION, TIME_KEYS
from pipeline.storyboard import HERO_BLOCKS, auto_sfx, validate_storyboard
from pipeline.sync_check import NUM, evaluate

ROOT = Path(__file__).resolve().parent.parent
GOOD = {
    "gauge": {"type": "gauge", "label": "Speed score", "at": "@word:score", "keys": [{"at": "@word:41", "value": 41},
              {"at": "@word:92", "value": 92, "dur": 1.0}], "zones": [{"to": 49, "tone": "danger"}, {"to": 100, "tone": "success"}]},
    "countdown": {"type": "countdown", "from": 7, "decimals": 1, "suffix": "s", "at": "@word:7"},
    "chat-thread": {"type": "chat-thread", "messages": [{"side": "left", "name": "Maya", "text": "Is it down?", "time": "9:41",
                                                       "at": "@word:down"}, {"side": "right", "text": "On it.", "at": "@word:fix"}]},
    "notification": {"type": "notification", "items": [{"app": "Uptime", "title": "Site is down", "body": "Again.", "icon": "zap",
                                                        "at": "@word:down"}]},
    "term-reveal": {"type": "term-reveal", "kicker": "This is called", "term": "Bounce rate", "termAt": "@word:bounce"},
    "verdict": {"type": "verdict", "text": "Rejected", "at": "@word:rejected", "sfx": "impact"},
    "comment-cta": {"type": "comment-cta", "prompt": "Want it?", "keyword": "SPEED", "typeStart": "@word:SPEED",
                    "sendAt": "@word:SPEED+0.6"},
    "poll": {"type": "poll", "question": "Which one?", "options": [{"text": "Speed", "at": "@word:speed"},
                                                                 {"text": "Design", "at": "@word:design"}], "pick": 0,
             "pickAt": "@word:design+0.4"},
    "next-episode": {"type": "next-episode", "label": "Part 2", "title": "Fixing images", "at": "@word:2"},
}
NARRATION = ("Your speed score is 41, then 92. You have 7 seconds. Is it down? I will fix it. This is called the bounce rate. "
             "Rejected. Comment SPEED. Speed or design? Part 2 is next.")


def _errors(block: dict) -> list[str]:
    sb = {"scenes": [{"id": "s1", "purpose": "hook", "narration": NARRATION, "blocks": [block]},
                     {"id": "s2", "purpose": "cta", "narration": "Bye.", "blocks": [{"type": "logo", "variant": "onDark"}]}]}
    errs, _ = validate_storyboard(sb)
    return errs


def test_contract_v3_lists_every_block_and_time_key():
    assert CONTRACT_VERSION == 3
    assert set(XB.TYPES) <= BLOCK_TYPES
    assert {"termAt", "subAt", "typeStart", "sendAt", "pickAt"} <= TIME_KEYS
    ts = (ROOT / "src/engine/types.ts").read_text()
    for t in XB.TYPES:
        assert f"type: '{t}'" in ts


@pytest.mark.parametrize("ty", list(GOOD))
def test_valid_blocks_pass(ty):
    assert _errors(GOOD[ty]) == []


@pytest.mark.parametrize("ty, patch, needle", [
    ("gauge", {"keys": []}, "1-8 objects"),
    ("gauge", {"keys": [{"at": "@word:41", "value": "41"}]}, "numeric 'value'"),
    ("gauge", {"keys": [{"value": 41}]}, "needs 'at'"),
    ("gauge", {"max": 50}, "values must lie in"),
    ("gauge", {"zones": [{"to": 80, "tone": "danger"}, {"to": 40, "tone": "success"}]}, "ascending"),
    ("gauge", {"zones": [{"to": 80, "tone": "red"}]}, "known tones"),
    ("gauge", {"style": "speedo"}, "style"),
    ("gauge", {"keys": [{"at": "@word:41", "value": 41, "dur": 9}]}, "dur"),
    ("countdown", {"from": 0}, "must differ"),
    ("countdown", {"decimals": 4}, "decimals"),
    ("chat-thread", {"messages": [{"side": "middle", "text": "Hi", "at": "@word:down"}]}, "left or right"),
    ("chat-thread", {"messages": [{"side": "left", "text": "", "at": "@word:down"}]}, "non-empty"),
    ("chat-thread", {"messages": [{"side": "left", "text": "Hi", "at": "@word:down", "typing": 5}]}, "typing"),
    ("notification", {"items": [{"app": "A", "title": "T", "at": "@word:down"}] * 4}, "1-3 objects"),
    ("notification", {"items": [{"app": "A", "at": "@word:down"}]}, "title"),
    ("term-reveal", {"term": ""}, "non-empty"),
    ("verdict", {"text": "This verdict text is far too long"}, "at most 24"),
    ("verdict", {"mark": "star"}, "mark"),
    ("verdict", {"tint": "yes"}, "tint"),
    ("verdict", {"sfx": 3}, "sfx"),
    ("comment-cta", {"keyword": "   "}, "non-empty"),
    ("poll", {"options": [{"text": "Only", "at": "@word:speed"}]}, "2-4 objects"),
    ("poll", {"pick": 5}, "option index"),
    ("poll", {"pickAt": None}, "go together"),
    ("next-episode", {"title": ""}, "non-empty"),
])
def test_bad_blocks_are_rejected(ty, patch, needle):
    b = copy.deepcopy(GOOD[ty])
    for k, v in patch.items():
        if v is None:
            b.pop(k)
        else:
            b[k] = v
    errs = _errors(b)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("ty", list(XB.REQUIRED))
def test_required_fields(ty):
    b = {k: v for k, v in GOOD[ty].items() if k not in XB.REQUIRED[ty]}
    errs = _errors(b)
    assert any(f"{ty} needs" in e for e in errs), errs


def test_word_anchors_are_validated_like_every_block_time():
    b = copy.deepcopy(GOOD["gauge"])
    b["keys"][0]["at"] = "@word:eighty"
    assert any("not in this scene's narration" in e for e in _errors(b))
    p = copy.deepcopy(GOOD["poll"])
    p["pickAt"] = "@nocue"
    assert any("unknown cue" in e for e in _errors(p))
    t = copy.deepcopy(GOOD["term-reveal"])
    t["termAt"] = "@word:latency"
    assert any("termAt" in e for e in _errors(t))


def test_explainer_blocks_are_hero_visuals():
    assert set(XB.TYPES) <= HERO_BLOCKS
    from pipeline.creative.rules import HERO
    assert set(XB.TYPES) <= HERO


def test_annotate_cross_is_a_valid_effect_kind():
    sc = {"id": "s1", "purpose": "problem", "narration": "Slow hosting? Rejected.",
          "effects": [{"type": "annotate", "kind": "cross", "target": 0, "at": "@word:hosting"}],
          "blocks": [{"type": "headline", "size": "m", "words": "Slow hosting"}]}
    assert FX.effect_errors(sc, "$", lambda p, v: []) == []
    sc["effects"][0]["kind"] = "zigzag"
    assert any("kind" in e for e in FX.effect_errors(sc, "$", lambda p, v: []))


# ---------------------------------------------------------------------------------------------- numbers rule
def _words(spec):
    return [{"text": t, "start": s, "end": s + 0.3} for t, s in spec]


def _scene(blocks, end=8.0):
    return [{"id": "s", "start": 0.0, "end": end, "blocks": blocks}]


def test_gauge_value_shown_on_its_word_passes_and_before_it_fails():
    w = _words([("score", 0.5), ("is", 0.9), ("41", 1.2), ("then", 2.0), ("92", 2.6)])
    ok = {"type": "gauge", "at": 0.4, "keys": [{"at": 1.2, "value": 41}, {"at": 2.6, "value": 92}]}
    assert not evaluate(_scene([ok]), w, 8.0)["early_numbers"]
    early = copy.deepcopy(ok)
    early["keys"][1]["at"] = 1.5
    r = evaluate(_scene([early]), w, 8.0)
    assert r["status"] == "FAIL" and r["early_numbers"][0]["number"] == "92"


def test_countdown_start_value_and_term_time_are_checked_where_they_appear():
    w = _words([("You", 0.2), ("have", 0.5), ("7", 1.4), ("seconds", 1.7)])
    assert not evaluate(_scene([{"type": "countdown", "from": 7, "at": 1.4}]), w, 8.0)["early_numbers"]
    assert evaluate(_scene([{"type": "countdown", "from": 7, "at": 0.3}]), w, 8.0)["early_numbers"]
    # a term with a number counts from termAt, not from the kicker's `at`
    w2 = _words([("This", 0.2), ("is", 0.4), ("called", 0.6), ("Web", 1.6), ("3", 2.0)])
    late_term = {"type": "term-reveal", "at": 0.2, "kicker": "This is called", "term": "Web 3", "termAt": 2.0}
    assert not evaluate(_scene([late_term]), w2, 8.0)["early_numbers"]
    assert evaluate(_scene([{**late_term, "termAt": 0.5}]), w2, 8.0)["early_numbers"]


def test_numbers_shown_per_part():
    shown = XB.numbers_shown({"type": "chat-thread", "at": 0.1, "messages": [
        {"side": "left", "text": "Down for 30 minutes", "time": "9:41", "at": 2.0}]}, NUM)
    assert shown == [("30", 2.0)]                       # the timestamp is UI, not a claim
    shown = XB.numbers_shown({"type": "comment-cta", "at": 1.0, "keyword": "WEB3", "typeStart": 3.0}, NUM)
    assert shown == [("3", 3.0)]
    assert XB.numbers_shown({"type": "headline", "words": []}, NUM) is None


def test_claimed_values_are_checked_against_facts():
    assert XB.claimed_values(GOOD["gauge"]) == [41, 92]
    assert XB.claimed_values(GOOD["countdown"]) == [7]
    assert XB.claimed_values(GOOD["poll"]) == []


# ---------------------------------------------------------------------------------------------- sound, flashes, timing
SND = {"impact": "thump", "tick": "t", "keys": ["k1", "k2"], "click": "c", "appear": ["p"], "success": ["s"], "whoosh": ["w"],
       "shimmer": "sh", "gains": {}}


def test_sound_cues_follow_the_blocks():
    from pipeline.storyboard import SceneTiming
    st = SceneTiming("s", 0.0, 8.0, 0.2, 7.0, [])
    blocks = [{"type": "verdict", "text": "No", "at": 2.0},
              {"type": "verdict", "text": "Yes", "at": 3.0, "sfx": "success"},
              {"type": "verdict", "text": "Hm", "at": 4.0, "sfx": False},
              {"type": "comment-cta", "keyword": "GO", "at": 1.0, "typeStart": 5.0, "typeEnd": 5.4, "sendAt": 6.0},
              {"type": "gauge", "at": 0.5, "keys": [{"at": 1.0, "value": 10}]},
              {"type": "poll", "question": "Q", "at": 0.5, "options": [{"text": "A", "at": 1}, {"text": "B", "at": 2}], "pick": 0,
               "pickAt": 2.5}]
    ev = auto_sfx(0, st, blocks, SND)
    at = {(e["t"], e["kind"]) for e in ev}
    assert (2.0, "impact") in at and (3.0, "success") in at
    assert not any(abs(e["t"] - 4.0) < 1e-6 for e in ev)                 # sfx: false is silent
    assert sum(1 for e in ev if e["kind"] == "keys") == 2 and (6.0, "click") in at
    assert sum(1 for e in ev if e["kind"] == "tick") == 4
    assert (2.5, "click") in at


def test_verdict_tints_share_the_flash_budget():
    resolved = [{"id": "a", "start": 0.0, "end": 3.0, "transition": "fade",
                 "effects": [{"type": "flash", "at": 0.2}, {"type": "flash", "at": 0.3}],
                 "blocks": [{"type": "verdict", "text": "No", "at": 0.4}, {"type": "verdict", "text": "No", "at": 0.5},
                            {"type": "verdict", "text": "Yes", "at": 2.0}]}]
    out, warns = FX.photosensitivity(resolved)
    blocks = out[0]["blocks"]
    assert blocks[0].get("tint", True) is True
    assert blocks[1]["tint"] is False                       # 4th flash within a second: the stamp stays, the tint goes
    assert blocks[2].get("tint", True) is True
    assert any("verdict tint" in w for w in warns)


def test_timing_warnings_for_payoffs_cut_off_at_the_scene_end():
    resolved = [{"id": "s", "start": 0.0, "end": 3.0, "blocks": [
        {"type": "gauge", "at": 0.5, "keys": [{"at": 2.8, "value": 50}]},
        {"type": "countdown", "from": 7, "at": 1.0},
        {"type": "poll", "question": "Q", "at": 0.2, "options": [], "pick": 0, "pickAt": 1.0}]}]
    w = XB.timing_warnings(resolved)
    assert any("gauge key 50" in x for x in w) and any("countdown end" in x for x in w)
    assert not any("poll" in x for x in w)


# ---------------------------------------------------------------------------------------------- the fixture
def test_fixture_storyboard_builds_both_formats_and_matches_the_engine_fixtures():
    from pipeline.config import load_project
    from pipeline.timeline import build_timeline, estimated_timing
    cfg, _ = load_project("tests/fixtures/explainer-project.json")
    tm = estimated_timing(cfg["storyboard"])
    tl = build_timeline(cfg, tm)
    assert set(tl.props) == {"short", "landscape"}
    assert tl.warnings == []
    types = {b["type"] for s in tl.resolved for b in s["blocks"]}
    assert set(XB.TYPES) <= types
    r = evaluate(tl.resolved, tm["words"], tl.duration)
    assert r["status"] == "PASS", r
    for fmt, p in tl.props.items():
        assert p["contractVersion"] == CONTRACT_VERSION
        committed = json.loads((ROOT / f"src/engine/fixtures/sample-explainer-{fmt}.json").read_text())
        assert committed["scenes"] == json.loads(json.dumps(p["scenes"])), f"regenerate sample-explainer-{fmt}.json"
