import pytest

from pipeline import captions as C
from pipeline.errors import TimingError
from pipeline.timing import Word, align, number_words, pause_cuts, shift_for_cuts, tokenize, validate_words
from pipeline.tts import Boundary as Bd


def test_exact_alignment_keeps_script_punctuation():
    ws = align("Stop overpaying, now!", [Bd("Stop", .1, .4), Bd("overpaying", .4, 1.0), Bd("now", 1.2, 1.5)], 2.0)
    assert [w.text for w in ws] == ["Stop", "overpaying,", "now!"]
    assert [w.start for w in ws] == [.1, .4, 1.2] and not any(w.interpolated for w in ws)


def test_merged_boundary_is_split_inside_its_measured_span():
    ws = align("Building a website", [Bd("Building a", 0.1, 0.6), Bd("website", 0.6, 1.0)], 1.2)
    assert [w.text for w in ws] == ["Building", "a", "website"]
    assert ws[0].start == 0.1 and abs(ws[1].end - 0.6) < 1e-9 and ws[0].interpolated and ws[1].interpolated
    assert ws[0].end <= ws[1].start + 1e-9


def test_split_boundary_is_joined():
    ws = align("visit shrotihost.in today", [Bd("visit", 0, .3), Bd("shrotihost", .3, .8), Bd(".", .8, .85),
                                             Bd("in", .85, 1.0), Bd("today", 1.1, 1.4)], 1.5)
    assert [w.text for w in ws] == ["visit", "shrotihost.in", "today"]
    assert ws[1].start == .3 and ws[1].end == 1.0


def test_numbers_match_spelled_out_provider_text():
    assert number_words(49) == "fortynine" and number_words(149) == "onehundredfortynine"
    ws = align("just ₹49 a month", [Bd("just", 0, .2), Bd("forty-nine", .2, .7), Bd("a", .7, .75), Bd("month", .75, 1)], 1.1)
    assert ws[1].text == "₹49" and ws[1].start == .2


def test_contractions_and_curly_apostrophes():
    ws = align("don’t wait", [Bd("don't", 0, .3), Bd("wait", .3, .6)], .8)
    assert [w.text for w in ws] == ["don’t", "wait"] and ws[0].start == 0


def test_em_dash_join_is_two_spoken_words():
    assert tokenize("a month—with the") == ["a", "month—", "with", "the"]


def test_missing_timestamps_interpolate_within_gap_and_limit_enforced():
    ws = align("one two three four five six", [Bd("one", 0, .2), Bd("two", .2, .4), Bd("four", .9, 1.1),
                                                Bd("five", 1.1, 1.3), Bd("six", 1.3, 1.5)], 1.6)
    three = ws[2]
    assert three.text == "three" and three.interpolated and .4 <= three.start < three.end <= .9
    with pytest.raises(TimingError):
        align("a b c d e f g h", [Bd("a", 0, .1), Bd("h", 1, 1.1)], 1.2)


def test_no_timestamps_at_all_is_transient_error():
    with pytest.raises(TimingError) as e:
        align("hello there", [], 1.0)
    assert e.value.transient


def test_validation_detects_impossible_timestamps():
    ws = [Word("a", 0, .5), Word("b", .4, .9), Word("c", .3, .6), Word("d", 1.0, 9.0)]
    rep = validate_words(ws, 2.0, fix=False)
    assert not rep.ok
    joined = " ".join(rep.errors)
    assert "overlap" in joined and "order broken" in joined and "outside audio" in joined


def test_validation_fixes_small_overlaps():
    ws = [Word("a", 0, .52), Word("b", .5, .9)]
    rep = validate_words(ws, 1.0)
    assert rep.ok and rep.fixed_overlaps == 1 and ws[0].end == .5


def test_pause_compression_shifts_following_words_exactly():
    ws = [Word("a", 0, .5), Word("b", 2.0, 2.4), Word("c", 2.5, 3.0)]
    cuts = pause_cuts(ws, 0.35)
    assert len(cuts) == 1 and abs(cuts[0][1] - (1.5 - .35)) < 1e-9
    shift_for_cuts(ws, cuts)
    assert abs(ws[1].start - (0.5 + .35)) < 1e-9 and abs(ws[2].start - ws[1].start - .5) < 1e-9


def _words(texts, step=.4):
    return [Word(t, i * step, i * step + .3) for i, t in enumerate(texts)]


def test_pages_break_on_sentences_and_respect_max_words():
    ws = _words("One two. Three four five six seven".split())
    pages = C.build_pages(ws, max_words=4, audio_end=3.0)
    assert [p.text(ws) for p in pages] == ["One two.", "Three four five six", "seven"]
    assert pages[-1].end <= 3.0


def test_pages_never_extend_beyond_voiceover():
    ws = _words(["a", "b", "c"])
    pages = C.build_pages(ws, hold=5, audio_end=1.2)
    assert all(p.end <= 1.2 for p in pages)
    assert not C.validate_pages(pages, ws, 1.2).errors


def test_srt_and_ass_are_valid_and_complete():
    ws = _words("Fast NVMe hosting for everyone today".split())
    pages = C.build_pages(ws, max_words=3, audio_end=3.0)
    srt = C.to_srt(pages, ws)
    cues = C.parse_srt(srt)
    assert len(cues) == len(pages) and " ".join(t for *_, t in cues).split() == [w.text for w in ws]
    ass = C.to_ass(pages, ws, width=1080, height=1920, font="Plus Jakarta Sans", font_size=66, bottom_frac=.27,
                   highlight="#cf6cf2")
    assert "[Script Info]" in ass and ass.count("Dialogue:") == len(pages) and "\\k" in ass
    assert "MarginV" in ass and ",518,1" in ass  # 27% of 1920


def test_invalid_caption_timings_are_reported():
    ws = _words(["a", "b", "c", "d"])
    bad = [C.Page(0, 1.0, [0, 1]), C.Page(.8, 9.0, [2, 3])]
    rep = C.validate_pages(bad, ws, 2.0)
    assert any("overlap" in e for e in rep.errors) and any("after the voiceover" in e for e in rep.errors)


def test_fast_reading_speed_warns():
    ws = [Word("supercalifragilistic", 0, .1), Word("expialidocious", .1, .2)]
    rep = C.validate_pages([C.Page(0, .3, [0, 1])], ws, 1.0, max_cps=25)
    assert rep.warnings and rep.max_cps > 25


def test_invalid_srt_raises():
    with pytest.raises(ValueError):
        C.parse_srt("this is not srt\nat all")
