"""Pre-render layout fitting: overflow is found from estimated timings and repaired conservatively."""
import copy

from pipeline.config import load_project
from pipeline.layout_fit import _overflows, fit_storyboard


def _cfg_with(block_patch):
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    cfg = copy.deepcopy(cfg)
    block_patch(cfg["storyboard"])
    return cfg


def test_clean_project_has_no_overflow():
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    assert _overflows(cfg) == []


def test_long_single_word_headline_steps_down_a_size():
    def patch(sb):
        sb["scenes"][0]["blocks"][0] = {"type": "headline", "size": "xl", "words": "Supercalifragilistic?"}
    sb, fixes, unresolved = fit_storyboard(_cfg_with(patch))
    assert fixes and fixes[0]["fix"].startswith("size xl ->") and not unresolved
    assert sb["scenes"][0]["blocks"][0]["size"] != "xl"


def test_dot_separated_line_is_shortened_and_recorded():
    def patch(sb):
        cta = next(b for s in sb["scenes"] for b in s["blocks"] if b["type"] == "cta")
        cta["sub"] = "Same price on renewal · NVMe · LiteSpeed · Free SSL · Daily backups · 24/7 support · Free migration"
    sb, fixes, unresolved = fit_storyboard(_cfg_with(patch))
    f = next(x for x in fixes if x["fix"] == "shortened sub")
    assert f["from"].startswith("Same price") and len(f["to"]) < len(f["from"]) and not unresolved
