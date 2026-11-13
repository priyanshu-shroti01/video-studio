"""Multi-brand isolation and static brand validation."""
import copy
import json
from pathlib import Path

import pytest

from pipeline import brands
from pipeline.config import load_project
from pipeline.errors import ConfigError

ROOT = Path(__file__).resolve().parent.parent


def _project(tmp_name, brand, storyboard):
    sb = ROOT / "projects" / f"{tmp_name}.storyboard.json"
    pj = ROOT / "projects" / f"{tmp_name}.json"
    sb.write_text(json.dumps(storyboard))
    pj.write_text(json.dumps({"name": tmp_name, "brand": brand, "preset": "shorts", "storyboard": f"projects/{sb.name}"}))
    return pj, sb


SB = {"scenes": [{"id": "s1", "purpose": "hook", "narration": "Hello there.",
                  "blocks": [{"type": "logo", "variant": "onDark"}]}]}


def test_both_brands_are_valid_and_listed():
    assert {"shrotihost", "acme-demo"} <= set(brands.list_brands())
    for b in ("shrotihost", "acme-demo"):
        theme = json.loads((ROOT / "brands" / b / "theme.json").read_text())
        assert brands.validate_brand(b, theme) == []


def test_cross_brand_asset_reference_is_rejected():
    sb = copy.deepcopy(SB)
    sb["scenes"][0]["blocks"].append({"type": "image", "asset": "brands/shrotihost/logos/logo-on-dark.svg"})
    pj, sbf = _project("isotest-acme", "acme-demo", sb)
    try:
        with pytest.raises(ConfigError) as e:
            load_project(pj.relative_to(ROOT))
        assert "another brand" in e.value.detail
    finally:
        pj.unlink(); sbf.unlink()


def test_theme_pointing_at_other_brand_fails_validation():
    theme = json.loads((ROOT / "brands/acme-demo/theme.json").read_text())
    theme["logo"]["onDark"] = "brands/shrotihost/logos/logo-on-dark.svg"
    assert any("cross-brand" in e for e in brands.validate_brand("acme-demo", theme))


def test_distorting_logo_aspect_is_caught():
    theme = json.loads((ROOT / "brands/shrotihost/theme.json").read_text())
    theme["logo"]["aspect"] = 3.0
    assert any("distort" in e for e in brands.validate_brand("shrotihost", theme))


def test_shared_roots_allowed_for_every_brand():
    assert brands.asset_allowed("acme-demo", "audio/kit/hit/x.wav")
    assert brands.asset_allowed("acme-demo", "public/shared/ui/frame.svg")
    assert not brands.asset_allowed("acme-demo", "public/brands/shrotihost/logos/icon.svg")


def test_invalid_watermark_policy(monkeypatch):
    monkeypatch.setattr(brands, "load_profile", lambda b: {"assetRoots": ["public/brands/shrotihost/"],
                                                            "watermark": {"policy": "sparkle"}, "publishing": {}})
    theme = json.loads((ROOT / "brands/shrotihost/theme.json").read_text())
    assert any("watermark policy" in e for e in brands.validate_brand("shrotihost", theme))
