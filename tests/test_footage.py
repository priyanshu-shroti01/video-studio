"""`footage` block (real video clips) on the Python side: validation, time expressions, ffprobe aspect/duration fill,
brand isolation, licence lookup, QA hooks, and (e2e) the low-cost preview still showing the right clip frame."""
import copy
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from pipeline import brands
from pipeline.assets import license_for, validate_file
from pipeline.config import load_project
from pipeline.contract import BLOCK_TYPES, TIME_KEYS
from pipeline.errors import ConfigError
from pipeline.footage import prepare_footage, probe_video, public_file
from pipeline.paths import ROOT
from pipeline.storyboard import HERO_BLOCKS, Resolver, SceneTiming, resolve_block, validate_storyboard
from pipeline.timeline import build_timeline, estimated_timing
from pipeline.timing import Word

CLIP = "shared/fixtures/footage-sample.mp4"
NARR = "Open the dashboard and check the preview before rendering."


def _sb(block, narration=NARR):
    return {"scenes": [{"id": "s1", "purpose": "example", "narration": narration, "blocks": [block]}]}


def _foot(**kw):
    return {"type": "footage", "asset": CLIP, **kw}


# ------------------------------------------------------------------------------------------------ contract + schema
def test_footage_is_a_known_hero_block_and_adds_no_time_key():
    assert "footage" in BLOCK_TYPES and "footage" in HERO_BLOCKS
    assert "at" in TIME_KEYS                          # zooms[].at
    assert not {"startFrom", "playbackRate", "aspect", "duration"} & TIME_KEYS   # clip seconds, not timeline times


def test_valid_footage_block_passes():
    b = _foot(frame="laptop", title="Dashboard", caption="Preview", startFrom=1.5, playbackRate=0.5, aspect=1.6,
              zooms=[{"at": "@word:dashboard", "x": 0.2, "y": 0.1, "scale": 2.5}, {"at": "@word:preview+0.2", "x": 0.5, "y": 0.5, "scale": 1}])
    assert validate_storyboard(_sb(b))[0] == []


@pytest.mark.parametrize("block,needle", [
    ({"type": "footage"}, "needs 'asset'"),
    (_foot(asset="shared/fixtures/clip.gif"), ".mp4 / .webm"),
    (_foot(frame="tablet"), "frame must be one of"),
    (_foot(playbackRate=0), "playbackRate"),
    (_foot(playbackRate=9), "playbackRate"),
    (_foot(startFrom=-1), "startFrom"),
    (_foot(aspect=0), "aspect must be a positive"),
    (_foot(zooms=[{"at": 1, "x": 0.5, "y": 0.5}]), "needs at, x, y and scale"),
    (_foot(zooms=[{"at": 1, "x": 1.5, "y": 0.5, "scale": 2}]), ".x: must be a normalised"),
    (_foot(zooms=[{"at": 1, "x": 0.5, "y": 0.5, "scale": 0.5}]), ".scale: must be between 1"),
    (_foot(zooms=[{"at": "@word:pricing", "x": 0.5, "y": 0.5, "scale": 2}]), "not in this scene's narration"),
    (_foot(title=3), "title must be a string"),
])
def test_footage_validation(block, needle):
    errs, _ = validate_storyboard(_sb(block))
    assert any(needle in e for e in errs), errs


def test_word_anchored_times_resolve_inside_zooms_but_clip_seconds_stay():
    ws = [Word(w, 1.0 + 0.4 * i, 1.3 + 0.4 * i) for i, w in enumerate(NARR.split())]
    st = SceneTiming("s1", 0.8, 6.0, 1.0, ws[-1].end, ws)
    b = resolve_block(_foot(at="@word:dashboard", startFrom=1.5, playbackRate=0.5,
                            zooms=[{"at": "@word:check", "x": 0.2, "y": 0.1, "scale": 2},
                                   {"at": "@word:preview-0.1", "x": 0.5, "y": 0.5, "scale": 1}]), Resolver(st, {}), 0, 30)
    assert b["at"] == 1.8                                    # "dashboard" is the 3rd word
    assert [z["at"] for z in b["zooms"]] == [2.6, 3.3]
    assert b["startFrom"] == 1.5 and b["playbackRate"] == 0.5


# ------------------------------------------------------------------------------------------------ ffprobe fill
def test_prepare_fills_aspect_and_duration_from_ffprobe_and_keeps_given_values():
    sb = _sb(_foot())
    sb["scenes"][0]["blocks"].append(_foot(aspect=2.0, duration=3.0))
    assert prepare_footage(sb) == []
    a, b = sb["scenes"][0]["blocks"]
    assert a["aspect"] == 1.6 and a["duration"] == pytest.approx(4.0)
    assert b["aspect"] == 2.0 and b["duration"] == 3.0


def test_probe_applies_sample_aspect_ratio_and_rotation(tmp_path):
    def ff(*a):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=1", "-vf", "setsar=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(tmp_path / "sar.mp4"))
    assert probe_video(tmp_path / "sar.mp4")["aspect"] == pytest.approx(1280 / 360, rel=1e-4)
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "a.mp4"))
    ff("-display_rotation", "90", "-i", str(tmp_path / "a.mp4"), "-c", "copy", str(tmp_path / "rot.mp4"))
    info = probe_video(tmp_path / "rot.mp4")
    assert info["aspect"] == pytest.approx(360 / 640, rel=1e-4) and info["duration"] == pytest.approx(1.0, abs=0.05)
    ff("-f", "lavfi", "-i", "testsrc2=s=320x240:r=10:d=1.2", "-c:v", "libvpx-vp9", "-b:v", "80k", str(tmp_path / "w.webm"))
    w = probe_video(tmp_path / "w.webm")
    assert w["aspect"] == pytest.approx(4 / 3) and w["duration"] == pytest.approx(1.2, abs=0.05)


def test_prepare_rejects_missing_non_video_escaping_and_out_of_range_start():
    junk = ROOT / "public/shared/fixtures/_pytest-not-a-video.mp4"
    junk.write_bytes(b"this is not a video")
    try:
        sb = {"scenes": [{"id": "s1", "blocks": [
            _foot(asset="shared/fixtures/missing.mp4"),
            _foot(asset="shared/fixtures/_pytest-not-a-video.mp4"),
            _foot(asset="../pipeline/footage.mp4"),
            _foot(asset="shared/assets.json"),
            _foot(startFrom=4.5)]}]}
        errs = prepare_footage(sb)
    finally:
        junk.unlink()
    text = "\n".join(errs)
    assert "missing video public/shared/fixtures/missing.mp4" in text
    assert "_pytest-not-a-video.mp4" in text and "cannot read video" in text
    assert "must be a file inside public/" in text
    assert "must be a video" in text
    assert "startFrom 4.5 s is past the end" in text
    assert len(errs) == 5
    assert public_file("/public/" + CLIP) == ROOT / "public" / CLIP


# ------------------------------------------------------------------------------------------------ isolation + licence
def _project(name, brand, storyboard):
    sb = ROOT / "projects" / f"{name}.storyboard.json"
    pj = ROOT / "projects" / f"{name}.json"
    sb.write_text(json.dumps(storyboard))
    pj.write_text(json.dumps({"name": name, "brand": brand, "preset": "shorts", "storyboard": f"projects/{sb.name}"}))
    return pj, sb


BRANDED = {"scenes": [{"id": "s1", "purpose": "example", "narration": NARR,
                       "blocks": [{"type": "logo", "variant": "onDark"},
                                  _foot(frame="browser", zooms=[{"at": "@word:preview", "x": 0.3, "y": 0.2, "scale": 2}])]}]}


def test_load_project_fills_footage_and_props_carry_it():
    pj, sbf = _project("footagetest-ok", "acme-demo", BRANDED)
    try:
        cfg, _ = load_project(pj.relative_to(ROOT))
    finally:
        pj.unlink(); sbf.unlink()
    assert CLIP in brands.referenced_assets(cfg["storyboard"])
    b = cfg["storyboard"]["scenes"][0]["blocks"][1]
    assert b["aspect"] == 1.6 and b["duration"] == pytest.approx(4.0)
    tl = build_timeline(cfg, estimated_timing(cfg["storyboard"]))
    pb = tl.props[cfg["formats"][0]]["scenes"][0]["blocks"][1]
    assert pb["type"] == "footage" and pb["aspect"] == 1.6 and pb["duration"] == pytest.approx(4.0)
    assert isinstance(pb["zooms"][0]["at"], float) and pb["zooms"][0]["at"] > pb["at"]


def test_footage_from_another_brand_is_rejected_and_bad_files_block_loading():
    sb = copy.deepcopy(BRANDED)
    sb["scenes"][0]["blocks"].append(_foot(asset="brands/shrotihost/footage/demo.mp4"))
    pj, sbf = _project("footagetest-iso", "acme-demo", sb)
    try:
        with pytest.raises(ConfigError) as e:
            load_project(pj.relative_to(ROOT))
    finally:
        pj.unlink(); sbf.unlink()
    assert "brands/shrotihost/footage/demo.mp4 belongs to another brand" in e.value.detail
    assert "missing video" in e.value.detail
    assert brands.asset_allowed("acme-demo", "brands/acme-demo/footage/demo.mp4")
    assert brands.asset_allowed("acme-demo", CLIP)
    assert not brands.asset_allowed("acme-demo", "brands/shrotihost/footage/demo.mp4")


def test_licence_lookup_and_file_validation_for_footage():
    p = ROOT / "public" / CLIP
    src, lic, _ = license_for(p)
    assert lic.startswith("PUBLIC-DOMAIN") and "self-generated" in src
    assert validate_file(p) == "mp4"


def test_unlicensed_footage_registers_as_unknown(tmp_path, registry, make_video):
    from pipeline.assets import AssetRegistry
    clip = ROOT / "public/shared/fixtures/_pytest-unlicensed.mp4"
    shutil.copy(make_video("x.mp4", 320, 200, 0.5, audio=False), clip)
    try:
        rec = AssetRegistry(registry).register(clip, ref="job-x")
    finally:
        clip.unlink()
    assert rec["type"] == "mp4" and rec["license"] == "UNKNOWN"   # -> blocking `license:unknown` review flag


# ------------------------------------------------------------------------------------------------ QA hooks
def test_preview_gate_reads_footage_title_and_caption():
    from pipeline.preview_gate import _strings
    keys = dict(_strings(_foot(title="Plans", caption="Starts at 99")))
    assert keys == {"title": "Plans", "caption": "Starts at 99"}


def test_visual_qa_media_aspect_check_and_footage_label_scope():
    from pipeline.visual_qa.checks import _center_in, _media_rects, static_checks
    media = {"role": "media", "kind": "video", "asset": CLIP, "frame": "browser", "bbox": {"x": 100, "y": 300, "w": 800, "h": 500},
             "aspect": 1.6, "expectedAspect": 1.6}
    blk = {"index": 0, "type": "footage", "bbox": {"x": 98, "y": 228, "w": 804, "h": 574}, "visible": {"from": 0.3, "to": 4},
           "texts": [], "logos": [], "media": [media]}
    m = {"scenes": [{"id": "s", "start": 0, "end": 4, "blocks": [blk]}], "safeArea": {"x": 70, "y": 130, "w": 940, "h": 1060},
         "captionBand": {"x": 108, "y": 1200, "w": 864, "h": 200}, "watermark": None, "brandBar": None}
    ok = {c.id: c for c in static_checks(m)}
    assert ok["layout.media_aspect"].status == "PASS"
    blk["media"][0] = {**media, "aspect": 1.4}
    assert {c.id: c for c in static_checks(m)}["layout.media_aspect"].status == "FAIL"
    assert _center_in((400, 500, 50, 20), _media_rects(m["scenes"][0], 1.0))
    assert not _center_in((400, 100, 50, 20), _media_rects(m["scenes"][0], 1.0))
    assert _media_rects(m["scenes"][0], 5.0) == []


# ------------------------------------------------------------------------------------------------ e2e: preview still
def _gray(png: Path, crop: dict | None = None) -> np.ndarray:
    vf = (f"crop={int(crop['w'])}:{int(crop['h'])}:{int(crop['x'])}:{int(crop['y'])}," if crop else "") + "scale=64:40"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(40, 64, 3).astype(float)


@pytest.mark.e2e
def test_preview_still_shows_the_held_last_frame(registry, tmp_path):
    from pipeline.preview import storyboard_stills
    from pipeline.visual_qa.checks import layout_manifest
    name = f"e2etest-footage-{int(time.time() * 1000)}"
    d = ROOT / "projects" / name
    d.mkdir()
    try:
        sb = {"scenes": [{"id": "clip", "purpose": "example", "narration": NARR,
                          # the still is taken once the block has settled (t ≈ at + 0.6 s): 2 + 0.6·4 > 4 s, so the clip holds
                          "blocks": [_foot(frame="none", startFrom=2, playbackRate=4)]}]}
        (d / "storyboard.json").write_text(json.dumps(sb))
        (d / "project.json").write_text(json.dumps({"name": name, "brand": "acme-demo", "preset": "shorts", "formats": ["short"],
                                                    "storyboard": f"projects/{name}/storyboard.json"}))
        info = storyboard_stills(d)
        still = ROOT / info["stills"][0]["png"]
        m = layout_manifest(d / "preview/props-short.json")
        box = m["scenes"][0]["blocks"][0]["media"][0]["bbox"]
        src = ROOT / "public" / CLIP
        shown = _gray(still, {k: box[k] + (2 if k in "xy" else -4) for k in box})
        diffs = {}
        for n in (0, 30, 60, 90, 110, 119):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f"select=eq(n\\,{n})", "-fps_mode", "vfr",
                            "-frames:v", "1", str(tmp_path / f"f{n}.png")], check=True)
            diffs[n] = float(np.abs(shown - _gray(tmp_path / f"f{n}.png")).mean())
        assert min(diffs, key=diffs.get) == 119, diffs     # the clip's held last frame, not black, empty or another moment
        assert diffs[119] < 20, diffs
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_storyboard_copy_with_a_banned_word_is_not_a_stray_label():
    """"Remotion renderer" placed by the storyboard is the message; a stray "Remotion" watermark elsewhere still fails."""
    from types import SimpleNamespace as NS
    from pipeline.visual_qa.checks import _intended_label_boxes, _is_intended
    sc = {"blocks": [{"visible": {"from": 0, "to": 5}, "texts": [
        {"text": "Remotion renderer", "bbox": {"x": 100, "y": 400, "w": 300, "h": 40}},
        {"text": "Kokoro voice", "bbox": {"x": 100, "y": 460, "w": 300, "h": 40}}]}]}
    boxes = _intended_label_boxes(sc, 1.0)
    assert len(boxes) == 1
    assert _is_intended(NS(text="Remotion renderer", x=110, y=405, w=280, h=30), boxes)
    assert not _is_intended(NS(text="Made with Remotion", x=110, y=405, w=280, h=30), boxes)   # extra banned words
    assert not _is_intended(NS(text="Remotion", x=900, y=1700, w=120, h=30), boxes)           # elsewhere: watermark
    assert not _intended_label_boxes(sc, 9.0)                                                  # block not visible
