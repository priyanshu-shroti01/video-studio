"""Effects (pipeline/effects.py, pipeline/beats.py, pipeline/creative/fx.py): schema, director choices + restraint,
beat detection on a synthetic click track, beat snapping that keeps the word-anchor rules, photosensitivity, and the
gate that keeps storyboards without effects byte-identical."""
from __future__ import annotations

import copy
import json
import shutil
import wave

import numpy as np
import pytest

from pipeline import beats, effects as FX
from pipeline.creative import fx as director_fx
from pipeline.storyboard import validate_storyboard
from pipeline.sync_check import evaluate


def _scene(**kw) -> dict:
    sc = {"id": "s1", "purpose": "hook", "narration": "Launch your site in five minutes flat.",
          "blocks": [{"type": "kinetic-text", "words": "Launch your site in five minutes", "at": "@word:Launch"},
                     {"type": "footage", "asset": "shared/fixtures/footage-sample.mp4", "at": "@word:site",
                      "zooms": [{"at": "@word:minutes", "x": 0.4, "y": 0.4, "scale": 1.6}]}]}
    sc.update(kw)
    return sc


def _errors(sc: dict) -> list[str]:
    errs, _ = validate_storyboard({"scenes": [sc, {"id": "s2", "purpose": "cta", "narration": "Get started.",
                                                   "blocks": [{"type": "logo", "variant": "onDark"}]}]})
    return errs


# ---------------------------------------------------------------------------------------------- schema
def test_valid_effects_and_transitions_pass():
    sc = _scene(transition="whip-pan", transitionDir="right", effects=[
        {"type": "punch-zoom", "at": "@word:minutes", "scale": 1.08},
        {"type": "annotate", "kind": "circle", "target": 0, "text": "minutes", "at": "@word:minutes"},
        {"type": "cursor", "target": 1, "at": "@word:minutes"},
        {"type": "tilt", "target": 1},
        {"type": "burst", "at": "@word:flat+0.1", "count": 20},
        {"type": "shake", "at": "@word:five", "amp": 6},
        {"type": "flash", "at": "@word:Launch", "intensity": 0.3}])
    assert _errors(sc) == []
    for tr in FX.FX_TRANSITIONS:
        assert _errors(_scene(transition=tr)) == []


@pytest.mark.parametrize("effect, needle", [
    ({"type": "sparkle", "at": "@word:five"}, "unknown effect type"),
    ({"type": "punch-zoom", "at": "@word:seven"}, "not in this scene's narration"),
    ({"type": "punch-zoom"}, "needs 'at'"),
    ({"type": "punch-zoom", "at": "@word:five", "scale": 1.5}, "scale"),
    ({"type": "shake", "at": "@word:five", "amp": 20}, "amp"),
    ({"type": "flash", "at": "@word:five", "intensity": 1.0}, "intensity"),
    ({"type": "annotate", "kind": "box", "target": 0, "at": "@word:five"}, "kind"),
    ({"type": "annotate", "kind": "circle", "at": "@word:five"}, "needs 'target'"),
    ({"type": "annotate", "kind": "circle", "target": 5, "at": "@word:five"}, "block index"),
    ({"type": "cursor", "target": 0, "at": "@word:five"}, "cursor clicks on"),
    ({"type": "tilt", "target": 0}, "tilt is for"),
    ({"type": "burst", "at": "@word:five", "colour": "red"}, "unknown field"),
])
def test_bad_effects_are_rejected(effect, needle):
    errs = _errors(_scene(effects=[effect]))
    assert any(needle in e for e in errs), errs


def test_transition_dir_only_with_a_moving_transition():
    assert any("transitionDir" in e for e in _errors(_scene(transition="fade", transitionDir="left")))
    assert any("transition" in e for e in _errors(_scene(transition="spin")))


def test_restraint_warnings_for_hand_edited_storyboards():
    scenes = [_scene(id=f"s{i}", transition="push", effects=[{"type": "flash", "at": "@word:five"},
                                                             {"type": "shake", "at": "@word:five"}]) for i in range(3)]
    w = FX.restraint_warnings(scenes)
    assert any("emphasis effects" in x for x in w)
    assert any("twice in a row" in x for x in w)
    assert any("flash effects" in x for x in w)


# ---------------------------------------------------------------------------------------------- photosensitivity
def test_photosensitivity_keeps_at_most_three_flashes_per_second():
    resolved = [{"id": "a", "start": 0, "end": 2, "transition": "fade",
                 "effects": [{"type": "flash", "at": t} for t in (0.1, 0.3, 0.5, 0.7, 0.9)]},
                {"id": "b", "start": 2, "end": 4, "transition": "light-leak", "effects": [{"type": "flash", "at": 2.2}]}]
    out, warns = FX.photosensitivity(copy.deepcopy(resolved))
    times = sorted([e["at"] for s in out for e in s.get("effects", [])] + [2.0])
    assert max(sum(1 for u in times if 0 <= u - t < 1.0) for t in times) <= 3
    assert len(warns) == 2          # 0.7 and 0.9 s would make a 4th and 5th flash in the same second


# ---------------------------------------------------------------------------------------------- sync check
def test_effects_count_as_visual_events_in_the_sync_check():
    words = [{"text": f"w{i}", "start": 0.4 * i, "end": 0.4 * i + 0.3} for i in range(12)]
    scenes = [{"id": "s", "start": 0.0, "end": 5.0, "blocks": [{"type": "text", "at": 0.1}]}]
    assert evaluate(scenes, words, 5.0)["longest_static_s"] > 2.5
    scenes[0]["effects"] = [{"type": "punch-zoom", "at": 2.4}]
    assert evaluate(scenes, words, 5.0)["static"] == []


# ---------------------------------------------------------------------------------------------- beat detection
def _click_track(bpm=120.0, offset=0.25, dur=12.0, sr=beats.SR):
    x = np.random.default_rng(1).normal(0, 0.003, int(dur * sr))
    period = 60.0 / bpm
    click = np.sin(2 * np.pi * 1800 * np.arange(int(0.012 * sr)) / sr) * np.exp(-np.arange(int(0.012 * sr)) / (0.003 * sr))
    ts = np.arange(offset, dur - 0.05, period)
    for t in ts:
        i = int(t * sr)
        x[i:i + len(click)] += 0.8 * click
    return x, ts


def test_beat_detection_on_a_synthetic_click_track():
    x, ts = _click_track()
    d = beats.detect(x)
    assert abs(d["bpm"] - 120.0) < 2.0
    bt = np.array(d["beats"])
    assert len(bt) >= len(ts) - 2
    # every detected beat lies on a click (one envelope hop = 23 ms)
    err = [np.min(np.abs(ts - b)) for b in bt]
    assert max(err) < 0.025, err
    assert d == beats.detect(x)                     # deterministic


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_beats_for_a_file_is_cached_per_sha256(tmp_path, monkeypatch):
    monkeypatch.setattr(beats, "CACHE_DIR", tmp_path / "cache")
    x, _ = _click_track(bpm=100.0, dur=8.0)
    f = tmp_path / "click.wav"
    with wave.open(str(f), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(beats.SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    d = beats.beats_for(f)
    assert abs(d["bpm"] - 100.0) < 2.0 and len(d["sha256"]) == 64
    assert (tmp_path / "cache" / "beats" / f"{d['sha256']}.json").exists()
    calls = []
    monkeypatch.setattr(beats, "decode", lambda p, sr=beats.SR: calls.append(p))
    assert beats.beats_for(f) == d and calls == []                   # served from the cache, no decode
    loop = beats.timeline_beats({"beats": [0.5, 1.5], "duration": 2.0}, 5.0)
    assert loop == [0.5, 1.5, 2.5, 3.5, 4.5]


# ---------------------------------------------------------------------------------------------- beat snapping
def _timeline():
    words = [{"text": t, "start": s, "end": s + 0.3} for t, s in
             [("Launch", 0.3), ("your", 0.7), ("site", 1.1), ("today.", 1.5),
              ("Plans", 2.6), ("from", 3.0), ("₹69", 3.4), ("a", 3.8), ("month.", 4.0), ("Done.", 4.6)]]
    resolved = [{"id": "a", "start": 0.0, "end": 2.2, "transition": "fade", "blocks": [{"type": "text", "at": 0.3}]},
                {"id": "b", "start": 2.2, "end": 6.0, "transition": "whip-pan",
                 "blocks": [{"type": "counter", "to": 69, "at": 3.4, "countEnd": 3.9}],
                 "effects": [{"type": "punch-zoom", "at": 3.4}, {"type": "punch-zoom", "at": 4.6}]}]
    anchors = {(1, 0): {"start": 3.4, "end": 3.7, "text": "₹69", "numeric": True},
               (1, 1): {"start": 4.6, "end": 4.9, "text": "Done.", "numeric": False}}
    return resolved, words, anchors


def test_snapping_moves_cuts_and_punches_onto_beats_within_120_ms():
    resolved, words, anchors = _timeline()
    sfx = [{"t": 2.3, "kind": "transition", "sound": "whoosh"}]
    rep = beats.snap_timeline(resolved, words, [2.13, 3.45, 4.66], 6.6, 30, anchors, sfx)
    got = {(x["kind"], x["from"]): x for x in rep["snapped"]}
    assert resolved[1]["start"] == resolved[0]["end"] == round(round(2.13 * 30) / 30, 3)
    assert ("transition", 2.2) in got and abs(got[("transition", 2.2)]["delta_ms"]) <= 120
    assert sfx[0]["t"] == round(resolved[1]["start"] + 0.1, 3)            # the whoosh follows the cut
    assert resolved[1]["effects"][0]["at"] == round(round(3.45 * 30) / 30, 3)
    assert resolved[1]["effects"][1]["at"] == round(round(4.66 * 30) / 30, 3)


def test_snapping_never_breaks_the_word_rules():
    resolved, words, anchors = _timeline()
    # beats just before the spoken number / outside the window / cutting the previous scene's last word
    words[3] = {"text": "today.", "start": 1.9, "end": 2.2}         # the previous scene speaks until 2.2 s
    rep = beats.snap_timeline(resolved, words, [2.1, 3.33, 4.3], 6.6, 30, anchors)
    assert rep["snapped"] == []
    reasons = " | ".join(k["reason"] for k in rep["kept"])
    assert "last word would be cut" in reasons
    assert "off the anchor word" in reasons
    assert "no beat within" in reasons
    assert resolved[1]["start"] == 2.2 and resolved[1]["effects"][0]["at"] == 3.4


def test_snapping_refuses_a_move_that_leaves_narration_static():
    words = [{"text": f"w{i}", "start": 0.2 + 0.4 * i, "end": 0.5 + 0.4 * i} for i in range(14)]
    resolved = [{"id": "a", "start": 0.0, "end": 3.0, "transition": "fade", "blocks": [{"type": "text", "at": 0.2}]},
                {"id": "b", "start": 3.0, "end": 6.0, "transition": "push", "blocks": [{"type": "text", "at": 5.6}],
                 "effects": [{"type": "punch-zoom", "at": 3.4}]}]
    # moving the punch later would leave > 2.5 s of narration without a visual event
    anchors = {(1, 0): {"start": 3.4, "end": 3.75, "text": "w8", "numeric": False}}
    before = evaluate(copy.deepcopy(resolved), words, 6.2)
    beats.snap_timeline(resolved, words, [3.52], 6.2, 30, anchors)
    after = evaluate(resolved, words, 6.2)
    assert len(after["static"]) <= len(before["static"])


# ---------------------------------------------------------------------------------------------- director
def _sb(motion: str, n=5) -> dict:
    scenes = [{"id": "s0", "purpose": "hook", "narration": "Fast hosting. Ten times faster pages.", "motion": motion,
               "transition": "fade",
               "blocks": [{"type": "kinetic-text", "words": "Ten times faster pages", "emphasis": ["faster"],
                           "at": "@word:Ten"}]}]
    for i in range(1, n):
        scenes.append({"id": f"s{i}", "purpose": "cta" if i == n - 1 else "point", "motion": motion,
                       "narration": "Watch the install finish in seconds.", "transition": "slide-up",
                       "blocks": [{"type": "footage", "asset": "shared/fixtures/footage-sample.mp4", "at": "@word:Watch",
                                   "zooms": [{"at": "@word:install", "x": 0.5, "y": 0.4, "scale": 1.6}]},
                                  {"type": "counter", "to": 30, "at": "@word:seconds"}]})
    return {"scenes": scenes}


def _check_restraint(sb):
    trs = [s["transition"] for s in sb["scenes"]]
    for a, b in zip(trs, trs[1:]):
        assert not (a == b and a in FX.FX_TRANSITIONS), trs
    flashes = sum(1 for s in sb["scenes"] for e in s.get("effects", []) if e["type"] == "flash") + trs.count("light-leak")
    assert flashes <= 2 and trs.count("glitch") <= 2
    for s in sb["scenes"]:
        assert sum(1 for e in s.get("effects", []) if e["type"] in FX.EMPHASIS) <= 1
    errs, _ = validate_storyboard(sb)
    assert errs == []


def test_director_energetic_whips_and_punches():
    sb = director_fx.plan(_sb("energetic"), {"style": "energetic"})
    trs = [s["transition"] for s in sb["scenes"][1:]]
    assert {"whip-pan", "push"} & set(trs)
    assert sb["scenes"][0]["effects"][0] == {"type": "punch-zoom", "at": "@word:faster", "scale": 1.06}
    assert any(e["type"] == "cursor" for e in sb["scenes"][1]["effects"])
    assert sb["beatSync"] is True
    _check_restraint(sb)


def test_director_cinematic_zooms_through_and_leaks_light():
    sb = director_fx.plan(_sb("cinematic", n=8), {"style": "cinematic"})
    trs = [s["transition"] for s in sb["scenes"][1:]]
    assert "zoom-through" in trs and "light-leak" in trs
    assert all(e["type"] != "punch-zoom" for s in sb["scenes"] for e in s.get("effects", []))
    assert any(e["type"] == "tilt" for s in sb["scenes"] for e in s.get("effects", []))
    _check_restraint(sb)


def test_director_calm_stays_minimal():
    base = _sb("calm")
    sb = director_fx.plan(copy.deepcopy(base), {"style": "calm"})
    assert [s["transition"] for s in sb["scenes"]] == [s["transition"] for s in base["scenes"]]
    assert all(e["type"] == "annotate" for s in sb["scenes"] for e in s.get("effects", []))
    assert "beatSync" not in sb
    _check_restraint(sb)


def test_director_restraint_holds_for_every_style_and_length():
    for style in director_fx.STYLES:
        for n in (2, 5, 9):
            _check_restraint(director_fx.plan(_sb(style, n), {"style": style}))


# ---------------------------------------------------------------------------------------------- byte-identical gate
def _project_cfg(sb):
    from pipeline.config import deep_merge, load_preset, load_theme
    cfg = deep_merge(load_preset("shorts"), {"storyboard": sb})
    cfg["theme"] = load_theme("shrotihost")
    return cfg


def test_storyboards_without_effects_give_identical_props(monkeypatch):
    from pipeline import timeline
    sb = {"scenes": [{"id": "s1", "purpose": "hook", "narration": "Launch your site in five minutes.",
                      "transition": "slide-up", "camera": "drift",
                      "blocks": [{"type": "kinetic-text", "words": "Launch your site", "at": "@word:Launch"},
                                 {"type": "counter", "to": 5, "suffix": " min", "at": "@word:five"}]},
                     {"id": "s2", "purpose": "cta", "narration": "Get started today.", "transition": "mask-wipe",
                      "blocks": [{"type": "logo", "variant": "onDark"}]}]}
    tm = timeline.estimated_timing(sb)
    a = timeline.build_timeline(_project_cfg(copy.deepcopy(sb)), tm)

    def boom(*a, **k):
        raise AssertionError("the effects code path must not run for storyboards without effects")
    monkeypatch.setattr(FX, "timeline_pass", boom)
    monkeypatch.setattr(FX, "resolve_effects", boom)
    b = timeline.build_timeline(_project_cfg(copy.deepcopy(sb)), tm)
    assert json.dumps(a.props, sort_keys=True) == json.dumps(b.props, sort_keys=True)
    for p in a.props.values():
        for s in p["scenes"]:
            assert not {"effects", "transitionDir"} & set(s)
    assert "beatSync" not in a.storyboard_out


def test_existing_concepts_rebuild_without_effects():
    """A concept saved before effects existed has no `effects` key: compose() leaves its storyboard untouched."""
    import inspect
    from pipeline.creative import director
    src = inspect.getsource(director.compose)
    assert 'if concept.get("effects"):' in src
    # ... and new concepts carry the effects plan (plan_concept)
    assert '"effects": {"version": FX_VERSION, "style": concept_style(bp["music"])}' in inspect.getsource(director.plan_concept)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_effect_timeline_end_to_end_resolves_words_and_records_beats(tmp_path, monkeypatch):
    from pipeline import timeline
    monkeypatch.setattr(beats, "CACHE_DIR", tmp_path / "cache")
    x, _ = _click_track(bpm=120.0, dur=10.0)
    f = tmp_path / "m.wav"
    with wave.open(str(f), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(beats.SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    sb = {"beatSync": True, "scenes": [
        {"id": "s1", "purpose": "hook", "narration": "Launch your site in five minutes flat.",
         "blocks": [{"type": "kinetic-text", "words": "Launch your site", "at": "@word:Launch"}],
         "effects": [{"type": "punch-zoom", "at": "@word:minutes"}]},
        {"id": "s2", "purpose": "cta", "narration": "Get started today.", "transition": "whip-pan",
         "blocks": [{"type": "logo", "variant": "onDark"}]}]}
    assert validate_storyboard(sb)[0] == []
    cfg = _project_cfg(sb)
    cfg["audio"]["music"] = str(f)
    tl = timeline.build_timeline(cfg, timeline.estimated_timing(sb))
    s1 = tl.props["short"]["scenes"][0]
    assert isinstance(s1["effects"][0]["at"], float)
    rep = tl.storyboard_out["beatSync"]
    assert rep["bpm"] and len(rep["snapped"]) + len(rep["kept"]) == 2
