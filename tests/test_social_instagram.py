"""Instagram Reels adapter (mocked HTTP only): container -> rupload headers -> status poll -> publish ->
permalink; ERROR/EXPIRED/timeout fail; rate limit; host restrictions; token refresh."""
import json
import os

import pytest

from _social_fixtures import ACCOUNTS, FakeInstagram, sw  # noqa: F401
from pipeline.social.brandcfg import NotConfigured
from pipeline.social.instagram import InstagramAdapter, InstagramError, refresh_token

TOKEN = "IGQ-secret-token-value"
META = {"caption": "Hook line\n\nLink in bio\n\n#A #B #C", "share_to_feed": True, "thumb_offset_ms": 4200,
        "is_ai_generated": True}


def _cfg(sw, brand="shrotihost", **over):
    return sw.secret(brand, "instagram", {"ig_user_id": ACCOUNTS[brand]["instagram"], "access_token": TOKEN,
                                          "api_host": "graph.facebook.com", "api_version": "v27.0", **over})


def _video(tmp_path):
    v = tmp_path / "reel.mp4"
    v.write_bytes(b"\x00\x00\x00\x18ftypmp42" + os.urandom(4096))
    return v


def test_resumable_reel_flow_order_headers_and_no_token_in_urls(sw, tmp_path):
    fake, sleeps = FakeInstagram(), []
    ad = InstagramAdapter(cfg_path=_cfg(sw), http=fake, sleep=sleeps.append)
    v = _video(tmp_path)
    res = ad.upload_reel(v, META)
    assert res["id"] == "M1" and res["permalink"] == "https://www.instagram.com/reel/abc/"
    assert fake.paths() == [("GET", "content_publishing_limit"), ("POST", "media"), ("POST", "rupload"),
                            ("GET", "C1"), ("GET", "C1"), ("POST", "media_publish"), ("GET", "M1")]
    create = fake.calls[1]
    assert create["url"].startswith("https://graph.facebook.com/v27.0/") and create["form"] == {
        "media_type": "REELS", "upload_type": "resumable", "caption": META["caption"], "share_to_feed": "true",
        "thumb_offset": "4200", "is_ai_generated": "true"}
    up = fake.calls[2]
    assert up["url"] == "https://rupload.facebook.com/ig-api-upload/v27.0/C1"
    assert up["headers"] == {"Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(v.stat().st_size)}
    assert up["bytes"] == v.stat().st_size
    assert fake.calls[5]["form"] == {"creation_id": "C1"}
    assert all(TOKEN not in c["url"] for c in fake.calls)                    # token only in the header
    assert TOKEN not in json.dumps(ad.sent) and len(sleeps) == 1


@pytest.mark.parametrize("status", ["ERROR", "EXPIRED"])
def test_error_or_expired_container_fails_and_is_not_published(sw, tmp_path, status):
    fake = FakeInstagram(statuses=["IN_PROGRESS", status])
    ad = InstagramAdapter(cfg_path=_cfg(sw), http=fake, sleep=lambda s: None)
    with pytest.raises(InstagramError) as e:
        ad.upload_reel(_video(tmp_path), META)
    assert status in e.value.message and ("POST", "media_publish") not in fake.paths()


def test_poll_timeout(sw, tmp_path):
    fake = FakeInstagram(statuses=["IN_PROGRESS"] * 50)
    ad = InstagramAdapter(cfg_path=_cfg(sw), http=fake, sleep=lambda s: None, poll_interval=60, poll_timeout=180)
    with pytest.raises(InstagramError) as e:
        ad.upload_reel(_video(tmp_path), META)
    assert "after 180 s" in e.value.message and ("POST", "media_publish") not in fake.paths()


def test_rate_limit_reached_uploads_nothing(sw, tmp_path):
    fake = FakeInstagram(quota=(50, 50))
    ad = InstagramAdapter(cfg_path=_cfg(sw), http=fake)
    with pytest.raises(InstagramError) as e:
        ad.upload_reel(_video(tmp_path), META)
    assert "publishing limit" in e.value.message and fake.paths() == [("GET", "content_publishing_limit")]


def test_hosts_and_permissions(sw, tmp_path):
    with pytest.raises(NotConfigured) as e:
        InstagramAdapter(cfg_path=_cfg(sw, api_host="graph.instagram.com"))
    assert "resumable" in e.value.message
    p = _cfg(sw)
    os.chmod(p, 0o644)
    with pytest.raises(NotConfigured):
        InstagramAdapter(cfg_path=p)
    fake = FakeInstagram(upload_uri="https://evil.example/upload/C1")
    ad = InstagramAdapter(cfg_path=_cfg(sw), http=fake)
    with pytest.raises(InstagramError) as e:
        ad.upload_reel(_video(tmp_path), META)
    assert "unexpected upload host" in e.value.message
    assert all("evil.example" not in c["url"] for c in fake.calls)


def test_token_refresh_writes_private_file_and_returns_no_token(sw):
    p = _cfg(sw, app_id="123", app_secret="app-secret")
    seen = []

    def http(method, url, headers=None, data=None):
        seen.append(url)
        return 200, {}, json.dumps({"access_token": "NEW-TOKEN", "token_type": "bearer", "expires_in": 5183944}).encode()
    res = refresh_token("shrotihost", cfg_path=p, http=http)
    assert "NEW-TOKEN" not in json.dumps(res) and res["token_expires_at"]
    assert seen[0].startswith("https://graph.facebook.com/v27.0/oauth/access_token?grant_type=fb_exchange_token")
    assert json.loads(p.read_text())["access_token"] == "NEW-TOKEN" and (os.stat(p).st_mode & 0o777) == 0o600
