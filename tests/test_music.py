"""Licensed music library: selection, licence gating, integrity."""
import json

import pytest

from pipeline import music
from pipeline.assets import license_for
from pipeline.errors import ConfigError


def test_every_mood_selects_a_publishable_brand_safe_track():
    for m in music.MOODS:
        t = music.select(m, 35)
        assert music.is_publishable(t) and t.get("brandSafe", True) and t["license"] == "CC0-1.0"


def test_test_tone_and_unsafe_tracks_never_selected():
    picked = {music.select(m, 35)["file"] for m in music.MOODS}
    assert "test-bed.wav" not in picked
    assert not any("horror" in f for f in picked)


def test_unknown_mood_rejected():
    with pytest.raises(ConfigError):
        music.select("spooky", 30)


def test_mood_resolution_is_deterministic():
    assert music.resolve("mood:corporate")[0] == music.resolve("mood:corporate")[0]


def test_library_integrity_and_licence_lookup():
    assert music.verify_library() == []
    t = music.select("corporate", 35)
    src, lic, attr = license_for(music.MUSIC_DIR / t["file"])
    assert lic == "CC0-1.0" and t["creator"] in attr and src.startswith("http")
    for rec in json.loads((music.MUSIC_DIR / "library.json").read_text())["tracks"]:
        assert set(rec["license_verified"]) == {"openverse:cc0", "landing-page:cc0"}
