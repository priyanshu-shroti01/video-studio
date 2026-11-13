import json
import shutil

import pytest

from pipeline import brand_init as BI
from pipeline.errors import ConfigError
from pipeline.paths import ROOT

HOME = b"""<html><head><title>Bloom Bakery | Fresh bread daily</title><meta name="theme-color" content="#E4572E">
<link rel="icon" href="/favicon.png"></head><body><img class="site-logo" src="/img/logo.svg" alt="Bloom logo">
<a href="/pricing">Pricing</a><a href="/products/cakes">Cakes</a><a href="https://other.example/plans">x</a>
<a href="/about">About</a></body></html>"""
LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100"><rect width="400" height="100"/></svg>'


def fake_fetch(url, timeout=30):
    if url.endswith("logo.svg"):
        return LOGO, "image/svg+xml"
    return HOME, "text/html"


@pytest.fixture
def brand_id():
    bid = "zz-test-bloom"
    yield bid
    for d in (ROOT / "brands" / bid, ROOT / "public/brands" / bid, ROOT / "knowledge" / bid):
        shutil.rmtree(d, ignore_errors=True)


def test_init_drafts_a_valid_isolated_brand(brand_id):
    r = BI.init_brand(brand_id, "https://www.bloom.example", industry="food", fetch=fake_fetch)
    assert r["name"] == "Bloom Bakery" and r["validation_errors"] == []
    prof = json.loads((ROOT / "brands" / brand_id / "brand.json").read_text())
    theme = json.loads((ROOT / "brands" / brand_id / "theme.json").read_text())
    assert prof["status"] == "draft" and prof["creative"]["industry"] == "food" and prof["outro"]["url"] == "bloom.example"
    assert theme["colors"]["brand"] == "#e4572e" and theme["logo"]["aspect"] == 4.0
    assert all(f["src"].startswith(f"brands/{brand_id}/") for fam in theme["fonts"].values() for f in fam["files"])
    facts = json.loads((ROOT / "knowledge" / brand_id / "facts.json").read_text())
    assert facts["facts"] == [] and set(facts["pages"]) == {"home", "pricing", "products-cakes"}   # same-site only
    assets = json.loads((ROOT / "brands" / brand_id / "assets.json").read_text())["assets"]
    assert assets[0]["license"].startswith("NEEDS_REVIEW")
    assert "shroti" not in json.dumps([prof, theme, facts]).lower().replace("brands/shrotihost", "")


def test_init_never_overwrites(brand_id):
    BI.init_brand(brand_id, "https://bloom.example", fetch=fake_fetch)
    with pytest.raises(ConfigError, match="never overwrites"):
        BI.init_brand(brand_id, "https://bloom.example", fetch=fake_fetch)
    with pytest.raises(ConfigError):
        BI.init_brand("shrotihost", "https://shrotihost.in", fetch=fake_fetch)


def test_https_only_and_safe_ids():
    with pytest.raises(ConfigError):
        BI.init_brand("zz-x", "http://insecure.example", fetch=fake_fetch)
    with pytest.raises(Exception):
        BI.init_brand("../etc", "https://x.example", fetch=fake_fetch)
