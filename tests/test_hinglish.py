"""Hinglish narration (voice.lang "hinglish"): Latin-script display words, Devanagari spoken words for Kokoro's
Hindi phonemizer, and timings that come back onto the display words. No model files needed (mock provider;
espeak comes with kokoro-onnx). Real Kokoro synthesis is in test_voice_models.py."""
import json
import re
from pathlib import Path

import pytest

from pipeline import tts
from pipeline.timing import align, norm, tokenize
from pipeline.voice import hinglish as H
from pipeline.voice import pronunciation as P
from pipeline.voice.engines import KokoroProvider, clean_phonemes
from pipeline.voice.schema import VOICE_SCHEMA, check_voice_config

ROOT = Path(__file__).resolve().parents[1]
LINE = "Aaj dekhte hain ki product video kaise banta hai. Sirf ₹49/mo mein apni website launch karo!"


def _pairs(text, overrides=None):
    p = P.prepare(text, overrides, lang="hinglish")
    out, k = [], 0
    for (disp, n), src in zip(p.groups, p.sources):
        out.append((" ".join(disp), " ".join(p.spoken_tokens[k:k + n]), src))
        k += n
    return p, out


def test_every_display_word_gets_a_devanagari_spoken_form():
    p, pairs = _pairs(LINE)
    assert p.spoken == ("आज देखते हैं कि प्रोडक्ट वीडियो कैसे बनता है. सिर्फ़ उनचास रुपये पर मंथ में अपनी वेबसाइट "
                        "लॉन्च करो!")
    assert [t for g, _ in p.groups for t in g] == tokenize(LINE)          # display tokens kept verbatim, in order
    assert sum(n for _, n in p.groups) == len(p.spoken_tokens) == len(tokenize(p.spoken))
    assert all(H.has_devanagari(s) for _, s, _ in pairs)
    assert dict((d, s) for d, s, _ in pairs)["₹49/mo"] == "उनचास रुपये पर मंथ"   # 1 display token -> 4 spoken words
    assert {src for *_, src in pairs} <= set(H.SOURCES)


@pytest.mark.parametrize("display,spoken", [
    ("₹0", "ज़ीरो रुपये"), ("₹1", "एक रुपया"), ("₹49", "उनचास रुपये"), ("₹100", "सौ रुपये"),
    ("₹1,299/month", "एक हज़ार दो सौ निन्यानवे रुपये पर मंथ"), ("₹2,50,000", "दो लाख पचास हज़ार रुपये"),
    ("99.9%", "निन्यानवे पॉइंट नौ परसेंट"), ("10GB", "दस जीबी"), ("2026", "दो हज़ार छब्बीस"),
    ("15000000", "एक करोड़ पचास लाख"),
])
def test_numbers_are_spoken_as_hindi_numbers(display, spoken):
    assert P.prepare(display, lang="hinglish").spoken == spoken


def test_hindi_numbers_0_to_99_are_complete_and_distinct():
    nums = H.lexicon()["numbers"]
    assert len(nums) == 100 and len(set(nums)) == 100 and all(H.has_devanagari(n) for n in nums)


def test_word_list_is_lowercase_latin_to_devanagari_without_clashes():
    L = H.lexicon()
    for sec in ("hindi", "english"):
        assert L[sec] and all(re.fullmatch(r"[a-z]+", k) for k in L[sec]), sec
        assert all(re.fullmatch(f"[{H.DEVA} ]+", v) for v in L[sec].values()), sec
    assert not set(L["hindi"]) & set(L["english"])
    assert len(L["hindi"]) + len(L["english"]) > 300
    raw = (ROOT / "pipeline/voice/hinglish.json").read_text(encoding="utf-8")
    dups = []

    def hook(kv):
        keys = [k for k, _ in kv]
        dups.extend(k for k in set(keys) if keys.count(k) > 1)
        return dict(kv)
    json.loads(raw, object_pairs_hook=hook)
    assert not dups


def test_ki_is_the_conjunction_after_a_verb_and_possessive_otherwise():
    assert P.prepare("dekhte hain ki", lang="hinglish").spoken == "देखते हैं कि"
    assert P.prepare("aapki website ki speed", lang="hinglish").spoken.split()[2] == "की"


@pytest.mark.parametrize("word,expected", [
    ("hosting", "होस्टिंग"), ("server", "सर्वर"), ("shop", "शॉप"), ("button", "बटन"), ("power", "पावर"),
    ("science", "सायंस"), ("options", "ऑप्शंस"), ("store", "स्टोर"), ("company", "कंपनी"), ("data", "डेटा"),
])
def test_english_words_outside_the_list_use_espeaks_english_pronunciation(word, expected, monkeypatch):
    monkeypatch.setitem(H.lexicon(), "english", {})              # force the rule path
    H.english_word.cache_clear()
    try:
        assert H.english_word(word) == expected
    finally:
        H.english_word.cache_clear()


@pytest.mark.parametrize("word,expected", [
    ("kamaao", "कमाओ"), ("aasaani", "आसानी"), ("khushiyan", "खुशियाँ"), ("dikhaiye", "दिखाइए"), ("pakki", "पक्की"),
    ("surakshit", "सुरक्षित"), ("raaton", "रातों"),
])
def test_romanised_hindi_outside_the_list_uses_spelling_rules(word, expected):
    assert H.looks_hindi(word)
    assert H.hindi_word(word) == expected
    _, pairs = _pairs(word)
    assert pairs == [(word, expected, "hindi-rules")]


@pytest.mark.parametrize("word", ["analytics", "followers", "marketing", "dashboard", "checkout", "engagement"])
def test_english_looking_words_are_not_read_with_hindi_rules(word):
    assert not H.looks_hindi(word)


def test_dictionary_brand_and_project_overrides():
    brand = {"Shroti Host": "Shro-tee Host", "shrotihost.in": "Shro-tee Host dot in"}
    _, pairs = _pairs("Shroti Host par NVMe aur cPanel, visit shrotihost.in", brand)
    got = {d: (s, src) for d, s, src in pairs}
    assert got["Shroti Host"] == ("श्रोटी होस्ट", "override")       # English respelling read as English
    assert got["NVMe"] == ("एन वी एम ई", "dictionary")
    assert got["cPanel,"] == ("सी पैनल,", "dictionary")
    assert got["shrotihost.in"][0].endswith("डॉट इन")
    # a project override in Devanagari wins over the word list and the brand respelling
    _, pairs = _pairs("Shroti Host ke saath", {**brand, "Shroti Host": "श्रोती होस्ट", "saath": "संग"})
    assert pairs[0] == ("Shroti Host", "श्रोती होस्ट", "override") and pairs[2] == ("saath", "संग", "override")
    assert P.load({"saath": "संग"}, "hinglish").fingerprint != P.load(None, "hinglish").fingerprint


def test_english_scripts_are_unchanged():
    text = "Launch at shrotihost.in for just ₹49 a month—with NVMe."
    a, b = P.prepare(text, {"shrotihost.in": "Shro-tee Host dot in"}), P.prepare(text, {"shrotihost.in": "Shro-tee Host dot in"}, lang="en-us")
    assert a.spoken == b.spoken == "Launch at Shro-tee Host dot in for just forty nine rupees a month, with N V M e."
    assert a.sources == [] and P.load().fingerprint == P.load(None, "en-us").fingerprint
    assert norm("Don’t-Wait!") == "dontwait" and norm("₹49") == "49"
    assert norm("हैं,") == "हैं" and tokenize("आज देखते हैं।") == ["आज", "देखते", "हैं।"]


def test_mock_provider_speaks_devanagari_and_returns_latin_display_tokens(tmp_path):
    seen = []

    class Spy(tts.MockProvider):
        def synthesize(self, text, *a, **k):
            seen.append(text)
            return super().synthesize(text, *a, **k)

    r = tts.synthesize(LINE, provider="mock", voice="mock", cache_dir=tmp_path, provider_obj=Spy(),
                       options={"lang": "hinglish"})
    assert seen == [P.prepare(LINE, lang="hinglish").spoken]
    assert [b.text for b in r.boundaries] == tokenize(LINE)
    ws = align(LINE, r.boundaries, r.duration)
    assert [w.text for w in ws] == tokenize(LINE) and not any(w.interpolated for w in ws)
    rs = r.meta["spoken_boundaries"]
    k = tokenize(LINE).index("₹49/mo")
    first = sum(n for _, n in P.prepare(LINE, lang="hinglish").groups[:k])
    assert r.boundaries[k].start == rs[first]["start"] and r.boundaries[k].end == rs[first + 3]["end"]


def test_voice_fingerprint_includes_the_word_list_only_for_hinglish():
    base = {"provider": "mock", "voice": "mock"}
    assert tts.voice_fingerprint(base) == tts.voice_fingerprint({**base, "lang": "en-us"})
    assert tts.voice_fingerprint(base) != tts.voice_fingerprint({**base, "lang": "hinglish"})


def test_kokoro_language_and_phoneme_clean_up():
    assert KokoroProvider.lang_for("hm_omega", "hinglish") == "hi"
    assert KokoroProvider.lang_for("hm_omega") == "en-us" and KokoroProvider.lang_for("bf_emma") == "en-gb"
    mixed = "ˈaːɟ dˈeːkʰtˌeː hɛ̃ kˈɪ (en)pɹˈɒdʌkt vˈɪdɪəʊ(hi) kˈɛːseː"
    assert clean_phonemes(mixed, "hi") == "ˈaːɟ dˈeːkʰtˌeː hɛ̃ kˈɪ pɹˈɒdʌkt vˈɪdɪəʊ kˈɛːseː"
    assert clean_phonemes("bˈʌr.aː, pˈeːr.. ɡˈʌr.h", "hi") == "bˈʌɽaː, pˈeːɽ. ɡˈʌɽh"
    assert clean_phonemes("fˈɑːɹ. (en)", "en-us") == "fˈɑːɹ. (en)"          # other languages untouched


def test_config_schema_and_checks():
    from pipeline.schema import validate
    assert not validate({"provider": "kokoro", "voice": "hm_omega", "lang": "hinglish"}, VOICE_SCHEMA)
    errs, warns = check_voice_config({"provider": "kokoro", "voice": "hm_omega", "lang": "hinglish"}, check_models=False)
    assert not errs and not any("hinglish" in w for w in warns)
    _, warns = check_voice_config({"provider": "kokoro", "voice": "am_michael", "lang": "hinglish"}, check_models=False)
    assert any("not a Hindi voice" in w for w in warns)
    errs, _ = check_voice_config({"provider": "piper", "voice": "en_GB-cori-medium", "lang": "hinglish"},
                                 check_models=False)
    assert any("needs the kokoro provider" in e for e in errs)


def test_brief_language_selects_the_hindi_voice_unless_one_is_given():
    from pipeline.api import apply_brief_voice
    from pipeline.intelligence.brief import BRIEF_SCHEMA
    from pipeline.schema import validate
    assert not validate({"brand": "b", "product": "p", "language": "hinglish"}, BRIEF_SCHEMA)
    preset = {"voice": {"provider": "kokoro", "voice": "am_michael", "rate": "+5%"}}
    v = apply_brief_voice(json.loads(json.dumps(preset)), {"language": "hinglish"})["voice"]
    assert v == {"provider": "kokoro", "voice": "hm_omega", "rate": "+5%", "lang": "hinglish"}
    v = apply_brief_voice(json.loads(json.dumps(preset)), {"language": "hinglish", "voice": "hf_alpha"})["voice"]
    assert v["voice"] == "hf_alpha" and v["lang"] == "hinglish"
    assert apply_brief_voice(json.loads(json.dumps(preset)), {"language": "english"}) == preset


def test_checklist_lists_every_transliterated_word_with_its_devanagari_form():
    from pipeline.visual_qa.review import pronunciation_checklist
    cfg = {"voice": {"provider": "kokoro", "voice": "hm_omega", "lang": "hinglish",
                     "pronunciation": {"Shroti": "श्रोती"}},
           "storyboard": {"scenes": [{"id": "s1", "narration": "Shroti par analytics dekho, sirf ₹49 mein."}]}}
    toks = tokenize(cfg["storyboard"]["scenes"][0]["narration"])
    timing = {"words": [{"text": t, "start": k * 0.5, "end": k * 0.5 + 0.4} for k, t in enumerate(toks)],
              "scene_spans": [[0, len(toks) * 0.5]]}
    md, items = pronunciation_checklist(cfg, timing)
    assert [it["display"] for it in sorted(items, key=lambda it: it["time"])] == toks
    by = {it["display"]: it for it in items}
    assert by["Shroti"]["spoken"] == "श्रोती" and by["Shroti"]["source"] == "override"
    assert by["₹49"]["spoken"] == "उनचास रुपये" and by["analytics"]["guess"]
    assert "| analytics | ऐनलिटिक्स | *guess*" in md and "Hinglish" in md
    assert md.index("analytics") < md.index("| Shroti |")                    # guesses first


# ---- Microsoft hi-IN voices (online, opt-in): mixed spoken form ----------------------------------------------
def test_mixed_form_keeps_english_words_and_writes_hindi_in_devanagari():
    from pipeline.voice import pronunciation as P
    p = P.prepare("Product video ke liye agency chahiye? Galat. Zero rupees, na API key.", None, lang="hinglish-mixed")
    assert p.spoken == "Product video के लिए agency चाहिए? गलत. Zero रुपये, ना API key."
    assert len(p.groups) == len(p.display_tokens)


def test_galat_is_said_galat_not_ghalat():
    from pipeline.voice import pronunciation as P
    assert P.prepare("Galat.", None, lang="hinglish").spoken == "गलत."


def test_edge_may_speak_hinglish_only_when_online_is_allowed():
    from pipeline.voice.schema import check_voice_config
    ok = {"provider": "edge", "voice": "hi-IN-MadhurNeural", "lang": "hinglish", "allowOnline": True}
    errs, warns = check_voice_config(ok)
    assert not errs and any("online" in w.lower() or "Microsoft" in w for w in warns)
    errs, _ = check_voice_config({**ok, "allowOnline": False})
    assert errs
    _, warns = check_voice_config({**ok, "voice": "en-US-GuyNeural"})
    assert any("not a Hindi voice" in w for w in warns)


def test_a_brief_naming_a_microsoft_hindi_voice_needs_its_own_online_consent():
    from pipeline import api
    on = api.apply_brief_voice({}, {"language": "hinglish", "voice": "hi-IN-MadhurNeural", "allow_online_voice": True})
    assert on["voice"] == {"provider": "edge", "lang": "hinglish", "voice": "hi-IN-MadhurNeural", "allowOnline": True}
    off = api.apply_brief_voice({}, {"language": "hinglish", "voice": "hi-IN-MadhurNeural"})
    assert off["voice"]["allowOnline"] is False


def test_edge_hinglish_goes_through_the_mixed_form_and_maps_back_to_display_words(tmp_path, monkeypatch):
    from pipeline import tts
    from pipeline.timing import Boundary
    seen = {}

    class FakeEdge:
        name, online, version, ext = "edge", True, "t", ".mp3"

        def synthesize(self, text, voice, rate, pitch, out, timeout, options=None):
            import subprocess
            seen["text"] = text
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=2", "-c:a", "libmp3lame",
                            str(out)], check=True)
            words = text.split()
            return [Boundary(w.strip(".,?"), round(0.1 + 0.4 * i, 3), round(0.4 + 0.4 * i, 3)) for i, w in enumerate(words)]

    r = tts.synthesize("Aaj product video banta hai.", provider="edge", voice="hi-IN-MadhurNeural", allow_online=True,
                       provider_obj=FakeEdge(), cache_dir=tmp_path, options={"lang": "hinglish"})
    assert seen["text"] == "आज product video बनता है."
    assert [b.text for b in r.boundaries] == ["Aaj", "product", "video", "banta", "hai."]


def test_everyday_hindi_drops_the_urdu_dots_but_keeps_z_and_f():
    from pipeline.voice import pronunciation as P
    assert P.prepare("Galat. Dono ki jarurat nahi. Dikkat? Mauka.", None, lang="hinglish").spoken == \
        "गलत. दोनों की जरूरत नहीं. दिक्कत? मौका."
    assert "ज़" in P.prepare("Zero", None, lang="hinglish").spoken


def test_each_scene_is_said_the_way_its_purpose_needs():
    from pipeline.voice.delivery import scene_delivery, scene_voice
    edge = {"provider": "edge", "voice": "hi-IN-MadhurNeural", "rate": "+0%", "pitch": "+0Hz"}
    assert scene_voice(edge, {"purpose": "hook"}) == {**edge, "rate": "+8%", "pitch": "+3Hz"}
    assert scene_voice(edge, {"purpose": "cta"})["rate"] == "-5%"
    assert scene_voice(edge, {"purpose": "journey"}) is edge
    assert scene_delivery({"purpose": "hook", "delivery": "calm"}) == "calm"     # the storyboard can override
    kokoro = scene_voice({"provider": "kokoro", "voice": "hm_omega", "rate": "+5%"}, {"purpose": "hook"})
    assert kokoro == {"provider": "kokoro", "voice": "hm_omega", "rate": "+13%"}   # no pitch for local engines
