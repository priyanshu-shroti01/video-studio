"""Render contract v3 on the Python side: HUD validation, `@word:` resolution of HUD events, caption tones and
speakers, the headline caption style, the sync check and the visual-QA HUD checks.

The engine fixtures src/engine/fixtures/sample-hud-{short,landscape}.json are built from tests/fixtures/hud-storyboard.json
by this pipeline (estimated timings):  uv run python tests/test_hud.py --write"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import captions as C  # noqa: E402
from pipeline import hud as H  # noqa: E402
from pipeline import sync_check  # noqa: E402
from pipeline.contract import CAPTION_TONES, CONTRACT_VERSION, HUD_KINDS, HUD_OPS, ts_contract_version  # noqa: E402
from pipeline.storyboard import validate_storyboard  # noqa: E402
from pipeline.timeline import build_timeline, estimated_timing  # noqa: E402
from pipeline.timing import Word  # noqa: E402

SB_FILE = ROOT / "tests/fixtures/hud-storyboard.json"
FIXTURES = ROOT / "src/engine/fixtures"
# the fixture's caption looks: a Short with pop captions (tones + speaker tags), a 16:9 with headline captions
STYLES = {"short": "pop", "landscape": "headline"}


def _sb() -> dict:
    return json.loads(SB_FILE.read_text())


def _cfg(fmt: str, sb: dict | None = None, style: str | None = None) -> dict:
    from pipeline.config import load_project
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    cfg = copy.deepcopy(cfg)
    cfg["storyboard"] = sb if sb is not None else _sb()
    cfg["formats"] = [fmt]
    cfg["captions"] = {**cfg["captions"], "style": style or STYLES[fmt]}
    cfg.pop("captionsByFormat", None)
    if fmt == "landscape":
        cfg["captions"].update({"fontSize": 50, "bottomFrac": 0.07})
    return cfg


def _timeline(fmt: str, sb: dict | None = None, style: str | None = None):
    cfg = _cfg(fmt, sb, style)
    return build_timeline(cfg, estimated_timing(cfg["storyboard"]))


def fixture_props(fmt: str) -> dict:
    return _timeline(fmt).props[fmt]


# ---------------------------------------------------------------------------------------------------------------
def test_contract_v3_and_vocabularies_match_the_engine():
    assert CONTRACT_VERSION == ts_contract_version() == 3
    ts = (ROOT / "src/engine/types.ts").read_text()
    for name, py in (("HUD_KINDS", HUD_KINDS), ("HUD_OPS", HUD_OPS), ("CAPTION_TONES", CAPTION_TONES)):
        seg = ts.split(f"export const {name} = [", 1)[1].split("]", 1)[0]
        assert {x.strip().strip("'") for x in seg.split(",")} == py, name


def test_fixture_storyboard_validates():
    errs, warns = validate_storyboard(_sb())
    assert errs == []
    assert not [w for w in warns if "hud" in w.lower()]


def _with(mut):
    sb = _sb()
    mut(sb)
    return validate_storyboard(sb)[0]


@pytest.mark.parametrize("mut,needle", [
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:visit", "target": "nope", "op": "show"}), "no HUD element 'nope'"),
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:visit", "target": "terms", "op": "advance"}), "does not apply to a chips"),
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:visit", "target": "terms", "op": "add"}), ".text: the chip"),
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:banana", "target": "step", "op": "show"}), "not in this scene's narration"),
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:visit", "target": "stakes", "op": "set", "part": 0}), "needs 'value'"),
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:visit", "target": "stakes", "op": "set", "part": 5, "value": 1}), ".part: a part index"),
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:visit", "target": "step", "op": "set", "index": 9}), ".index: a step index"),
    (lambda sb: sb["scenes"][1]["hud"].append({"at": "@word:visit", "target": "step", "op": "advance"}), "advances 3× but has only 3 steps"),
    (lambda sb: sb["hud"]["elements"].append({"id": "two", "kind": "chips"}), "only one HUD element of kind 'chips'"),
    (lambda sb: sb["hud"]["elements"].append({"id": "step", "kind": "progress", "total": 3}), "duplicate HUD element id"),
    (lambda sb: sb["hud"]["elements"][2].update(total=0), ".total: an integer"),
    (lambda sb: sb["hud"]["elements"][2].update(style="segments"), "'segments' is for chapters"),
    (lambda sb: sb.pop("hud"), "HUD events need a storyboard.hud definition"),
    (lambda sb: sb["scenes"][1].update(captionTones={"banana": "danger"}), "word 'banana' is not in this scene's narration"),
    (lambda sb: sb["scenes"][1].update(captionTones={"scratch": "purple"}), "not one of"),
    (lambda sb: sb["scenes"][1].update(speaker="MOM"), "speaker 'MOM' is not in storyboard.speakers"),
    (lambda sb: sb["scenes"][0].update(speaker=[{"name": "VISITOR"}, {"name": "YOU"}]), "needs 'from'"),
])
def test_hud_and_caption_validation(mut, needle):
    errs = _with(mut)
    assert any(needle in e for e in errs), errs


def test_storyboards_without_v3_keys_give_unchanged_props():
    """No hud / captionTones / speaker: no `hud` in the props and pages with exactly start / end / wordIdx."""
    from pipeline.config import load_project
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    tl = build_timeline(cfg, estimated_timing(cfg["storyboard"]))
    p = tl.props["short"]
    assert "hud" not in p and tl.hud is None and "speakers" not in p["captions"]
    assert all(set(pg) == {"start", "end", "wordIdx"} for pg in p["captions"]["pages"])
    assert p["contractVersion"] == 3


def test_hud_events_resolve_on_their_words():
    cfg = _cfg("short")
    tm = estimated_timing(cfg["storyboard"])
    tl = build_timeline(cfg, tm)
    hud = tl.props["short"]["hud"]
    assert [e["id"] for e in hud["elements"]] == ["stakes", "step", "series", "terms"]
    starts = {w["text"].strip(".,:?!").lower(): w["start"] for w in reversed(tm["words"])}   # first occurrence
    ev = {(e["target"], e["op"], e.get("text")): e["at"] for e in hud["events"]}
    assert ev[("stakes", "show", None)] == round(starts["4"], 3)
    assert ev[("terms", "add", "TTL")] == round(starts["ttl"], 3)
    assert ev[("terms", "add", "Queue")] == round(starts["queue"], 3)
    ats = [e["at"] for e in hud["events"]]
    assert ats == sorted(ats) and all("_word" not in e for e in hud["events"])
    assert tl.storyboard_out["hud"] == hud


def test_caption_tones_terms_and_speakers():
    tl = _timeline("short")
    p = tl.props["short"]
    words = p["words"]
    tone_of = {}
    for pg in p["captions"]["pages"]:
        for wi, tn in zip(pg["wordIdx"], pg.get("tones") or [None] * len(pg["wordIdx"])):
            tone_of[wi] = tn
    by = lambda txt: [i for i, w in enumerate(words) if w["text"].strip(".,:?!") == txt]  # noqa: E731
    assert tone_of[by("4")[0]] == "danger" and tone_of[by("seconds")[0]] == "danger"
    assert tone_of[by("scratch")[0]] == "danger" and tone_of[by("fresh")[0]] == "success"
    assert tone_of[by("cache")[0]] == "term" and tone_of[by("TTL")[0]] == "term"      # chip words become terms
    assert tone_of[by("Fixed")[0]] == "success"
    assert tone_of[by("Every")[0]] is None
    # speakers: VISITOR until "Day", then YOU; a page never spans both; declared order kept
    assert list(p["captions"]["speakers"]) == ["VISITOR", "YOU"]
    day = by("Day")[0]
    for pg in p["captions"]["pages"]:
        if pg["wordIdx"][0] < day:
            assert pg["speaker"] == "VISITOR" and pg["wordIdx"][-1] < day
        elif words[pg["wordIdx"][0]]["start"] < tl.resolved[1]["start"]:
            assert pg["speaker"] == "YOU"
        else:
            assert "speaker" not in pg
    # term tones can be switched off
    sb = _sb()
    sb["hud"]["termTones"] = False
    p2 = _timeline("short", sb).props["short"]
    assert not any("term" in (pg.get("tones") or []) for pg in p2["captions"]["pages"])


def test_headline_style_builds_clause_pages():
    ws = [Word(t, i * 0.4, i * 0.4 + 0.3) for i, t in enumerate("Step 2: caching. A cache keeps a ready copy, and a TTL decides how long it stays fresh.".split())]
    pages = C.pages_for({"style": "headline", "maxWords": 4}, ws, ws[-1].end)
    assert max(len(p.word_idx) for p in pages) > 4 and all(len(p.word_idx) <= 7 for p in pages)
    assert [ws[p.word_idx[-1]].text for p in pages][:2] == ["2:", "caching."]
    p = _timeline("landscape").props["landscape"]
    assert p["captions"]["style"] == "headline"


def test_sync_check_counts_hud_events_and_catches_early_stakes():
    tl = _timeline("short")
    words = [w.as_dict() for w in tl.words]
    ok = sync_check.evaluate(tl.resolved, words, tl.duration, hud=tl.hud)
    assert ok["status"] == "PASS", sync_check.summary(ok)
    assert ok["events"] > sync_check.evaluate(tl.resolved, words, tl.duration)["events"]
    early = copy.deepcopy(tl.hud)
    first = min(w["start"] for w in words)
    for e in early["events"]:
        if e["target"] == "stakes" and e["op"] == "show":
            e["at"] = round(first, 3)                     # "4s" on screen at "Why", 4 is spoken later
    r = sync_check.evaluate(tl.resolved, words, tl.duration, hud=early)
    assert any(x["number"] == "4" for x in r["early_numbers"]), r
    # step numbers and series counts are structure, not claims
    assert {n for n, _ in H.numbers_shown(tl.hud)} == {"4", "1"}


def test_numbers_shown_lands_after_the_count():
    hud = {"elements": [{"id": "s", "kind": "stakes", "parts": [{"value": 212, "label": "applications"}]}],
           "events": [{"at": 1.0, "target": "s", "op": "show"}, {"at": 3.0, "target": "s", "op": "set", "part": 0, "value": 240}]}
    got = H.numbers_shown(hud)
    assert got[0] == ("212", pytest.approx(1.0 - H.LEAD_S)) and got[1] == ("240", pytest.approx(3.0 - H.LEAD_S + H.COUNT_S))


def test_storyboard_numbers_for_the_facts_check():
    sb = _sb()
    sb["scenes"][2]["hud"].append({"at": "@word:TTL", "target": "terms", "op": "add", "text": "HTTP 2"})
    got = {(n, w.split(":")[0]) for n, w in H.storyboard_numbers(sb)}
    assert ("4", "hud.stakes.parts[0].value") in got and ("1", "queue/hud.stakes.set") in got
    assert ("2", "caching/hud.terms") in got
    assert not any(n == "30" for n, _ in got)          # the series total is structure (a count, not a claim)


def test_layout_manifest_has_the_hud_and_qa_checks_pass(tmp_path):
    from pipeline.visual_qa import checks as V
    for fmt in ("short", "landscape"):
        f = tmp_path / f"{fmt}.json"
        f.write_text(json.dumps(fixture_props(fmt)))
        m = V.layout_manifest(f)
        assert {e["kind"] for e in m["hud"]["elements"]} == set(HUD_KINDS)
        cs = {c.id: c for c in V.static_checks(m)}
        for cid in ("layout.hud_clear", "layout.hud_safe", "layout.caption_band", "layout.safe_area", "layout.text_overflow"):
            assert cs[cid].status == "PASS", (fmt, cid, cs[cid].detail)
        if fmt == "landscape":                       # headline captions: every scene has its own top band
            assert all("captionBand" in sc for sc in m["scenes"])
        assert all(sc.get("hudBottom") for sc in m["scenes"][1:4])
        # a block moved under the HUD is caught
        bad = copy.deepcopy(m)
        hb = bad["hud"]["elements"][0]["bbox"]
        bad["scenes"][1]["blocks"][0]["bbox"] = {**hb}
        bad["scenes"][1]["blocks"][0]["visible"] = {"from": bad["scenes"][1]["start"], "to": bad["scenes"][1]["end"]}
        bad["hud"]["elements"][0]["visibleRanges"] = [[0, bad["scenes"][-1]["end"]]]
        assert {c.id: c for c in V.hud_checks(bad)}["layout.hud_clear"].status == "FAIL"


def test_committed_engine_fixtures_match_the_pipeline():
    """The engine fixtures are this pipeline's output (HUD, caption pages and tones), not hand-edited JSON."""
    for fmt in ("short", "landscape"):
        want = fixture_props(fmt)
        got = json.loads((FIXTURES / f"sample-hud-{fmt}.json").read_text())
        assert got["hud"] == want["hud"]
        assert got["captions"] == want["captions"]
        assert got["words"] == want["words"] and got["scenes"] == want["scenes"]


if __name__ == "__main__" and "--write" in sys.argv:
    for _fmt in ("short", "landscape"):
        (FIXTURES / f"sample-hud-{_fmt}.json").write_text(json.dumps(fixture_props(_fmt), ensure_ascii=False, indent=1) + "\n")
        print("wrote", FIXTURES / f"sample-hud-{_fmt}.json")
