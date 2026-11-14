"""Caption styles (pipeline/captions.py): schema, defaults for new productions, word-synced paging, reading-speed QA
over windows, and proof that classic projects keep exactly the same pages and props."""
import copy
import json

import pytest

from pipeline import captions as C
from pipeline.config import CAPTION_SCHEMA, load_project
from pipeline.intelligence.brief import parse_brief
from pipeline.paths import ROOT
from pipeline.qa import caption_checks
from pipeline.schema import validate
from pipeline.timeline import build_timeline, estimated_timing
from pipeline.timing import Word
from pipeline.visual_qa.checks import caption_ui_check


def _words(text: str, step: float = 0.42, gap_after_punct: float = 0.25) -> list[Word]:
    out, t = [], 0.1
    for tok in text.split():
        out.append(Word(tok, round(t, 3), round(t + step - 0.05, 3)))
        t += step + (gap_after_punct if tok[-1] in ".,!?:;" else 0)
    return out


SCRIPT = ("Meet Video Studio. A brief goes in, a finished film comes out. Then the pipeline runs the voice, the "
          "timeline and the checks before Shroti Host publishes the exact package for ₹49 a month.")


# --- schema and defaults ---------------------------------------------------------------------------------------

def test_schema_accepts_every_style_and_rejects_unknown():
    for s in C.STYLES:
        assert validate({"style": s, "uppercase": True, "emphasis": False}, CAPTION_SCHEMA, "$") == []
    assert validate({"style": "wobble"}, CAPTION_SCHEMA, "$")


def test_brief_accepts_a_caption_style():
    b, _ = parse_brief({"brand": "Video Studio", "product": "x", "captions": {"style": "highlight"}})
    assert b["captions"]["style"] == "highlight"
    with pytest.raises(Exception):
        parse_brief({"brand": "Video Studio", "product": "x", "captions": {"style": "wobble"}})


def test_default_style_resolution_brief_then_brand_then_format():
    assert C.default_style("short") == "pop"
    assert C.default_style("landscape") == "minimal"
    brand = {"creative": {"captions": {"style": "highlight"}}}
    assert C.default_style("short", brand) == "highlight"
    per_fmt = {"creative": {"captions": {"style": {"short": "karaoke"}}}}
    assert C.default_style("short", per_fmt) == "karaoke" and C.default_style("landscape", per_fmt) == "minimal"
    assert C.default_style("short", brand, {"captions": {"style": "classic"}}) == "classic"
    assert C.default_style("short", {"creative": {"captions": {"style": "nope"}}}) == "pop"   # invalid -> fallback


def test_new_project_gets_styles_explicit_values_win():
    p = C.apply_default_style({"formats": ["short"]})
    assert p["captions"]["style"] == "pop" and p["captionsByFormat"]["landscape"]["style"] == "minimal"
    p = C.apply_default_style({"formats": ["short"]}, None, {"captions": {"style": "karaoke"}})
    assert p["captions"]["style"] == "karaoke" and p["captionsByFormat"]["landscape"]["style"] == "minimal"
    p = C.apply_default_style({"formats": ["landscape"]})
    assert p["captions"]["style"] == "minimal" and "captionsByFormat" not in p
    p = C.apply_default_style({"formats": ["short"], "captions": {"style": "word"}})
    assert p["captions"]["style"] == "word"


def test_default_project_resolves_the_style_for_new_productions():
    from pipeline.api import default_project
    p = default_project({"brand": "videostudio", "id": "x1", "brief": {"format": "short"}})
    assert p["captions"]["style"] == "pop"
    assert load_project  # existing files are never rewritten: see test_existing_project_without_style_stays_classic


def test_existing_project_without_style_stays_classic():
    raw = json.loads((ROOT / "projects/shrotihost/shrotihost-short.json").read_text())
    assert "style" not in raw.get("captions", {})
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    assert C.is_kinetic(cfg["captions"].get("style")) is False
    assert cfg["captions"].get("style", "word") in C.CLASSIC_STYLES


# --- paging -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("style,cap", [("pop", 3), ("highlight", 3), ("karaoke", 4)])
def test_kinetic_pages_are_short_cover_every_word_and_break_on_punctuation(style, cap):
    ws = _words(SCRIPT)
    pages = C.pages_for({"style": style, "maxWords": 4, "maxChars": 28}, ws, ws[-1].end + 0.3,
                        names=["Video Studio", "Shroti Host"])
    assert sorted(i for p in pages for i in p.word_idx) == list(range(len(ws)))
    for p in pages:
        assert 1 <= len(p.word_idx) <= cap
        for i in p.word_idx[:-1]:       # punctuation only ever ends a page
            assert not (C.SENTENCE_END.search(ws[i].text) or C.CLAUSE_END.search(ws[i].text)), p.text(ws)
    texts = [p.text(ws) for p in pages]
    for name in ("Video Studio", "Shroti Host"):
        assert any(name in t for t in texts), (name, texts)   # never split across pages
    assert not any(t.split()[-1].lower() in {"the", "a", "of"} for t in texts if len(t.split()) > 1)


def test_capitalised_names_are_kept_together_but_sentence_starts_are_not():
    ws = _words("Built with Plus Jakarta today. Meet Video Studio now")
    spans = [(a, b) for a, b in C.protected_spans(ws)]
    assert (2, 4) in spans                                    # "Plus Jakarta"
    assert any(ws[a].text == "Video" for a, _ in spans)       # "Meet" (sentence start) is excluded
    assert not any(ws[a].text == "Meet" for a, _ in spans)


def test_classic_paging_is_byte_identical():
    ws = _words(SCRIPT)
    for style in ("word", "phrase", "classic", "minimal"):
        a = C.pages_for({"style": style, "maxWords": 4, "maxChars": 28, "hold": 0.6}, ws, ws[-1].end + 0.3)
        b = C.build_pages(ws, max_words=4, max_chars=28, hold=0.6, audio_end=ws[-1].end + 0.3)
        assert a == b


def test_classic_project_props_are_unchanged():
    """A project without a style renders exactly as before: same caption keys, same pages, same ASS karaoke."""
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    tl = build_timeline(cfg, estimated_timing(cfg["storyboard"]))
    cap = tl.props["short"]["captions"]
    assert set(cap) == {"enabled", "style", "maxWords", "fontSize", "bottomFrac", "maxWidthFrac", "pages"}
    assert cap["style"] == "word"
    cc = cfg["captions"]
    ref = C.build_pages(tl.words, max_words=cc.get("maxWords", 4), max_chars=cc.get("maxChars", 28),
                        hold=cc.get("hold", 0.6), audio_end=estimated_timing(cfg["storyboard"])["duration"])
    assert cap["pages"] == [{"start": p.start, "end": p.end, "wordIdx": p.word_idx} for p in ref]
    assert "\\k" in tl.ass["short"]


def test_kinetic_project_props_carry_style_and_short_pages():
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    cfg = copy.deepcopy(cfg)
    cfg["captions"].update(style="pop", uppercase=True)
    tl = build_timeline(cfg, estimated_timing(cfg["storyboard"]))
    cap = tl.props["short"]["captions"]
    assert cap["style"] == "pop" and cap["uppercase"] is True and "emphasis" not in cap
    assert max(len(p["wordIdx"]) for p in cap["pages"]) <= 3 or any(
        len(p["wordIdx"]) > 3 and " ".join(tl.words[i].text for i in p["wordIdx"]).startswith("Shroti Host")
        for p in cap["pages"])
    assert tl.srt.count("-->") == len(cap["pages"])


# --- reading speed --------------------------------------------------------------------------------------------------

def _pages(ws, size):
    idx = [list(range(i, min(i + size, len(ws)))) for i in range(0, len(ws), size)]
    return C._timed(idx, ws, min_dur=0.2, hold=0.6, audio_end=ws[-1].end + 0.3)


def test_window_keeps_word_synced_pages_meaningful():
    # ordinary narration (2.4 words/s): a 1-word page of "orchestrates." is ~30 chars/s on its own (a false alarm),
    # but the eye reads it in a stream: over 1.5 s windows the rate is the real ~15 chars/s
    ws = _words("Python orchestrates. Kokoro speaks. Remotion renders everything locally today.", step=0.42, gap_after_punct=0)
    pages = _pages(ws, 1)
    per_page = C.validate_pages(pages, ws, ws[-1].end + 0.3)
    windowed = C.validate_pages(pages, ws, ws[-1].end + 0.3, **C.validate_opts("pop"))
    assert per_page.max_cps > 25 and per_page.warnings
    assert windowed.max_cps <= 25 and not [w for w in windowed.warnings if "chars/s" in w]


def test_window_still_flags_genuinely_fast_speech():
    ws = _words("Internationalisation considerations notwithstanding, administrators recommend", step=0.22,
                gap_after_punct=0)
    rep = C.validate_pages(_pages(ws, 2), ws, ws[-1].end + 0.3, **C.validate_opts("pop"))
    assert any("chars/s" in w for w in rep.warnings)


def test_qa_reading_speed_uses_the_window_for_kinetic_styles(tmp_path):
    ws = _words("Python orchestrates. Kokoro speaks. Remotion renders everything locally today.", step=0.42, gap_after_punct=0)
    pages = _pages(ws, 1)
    srt = tmp_path / "c.srt"
    srt.write_text(C.to_srt(pages, ws))
    words = [w.as_dict() for w in ws]
    dur = ws[-1].end + 0.3
    classic = {c.id: c for c in caption_checks(srt, None, dur, words, 25)}
    kinetic = {c.id: c for c in caption_checks(srt, None, dur, words, 25, window=C.reading_window("pop"))}
    assert classic["captions.reading_speed"].status == "WARN"
    assert kinetic["captions.reading_speed"].status == "PASS" and "windows" in kinetic["captions.reading_speed"].detail
    assert C.reading_window("word") == 0 and C.reading_window("minimal") == 0


# --- platform UI zone ------------------------------------------------------------------------------------------------

def test_caption_ui_check_on_the_layout_manifest():
    base = {"format": "short", "width": 1080, "height": 1920}
    ok = caption_ui_check({**base, "captionBand": {"x": 108, "y": 1192.8, "w": 864, "h": 208.8}})   # classic 0.27 / 80 %
    assert ok.status == "PASS"
    low = caption_ui_check({**base, "captionBand": {"x": 140, "y": 1500, "w": 800, "h": 200}})
    rail = caption_ui_check({**base, "captionBand": {"x": 60, "y": 1100, "w": 960, "h": 200}})
    assert low.status == "WARN" and rail.status == "WARN"
