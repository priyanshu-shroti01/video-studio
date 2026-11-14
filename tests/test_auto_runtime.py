"""Automatic local-LLM runtime lifecycle: concepts / concept selection start Ollama if needed and stop it again only
if they started it; a render stops a pipeline-started runtime; missing Ollama/model falls back with a plain warning.
No real Ollama: the runtime start/stop/health functions are monkeypatched."""
from __future__ import annotations

import contextlib
import json

import pytest

import pipeline.intelligence.providers as P
from pipeline import creative
from pipeline import intelligence_bridge as ib
from pipeline.runner import JobRunner

BRIEF = {"brand": "Shroti Host", "product": "WordPress Hosting", "price": "₹39/month", "audience": "Website beginners",
         "format": "short", "duration_seconds": 35, "goal": "Conversions", "cta": "Get Started",
         "request": "Create a 35-second YouTube Short promoting WordPress Hosting at ₹39/month for beginners."}


@pytest.fixture
def rt(tmp_path, monkeypatch):
    """Fake runtime: records calls; `state` drives what start/model_ready report."""
    monkeypatch.setattr(P, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(ib, "HeavyWork", lambda *a, **k: contextlib.nullcontext())   # scheduler is tested elsewhere
    events: list[str] = []
    state = {"running": False, "model": True}

    def start(self, wait=20.0):
        events.append("start")
        if state["running"]:
            return {"started": False, "already_running": True, "version": "x"}
        state["running"] = True
        return {"started": True, "pid": 4242, "version": "x", "startup_s": 0.1}

    def stop(self):
        events.append("stop")
        state["running"] = False
        return {"stopped": True, "pid": 4242}

    monkeypatch.setattr(P.OllamaRuntime, "start", start)
    monkeypatch.setattr(P.OllamaRuntime, "stop", stop)
    monkeypatch.setattr(P.OllamaRuntime, "running", lambda self: state["running"])
    monkeypatch.setattr(P, "model_ready", lambda *a, **k: (True, "ok") if state["model"] else
                        (False, "model 'qwen' is not pulled (ollama pull qwen)"))
    # the engine itself never reaches a model in these tests: it falls back to the copy bank
    monkeypatch.setattr(P.OllamaProvider, "available", lambda self: (False, "offline in tests"))
    real = creative.generate_concepts

    def engine(*a, **k):
        events.append("engine")
        return real(*a, **k)
    monkeypatch.setattr(creative, "generate_concepts", engine)
    return {"events": events, "state": state}


def _concepts(tmp_path, provider="ollama"):
    out = tmp_path / "P1" / "concepts"
    return ib.concepts(dict(BRIEF), out, brand="shrotihost", provider=provider), out


def test_concepts_start_and_stop_the_runtime_they_started(rt, tmp_path):
    res, out = _concepts(tmp_path)
    assert rt["events"] == ["start", "engine", "stop"]
    assert res["llm_runtime"]["started"] and res["llm_runtime"]["stopped"] and res["llm_runtime"]["warning"] is None
    assert "warnings" not in res
    assert json.loads((out / "concepts.json").read_text())["llm_runtime"]["started"] is True
    assert "**Note:**" not in (out / "concepts.md").read_text()


def test_user_started_runtime_is_never_stopped(rt, tmp_path):
    rt["state"]["running"] = True                       # the user's own `ollama serve` / Ollama.app
    res, _ = _concepts(tmp_path)
    assert rt["events"] == ["start", "engine"]
    assert res["llm_runtime"]["started"] is False and res["llm_runtime"]["stopped"] is False


def test_concept_selection_is_managed_too(rt, tmp_path):
    _, out = _concepts(tmp_path, provider="none")
    rt["events"].clear()
    cid = json.loads((out / "concepts.json").read_text())["concepts"][0]["id"]
    _, _, reports = ib.storyboard(dict(BRIEF), out.parent, cid, brand="shrotihost", provider="ollama")
    assert rt["events"] == ["start", "stop"]
    assert reports["llm_runtime"]["started"] and reports["llm_runtime"]["stopped"]


def test_model_not_pulled_falls_back_with_warning_and_still_stops(rt, tmp_path):
    rt["state"]["model"] = False
    res, out = _concepts(tmp_path)
    assert rt["events"] == ["start", "engine", "stop"]
    assert res["warnings"] == [P.MODEL_MISSING_WARNING]
    assert P.MODEL_MISSING_WARNING in (out / "concepts.md").read_text()


def test_missing_ollama_falls_back_to_copy_bank_with_plain_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(ib, "HeavyWork", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(P, "ollama_binary", lambda: None)            # not installed
    monkeypatch.setattr(P.OllamaRuntime, "running", lambda self: False)
    stops = []
    monkeypatch.setattr(P.OllamaRuntime, "stop", lambda self: stops.append(1) or {"stopped": False})
    res, out = _concepts(tmp_path)                                  # real start() raises LLMUnavailable inside
    assert not stops
    assert res["llm_runtime"]["ready"] is False and "not installed" in res["llm_runtime"]["reason"]
    assert res["warnings"] == [P.MODEL_MISSING_WARNING]
    assert all(c["hook_choice"]["source"] == "bank" for c in res["concepts"])
    md = (out / "concepts.md").read_text()
    assert md.startswith("# Concepts") and f"> **Note:** {P.MODEL_MISSING_WARNING}" in md
    assert json.loads((out / "concepts.json").read_text())["warnings"] == [P.MODEL_MISSING_WARNING]


def test_provider_none_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ib, "HeavyWork", lambda *a, **k: contextlib.nullcontext())

    def boom(*a, **k):
        raise AssertionError("runtime must not be touched for provider 'none'")
    for name in ("start", "stop", "running", "version"):
        monkeypatch.setattr(P.OllamaRuntime, name, boom)
    monkeypatch.setattr(P, "model_ready", boom)
    res, out = _concepts(tmp_path, provider="none")
    assert "llm_runtime" not in res and "warnings" not in res
    assert "llm_runtime" not in json.loads((out / "concepts.json").read_text())
    assert "**Note:**" not in (out / "concepts.md").read_text()


# ---- render ---------------------------------------------------------------------------------------
class _StubRunner:
    def __init__(self):
        self.logs = []

    def log(self, msg, level="info", **k):
        self.logs.append((level, msg))


@pytest.fixture
def pidfile(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RUNTIME_DIR", tmp_path)
    kills = []
    monkeypatch.setattr(P.os, "killpg", lambda pid, sig: kills.append(pid))
    monkeypatch.setattr(P.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()))
    return tmp_path / "ollama.pid", kills


def test_render_stops_a_pipeline_started_runtime(pidfile, monkeypatch):
    pf, kills = pidfile
    pf.write_text("4242")
    monkeypatch.setattr(P, "_is_ollama_pid", lambda pid: True)
    r = _StubRunner()
    JobRunner._free_llm_runtime(r)
    assert kills == [4242] and not pf.exists()
    assert any("free memory for rendering" in m for _, m in r.logs)


def test_render_leaves_a_user_started_runtime_alone(pidfile):
    pf, kills = pidfile                                  # no pid file: not ours
    r = _StubRunner()
    JobRunner._free_llm_runtime(r)
    assert kills == [] and r.logs == []
    assert P.OllamaRuntime().stop()["stopped"] is False  # `runtime stop` CLI keeps refusing too


def test_stale_pid_file_never_signals_another_process(pidfile, monkeypatch):
    pf, kills = pidfile
    pf.write_text("4242")
    monkeypatch.setattr(P, "_is_ollama_pid", lambda pid: False)     # pid recycled by some other program
    assert P.stop_pipeline_runtime()["stopped"] is False
    assert kills == [] and not pf.exists()
    pf.write_text("")                                               # empty pid file must never mean killpg(0)
    assert P.stop_pipeline_runtime()["stopped"] is False and kills == []


def test_render_never_fails_over_the_runtime(monkeypatch):
    def broken(*a, **k):
        raise OSError("ps unavailable")
    monkeypatch.setattr(P, "stop_pipeline_runtime", broken)
    r = _StubRunner()
    JobRunner._free_llm_runtime(r)
    assert r.logs and r.logs[0][0] == "warn"
