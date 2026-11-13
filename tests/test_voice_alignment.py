"""Alignment + validation of word timings from local engines / Whisper onto script tokens."""
import pytest

from pipeline.errors import TimingError
from pipeline.timing import Word, align, align_with_stats, script_mismatches, tokenize, validate_words
from pipeline.tts import Boundary as Bd
from pipeline.voice.native import Ph, words_from_phonemes


def _w(texts, step=.3):
    return [Word(t, k * step, k * step + .25) for k, t in enumerate(texts)]


def test_missing_word_is_reported_against_script():
    errs = script_mismatches("Meet Shroti Host today.", _w(["Meet", "Host", "today."]))
    assert errs == ["script word 1 'Shroti' missing from timings"]
    rep = validate_words(_w(["Meet", "Host", "today."]), 2.0, script="Meet Shroti Host today.")
    assert not rep.ok


def test_repeated_word_is_reported_and_skipped_by_align():
    errs = script_mismatches("Stop overpaying now.", _w(["Stop", "overpaying", "overpaying", "now."]))
    assert any("repeated" in e for e in errs)
    ws, st = align_with_stats("Stop overpaying now.", [Bd("Stop", 0, .2), Bd("overpaying", .2, .6),
                                                       Bd("overpaying", .6, 1.0), Bd("now", 1.1, 1.3)], 1.5)
    assert [w.text for w in ws] == ["Stop", "overpaying", "now."] and st["skipped"] == 1
    assert validate_words(ws, 1.5, script="Stop overpaying now.").ok


def test_reordered_words_are_reported():
    errs = script_mismatches("fast cheap hosting", _w(["cheap", "fast", "hosting"]))
    assert any("out of script order" in e for e in errs)
    ws, st = align_with_stats("fast cheap hosting", [Bd("cheap", 0, .2), Bd("fast", .3, .5), Bd("hosting", .6, .9)], 1)
    assert st["skipped"] + st["missing"] >= 1                      # the reorder is visible in the stats
    assert [w.text for w in ws] == ["fast", "cheap", "hosting"]
    assert all(b.start >= a.start for a, b in zip(ws, ws[1:]))      # never out of time order


def test_overlap_and_out_of_bounds_detected():
    rep = validate_words([Word("a", 0, .5), Word("b", .3, .7), Word("c", .8, 3.0)], 1.0, fix=False)
    j = " ".join(rep.errors)
    assert "overlap" in j and "outside audio" in j


def test_punctuation_only_boundaries_are_ignored_and_tokens_keep_punctuation():
    ws = align("Hello, world.", [Bd("Hello", 0, .3), Bd(",", .3, .32), Bd("world", .4, .8), Bd(".", .8, .82)], 1)
    assert [w.text for w in ws] == ["Hello,", "world."] and ws[1].start == .4


def test_numbers_against_asr_digits_and_spoken_words():
    # spoken form "forty nine rupees" vs Whisper writing "₹49"
    ws = align("forty nine rupees", [Bd("₹49", .1, .6), Bd("rupees", .6, 1.0)], 1.2)
    assert [w.text for w in ws] == ["forty", "nine", "rupees"] and ws[0].start == .1
    # display "₹49" vs a provider that splits it into two words
    ws = align("just ₹49 a month", [Bd("just", 0, .2), Bd("forty", .2, .45), Bd("nine", .45, .7), Bd("a", .7, .75),
                                    Bd("month", .75, 1)], 1.1)
    assert ws[1].text == "₹49" and ws[1].start == .2 and ws[1].end == .7


def test_contractions_split_by_asr():
    ws = align("Don’t wait", [Bd("Do", 0, .15), Bd("n't", .15, .3), Bd("wait", .35, .6)], .8)
    assert [w.text for w in ws] == ["Don’t", "wait"] and ws[0].end == .3


def test_domain_name_split_by_asr():
    ws = align("at shrotihost.in.", [Bd("at", 0, .1), Bd("Shroti", .15, .5), Bd("host.in", .5, 1.0)], 1.2)
    assert ws[1].text == "shrotihost.in." and ws[1].start == .15 and ws[1].end == 1.0


def test_misheard_indian_name_is_interpolated_not_fatal():
    ws, st = align_with_stats("Meet Priyanka Sharma today",
                              [Bd("Meet", 0, .2), Bd("Prianka", .25, .7), Bd("Sharma", .75, 1.1), Bd("today", 1.2, 1.5)], 1.6)
    assert ws[1].interpolated and .2 <= ws[1].start < ws[1].end <= .75 and st["missing"] == 1
    assert validate_words(ws, 1.6, script="Meet Priyanka Sharma today").ok


def test_too_many_unmatched_words_fail():
    with pytest.raises(TimingError):
        align("one two three four five", [Bd("one", 0, .2), Bd("xx", .2, .4), Bd("yy", .4, .6)], 1)


def _phs(s, step=.05):
    return [Ph(ch, k * step, (k + 1) * step) for k, ch in enumerate(s)]


def test_native_words_one_to_one():
    b, how = words_from_phonemes(["Meet", "Shroti."], _phs("mˈiːt ʃɹˈoʊɾi."))
    assert how == "native" and [x.text for x in b] == ["Meet", "Shroti."]
    assert b[0].start == 0.0 and b[1].start == pytest.approx(0.05 * 6) and b[1].end == pytest.approx(0.05 * 13)


def test_native_words_espeak_merge_resolved_by_dp():
    phs = _phs("mˈʌnθ, wɪððə pɹˈaɪs")
    with pytest.raises(ValueError):
        words_from_phonemes(["month,", "with", "the", "price"], phs)
    b, how = words_from_phonemes(["month,", "with", "the", "price"], phs, ["mˈʌnθ", "wˈɪð", "ðˈə", "pɹˈaɪs"])
    assert how == "native+dp" and [x.text for x in b] == ["month,", "with", "the", "price"]
    w, t = b[1], b[2]
    assert w.end <= t.start + 1e-9 and w.start == pytest.approx(0.05 * 7) and t.end == pytest.approx(0.05 * 12)


def test_tokenize_matches_spoken_words():
    assert tokenize("Shrohtee Host dot in.") == ["Shrohtee", "Host", "dot", "in."]
