"""A render killed mid-way doesn't leave its production stuck; the brief's voice and pace reach the project;
the film's first word starts almost at once."""
import pytest

from pipeline import api
from pipeline.productions import Productions


@pytest.fixture
def prod(registry, tmp_path, monkeypatch):
    import pipeline.productions as P
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", tmp_path / "productions")
    return Productions(registry)


def _rendering(prod, registry, tmp_path, job_state):
    p = prod.create("videostudio", "demo", {"brand": "Video Studio", "product": "x"})
    job = registry.create("demo", f"k-{job_state}", {}, None, tmp_path / "out")
    prod.update(p["id"], job_id=job["id"])
    for s in ("STORYBOARD_READY", "RENDERING"):
        prod.transition(p["id"], s)
    if job_state != "QUEUED":
        registry.transition(job["id"], "PREPARING", message="test")      # a worker started, then stopped
        registry.transition(job["id"], job_state, message="test")
    return p["id"]


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED"])
def test_a_dead_render_fails_its_production_so_it_can_render_again(prod, registry, tmp_path, state):
    pid = _rendering(prod, registry, tmp_path, state)
    assert api.reconcile_productions(registry) == [pid]
    assert prod.get(pid)["state"] == "FAILED"
    assert api.reconcile_productions(registry) == []            # idempotent


def test_a_running_render_is_left_alone(prod, registry, tmp_path):
    pid = _rendering(prod, registry, tmp_path, "QUEUED")
    assert api.reconcile_productions(registry) == []
    assert prod.get(pid)["state"] == "RENDERING"


@pytest.mark.parametrize("brief,want", [
    ({"voice": "am_fenrir"}, {"voice": "am_fenrir", "rate": "+0%"}),
    ({"voice": "am_fenrir", "pace": "calm"}, {"voice": "am_fenrir", "rate": "-8%"}),
    ({"pace": "brisk"}, {"voice": "am_michael", "rate": "+5%"}),
    ({"pace": "normal"}, {"voice": "am_michael", "rate": "+0%"}),
])
def test_brief_voice_and_pace_override_the_preset(brief, want):
    project = api.apply_brief_voice({"voice": {"voice": "am_michael", "rate": "+0%", "maxPause": 0.5}}, brief)
    assert {k: project["voice"][k] for k in want} == want and project["voice"]["maxPause"] == 0.5


def test_a_brief_without_voice_leaves_the_preset_untouched():
    assert "voice" not in api.apply_brief_voice({}, {"product": "x"})


def test_pace_is_a_valid_brief_field():
    from pipeline.intelligence.brief import BRIEF_SCHEMA
    assert BRIEF_SCHEMA["properties"]["pace"]["enum"] == ["calm", "normal", "brisk"]


def test_a_hand_saved_storyboard_gets_every_format_the_brief_asks_for():
    p = {"id": "P1", "brand": "videostudio", "brief": {"format": "short", "formats": ["short", "landscape"]}}
    assert api.default_project(p)["formats"] == ["short", "landscape"]
    assert api.default_project({**p, "brief": {"format": "landscape"}})["formats"] == ["landscape"]


def test_the_preview_gate_catches_a_dark_scene_that_opens_empty():
    from pipeline.preview_gate import scene_open_report
    scenes = [{"id": "a", "start": 0.0, "end": 4.0, "backdrop": "deep", "blocks": [{"at": 1.4}]},
              {"id": "b", "start": 4.0, "end": 8.0, "backdrop": "light", "blocks": [{"at": 5.0}]},
              {"id": "c", "start": 8.0, "end": 12.0, "backdrop": "deep", "blocks": [{"at": 8.05}]}]
    r = {x["scene"]: x for x in scene_open_report(scenes)}
    assert r["a"]["dark"] and r["a"]["opens_s"] == 1.4
    assert not r["b"]["dark"] and "c" not in r


def test_qa_flags_a_sentence_that_runs_straight_into_the_next():
    from pipeline.qa import sentence_pause_check
    ok = [{"text": "se.", "start": 0.0, "end": 0.4}, {"text": "Brief", "start": 1.0, "end": 1.3}]
    assert sentence_pause_check(ok).status == "PASS"
    bad = [{"text": "se.", "start": 0.0, "end": 0.4}, {"text": "Brief", "start": 0.4, "end": 0.7},
           {"text": "do,", "start": 0.7, "end": 0.9}, {"text": "aur", "start": 0.9, "end": 1.0}]
    c = sentence_pause_check(bad)
    assert c.status == "WARN" and "se. → Brief" in c.detail and "do," not in c.detail
