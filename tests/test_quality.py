"""Quality presets (pipeline/quality.py): standard 1080p30 / smooth 1080p60 / ultra 2x60.
Presets -> props, timeline exactness at 60 fps, render flags, QA scaling."""
import copy
import json
import subprocess

import numpy as np
import pytest

from pipeline import qa as Q
from pipeline import quality
from pipeline import render as R
from pipeline.config import RENDER_SCHEMA, deep_merge, load_preset, load_theme
from pipeline.errors import ConfigError
from pipeline.intelligence.brief import parse_brief
from pipeline.paths import ROOT
from pipeline.procs import ProcResult
from pipeline.schema import validate
from pipeline.storyboard import Resolver, SceneTiming, resolve_block
from pipeline.timeline import build_timeline, estimated_timing
from pipeline.timing import Word
from pipeline.visual_qa import checks as V

STORY = {"scenes": [
    {"id": "hook", "purpose": "hook", "narration": "Stop overpaying for hosting right now.",
     "blocks": [{"type": "headline", "size": "xl", "words": "Stop overpaying for hosting.", "at": "@word:Stop"},
                {"type": "pill", "text": "NVMe", "at": "@word:hosting"}]},
    {"id": "cta", "purpose": "cta", "narration": "Launch today at shrotihost.in.",
     "blocks": [{"type": "logo", "variant": "onDark", "width": 700},
                {"type": "cta", "text": "Launch today", "url": "shrotihost.in", "urlAt": "@word:shrotihost"}]}]}


def _cfg(q=None, fmt="short"):
    over = {"name": "q", "brand": "shrotihost", "preset": "shorts", "formats": [fmt], "storyboard": copy.deepcopy(STORY)}
    if q:
        over["render"] = {"quality": q}
    cfg = deep_merge(load_preset("shorts"), over)
    cfg["theme"] = load_theme("shrotihost")
    return cfg


def _tm():
    return estimated_timing(STORY)


# ---- presets + config -------------------------------------------------------------------------------
def test_presets_table():
    assert quality.preset(None).name == "standard" == quality.DEFAULT_QUALITY
    s, m, u = (quality.preset(q) for q in ("standard", "smooth", "ultra"))
    assert (s.fps, s.scale, m.fps, m.scale, u.fps, u.scale) == (30, 1, 60, 1, 60, 2)
    assert u.size("short") == (2160, 3840) and u.size("landscape") == (3840, 2160)
    assert s.size("short") == m.size("short") == (1080, 1920)
    with pytest.raises(ConfigError):
        quality.preset("8k")


def test_render_schema_and_brief_accept_quality_only_from_the_enum():
    assert validate({"quality": "ultra"}, RENDER_SCHEMA, "$") == []
    assert validate({"quality": "max"}, RENDER_SCHEMA, "$")
    b, _ = parse_brief({"brand": "shrotihost", "product": "Hosting", "quality": "smooth"})
    assert b["quality"] == "smooth"
    with pytest.raises(ConfigError):
        parse_brief({"brand": "shrotihost", "product": "Hosting", "quality": "4k"})


def test_productions_inherit_brief_quality():
    assert quality.apply_to_project({"name": "x"}, {"quality": "ultra"}) == {"name": "x", "render": {"quality": "ultra"}}
    assert quality.apply_to_project({"name": "x", "render": {"bitrate": "40M"}}, {"quality": "smooth"})["render"] == \
        {"bitrate": "40M", "quality": "smooth"}
    assert quality.apply_to_project({"name": "x"}, {}) == {"name": "x"}          # nothing configured -> unchanged


# ---- presets -> props ---------------------------------------------------------------------------------
def test_standard_is_unchanged_and_explicit_standard_is_identical():
    tm = _tm()
    base = build_timeline(_cfg(), tm)
    std = build_timeline(_cfg("standard"), tm)
    assert base.fps == 30 and base.props["short"]["fps"] == 30
    assert base.frames == round(round(tm["duration"] + 0.7, 3) * 30)
    assert json.dumps(base.props, sort_keys=True) == json.dumps(std.props, sort_keys=True)


@pytest.mark.parametrize("q", ["smooth", "ultra"])
def test_60fps_props_have_fps_and_frames_but_design_units(q):
    tm = _tm()
    s30, s60 = build_timeline(_cfg(), tm), build_timeline(_cfg(q), tm)
    p30, p60 = s30.props["short"], s60.props["short"]
    assert p60["fps"] == 60 and p60["durationInFrames"] == round(round(tm["duration"] + 0.7, 3) * 60)
    assert abs(p60["durationInFrames"] / 60 - p30["durationInFrames"] / 30) <= 1 / 60
    assert p60["format"] == "short" and "scale" not in p60 and "width" not in p60   # size stays in design units
    # every resolved time (seconds) is the same at both rates: scenes, block anchors, captions, words
    # (the last scene ends at the video's end, which is quantised to each rate's frames: within one 30-fps frame)
    e30 = [x for s in p30["scenes"] for x in (s["start"], s["end"])]
    e60 = [x for s in p60["scenes"] for x in (s["start"], s["end"])]
    assert e60[:-1] == e30[:-1] and e60[-1] == round(s60.duration, 3) and abs(e60[-1] - e30[-1]) < 1 / 30
    assert [b["at"] for s in p60["scenes"] for b in s["blocks"]] == [b["at"] for s in p30["scenes"] for b in s["blocks"]]
    assert p60["captions"]["pages"] == p30["captions"]["pages"] and p60["words"] == p30["words"]
    assert [e["t"] for e in s60.sfx] == [e["t"] for e in s30.sfx]                  # sfx are placed in seconds
    assert s60.storyboard_out["fps"] == 60


def test_word_anchors_land_on_the_first_frame_at_or_after_the_word_at_60fps():
    tm = _tm()
    tl = build_timeline(_cfg("smooth"), tm)
    words = {w["text"].strip(".,"): w["start"] for w in tm["words"]}
    pill = next(b for s in tl.props["short"]["scenes"] for b in s["blocks"] if b["type"] == "pill")
    assert pill["at"] == words["hosting"]
    first = next(f for f in range(tl.frames) if f / 60 >= pill["at"])           # the engine's t = frame / fps
    assert 0 <= first / 60 - pill["at"] < 1 / 60                                 # exact to the 60-fps frame


def _st():
    ws = [Word("Pick", 10.0, 10.2), Word("the", 10.2, 10.3), Word("Grow", 10.3, 10.6), Word("plan", 10.6, 10.9),
          Word("at", 11.0, 11.1)]
    return SceneTiming("s", 9.8, 13.0, 10.0, 11.1, ws)


def test_domain_keystrokes_keep_their_pace_at_60fps():
    b = {"type": "domain-input", "title": "t", "domain": "abcdef.in", "typeAt": "@word:plan", "availableText": "ok",
         "button": {"idle": "a", "busy": "b", "done": "c", "clickAt": "@word:at", "doneAt": 12.0}}
    k30 = resolve_block(b, Resolver(_st(), {}), 0, 30)["keyTimes"]
    k60 = resolve_block(b, Resolver(_st(), {}), 0, 60)["keyTimes"]
    assert len(k30) == len(k60) == 9
    assert all(abs(a - b_) <= 1 / 60 + 1e-9 for a, b_ in zip(k30, k60))         # same typing speed
    assert all(abs(t * 60 - round(t * 60)) < 0.06 for t in k60)                  # on 60-fps frames


def test_rules_sync_report_takes_the_project_fps():
    from pipeline.creative.rules import sync_report
    assert sync_report(STORY, fps=60)["scenes"] and sync_report(STORY) == sync_report(STORY, fps=30)


# ---- render settings -> Remotion flags -----------------------------------------------------------------
def test_render_settings_from_quality(monkeypatch):
    monkeypatch.setattr(R, "recommended_concurrency", lambda fmt: 6)
    base = load_preset("shorts")["render"]
    std = R.RenderSettings.from_config(base, "short")
    assert (std.scale, std.bitrate, std.chunk_frames, std.concurrency, std.timeout_per_chunk) == (1, "40M", 300, 6, 900)
    sm = R.RenderSettings.from_config({**base, "quality": "smooth"}, "short")
    assert (sm.scale, sm.bitrate, sm.chunk_frames, sm.concurrency) == (1, "24M", 600, 6)   # chunks stay 10 s
    assert sm.timeout_per_chunk == 1800
    ul = R.RenderSettings.from_config({**base, "quality": "ultra"}, "short")
    assert (ul.scale, ul.bitrate, ul.chunk_frames) == (2, "60M", 600)
    assert ul.concurrency == R.ULTRA_MAX_CONCURRENCY and ul.per_tab_mb == 1400 and ul.timeout_per_chunk == 900 * 8
    assert R.RenderSettings.from_config({**base, "quality": "ultra", "concurrency": 3}, "short").concurrency == 3


class _Fake:
    def __init__(self, size="1080x1920", rate=30):
        self.calls, self.size, self.rate = [], size, rate

    def __call__(self, args, **kw):
        self.calls.append(args)
        a, b = map(int, next(x for x in args if x.startswith("--frames=")).split("=")[1].split("-"))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={self.size}:r={self.rate}",
                        "-frames:v", str(b - a + 1), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                        args[4]], check=True)
        return ProcResult(args, 0, "", 0.5, 300.0)


def _render(tmp_path, s, fr, frames=120, fps=60):
    return R.render_format(props_file=tmp_path / "p.json", props_hash="h", fmt="short", total_frames=frames, fps=fps,
                           out=tmp_path / "v.mp4", chunks_dir=tmp_path / "chunks", s=s, bundle=tmp_path,
                           should_cancel=lambda: False, log=lambda m: None, runner=fr)


def test_scale_flag_is_passed_and_chunks_of_another_scale_are_not_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    fr = _Fake(rate=60)
    rep = _render(tmp_path, R.RenderSettings(chunk_frames=60, scale=1, retries=0), fr)
    assert len(fr.calls) == 2 and not any(a.startswith("--scale") for a in fr.calls[0]) and rep.scale == 1
    fr2 = _Fake(size="2160x3840", rate=60)
    rep = _render(tmp_path, R.RenderSettings(chunk_frames=60, scale=2, bitrate="60M", retries=0), fr2)
    assert len(fr2.calls) == 2 and "--scale=2" in fr2.calls[0] and "--video-bitrate=60M" in fr2.calls[0]
    assert rep.as_dict()["scale"] == 2
    meta = json.loads(next((tmp_path / "chunks").glob("*.json")).read_text())
    assert (meta["w"], meta["h"], meta["scale"]) == (2160, 3840, 2)
    fr3 = _Fake(size="2160x3840", rate=60)                                       # same settings -> reused
    assert all(c.reused for c in _render(tmp_path, R.RenderSettings(chunk_frames=60, scale=2, bitrate="60M"), fr3).chunks)
    assert fr3.calls == []


# ---- QA at 60 fps and 2x scale -------------------------------------------------------------------------
def _ex(**kw):
    base = dict(fmt="short", fps=30, duration=2.0, lufs=None, speech=[], scene_starts=[0.0])
    base.update(kw)
    return Q.Expect(**base)


def _st_of(cs, cid):
    return next(c.status for c in cs if c.id == cid)


def test_qa_structural_at_60fps_and_scale_2(make_video):
    v = make_video(w=2160, h=3840, fps=60, seconds=1.0)
    cs, _ = Q.structural(v, _ex(fps=60, duration=1.0, scale=2))
    assert all(c.status == "PASS" for c in cs if c.critical), [c for c in cs if c.status != "PASS"]
    cs, _ = Q.structural(v, _ex(fps=60, duration=1.0))                             # scale 1 expected -> wrong size
    assert _st_of(cs, "video.resolution") == "FAIL"
    cs, _ = Q.structural(make_video(fps=30, seconds=1.0), _ex(fps=60, duration=1.0))
    assert _st_of(cs, "video.fps") == "FAIL"


def test_qa_frame_size_helper():
    assert V.qa_frame_size((1080, 1920), (1080, 1920)) is None
    assert V.qa_frame_size((2160, 3840), (1080, 1920)) == (1080, 1920)
    assert V.qa_frame_size((3840, 2160), (1920, 1080)) == (1920, 1080)
    with pytest.raises(ValueError):
        V.qa_frame_size((1500, 1920), (1080, 1920))


def test_qa_frames_are_downscaled_to_design_coordinates(tmp_path):
    # a 2x frame with a white box at design (100,200,50x40) -> after frame_at(size=design) it is at the design box
    src = tmp_path / "big.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=2160x3840:r=60:d=0.5",
                    "-vf", "drawbox=x=200:y=400:w=100:h=80:color=white:t=fill", "-c:v", "libx264", "-preset",
                    "ultrafast", "-pix_fmt", "yuv420p", str(src)], check=True)
    assert V.video_size(src) == (2160, 3840)
    img = V.rgb(V.frame_at(src, 0.25, tmp_path / "f.png", (1080, 1920)))
    assert img.shape[:2] == (1920, 1080)
    box = V.crop(img, {"x": 100, "y": 200, "w": 50, "h": 40})
    assert box.mean() > 200 and V.crop(img, {"x": 300, "y": 300, "w": 50, "h": 40}).mean() < 30
    assert V.content_coverage(box, np.zeros(3)) > 0.95


def test_qa_previews_contact_sheet_at_60fps(make_video, tmp_path):
    v = make_video(w=2160, h=3840, fps=60, seconds=1.0)
    prev = Q.previews(v, tmp_path / "prev", [0.0], 1.0, 2160, 3840, fps=60)
    assert (tmp_path / "prev" / "contact-sheet.jpg").exists() and prev["frames"]["first"]


def test_quality_module_names_no_brand():
    assert "shroti" not in (ROOT / "pipeline/quality.py").read_text().lower()
