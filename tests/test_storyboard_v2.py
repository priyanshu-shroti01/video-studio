"""Contract v2 on the Python side: new block validation, kinetic-text expansion, SFX conventions, props."""
import json
from pathlib import Path

import pytest

from pipeline.contract import BLOCK_TYPES, CONTRACT_VERSION, ts_contract_version
from pipeline.storyboard import Resolver, SceneTiming, auto_sfx, resolve_block, validate_storyboard
from pipeline.timeline import build_timeline, estimated_timing
from pipeline.timing import Word

ROOT = Path(__file__).resolve().parent.parent


def test_contract_versions_match_and_v2_blocks_known():
    assert CONTRACT_VERSION == ts_contract_version() == 2
    assert {"kinetic-text", "price-compare", "terminal", "logo-sting", "outro"} <= BLOCK_TYPES


def _sb(block, **scene):
    return {"scenes": [{"id": "s1", "purpose": "journey", "narration": "Pick the Grow plan today.", "blocks": [block], **scene}]}


@pytest.mark.parametrize("block,needle", [
    ({"type": "counter"}, "needs 'to'"),
    ({"type": "price-compare", "columns": ["A", "B"], "rows": [{"label": "x", "values": ["1"], "at": 0}]}, "1 values for 2 columns"),
    ({"type": "device", "frame": "phone"}, "needs 'asset' or 'screen'"),
    ({"type": "chart", "kind": "pie", "data": []}, "bar or line"),
    ({"type": "outro"}, "needs 'url'"),
])
def test_v2_block_requirements(block, needle):
    errs, _ = validate_storyboard(_sb(block))
    assert any(needle in e for e in errs), errs


def test_scene_camera_motion_transition_enums():
    ok = _sb({"type": "outro", "url": "shrotihost.in"}, camera="pan-left", motion="cinematic", transition="mask-wipe")
    assert validate_storyboard(ok)[0] == []
    bad = _sb({"type": "outro", "url": "x"}, camera="zoom-crazy")
    assert validate_storyboard(bad)[0]


def _st():
    ws = [Word("Pick", 1.0, 1.2), Word("the", 1.2, 1.3), Word("Grow", 1.3, 1.6), Word("plan", 1.6, 1.9), Word("today.", 2.0, 2.4)]
    return SceneTiming("s", 0.8, 3.0, 1.0, 2.4, ws)


def test_kinetic_text_words_follow_speech_with_emphasis():
    b = resolve_block({"type": "kinetic-text", "words": "Pick the Grow plan", "emphasis": ["Grow"]}, Resolver(_st(), {}), 0, 30)
    assert [w["text"] for w in b["words"]] == ["Pick", "the", "Grow", "plan"]
    assert b["words"][2]["emphasis"] and abs(b["words"][2]["at"] - 1.24) < 1e-6 and "emphasis" not in b["words"][0]


def test_v2_auto_sfx_conventions():
    snd = json.loads((ROOT / "brands/shrotihost/theme.json").read_text())["sfx"]
    blocks = [{"type": "terminal", "at": 1.0, "lines": [{"text": "wp core install", "kind": "cmd", "at": 1.0, "typeEnd": 1.8},
                                                       {"text": "Success", "kind": "ok", "at": 2.0}]},
              {"type": "logo-sting", "at": 2.2}, {"type": "outro", "at": 2.4, "url": "x", "urlAt": 2.8}]
    kinds = [e["kind"] for e in auto_sfx(0, _st(), blocks, snd)]
    assert kinds.count("keys") >= 5 and "success" in kinds and "impact" in kinds and kinds.count("shimmer") == 2


def test_timeline_emits_v2_watermark_and_motion():
    from pipeline.config import load_project
    cfg, _ = load_project("projects/shrotihost/shrotihost-short.json")
    cfg = {**cfg, "motion": "cinematic"}
    tl = build_timeline(cfg, estimated_timing(cfg["storyboard"]))
    p = tl.props["short"]
    assert p["contractVersion"] == 2 and p["motion"] == "cinematic"
    assert p["watermark"]["policy"] == "platform" and p["watermark"]["variant"] == "mark"
