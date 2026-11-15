"""Preview voice: the render's own TTS path, cached per narration, and the player switching to real voice timing.
The TTS call is monkeypatched onto the offline mock provider; the scheduler is replaced by a recorder."""
import json
import shutil
import uuid
from pathlib import Path

import pytest

from pipeline import __version__
from pipeline import preview_player as PP
from pipeline import preview_voice as PV
from pipeline import tts
from pipeline.config import load_project
from pipeline.errors import NotFound, PipelineError, TTSError
from pipeline.paths import sha256_json
from pipeline.timeline import build_timeline


@pytest.fixture
def ws_tmp():
    from pipeline.paths import TMP_DIR
    d = TMP_DIR / f"test-pvoice-{uuid.uuid4().hex[:8]}"
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def fake_tts(ws_tmp, monkeypatch):
    """synthesize_from_config -> the deterministic mock provider (real audio files, known boundaries); counts calls."""
    calls = []

    def synth(text, v, **kw):
        calls.append(text)
        return tts.synthesize(text, provider="mock", voice=v["voice"], cache_dir=ws_tmp / "tts-cache",
                              pronunciation=v.get("pronunciation"))
    monkeypatch.setattr(tts, "synthesize_from_config", synth)
    return calls


@pytest.fixture
def heavy(monkeypatch):
    """Records every scheduler grant (the preview voice must queue as 'tts' like the render's audio stage)."""
    log = []

    class FakeHeavy:
        def __init__(self, reg, kind, ref="", **kw):
            self.kind, self.ref = kind, ref

        def __enter__(self):
            log.append(("enter", self.kind, self.ref))
            from pipeline.scheduler import Grant
            return Grant(1, self.kind, 0.0, 4096.0)

        def __exit__(self, *exc):
            log.append(("exit", self.kind, self.ref))
            return False
    import pipeline.scheduler as Sch
    monkeypatch.setattr(Sch, "HeavyWork", FakeHeavy)
    return log


def _prod(base, monkeypatch, narration=None):
    import pipeline.productions as P
    from pipeline import api
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", base / "productions")
    p = api.create_production("shrotihost", {"brand": "Shroti Host", "product": "WordPress Hosting", "format": "short"})
    sb = json.loads(Path("tests/fixtures/gate-storyboard.json").read_text())
    proj = json.loads(Path("tests/fixtures/gate-project.json").read_text())
    proj["name"] = "pvoice-test"
    api.save_storyboard(p["id"], sb, project=proj)
    return api, p["id"], Path(api.Productions().get(p["id"])["dir"]), sb, proj


def _cfg(pd):
    return load_project(str(pd.relative_to(Path.cwd()) / "project.json"))[0]


def test_cache_key_is_the_render_audio_stage_input_hash(registry, ws_tmp, monkeypatch):
    _, _, pd, _, _ = _prod(ws_tmp, monkeypatch)
    cfg = _cfg(pd)
    v, scenes = cfg["voice"], cfg["storyboard"]["scenes"]
    from pipeline.voice.delivery import scene_delivery
    runner_ih = sha256_json({"voice": v, "vfp": tts.voice_fingerprint(v), "narr": [s["narration"] for s in scenes],
                             "delivery": [scene_delivery(s) for s in scenes],
                             "hold": [s.get("holdAfter", 0) for s in scenes], "v": __version__})
    key = PV.voice_key(cfg)
    assert key == runner_ih and PV.voice_key(_cfg(pd)) == key                 # stable
    import copy
    for mutate in (lambda c: c["storyboard"]["scenes"][0].update(narration="Something else entirely."),
                   lambda c: c["storyboard"]["scenes"][1].update(holdAfter=c["storyboard"]["scenes"][1].get("holdAfter", 0) + 0.37),
                   lambda c: c["voice"].update(voice="af_heart"),
                   lambda c: c["voice"].update(rate="+10%"),
                   lambda c: c["storyboard"]["scenes"][0].update(delivery="calm" if c["storyboard"]["scenes"][0].get("delivery") != "calm" else "urgent"),
                   lambda c: c["voice"].setdefault("pronunciation", {}).update({"Zyxquor": "zix-kwor"})):
        c = copy.deepcopy(cfg)
        mutate(c)
        assert PV.voice_key(c) != key
    # the global pronunciation dictionary is part of the key too (via voice_fingerprint)
    monkeypatch.setattr(tts, "voice_fingerprint", lambda v: "other-dictionary")
    assert PV.voice_key(cfg) != key


def test_generate_uses_the_scheduler_and_is_not_resynthesised_when_unchanged(registry, ws_tmp, monkeypatch,
                                                                            fake_tts, heavy):
    unloads = []
    monkeypatch.setattr(tts, "unload_all", lambda: unloads.append(1))
    _, pid, pd, sb, _ = _prod(ws_tmp, monkeypatch)
    cfg = _cfg(pd)
    assert cfg["voice"]["provider"] not in ("mock", "edge")                   # local model -> HeavyWork
    r = PV.generate_preview_voice(pid)
    assert not r["cached"] and len(fake_tts) == len(sb["scenes"])
    assert heavy == [("enter", "tts", pid), ("exit", "tts", pid)] and unloads == [1]
    e = PV.entry_dir(pd, r["key"])
    assert (e / "voiceover.wav").is_file() and (e / "meta.json").is_file()
    tm = json.loads((e / "timing.json").read_text())
    assert set(tm) >= {"duration", "words", "scene_spans", "removed_pause_s", "report", "voice"}   # render timing.json
    assert len(tm["scene_spans"]) == len(sb["scenes"]) and r["durationS"] == tm["duration"]
    assert r["audio"]["url"].endswith(f"/preview/voice/{r['key'][:16]}/voiceover.wav")
    assert r["audio"]["url"].startswith("/files/")
    assert not list(PV.voice_dir(pd).glob(".tmp-*"))
    st = PV.status(pid)
    assert st["ready"] and st["state"] == "ready" and st["key"] == r["key"] and st["audio"] == r["audio"]

    again = PV.generate_preview_voice(pid)                                    # unchanged narration: no TTS at all
    assert again["cached"] and again["key"] == r["key"] and len(fake_tts) == len(sb["scenes"])
    assert len(heavy) == 2


def test_player_switches_to_real_voice_timing(registry, ws_tmp, monkeypatch, fake_tts, heavy):
    api, pid, pd, sb, proj = _prod(ws_tmp, monkeypatch)
    before = PP.player_props(pid, "short")
    assert before["timing"] == "estimated" and before["audio"] is None and before["voiceKey"]
    with pytest.raises(NotFound):
        PP.player_props(pid, "short", timing="voice")
    PV.generate_preview_voice(pid)

    out = PP.player_props(pid, "short")
    cfg = _cfg(pd)
    hit = PV.find(pd, PV.voice_key(cfg))
    expected = build_timeline({**cfg, "formats": ["short"]}, hit["timing"]).props["short"]   # as BUILDING_TIMELINE
    assert out["props"] == expected and out["propsHash"] != before["propsHash"]
    assert out["timing"] == "voice" and "real voice" in out["timingNote"].lower()
    assert out["audio"] == {"url": PV.file_url(hit["audio"]), "durationS": hit["timing"]["duration"]}
    assert out["durationInFrames"] == round(round(hit["timing"]["duration"] + cfg["audio"].get("tail", 0.7), 3) * 30)
    # backwards-compatible contract: every key the estimated payload had is still there
    assert set(before) == set(out)
    assert PP.player_props(pid, "short", timing="voice")["props"] == expected
    forced = PP.player_props(pid, "short", timing="estimated")
    assert forced["timing"] == "estimated" and forced["audio"] is None and forced["props"] == before["props"]
    assert PP.player_props(pid, "landscape")["timing"] == "voice"            # one voice serves every format
    with pytest.raises(PipelineError):
        PP.player_props(pid, "short", timing="exact")
    json.dumps(out)

    sb["scenes"][-1]["holdAfter"] = sb["scenes"][-1].get("holdAfter", 0) + 0.5   # timing edit -> stale voice ignored
    api.save_storyboard(pid, sb, project=proj)
    stale = PP.player_props(pid, "short")
    assert stale["timing"] == "estimated" and stale["audio"] is None
    assert not PV.status(pid)["ready"]
    n = len(fake_tts)
    PV.generate_preview_voice(pid)
    assert PP.player_props(pid, "short")["timing"] == "voice"
    assert len(fake_tts) == n + len(sb["scenes"])                            # whole voiceover rebuilt ...
    # (the unchanged scenes come from the per-text TTS cache inside tts.synthesize, as in the render)


def test_failure_is_reported_and_leaves_no_entry(registry, ws_tmp, monkeypatch, heavy):
    def boom(text, v, **kw):
        raise TTSError("model missing")
    monkeypatch.setattr(tts, "synthesize_from_config", boom)
    _, pid, pd, _, _ = _prod(ws_tmp, monkeypatch)
    with pytest.raises(TTSError):
        PV.generate_preview_voice(pid)
    st = PV.status(pid)
    assert st["state"] == "failed" and "model missing" in st["error"] and not st["ready"]
    assert heavy[-1][0] == "exit"                                             # the scheduler slot is released
    assert not list(PV.voice_dir(pd).glob(".tmp-*")) and not PV.entry_dir(pd, st["key"]).exists()
    assert PP.player_props(pid)["timing"] == "estimated"


def test_online_voice_is_refused_without_opt_in(registry, ws_tmp, monkeypatch, fake_tts, heavy):
    _, pid, pd, _, _ = _prod(ws_tmp, monkeypatch)
    real = PV._load
    monkeypatch.setattr(PV, "_load", lambda p: (lambda c, d: ({**c, "voice": {**c["voice"], "provider": "edge"}}, d))(*real(p)))
    with pytest.raises(TTSError, match="ONLINE"):
        PV.generate_preview_voice(pid)
    assert fake_tts == [] and heavy == []
