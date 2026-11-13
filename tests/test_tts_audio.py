import json
import math
from pathlib import Path

import pytest

from pipeline import audio as A
from pipeline import tts
from pipeline.errors import AssetError, PipelineError, TTSError
from pipeline.timing import align


def synth(text, tmp_path, prov=None, **kw):
    return tts.synthesize(text, provider="mock", voice="mock", cache_dir=tmp_path / "cache",
                          provider_obj=prov or tts.MockProvider(), **kw)


def test_mock_provider_audio_and_timings_are_consistent(tmp_path):
    r = synth("Fast hosting. Same price.", tmp_path)
    assert r.duration > 1.0 and len(r.boundaries) == 4
    assert all(0 <= b.start < b.end <= r.duration + 0.05 for b in r.boundaries)
    ws = align("Fast hosting. Same price.", r.boundaries, r.duration)
    assert [w.text for w in ws] == ["Fast", "hosting.", "Same", "price."]


def test_cache_hit_and_corrupt_cache_rebuilt(tmp_path):
    p = tts.MockProvider()
    a = synth("cache me please", tmp_path, p)
    b = synth("cache me please", tmp_path, p)
    assert b.meta["cache"] == "hit" and p.calls == 1
    a.audio.write_bytes(b"garbage")                      # corrupt the cached file
    c = synth("cache me please", tmp_path, p)
    assert c.meta["cache"] == "miss" and p.calls == 2 and c.duration > 0.5


def test_tts_timeout_is_retried_then_succeeds(tmp_path, no_sleep):
    p = tts.MockProvider(fail_times=2, fail_kind="timeout")
    r = synth("retry this", tmp_path, p, attempts=4)
    assert p.calls == 3 and r.duration > 0 and len(no_sleep) == 2


def test_tts_timeout_exhausts_attempts(tmp_path, no_sleep):
    p = tts.MockProvider(fail_times=10, fail_kind="timeout")
    with pytest.raises(TTSError) as e:
        synth("never works", tmp_path, p, attempts=3)
    assert e.value.transient and p.calls == 3


def test_permanent_tts_error_not_retried(tmp_path, no_sleep):
    p = tts.MockProvider(fail_times=10, fail_kind="permanent")
    with pytest.raises(TTSError):
        synth("bad voice", tmp_path, p, attempts=4)
    assert p.calls == 1 and not no_sleep


@pytest.mark.parametrize("text", ["", "   ", "x" * 5000, "bad\x07char"])
def test_tts_input_validation(text, tmp_path):
    with pytest.raises(TTSError):
        synth(text, tmp_path)


def test_edge_provider_rejects_bad_voice_without_network():
    with pytest.raises(Exception):
        tts.EdgeProvider().synthesize("hi", "not-a-voice", "+0%", "+0Hz", Path("/tmp/never.mp3"), 5)


def test_voiceover_assembly_shortens_pauses_and_shifts_words(tmp_path):
    texts = ["One. Two.", "Three four."]
    scenes = []
    for t in texts:
        r = synth(t, tmp_path)
        scenes.append(A.SceneVoice(r.audio, align(t, r.boundaries, r.duration), r.duration))
    vo = A.build_voiceover(scenes, tmp_path / "vo.wav", max_pause=0.1, pad=0.2, gap=0.3)
    gaps = [b.start - a.end for a, b in zip(vo.words, vo.words[1:])]
    assert vo.removed_s > 0 and all(g <= 0.1 + 0.3 + 0.2 for g in gaps)
    assert vo.words[-1].end <= vo.duration and abs(vo.duration - A.ffprobe_duration(vo.path)) < 0.01
    # each word's audio must actually be there: tone energy inside every word span
    x = A.decode_f32(vo.path, sr=8000)
    for w in vo.words:
        assert A.rms_db(x, int((w.start + .03) * 8000), int((w.end - .03) * 8000)) > -40, w


def test_mix_ducks_music_and_hits_loudness(tmp_path, make_tone):
    r = synth("This is the narrator talking for a while now.", tmp_path)
    ws = align("This is the narrator talking for a while now.", r.boundaries, r.duration)
    music = make_tone("music.wav", seconds=6, freq=220, volume=0.5)
    kit = A.Kit(Path("audio/kit"))
    s = A.MixSettings(music_db=-6, lufs=-14)
    res = A.mix(out=tmp_path / "mix.wav", duration=r.duration + 1, voice=[(r.audio, 0.0)], music=music,
                sfx=[A.SfxEvent(str(make_tone("fx.wav", .2, 1000)), 0.5, -6)], kit=kit, s=s, stems_dir=tmp_path / "stems")
    duck = A.ducking_depth(res.stems, ws)
    assert duck["under_voice_db"] <= -6, duck
    an = A.analyze(res.path)
    assert abs(an["integrated_lufs"] - (-14)) <= 0.6 and an["true_peak_dbtp"] <= -1.0 and an["clipped_samples"] == 0
    assert len(res.events) == 1


def test_clipping_and_silence_detection(tmp_path, make_tone):
    clipped = make_tone("clip.wav", seconds=1, volume=30.0)      # sine is 1/8 FS; x30 hard-clips in s16
    assert A.analyze(clipped)["clipped_samples"] > 100
    quiet = make_tone("quiet.wav", seconds=2, volume=0.0)
    assert A.silences(quiet, min_s=0.5)


def test_corrupted_audio_input_fails_cleanly(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunkjunk")
    with pytest.raises(PipelineError) as e:
        A.mix(out=tmp_path / "o.wav", duration=1, voice=[(bad, 0)], music=None, sfx=[], kit=A.Kit(Path("audio/kit")),
              s=A.MixSettings())
    assert not e.value.transient
    with pytest.raises(AssetError):
        A.mix(out=tmp_path / "o.wav", duration=1, voice=[(tmp_path / "missing.wav", 0)], music=None, sfx=[],
              kit=A.Kit(Path("audio/kit")), s=A.MixSettings())


def test_unknown_sound_spec_rejected():
    with pytest.raises(AssetError):
        A.Kit(Path("audio/kit")).resolve("definitely-not-a-sound")
