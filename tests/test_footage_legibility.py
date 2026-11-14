"""footage.legibility (recorded UI text size in footage viewports / callouts), the new footage block fields (fit,
zoom regions, callouts) and brand footage spec validation."""
from __future__ import annotations

import json

import pytest

from pipeline.footage import footage_spec_errors
from pipeline.qa import FAIL, PASS, WARN
from pipeline.storyboard import _footage_errors
from pipeline.visual_qa.checks import (LEGIBILITY, _footage_rects, footage_sample_times, legibility_check,
                                       legibility_stats)
from pipeline.visual_qa.ocr import TextBox

VIEW = {"x": 100, "y": 300, "w": 880, "h": 830}
LENS = {"x": 140, "y": 330, "w": 780, "h": 300}


def _box(text, h, x=200, y=500, conf=0.9):
    return TextBox(text=text, conf=conf, x=x, y=y, w=10 * len(text), h=h)


def _scene(media=None, vis=(1.0, 9.0), end=9.0):
    md = {"role": "media", "kind": "video", "bbox": VIEW, **(media or {})}
    return {"id": "s1", "start": 0.0, "end": end, "blocks": [{"type": "footage", "visible": {"from": vis[0], "to": vis[1]},
                                                           "media": [md]}, {"type": "pill", "visible": {"from": 2, "to": 9}}]}


def test_stats_only_count_readable_lines_inside_the_footage():
    items = [_box("Production pipeline", 30), _box("Render", 34), _box("ok", 80),            # < 3 alnum: not a line
             _box("Storyboard", 90, x=10, y=10),                                             # outside the viewport
             _box("blurry text", 60, conf=0.2)]                                              # not readable
    st = legibility_stats(items, [VIEW], 1920)
    assert st == {"lines": 2, "median_px": 32.0, "median_frac": round(32 / 1920, 4)}
    assert legibility_stats([_box("Outside", 40, x=0, y=0)], [VIEW], 1920) is None


def test_threshold_is_phone_legible_for_shorts_and_advisory_for_landscape():
    assert LEGIBILITY["short"][0] * 1920 == pytest.approx(28.8)
    assert LEGIBILITY["landscape"][0] * 1080 == pytest.approx(11.88)
    small = {"s1": [{"lines": 40, "median_px": 14.2, "median_frac": 0.0074}] * 3}
    c = legibility_check(small, "short", 1920)
    assert (c.status, c.critical) == (FAIL, True) and "s1 14.2px" in c.detail and "28.8px" in c.detail
    c = legibility_check({"s1": [{"lines": 9, "median_px": 10.0, "median_frac": 0.009}]}, "landscape", 1080)
    assert (c.status, c.critical) == (WARN, False)
    big = {"s1": [{"lines": 9, "median_px": 31.0, "median_frac": 0.016}, None,
                  {"lines": 3, "median_px": 20.0, "median_frac": 0.01}, {"lines": 4, "median_px": 33.0, "median_frac": 0.017}]}
    assert legibility_check(big, "short", 1920).status == PASS          # median of the samples' medians (None skipped)
    assert legibility_check({"s1": [None, None]}, "short", 1920).status == WARN   # no readable text at all


def test_while_a_callout_is_up_its_panel_is_what_is_measured():
    sc = _scene({"callouts": [{"bbox": LENS, "from": 3.0, "to": 4.0, "mag": 2.1}]})
    assert _footage_rects(sc, 2.0) == [VIEW]
    assert _footage_rects(sc, 3.5) == [LENS]
    assert _footage_rects(sc, 9.5) == []                                 # block not visible
    items = [_box("GENERATING AUDIO", 60, x=200, y=400), _box("tiny thumbnail text", 12, x=200, y=900)]
    assert legibility_stats(items, _footage_rects(sc, 3.5), 1920)["median_px"] == 60
    assert legibility_stats(items, _footage_rects(sc, 2.0), 1920)["median_px"] == 36


def test_samples_at_settled_zooms_callouts_and_scene_end():
    sc = _scene({"settle": [2.0, 4.5, 20.0], "callouts": [{"bbox": LENS, "from": 5.0, "to": 6.0, "mag": 2}]})
    assert footage_sample_times(sc) == [2.05, 4.55, 5.5, 8.6]
    assert footage_sample_times(_scene()) == [2.8, 5.05, 7.3, 8.6]         # no zoom data: spread over the window


def test_footage_block_validates_fit_regions_and_callouts():
    ok = {"type": "footage", "asset": "x.mp4", "fit": {"short": "fill"},
          "zooms": [{"at": 1, "x": 0.5, "y": 0.5, "scale": 1, "region": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}}],
          "callouts": [{"at": 2, "x": 0.6, "y": 0.6, "w": 0.2, "h": 0.1, "hold": 1.5}]}
    assert _footage_errors(ok, "b") == []
    assert _footage_errors({**ok, "fit": "fill"}, "b") == []
    assert any("fit" in e for e in _footage_errors({**ok, "fit": "zoom"}, "b"))
    assert any("fit" in e for e in _footage_errors({**ok, "fit": {"tall": "fill"}}, "b"))
    bad = dict(ok, zooms=[{"at": 1, "x": 0.5, "y": 0.5, "scale": 1, "region": {"x": 0.9, "y": 0, "w": 0.3, "h": 0.1}}])
    assert any("region must lie inside" in e for e in _footage_errors(bad, "b"))
    bad = dict(ok, callouts=[{"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}])
    assert any("needs at" in e for e in _footage_errors(bad, "b"))
    bad = dict(ok, callouts=[{"at": 1, "x": 0.1, "y": 0.1, "w": 0, "h": 0.1, "hold": -1}])
    errs = _footage_errors(bad, "b")
    assert any("region" in e for e in errs) and any("hold" in e for e in errs)


def test_brand_footage_specs_are_valid_and_point_at_existing_recordings():
    media = json.load(open("brands/videostudio/brand.json"))["creative"]["footage"]
    assert media
    for cid, spec in media.items():
        assert footage_spec_errors(spec, cid) == [], cid
    # every beat that names a UI element carries its measured region; zoom-outs carry none
    regions = [b for s in media.values() for b in s["beats"] if b.get("region")]
    assert len(regions) >= 15


def test_footage_spec_errors_catch_bad_specs():
    assert footage_spec_errors({"asset": "brands/x/footage/a.png"})
    assert any("missing video" in e for e in footage_spec_errors({"asset": "brands/videostudio/footage/nope.mp4"}))
    spec = {"asset": "shared/fixtures/footage-sample.mp4",
            "beats": [{"cues": [], "x": 0.5, "y": 0.5, "scale": 1},
                      {"cues": ["a"], "x": 1.5, "y": 0.5, "scale": 9, "region": {"x": 0.5, "y": 0.5, "w": 0.6, "h": 0.1},
                       "callout": "yes"}]}
    errs = footage_spec_errors(spec, "c")
    assert any("cues" in e for e in errs) and any("x and y" in e for e in errs) and any("scale" in e for e in errs)
    assert any("region" in e for e in errs) and any("callout" in e for e in errs)


def test_director_uses_fill_in_shorts_regions_and_callouts_for_small_elements():
    from types import SimpleNamespace

    from pipeline.creative.industries.software import CALLOUT_CONTEXT_SCALE, footage_block

    class A:
        def first_word(self, off, name):
            return "@start"

        def at(self, cues, off, name=""):
            return f"@word:{cues[0]}"

    spec = {"asset": "brands/videostudio/footage/render-monitor-v2.mp4", "frame": "browser",
            "beats": [{"cues": ["stages"], "x": 0.5, "y": 0.6, "scale": 1.3, "region": {"x": 0.1, "y": 0.6, "w": 0.8, "h": 0.15}},
                      {"cues": ["voice"], "x": 0.3, "y": 0.68, "scale": 4.0, "region": {"x": 0.24, "y": 0.6, "w": 0.13, "h": 0.15}},
                      {"cues": ["wide"], "x": 0.5, "y": 0.5, "scale": 1.0}]}
    ctx = SimpleNamespace(pf=SimpleNamespace(media={"render": spec}), L=lambda s, src: s)
    b = footage_block(ctx, A(), "render")
    assert b["fit"] == {"short": "fill"}
    assert b["zooms"][0]["region"] == spec["beats"][0]["region"]                  # a wide element: framed by the zoom
    assert "region" not in b["zooms"][1] and b["zooms"][1]["scale"] == CALLOUT_CONTEXT_SCALE
    assert b["callouts"] == [{"at": "@word:voice", "x": 0.24, "y": 0.6, "w": 0.13, "h": 0.15}]
    assert "region" not in b["zooms"][2]
    assert _footage_errors({**b, "zooms": [{**z, "at": 1} for z in b["zooms"]],
                            "callouts": [{**c, "at": 1} for c in b["callouts"]]}, "b") == []
