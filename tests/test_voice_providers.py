"""Provider selection, the online opt-in gate, preset defaults and model-missing errors."""
import json
from pathlib import Path

import pytest

from pipeline import tts
from pipeline.config import load_project
from pipeline.errors import TTSError
from pipeline.schema import validate
from pipeline.voice import registry
from pipeline.voice.schema import VOICE_SCHEMA, check_voice_config

ROOT = Path(__file__).resolve().parents[1]


class FakeOnline(tts.MockProvider):
    """Behaves like Edge (online, no pronunciation layer) without touching the network."""
    name, online, uses_pronunciation = "edge", True, False


def test_edge_is_refused_without_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.EdgeProvider, "synthesize", lambda *a, **k: pytest.fail("network provider was called"))
    tts._instances.pop("edge", None)
    with pytest.raises(TTSError) as e:
        tts.synthesize("Hello there.", provider="edge", voice="en-IN-PrabhatNeural", cache_dir=tmp_path)
    assert "allowOnline" in e.value.message and not e.value.transient
    assert "edge" not in tts._instances                      # never even instantiated
    with pytest.raises(TTSError):                            # also when handed a provider object
        tts.synthesize("Hello there.", provider="edge", voice="x", cache_dir=tmp_path, provider_obj=FakeOnline())


def test_edge_works_only_with_allow_online(tmp_path):
    r = tts.synthesize("Hello there.", provider="edge", voice="v", cache_dir=tmp_path, provider_obj=FakeOnline(),
                       allow_online=True)
    assert [b.text for b in r.boundaries] == ["Hello", "there"]


def test_voice_config_gate():
    errs, _ = check_voice_config({"provider": "edge", "voice": "en-IN-PrabhatNeural"})
    assert errs and "allowOnline" in errs[0]
    errs, warns = check_voice_config({"provider": "edge", "voice": "en-IN-PrabhatNeural", "allowOnline": True})
    assert not errs and any("online" in w.lower() for w in warns)
    errs, _ = check_voice_config({"provider": "edge", "voice": "en-IN-PrabhatNeural", "allowOnline": "yes"})
    assert errs                                               # only literal true opts in
    assert validate({"provider": "edge", "allowOnline": "yes"}, VOICE_SCHEMA)  # schema rejects non-boolean


def test_voice_config_rejects_mismatched_or_unknown_voices():
    assert check_voice_config({"provider": "kokoro", "voice": "en-IN-PrabhatNeural"})[0]
    assert check_voice_config({"provider": "piper", "voice": "af_heart"})[0]
    assert check_voice_config({"provider": "kokoro", "voice": "zz_nobody"})[0]
    assert check_voice_config({"provider": "mock", "voice": "af_heart"})[0]
    assert validate({"provider": "kokoro", "voice": "af_heart", "typo": 1}, VOICE_SCHEMA)  # unknown field


@pytest.mark.parametrize("preset", sorted((ROOT / "presets").glob("*.json")), ids=lambda p: p.stem)
def test_presets_default_to_a_local_commercial_voice(preset):
    v = json.loads(preset.read_text())["voice"]
    assert v["provider"] in tts.LOCAL_PROVIDERS and "allowOnline" not in v
    assert not validate(v, VOICE_SCHEMA, "$.voice")
    errs, _ = check_voice_config(v, check_models=False)
    assert not errs
    assert registry.voices(v["provider"])[v["voice"]]["commercial"] is True


@pytest.mark.parametrize("project", ["projects/shrotihost/shrotihost-short.json", "projects/shrotihost/shrotihost-landscape.json"])
def test_existing_projects_resolve_to_local_voice(project):
    cfg, _ = load_project(project)
    assert cfg["voice"]["provider"] in tts.LOCAL_PROVIDERS
    assert not check_voice_config(cfg["voice"], check_models=False)[0]


def test_unknown_provider_is_a_clear_error():
    with pytest.raises(TTSError, match="unknown TTS provider"):
        tts.get_provider("espeak-online")


def test_missing_model_is_clear_not_transient_and_not_retried(tmp_path, monkeypatch, no_sleep):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path / "nothing-here")
    for name in ("kokoro", "piper"):
        tts._instances.pop(name, None)
    monkeypatch.setattr(tts.EdgeProvider, "synthesize", lambda *a, **k: pytest.fail("silent fallback to edge"))
    with pytest.raises(registry.ModelMissing) as e:
        tts.synthesize("Meet Shroti Host.", provider="kokoro", voice="af_heart", cache_dir=tmp_path / "c")
    assert "pipeline.voice.registry fetch kokoro" in e.value.message and not e.value.transient
    assert "kokoro/model.onnx" in (e.value.detail or "") and "missing" in e.value.detail
    with pytest.raises(registry.ModelMissing):
        tts.synthesize("Meet Shroti Host.", provider="piper", voice="en_GB-cori-medium", cache_dir=tmp_path / "c")
    assert not no_sleep                                        # permanent error: no retry back-off
    errs, warns = check_voice_config({"provider": "kokoro", "voice": "af_heart"})
    assert not errs and any("fetch kokoro" in w for w in warns)
    for name in ("kokoro", "piper"):
        tts._instances.pop(name, None)


def test_registry_entries_are_complete():
    reg = registry.load()
    for f in reg["files"]:
        assert f["licence"] and f["path"]
        if not f.get("derived"):
            assert f["url"].startswith("https://huggingface.co/") and "/resolve/" in f["url"]
            assert len(f["sha256"]) == 64 and f["size"] > 0
    for prov, voices in reg["voices"].items():
        for v, meta in voices.items():
            assert meta["commercial"] is True, v
            for fid in meta["files"]:
                registry.entry(fid)


def test_unload_all_is_safe():
    tts.unload_all()
