"""TTS cache integrity for the local path (pronunciation + display mapping) and Edge cache compatibility."""
import json

from pipeline import tts
from pipeline.paths import sha256_json


def synth(text, tmp_path, prov, **kw):
    return tts.synthesize(text, provider="mock", voice="mock", cache_dir=tmp_path, provider_obj=prov, **kw)


def test_local_path_cache_hit_returns_same_display_timings(tmp_path):
    p = tts.MockProvider()
    from pipeline.brands import load_pronunciation
    pron = load_pronunciation("shrotihost")          # brand names come from the brand, not the shared dictionary
    a = synth("Visit shrotihost.in for ₹49.", tmp_path, p, pronunciation=pron)
    b = synth("Visit shrotihost.in for ₹49.", tmp_path, p, pronunciation=pron)
    assert b.meta["cache"] == "hit" and p.calls == 1
    assert [x.__dict__ for x in a.boundaries] == [x.__dict__ for x in b.boundaries]
    assert b.meta["spoken"] == "Visit Shro-tee Host dot in for forty nine rupees."


def test_corrupt_or_tampered_entries_are_rebuilt(tmp_path):
    p = tts.MockProvider()
    a = synth("Fast NVMe hosting.", tmp_path, p)
    a.audio.write_bytes(b"garbage")
    assert synth("Fast NVMe hosting.", tmp_path, p).meta["cache"] == "miss" and p.calls == 2
    meta_f = a.audio.parent / "meta.json"
    m = json.loads(meta_f.read_text()); m["text"] = "something else"; meta_f.write_text(json.dumps(m))
    assert synth("Fast NVMe hosting.", tmp_path, p).meta["cache"] == "miss" and p.calls == 3
    meta_f.write_text("{not json")
    assert synth("Fast NVMe hosting.", tmp_path, p).meta["cache"] == "miss" and p.calls == 4


def test_pronunciation_override_changes_the_cache_entry(tmp_path):
    p = tts.MockProvider()
    a = synth("Fast NVMe hosting.", tmp_path, p)
    b = synth("Fast NVMe hosting.", tmp_path, p, pronunciation={"NVMe": "nuh vee me"})
    assert b.meta["cache"] == "miss" and a.audio != b.audio and b.meta["spoken"] == "Fast nuh vee me hosting."


class FakeEdge(tts.MockProvider):
    name, online, uses_pronunciation, version = "edge", True, False, "7.3.1"


def test_edge_cache_key_is_unchanged_so_old_entries_stay_valid(tmp_path):
    text, voice, rate, pitch = "Meet Shroti Host.", "en-IN-PrabhatNeural", "+5%", "+0Hz"
    legacy = sha256_json({"p": "edge", "v": "7.3.1", "voice": voice, "rate": rate, "pitch": pitch, "text": text})
    r = tts.synthesize(text, provider="edge", voice=voice, rate=rate, pitch=pitch, cache_dir=tmp_path,
                       provider_obj=FakeEdge(), allow_online=True)
    assert r.audio == tmp_path / legacy[:2] / legacy / "voice.mp3"
    assert "spoken" not in r.meta                                  # legacy behaviour: no pronunciation layer
