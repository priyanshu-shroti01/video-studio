"""Real local synthesis (Kokoro, Piper) and ASR. Skips cleanly when the model files are not installed
(`uv run python -m pipeline.voice.registry fetch all`). ~1-2 GB RAM while running; models are unloaded."""
import json
from pathlib import Path

import pytest

from pipeline import tts
from pipeline.timing import align, tokenize, validate_words
from pipeline.voice import registry

ROOT = Path(__file__).resolve().parents[1]
TEXT = "Fast NVMe hosting from just ₹49 a month—launch today at shrotihost.in."
pytestmark = pytest.mark.models


def _need(ids, group):
    errs = registry.problems(ids, verify=False)
    if errs:
        pytest.skip(f"{group} models not installed: {errs[0]}")


def _default_voice():
    return json.loads((ROOT / "presets" / "shorts.json").read_text())["voice"]


@pytest.fixture(autouse=True)
def _unload():
    yield
    tts.unload_all()


@pytest.mark.parametrize("provider,voice", [("kokoro", None), ("piper", "en_GB-cori-medium")])
def test_real_local_synthesis_with_native_word_timings(provider, voice, tmp_path):
    if voice is None:
        voice = _default_voice()["voice"] if _default_voice()["provider"] == provider else "af_heart"
    files = registry.voice_files(provider, voice) + (["kokoro-model", "kokoro-vocab"] if provider == "kokoro" else [])
    _need(files, provider)
    r = tts.synthesize(TEXT, provider=provider, voice=voice, rate="+5%", cache_dir=tmp_path)
    assert r.meta["engine"]["timing_method"] in ("native", "native+dp")
    assert [b.text for b in r.boundaries] == tokenize(TEXT)
    ws = align(TEXT, r.boundaries, r.duration)
    rep = validate_words(ws, r.duration, fix=False, script=TEXT)
    assert rep.ok, rep.errors
    assert 3.0 < r.duration < 12.0
    again = tts.synthesize(TEXT, provider=provider, voice=voice, rate="+5%", cache_dir=tmp_path)
    assert again.meta["cache"] == "hit"


def test_asr_round_trip_hears_the_words(tmp_path):
    _need(["kokoro-model", "kokoro-vocab", "kokoro-voice-af_heart"], "kokoro")
    _need(["whisper-model", "whisper-config", "whisper-tokenizer", "whisper-vocab"], "whisper")
    from pipeline.voice.asr import Whisper
    r = tts.synthesize("Launch your site today with free SSL.", provider="kokoro", voice="af_heart",
                       cache_dir=tmp_path)
    w = Whisper()
    text, words = w.transcribe(r.audio)
    w.unload()
    low = text.lower()
    assert "launch" in low and "site today" in low and words


def test_worker_timeout_is_transient_and_kills_worker(tmp_path):
    _need(["kokoro-model", "kokoro-vocab", "kokoro-voice-am_michael"], "kokoro")
    from pipeline.errors import TTSError
    with pytest.raises(TTSError) as e:
        tts.synthesize("Meet Shroti Host.", provider="kokoro", voice="am_michael", cache_dir=tmp_path, timeout=0.001,
                       attempts=1)
    assert e.value.transient and tts.get_provider("kokoro").proc is None


HINGLISH = "Bada plan, chhota price! Aaj dekhte hain ki ₹49 mein website kaise banti hai."


@pytest.mark.parametrize("voice", ["hm_omega", "hf_alpha"])
def test_real_kokoro_hinglish_speaks_devanagari_with_native_timings_on_latin_words(voice, tmp_path):
    _need(["kokoro-model", "kokoro-vocab", f"kokoro-voice-{voice}"], "kokoro")
    v = {"provider": "kokoro", "voice": voice, "lang": "hinglish"}
    r = tts.synthesize_from_config(HINGLISH, v, cache_dir=tmp_path)
    eng = r.meta["engine"]
    assert eng["lang"] == "hi" and eng["timing_method"] in ("native", "native+dp")
    assert "(" not in eng["phonemes"] and "r." not in eng["phonemes"]          # no language-switch markers, ड़ -> ɽ
    assert "उनचास रुपये" in r.meta["spoken"] and "बड़ा" in r.meta["spoken"]
    assert [b.text for b in r.boundaries] == tokenize(HINGLISH)                # Latin display words come back
    ws = align(HINGLISH, r.boundaries, r.duration)
    rep = validate_words(ws, r.duration, fix=False, script=HINGLISH)
    assert rep.ok, rep.errors
    assert not r.meta["interpolated"]
    rupees = ws[tokenize(HINGLISH).index("₹49")]
    assert rupees.end - rupees.start > 0.4                                     # spans both spoken words
    assert 3.0 < r.duration < 12.0
