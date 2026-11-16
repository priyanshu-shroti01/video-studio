"""Hinglish copy (brief `language: "hinglish"`): copy banks, cue aliases, Hindi number words, the LLM copy gate and the
speaking-rate estimate (pipeline/creative/language.py, hinglish_copy.py, pipeline/spoken_numbers.py). Mock providers only."""
from __future__ import annotations

import pytest

from pipeline.creative import build_storyboard, generate_concepts
from pipeline.creative import copywriter, hinglish_copy, language
from pipeline.creative.anchors import Anchors
from pipeline.creative.copybank import GENERIC_BANK, word_count
from pipeline.creative.industries import software, web_hosting
from pipeline.intelligence.facts import load_facts
from pipeline.intelligence.providers import MockProvider
from pipeline.spoken_numbers import normalize_hindi, spoken_index, spoken_numbers
from pipeline.timing import tokenize

VS = {"brand": "Video Studio", "brand_id": "videostudio", "product": "Video Studio", "duration_seconds": 33,
      "cta": "Explore the code", "audience": "Indian marketers and founders", "goal": "launch", "format": "short",
      "language": "hinglish"}
WP = {"brand": "Shroti Host", "brand_id": "shrotihost", "product": "WordPress Hosting", "duration_seconds": 33,
      "cta": "Get started", "format": "short", "language": "hinglish"}


def _english_lines() -> set[str]:
    out = set()
    for bank in (GENERIC_BANK, software.BANK, web_hosting.BANK):
        for fams in bank.values():
            for vs in fams.values():
                out |= {v["narration"] for v in vs}
    return out


@pytest.fixture(scope="module")
def vs():
    return generate_concepts(dict(VS), provider="none")


@pytest.fixture(scope="module")
def vs_long():
    return generate_concepts({**VS, "duration_seconds": 45, "duration_flexible": True}, provider="none")


# ---- numbers ---------------------------------------------------------------------------------------------------
def test_hindi_number_words_are_spoken_numbers():
    toks = tokenize("Studio teen ideas deta hai, aur do hazaar paanch sau log dekhte hain.")
    assert [v for _, v in spoken_numbers(toks, "hinglish")] == [3, 2500]
    assert spoken_index(toks, 3, "hinglish") == 1
    assert spoken_numbers(toks) == []                      # English: Hindi words are not numbers
    assert spoken_numbers(tokenize("31 blocking checks"), "hinglish") == [(0, 31.0)]
    assert spoken_numbers(tokenize("thirty-one checks"), "hinglish") == [(0, 31.0)]


def test_do_and_saath_are_numbers_only_before_a_noun():
    for text in ("Brief do, aur video lo.", "Brief do aur video lo.", "asli awaaz ke saath.", "Do it now."):
        assert spoken_numbers(tokenize(text), "hinglish") == [], text
    assert spoken_numbers(tokenize("mujhe do ideas chahiye"), "hinglish") == [(1, 2.0)]
    assert normalize_hindi("ke saath free SSL") == "ke saath free SSL"


def test_hindi_numbers_normalise_for_claims_but_ek_stays_a_word():
    assert normalize_hindi("teen ideas, paanch sau rupees") == "3 ideas, 500 rupees"
    assert normalize_hindi("Sab kuch ek Mac par.") == "Sab kuch ek Mac par."
    from pipeline.intelligence.claims import normalize_numbers
    assert normalize_numbers("teen ideas") == "teen ideas"                   # English text: unchanged
    assert normalize_numbers("teen ideas", "hinglish") == "3 ideas"


def test_sync_check_matches_a_number_spoken_in_hindi():
    from pipeline.sync_check import evaluate
    w = [{"text": t, "start": s, "end": s + 0.3} for t, s in (("Studio", 0.2), ("aapko", 0.8), ("teen", 2.5), ("ideas", 2.9))]
    sc = [{"id": "s", "start": 0.0, "end": 3.5, "blocks": [{"type": "text", "text": "3 ideas", "at": 0.1}]}]
    assert evaluate(sc, w, 3.5)["early_numbers"] == []                       # English: "teen" is not a number
    early = evaluate(sc, w, 3.5, lang="hinglish")["early_numbers"]
    assert early and early[0]["number"] == "3" and early[0]["spoken"] == 2.5


def test_creative_sync_rule_times_hindi_numbers():
    from pipeline.creative.rules import _spoken_time
    from pipeline.timing import Word
    ws = [Word("Saat", 1.0, 1.3), Word("din", 1.4, 1.6)]
    assert _spoken_time(ws, 7) is None and _spoken_time(ws, 7, "hinglish") == 1.0


# ---- copy bank and cue words -------------------------------------------------------------------------------------
def test_every_generic_and_software_template_has_hinglish_copy():
    for tid in GENERIC_BANK:
        assert tid in hinglish_copy.GENERIC, tid
    for tid in software.BANK:
        assert tid in hinglish_copy.SOFTWARE, tid
    missing = set(web_hosting.BANK) - set(hinglish_copy.WEB_HOSTING) - set(hinglish_copy.GENERIC)
    assert missing == {"proof-plan-compare"}                                # documented in hinglish_copy.py


def test_hinglish_copy_is_brand_neutral_and_latin_script():
    text = str(hinglish_copy.SOFTWARE) + str(hinglish_copy.WEB_HOSTING) + str(hinglish_copy.GENERIC)
    assert "Video Studio" not in text and "Shroti" not in text
    assert all(ord(ch) < 0x900 for ch in text)                               # no Devanagari in the copy


def test_english_variants_are_unchanged_by_the_language_plumbing():
    from pipeline.creative.director import studio
    en = studio({k: v for k, v in VS.items() if k != "language"}, load_facts("videostudio"))
    assert en.lang == "english" and en.wps == 2.33
    assert [v["id"] for v in en.variants("demo-app-footage")] == [v["id"] for v in software.BANK["demo-app-footage"]["app"]]
    hi = studio(dict(VS), load_facts("videostudio"))
    assert hi.lang == "hinglish" and hi.wps == language.WPS["hinglish"]
    assert {v["narration"] for v in hi.variants("demo-app-footage")}.isdisjoint(_english_lines())
    assert "sabse best" in hi.banned and "sabse best" not in en.banned


def test_cue_aliases_only_for_hinglish():
    hi = Anchors("Milo Video Studio se. Brief do, aur poori film lo.", "hinglish")
    assert hi.at(["Meet", "This"]) == "@word:Milo" and hi.has("Meet")
    en = Anchors("Milo Video Studio se. Brief do, aur poori film lo.")
    assert not en.has("Meet")
    assert Anchors("ek insaan approve karta hai", "hinglish").at(["approves"]) == "@word:approve"


def test_word_budgets_scale_with_the_speaking_rate():
    assert language.word_budget((14, 32), "english") == (14, 32)
    assert language.word_budget((14, 32), "hinglish") == (12, 27)


def test_fact_numbers_are_digits_in_hinglish():
    vals = language.localize_values({"qa_spoken": "thirty-one", "cost_spoken": "zero rupees", "period_word": "a month"}, "hinglish")
    assert vals["qa_spoken"] == "31" and vals["cost_spoken"] == "zero rupees" and vals["period_per"] == "per month"
    assert language.localize_values({"qa_spoken": "thirty-one"}, "english") == {"qa_spoken": "thirty-one"}


# ---- concepts and storyboards --------------------------------------------------------------------------------------
def _check_storyboard(brief, concept, provider="none"):
    sb, _, rep = build_storyboard(brief, concept, provider=provider)
    assert sb["language"] == "hinglish"
    bad = [r for r in rep["rules"] if r["status"] == "FAIL"]
    assert not bad, bad
    ids = {r["id"] for r in rep["rules"] if r["status"] == "PASS"}
    assert {"duration", "sync-gaps", "sync-numbers", "beats-on-words", "claims"} <= ids
    assert "2.0 words/s" in next(r["rule"] for r in rep["rules"] if r["id"] == "duration")
    assert rep["review"]["status"] == "READY_FOR_HUMAN_REVIEW", rep["review"]["reasons"]
    english = _english_lines()
    assert not [s["narration"] for s in sb["scenes"] if s["narration"] in english]
    # every beat that found its word is on a word of the Hinglish line
    for sid, used in rep["beats"].items():
        narr = next(s["narration"] for s in sb["scenes"] if s["id"] == sid)
        for u in used:
            if u["word"] and not u["word"].startswith("<"):
                assert Anchors(narr, "hinglish").has(u["word"]), (sid, u)
    return sb, rep


def test_hinglish_teaser_from_the_copy_bank(vs):
    assert vs["concepts"], vs["rejected"]
    c = vs["concepts"][0]
    assert c["pacing"]["words_per_second"] == language.WPS["hinglish"]
    sb, rep = _check_storyboard(vs["brief"], c)
    assert 30 <= rep["check"]["estimate_s"] <= 35
    narr = " ".join(s["narration"] for s in sb["scenes"])
    assert "teen ideas" in narr or "teen concepts" in narr


def test_hinglish_long_brief_gets_three_concepts(vs_long):
    assert len(vs_long["concepts"]) == 3, vs_long["rejected"]
    for c in vs_long["concepts"]:
        _check_storyboard(vs_long["brief"], c)


def test_hinglish_mock_llm_path(vs_long):
    res = generate_concepts({**VS, "duration_seconds": 45, "duration_flexible": True}, provider="mock")
    assert any(c["hook_choice"]["source"] == "llm" for c in res["concepts"])
    _, rep = _check_storyboard(res["brief"], res["concepts"][0], provider="mock")
    assert any(s["narration"] == "llm" for s in rep["copy_sources"].values())


def test_hinglish_web_hosting_concepts():
    res = generate_concepts(dict(WP), provider="none")
    assert len(res["concepts"]) >= 2, res["rejected"]
    for c in res["concepts"]:
        assert "proof-plan-compare" not in c["templates"]
        _check_storyboard(res["brief"], c)


# ---- the LLM copy assistant ----------------------------------------------------------------------------------------
def test_hinglish_prompts_ask_for_latin_hinglish():
    assert "Hinglish" in copywriter.system_prompt(lang="hinglish") and "Hinglish" not in copywriter.system_prompt()
    brief = {"product": "Video Studio", "brand": "Video Studio", "tone": "direct"}
    concept = {"name": "x", "logline": "y"}
    assert "LANGUAGE: Hinglish" in copywriter.copy_prompt(brief, concept, [], [], "hinglish")
    assert "LANGUAGE" not in copywriter.copy_prompt(brief, concept, [], [])
    from pipeline.intelligence.storyboard_gen import _language_note
    assert "Hinglish" in _language_note({"language": "hinglish"}) and _language_note({}) == ""


def test_hinglish_validation_catches_numbers_cliches_and_script():
    fb = load_facts("videostudio")
    slot = {"words": (10, 26), "allowed_numbers": [3], "headline": None}
    ok = "Apni website chuno, product likho, aur studio teen ideas deta hai, aap chuno."
    kw = {"fb": fb, "brief": dict(VS), "domain": "github.com", "banned": language.banned("hinglish")}
    assert copywriter.validate_line(slot, ok, None, **kw) == []
    bad_num = "Apni website chuno, product likho, aur studio paanch minute mein teen ideas deta hai."
    assert any("numbers [5]" in p for p in copywriter.validate_line(slot, bad_num, None, **kw))
    cliche = "Apni website chuno, product likho, aur sabse best studio teen ideas deta hai."
    assert any("sabse best" in p for p in copywriter.validate_line(slot, cliche, None, **kw))
    deva = "अपनी website चुनो, product लिखो, aur studio teen ideas deta hai, aap chuno."
    assert any("non-Latin" in p for p in copywriter.validate_line(slot, deva, None, **kw))


def test_hinglish_llm_line_with_an_invented_number_falls_back(vs_long):
    c = vs_long["concepts"][0]
    sid = next(sp["scene"] for sp in c["scene_plan"] if sp["template"] == "proof-local-stack")
    script = [{sid: {"narration": "Python, Kokoro, Remotion aur FFmpeg. Sab kuch paanch minute mein, ek hi Mac par."}}]
    _, _, rep = build_storyboard(vs_long["brief"], c, provider=MockProvider(script=script))
    src = rep["copy_sources"][sid]
    assert src["narration"] == "bank" and any("[5]" in r for r in src["reasons"])


# ---- estimates -----------------------------------------------------------------------------------------------------
def test_estimates_follow_the_storyboard_language():
    from pipeline.timeline import estimated_timing
    sc = [{"id": "s1", "purpose": "hook", "narration": "Render se pehle dekho: har frame, asli awaaz, aur har scene preview mein.",
           "blocks": []}]
    en = estimated_timing({"scenes": sc})["duration"]
    hi = estimated_timing({"scenes": sc, "language": "hinglish"})["duration"]
    assert hi > en * 1.1
    from pipeline.storyboard import validate_storyboard
    errs, _ = validate_storyboard({"language": "hinglish", "scenes": [{**sc[0], "blocks": [{"type": "text", "text": "x", "size": "m"}]}]})
    assert not [e for e in errs if "language" in e]
