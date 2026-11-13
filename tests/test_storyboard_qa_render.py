import copy
import json
import subprocess
from pathlib import Path

import pytest

from pipeline import qa as Q
from pipeline import render as R
from pipeline.config import load_project
from pipeline.errors import ConfigError, PipelineError, ProcessStalled, RenderError
from pipeline.procs import ProcResult
from pipeline.storyboard import Resolver, SceneTiming, auto_sfx, resolve_block, validate_storyboard
from pipeline.timing import Word

ROOT = Path(__file__).resolve().parent.parent


# ---- storyboard / config ------------------------------------------------------------------------
def test_real_projects_validate():
    for p in ("projects/shrotihost/shrotihost-short.json", "projects/shrotihost/shrotihost-landscape.json"):
        cfg, warns = load_project(p)
        assert cfg["theme"]["name"] == "Shroti Host"
        # the only warning allowed: the synthetic test tone is not cleared for publication
        assert all("not cleared for publication" in w for w in warns), warns


def _sb(**over):
    sc = {"id": "s1", "purpose": "hook", "narration": "Pick the Grow plan today.",
          "blocks": [{"type": "text", "text": "hi", "size": "m", "at": "@word:Grow"}]}
    sc.update(over)
    return {"scenes": [sc]}


@pytest.mark.parametrize("over,needle", [
    ({"blocks": [{"type": "sparkles"}]}, "unknown block type"),
    ({"blocks": [{"type": "text", "text": "x", "size": "m", "at": "@nope"}]}, "unknown cue"),
    ({"blocks": [{"type": "text", "text": "x", "size": "m", "at": "@word:banana"}]}, "not in this scene"),
    ({"blocks": [{"type": "text", "text": "x", "size": "m", "at": "@@bad"}]}, "bad time expression"),
    ({"blocks": [{"type": "pill", "text": "x", "tone": "neon"}]}, "unknown tone"),
    ({"id": "Bad Id"}, "does not match"),
    ({"extra": 1}, "unknown field"),
])
def test_storyboard_validation_errors(over, needle):
    errs, _ = validate_storyboard(_sb(**over))
    assert any(needle in e for e in errs), errs


def test_structure_warning():
    sb = {"scenes": [_sb(purpose="cta")["scenes"][0], {**_sb()["scenes"][0], "id": "s2", "purpose": "hook"}]}
    _, warns = validate_storyboard(sb, structure=["hook", "problem", "cta"])
    assert any("structure" in w for w in warns)


def _st():
    ws = [Word("Pick", 10.0, 10.2), Word("the", 10.2, 10.3), Word("Grow", 10.3, 10.6), Word("plan", 10.6, 10.9),
          Word("at", 11.0, 11.1), Word("₹79,", 11.1, 11.6), Word("Grow", 12.0, 12.3)]
    return SceneTiming("s", 9.8, 13.0, 10.0, 12.3, ws)


def test_time_expressions_resolve_against_spoken_words():
    R_ = Resolver(_st(), {"g": {"word": "Grow"}, "g2": {"word": "Grow", "nth": 2}, "after": {"at": "@g+0.5"},
                          "loop": {"at": "@loop"}})
    assert R_.time("@word:Grow+0.45") == 10.75 and R_.time("@g2") == 12.0 and R_.time("@after") == 10.8
    assert R_.time("@word:seventynine") == 11.1           # number forms
    assert R_.time(1.5) == 11.5 and R_.time("@end-0.3") == 12.7
    with pytest.raises(Exception):
        R_.time("@loop")


def test_domain_keytimes_are_frame_quantised_and_sfx_follow():
    b = {"type": "domain-input", "title": "t", "domain": "ab.in", "typeAt": "@word:plan", "availableText": "ok",
         "button": {"idle": "a", "busy": "b", "done": "c", "clickAt": "@word:at", "doneAt": 12.0}}
    out = resolve_block(b, Resolver(_st(), {}), 0, 30)
    assert out["keyTimes"][0] == 10.6 and len(out["keyTimes"]) == 5
    assert all(abs(t * 30 - round(t * 30)) < 0.05 for t in out["keyTimes"])  # ms-rounded frame times
    snd = json.loads((ROOT / "brands/shrotihost/theme.json").read_text())["sfx"]
    ev = auto_sfx(1, _st(), [out], snd)
    kinds = [e["kind"] for e in ev]
    assert kinds.count("keys") == 5 and "click" in kinds and kinds[0] == "transition"


# ---- QA engine ----------------------------------------------------------------------------------
def _ex(**kw):
    base = dict(fmt="short", fps=30, duration=2.0, lufs=None, speech=[], scene_starts=[0.0])
    base.update(kw)
    return Q.Expect(**base)


def _status(checks, cid):
    return next(c.status for c in checks if c.id == cid)


def test_qa_structural_pass(make_video):
    cs, _ = Q.structural(make_video(), _ex())
    assert all(c.status == "PASS" for c in cs if c.critical), [c for c in cs if c.status != "PASS"]


def test_qa_detects_wrong_aspect_ratio(make_video):
    cs, _ = Q.structural(make_video(w=1080, h=1080), _ex())
    assert _status(cs, "video.resolution") == "FAIL" and _status(cs, "video.aspect") == "FAIL"


def test_qa_detects_missing_audio_stream(make_video):
    cs, _ = Q.structural(make_video(audio=False), _ex())
    assert _status(cs, "stream.audio") == "FAIL"


def test_qa_detects_truncated_file(make_video, tmp_path):
    v = make_video(seconds=3)
    data = v.read_bytes()
    t = tmp_path / "trunc.mp4"
    t.write_bytes(data[: len(data) // 2])
    cs, _ = Q.structural(t, _ex(duration=3.0))
    assert any(c.status == "FAIL" and c.critical for c in cs)


def test_qa_detects_black_and_blank_frames(make_video):
    v = make_video(color="black", seconds=2)
    cs = Q.visual(v, _ex(), 2.0)
    assert _status(cs, "visual.black_frames") == "FAIL" and _status(cs, "visual.blank_scenes") == "FAIL"


def test_qa_caption_timing_outside_audio(tmp_path):
    srt = tmp_path / "c.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n\n2\n00:00:00,500 --> 00:00:09,000\nworld\n")
    cs = Q.caption_checks(srt, None, 2.0, [{"text": "hello"}, {"text": "world"}], 25)
    assert _status(cs, "captions.within_audio") == "FAIL" and _status(cs, "captions.no_overlap") == "FAIL"
    assert Q.caption_checks(None, None, 2.0, [], 25)[0].status == "FAIL"


def test_qa_silent_voice_detected(make_video):
    v = make_video(seconds=2)
    cs, _ = Q.audio_checks(v, _ex(speech=[(0.2, 0.6), (0.7, 1.2)]))
    assert _status(cs, "audio.voice_present") == "PASS"
    silent = make_video(name="s.mp4", seconds=2, audio=True, color="gray")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-af", "volume=0", "-c:v", "copy",
                    str(silent.with_name("s0.mp4"))], check=True)
    cs, _ = Q.audio_checks(silent.with_name("s0.mp4"), _ex(speech=[(0.2, 0.6), (0.7, 1.2)]))
    assert _status(cs, "audio.voice_present") == "FAIL"


# ---- render controller (fake Remotion runner) -----------------------------------------------------
def _fake_chunk(path: Path, frames: int):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:r=30",
                    "-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(path)], check=True)


class FakeRemotion:
    """Stands in for `remotion render`: writes a real H.264 chunk, or fails on demand."""
    def __init__(self, failures=None):
        self.calls, self.failures = [], dict(failures or {})

    def __call__(self, args, **kw):
        self.calls.append(args)
        frames = next(a for a in args if a.startswith("--frames=")).split("=")[1]
        a, b = map(int, frames.split("-"))
        key = (a, len([c for c in self.calls if f"--frames={a}-{b}" in c]))
        if key in self.failures:
            raise self.failures[key]
        _fake_chunk(Path(args[4]), b - a + 1)
        return ProcResult(args, 0, "", 0.5, 300.0)


def _render(tmp_path, runner, frames=90, enc="auto"):
    s = R.RenderSettings(encoder=enc, chunk_frames=30, concurrency=4, retries=2)
    return R.render_format(props_file=tmp_path / "p.json", props_hash="h", fmt="short", total_frames=frames, fps=30,
                           out=tmp_path / "v.mp4", chunks_dir=tmp_path / "chunks", s=s, bundle=tmp_path,
                           should_cancel=lambda: False, log=lambda m: None, runner=runner)


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)


def test_chunked_render_concatenates_exact_frames(tmp_path, fast):
    fr = FakeRemotion()
    rep = _render(tmp_path, fr)
    assert R.count_frames(tmp_path / "v.mp4") == 90 and len(rep.chunks) == 3 and len(fr.calls) == 3


def test_chromium_crash_is_retried_with_fewer_tabs(tmp_path, fast):
    fr = FakeRemotion({(30, 1): PipelineError("remotion exited with 1", detail="Error: Target closed (Page crashed)")})
    rep = _render(tmp_path, fr)
    assert R.count_frames(tmp_path / "v.mp4") == 90
    retried = [c for c in fr.calls if "--frames=30-59" in c]
    assert len(retried) == 2 and "--concurrency=2" in retried[1] and rep.chunks[1].attempts == 2


def test_stalled_worker_is_retried(tmp_path, fast):
    fr = FakeRemotion({(0, 1): ProcessStalled("no output for 120s")})
    _render(tmp_path, fr)
    assert R.count_frames(tmp_path / "v.mp4") == 90


def test_videotoolbox_failure_falls_back_to_x264(tmp_path, fast):
    fr = FakeRemotion({(0, 1): PipelineError("remotion exited", detail="h264_videotoolbox: Error initializing output stream")})
    rep = _render(tmp_path, fr)
    assert "--hardware-acceleration=required" in fr.calls[0] and "--hardware-acceleration=disable" in fr.calls[1]
    assert rep.chunks[0].encoder == "x264"


def test_ffmpeg_style_permanent_failure_raises(tmp_path, fast):
    fr = FakeRemotion({(0, 1): PipelineError("remotion exited", detail="Error: Invalid props: contractVersion")})
    with pytest.raises(RenderError) as e:
        _render(tmp_path, fr)
    assert not e.value.transient


def test_restart_reuses_validated_chunks(tmp_path, fast):
    fr = FakeRemotion({(60, 1): PipelineError("killed", detail="SIGKILL")})   # "process died" on chunk 3
    with pytest.raises(RenderError):
        _render(tmp_path, fr)
    fr2 = FakeRemotion()
    rep = _render(tmp_path, fr2)
    assert [c.reused for c in rep.chunks] == [True, True, False] and len(fr2.calls) == 1


def test_stale_chunk_with_other_props_is_not_reused(tmp_path, fast):
    _render(tmp_path, FakeRemotion())
    fr = FakeRemotion()
    s = R.RenderSettings(chunk_frames=30, retries=0)
    R.render_format(props_file=tmp_path / "p.json", props_hash="DIFFERENT", fmt="short", total_frames=90, fps=30,
                    out=tmp_path / "v2.mp4", chunks_dir=tmp_path / "chunks", s=s, bundle=tmp_path,
                    should_cancel=lambda: False, log=lambda m: None, runner=fr)
    assert len(fr.calls) == 3
