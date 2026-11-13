"""Display text <-> spoken text: captions keep the script, the engine gets the spoken form, and timings
of the spoken words are mapped back onto the display tokens."""
import pytest

from pipeline import tts
from pipeline.errors import TimingError
from pipeline.timing import Word, align, map_to_display, tokenize
from pipeline.brands import load_pronunciation
from pipeline.voice import pronunciation as P

BRAND = load_pronunciation("shrotihost")   # brand names live in brands/shrotihost/pronunciation.json


@pytest.mark.parametrize("display,spoken", [
    ("Launch at shrotihost.in.", "Launch at Shro-tee Host dot in."),
    ("Meet Shroti Host.", "Meet Shro-tee Host."),
    ("ShrotiHost", "Shro-tee Host"),
    ("just ₹49 a month", "just forty nine rupees a month"),
    ("₹1 only", "one rupee only"),
    ("from ₹1,299/mo", "from one thousand two hundred ninety nine rupees a month"),
    ("at 79 rupees,", "at seventy nine rupees,"),
    ("Fast NVMe hosting", "Fast N V M e hosting"),
    ("cPanel and WHMCS", "see panel and W H M C S"),
    ("a VPS with WordPress on LiteSpeed", "a V P S with Word Press on Lite Speed"),
    ("free SSL, 10GB and 1 GB", "free S S L, ten gigabytes and one gigabyte"),
    ("99.9% uptime", "ninety nine point nine percent uptime"),
    ("month—with", "month, with"),
    ("Don’t wait, Priyanka!", "Don’t wait, Priyanka!"),        # contractions and Indian names pass through
    ("visit example.co.in", "visit example dot co dot in"),
])
def test_spoken_forms(display, spoken):
    p = P.prepare(display, BRAND)
    assert p.spoken == spoken
    assert sum(n for _, n in p.groups) == len(p.spoken_tokens)
    assert [t for g, _ in p.groups for t in g] == tokenize(display)   # every display token kept, in order


def test_brand_names_come_from_the_brand_not_the_shared_dictionary():
    assert not any("shroti" in e.display.lower() for e in P.load().entries)
    assert P.prepare("Meet Shroti Host.", BRAND).spoken == "Meet Shro-tee Host."


def test_groups_are_explicit():
    p = P.prepare("Launch your site today at shrotihost.in.", BRAND)
    assert p.groups[-1] == (["shrotihost.in."], 4)
    p = P.prepare("Meet Shroti Host.", BRAND)
    assert p.groups == [(["Meet"], 1), (["Shroti", "Host."], 2)]


def test_project_overrides_win_and_change_the_fingerprint():
    base = P.load()
    over = P.load({"NVMe": "en vee em ee", "Grow": "Gro"})
    assert P.prepare("NVMe Grow plan", d=over).spoken == "en vee em ee Gro plan"
    assert base.fingerprint != over.fingerprint
    assert P.prepare("NVMe", {"NVMe": "Nuh Vee Me"}).spoken == "Nuh Vee Me"


def test_numbers_in_words():
    assert P.say_int(49) == "forty nine" and P.say_int(149) == "one hundred forty nine"
    assert P.say_int(100000) == "one hundred thousand" and P.say_number("2026") == "twenty twenty six"
    assert P.say_number("2005") == "two thousand five" and P.say_number("0.5") == "zero point five"


def test_map_to_display_spans_spoken_words():
    p = P.prepare("Visit shrotihost.in for ₹49 NVMe.", BRAND)
    spoken = [Word(t, k * .3, k * .3 + .25) for k, t in enumerate(p.spoken_tokens)]
    disp = map_to_display(p.groups, spoken)
    assert [w.text for w in disp] == ["Visit", "shrotihost.in", "for", "₹49", "NVMe."]
    dom = disp[1]
    assert dom.start == spoken[1].start and dom.end == spoken[4].end   # "Shro-tee Host dot in"
    assert disp[3].start == spoken[6].start and disp[3].end == spoken[8].end  # "forty nine rupees"
    assert not any(w.interpolated for w in disp)


def test_map_to_display_unequal_multiword_entry_is_interpolated_inside_span():
    disp = map_to_display([(["Shroti", "Host"], 3)], [Word("a", 0, .2), Word("b", .2, .4), Word("c", .5, .9)])
    assert [w.text for w in disp] == ["Shroti", "Host"] and all(w.interpolated for w in disp)
    assert disp[0].start == 0 and abs(disp[-1].end - .9) < 1e-9 and disp[0].end <= disp[1].start + 1e-9


def test_map_to_display_count_mismatch_raises():
    with pytest.raises(TimingError):
        map_to_display([(["a"], 2)], [Word("x", 0, .1)])


def test_provider_speaks_spoken_form_and_returns_display_tokens(tmp_path):
    seen = []

    class Spy(tts.MockProvider):
        def synthesize(self, text, *a, **k):
            seen.append(text)
            return super().synthesize(text, *a, **k)

    text = "Launch at shrotihost.in for just ₹49 a month—with NVMe."
    r = tts.synthesize(text, provider="mock", voice="mock", cache_dir=tmp_path, provider_obj=Spy(),
                           pronunciation=BRAND)
    assert seen == ["Launch at Shro-tee Host dot in for just forty nine rupees a month, with N V M e."]
    assert [b.text for b in r.boundaries] == tokenize(text)               # display tokens, verbatim
    sb = r.meta["spoken_boundaries"]
    assert r.boundaries[2].start == sb[2]["start"] and r.boundaries[2].end == sb[5]["end"]
    # the runner's align() over the display text is then an exact 1:1 match
    ws = align(text, r.boundaries, r.duration)
    assert [w.text for w in ws] == tokenize(text) and not any(w.interpolated for w in ws)
    assert all(0 <= w.start < w.end <= r.duration + 0.05 for w in ws)


def test_edge_does_not_get_the_pronunciation_layer():
    assert getattr(tts.EdgeProvider, "uses_pronunciation", False) is False
