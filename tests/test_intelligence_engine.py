"""Concepts (distinctness), storyboard generation (validate_storyboard, repair loop, template fallback),
providers (mock, runtime missing, privacy guards, memory guard), and the optional real-model smoke test."""
import copy
import json
import os
import urllib.request

import pytest

from pipeline.config import PROJECT_SCHEMA
from pipeline.intelligence import api
from pipeline.intelligence.brief import parse_brief
from pipeline.intelligence.concepts import distinctness, generate_concepts, pair_distinctness
from pipeline.intelligence.facts import load_facts
from pipeline.intelligence.patterns import PATTERNS
from pipeline.intelligence.planner import template_concept, template_draft
from pipeline.intelligence.providers import (DEFAULT_MODEL, LLMError, LLMUnavailable, MockProvider, OllamaProvider,
                                             OllamaRuntime)
from pipeline.intelligence.storyboard_gen import build_storyboard, compile_draft
from pipeline.schema import validate
from pipeline.storyboard import validate_storyboard

from test_intelligence_claims import DEMO, REQ


@pytest.fixture(scope="module")
def brief():
    return parse_brief(DEMO, REQ)[0]


@pytest.fixture(scope="module")
def fb():
    return load_facts("shrotihost")


def test_three_template_concepts_are_distinct(brief, fb):
    res = generate_concepts(brief, fb, None)
    cs = res["concepts"]
    assert len(cs) == 3 and res["path"] == "template"
    assert len({c["pattern"] for c in cs}) == 3 and len({c["animation_style"] for c in cs}) == 3
    assert res["distinctness"]["all_distinct"] and res["distinctness"]["min_score"] >= 0.45
    assert all(not c["requirements_missing"] for c in cs)


def test_near_duplicate_is_detected(brief, fb):
    a = template_concept(brief, fb, "before-after", 1)
    b = copy.deepcopy(a); b["id"] = "concept-2"; b["hook"] = a["hook"].replace("blank", "empty")
    p = pair_distinctness(a, b)
    assert p["near_duplicate"] and "same narrative pattern" in p["reasons"] and p["hook_similarity"] > 0.55
    assert not distinctness([a, b])["all_distinct"]


def test_llm_duplicate_concept_is_rejected_and_replaced(brief, fb):
    first = MockProvider().generate_json(system="", messages=[], schema={}, task="concept",
                                         context={"brief": brief, "allowed": ["hook-problem-solution-demo-cta"], "slot": 1}).data
    # other pattern/animation/music/CTA (the grammar forces those to differ) but the same hook and blocks
    dup = dict(first, pattern="myth-reality-explanation", animation_style="kinetic-type", music_mood="energetic",
               cta_style="offer-stamp")
    prov = MockProvider(script=[first, dup, dup, dup])            # slot 2 keeps returning a near-duplicate
    res = generate_concepts(brief, fb, prov)
    assert any(e["event"] == "rejected_near_duplicate" for e in res["log"])
    assert res["concepts"][0]["source"] == "llm" and res["concepts"][1]["source"] == "template"
    assert res["distinctness"]["all_distinct"]


def test_llm_concept_with_invented_claim_is_repaired(brief, fb):
    good = MockProvider().generate_json(system="", messages=[], schema={}, task="concept",
                                        context={"brief": brief, "allowed": ["hook-problem-solution-demo-cta"], "slot": 1}).data
    bad = dict(good, hook="The fastest WordPress hosting in India, 10x faster!")
    prov = MockProvider(script=[bad, good])
    res = generate_concepts(brief, fb, prov, n=1)
    ev = [e for e in res["log"] if e["event"] == "concept_generated"]
    assert ev[0]["invented_claims"] and not ev[1]["invented_claims"]
    assert res["concepts"][0]["source"] == "llm" and "fastest" not in res["concepts"][0]["hook"]


@pytest.mark.parametrize("pid", list(PATTERNS))
def test_template_storyboards_pass_validation(brief, fb, pid):
    c = template_concept(brief, fb, pid, 1)
    sb, fixes = compile_draft(template_draft(brief, fb, c), brief, fb, pattern=pid)
    errors, _ = validate_storyboard(sb)
    assert errors == []
    assert sb["scenes"][-1]["purpose"] == "cta" and any(b["type"] == "cta" for b in sb["scenes"][-1]["blocks"])
    assert all(len(s["blocks"]) <= 3 for s in sb["scenes"])


def test_mock_llm_storyboard_path_and_outputs(brief, fb, tmp_path):
    res = api.generate_concepts(brief, provider="mock", out_dir=tmp_path)
    sb, project, rep = api.build_storyboard(res["brief"], res["concepts"][0], provider="mock", out_dir=tmp_path)
    assert rep["path"] == "llm"
    assert validate_storyboard(sb)[0] == []
    assert validate(project, PROJECT_SCHEMA, "$") == []
    assert rep["check"]["duration_error"] is None and 29 <= rep["check"]["estimate_s"] <= 39
    # ₹39 is not on the site -> blocking review flag, attributed to the brief
    assert rep["review"]["blocking"] and rep["review"]["status"] == "BLOCKED"
    assert any(c["origin"] == "brief" and "39" in c["text"] for c in rep["review"]["needs_review"])
    assert not [c for c in rep["review"]["needs_review"] if c["origin"] == "generated"]
    for f in ("concepts.json", "concepts.md", "storyboard-preview.md", "review.json", "claims.json", "creative-plan.json"):
        assert (tmp_path / f).exists(), f
    plan = json.loads((tmp_path / "creative-plan.json").read_text())
    assert plan["music"]["mood"] in plan["music"]["vocabulary"] and plan["captions"]["style"] == "word"
    assert "BLOCKED" in (tmp_path / "storyboard-preview.md").read_text()


def _scene(brief, fb, concept, k):
    from pipeline.intelligence.planner import template_scenes
    sc = template_scenes(brief, fb, concept["pattern"])[k]
    return {x: copy.deepcopy(sc[x]) for x in ("narration", "blocks", "mood") if x in sc}


def test_templates_align_with_pattern_beats(brief, fb):
    from pipeline.intelligence.planner import template_scenes
    for pid, p in PATTERNS.items():
        assert [s["purpose"] for s in template_scenes(brief, fb, pid)] == [b["purpose"] for b in p["beats"]], pid


def test_scene_repair_loop_fixes_bad_anchor(brief, fb):
    concept = template_concept(brief, fb, "hook-problem-solution-demo-cta", 1)
    good = _scene(brief, fb, concept, 0)
    bad = copy.deepcopy(good)
    bad["blocks"][1]["at"] = "@word:banana"                       # not spoken in that scene
    prov = MockProvider(script=[bad, good])                       # later scenes: default mock answers
    r = build_storyboard(brief, concept, fb, prov)
    assert r["scene_sources"][0] == "llm+repair(1)" and r["path"] == "llm+repair"
    repair_msg = prov.calls[1]["messages"][-1]["content"]
    assert "banana" in repair_msg and "not in this scene's narration" in repair_msg
    assert validate_storyboard(r["storyboard"])[0] == []


def test_invented_scene_claim_is_fed_back_then_replaced_by_template(brief, fb):
    concept = template_concept(brief, fb, "before-after", 1)
    junk = {"narration": "Only 9 rupees a month, with 100% uptime guaranteed and 10x faster pages.",
            "blocks": [{"type": "text", "text": "Fastest hosting", "size": "m", "at": "@word:nope"}]}
    prov = MockProvider(script=[junk, junk, junk])
    r = build_storyboard(brief, concept, fb, prov, max_repairs=2)
    assert r["scene_sources"][0] == "template" and r["path"].startswith("llm+template(1/")
    fb_msgs = prov.calls[1]["messages"][-1]["content"]
    assert "unverified claim" in fb_msgs and "nope" in fb_msgs
    assert any(e["event"] == "scene_gave_up" for e in r["log"])
    assert not r["check"]["invented"] and validate_storyboard(r["storyboard"])[0] == []


def test_model_that_always_fails_falls_back_to_template(brief, fb):
    concept = template_concept(brief, fb, "myth-reality-explanation", 1)
    junk = lambda task, ctx, msgs: {"narration": "x", "blocks": [{"type": "text", "text": "y", "size": "m", "at": "@word:zzz"}]} \
        if task == "scene" else {"title": "Best hosting, 100% guaranteed", "description": "The fastest host ever.", "hashtags": ["#a1", "#b2", "#c3"]}
    r = build_storyboard(brief, concept, fb, MockProvider(responder=junk), max_repairs=1)
    assert r["path"] == "template (llm fallback)" and r["publishing_source"] == "template"
    assert validate_storyboard(r["storyboard"])[0] == []


def test_runtime_missing_falls_back_cleanly(brief, fb, monkeypatch):
    prov = OllamaProvider(DEFAULT_MODEL, host="http://127.0.0.1:9", autostart=False)
    ok, why = prov.available()
    assert not ok and why
    with pytest.raises(LLMUnavailable):
        prov.generate_json(system="", messages=[], schema={}, task="concept")
    res = generate_concepts(brief, fb, prov)
    assert res["path"] == "template" and res["log"][0]["event"] == "llm_unavailable"
    sb, project, rep = api.build_storyboard(brief, res["concepts"][0], provider=prov)
    assert rep["path"] == "template" and validate_storyboard(sb)[0] == []


def test_privacy_guards(monkeypatch):
    with pytest.raises(LLMError):
        OllamaRuntime("http://192.168.1.20:11434")                  # never send briefs off the machine
    import pipeline.intelligence.providers as P
    monkeypatch.setattr(P, "_http", lambda url, payload=None, timeout=10: {"models": [
        {"name": "glm-5.3:cloud", "remote_host": "https://ollama.com"}]} if url.endswith("/api/tags") else {"version": "x"})
    prov = OllamaProvider("glm-5.3:cloud", autostart=False)
    ok, why = prov.available()
    assert not ok and "remote" in why


def test_memory_guard_refuses_when_low(monkeypatch):
    import pipeline.intelligence.providers as P
    from pipeline.system import MemSnapshot
    monkeypatch.setattr(P, "_http", lambda url, payload=None, timeout=10: {"models": []})
    monkeypatch.setattr(P, "mem_snapshot", lambda: MemSnapshot(16384, 900, 6000, 0, 0))
    prov = OllamaProvider(DEFAULT_MODEL, autostart=False, required_mb=3000)
    with pytest.raises(LLMUnavailable, match="not enough reclaimable memory"):
        prov.memory_guard()


def _real_model_ready() -> bool:
    if os.environ.get("VIDEO_LLM_TESTS") != "1":
        return False
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            return any(m["name"] == DEFAULT_MODEL for m in json.loads(r.read())["models"])
    except OSError:
        return False


@pytest.mark.skipif(not _real_model_ready(), reason="real local model: set VIDEO_LLM_TESTS=1 with Ollama running and the model pulled")
def test_real_model_concept_smoke(brief, fb):
    prov = OllamaProvider(DEFAULT_MODEL, autostart=False)
    try:
        res = generate_concepts(brief, fb, prov, n=1)
    except LLMUnavailable as e:
        pytest.skip(e.message)
    assert len(res["concepts"]) == 1 and res["concepts"][0]["hook"]
