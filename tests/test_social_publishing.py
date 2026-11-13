"""The publish gate for BOTH adapters: approval + valid hash + brand-bound account. A video of one brand can
never go to another brand's account. All HTTP is faked."""
import json

import pytest

from _social_fixtures import ACCOUNTS, FakeInstagram, FakeYouTube, approve, make_production, sw  # noqa: F401
from pipeline import publishing
from pipeline.productions import ApprovalError
from pipeline.social import metadata as M
from pipeline.social import service
from pipeline.social.brandcfg import AccountMismatch, NotConfigured
from pipeline.social.instagram import InstagramAdapter


def _ready(sw, brand="shrotihost", **kw):
    pid, out = make_production(sw, brand=brand, **kw)
    M.draft(sw.prod, pid, provider="template")
    approve(sw, pid)
    return pid, out


def _yt(sw, brand="shrotihost", channel=None):
    p = sw.secret(brand, "youtube", {"client_id": "cid", "refresh_token": "rt"})
    fake = FakeYouTube(channel or ACCOUNTS[brand]["youtube"])
    return publishing.YouTubeAdapter(p, http=fake), fake


def _ig(sw, brand="shrotihost", ig_user=None, fake_id=None):
    p = sw.secret(brand, "instagram", {"ig_user_id": ig_user or ACCOUNTS[brand]["instagram"], "access_token": "tok"})
    fake = FakeInstagram(ig_id=fake_id or ig_user or ACCOUNTS[brand]["instagram"])
    return InstagramAdapter(cfg_path=p, http=fake, sleep=lambda s: None), fake


def test_unapproved_production_is_refused_by_both_adapters(sw):
    pid, _ = make_production(sw)
    M.draft(sw.prod, pid, provider="template")
    for platform, (ad, fake) in (("youtube", _yt(sw)), ("instagram", _ig(sw))):
        with pytest.raises(ApprovalError):
            publishing.publish(sw.prod, pid, platform, "short", confirm=True, actor="Test Person", adapter=ad)
        assert fake.calls == []


def test_changed_video_or_metadata_after_approval_is_refused(sw):
    pid, out = _ready(sw)
    v = out / "video/final-short.mp4"
    v.write_bytes(v.read_bytes() + b"\x00")
    ad, fake = _ig(sw)
    with pytest.raises(ApprovalError):
        publishing.publish(sw.prod, pid, "instagram", "short", confirm=True, actor="Test Person", adapter=ad)
    assert fake.calls == [] and sw.prod.get(pid)["state"] == "AWAITING_APPROVAL"
    pid, out = _ready(sw)
    d = json.loads((out / "publishing/metadata.json").read_text())
    d["formats"]["short"]["instagram"]["caption"] += " edited"
    (out / "publishing/metadata.json").write_text(json.dumps(d))
    ad, fake = _yt(sw)
    with pytest.raises(ApprovalError):
        publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person", adapter=ad)
    assert fake.calls == []


def test_instagram_then_youtube_publish_and_no_duplicates(sw):
    pid, out = _ready(sw)
    ad, fake = _ig(sw)
    res = publishing.publish(sw.prod, pid, "instagram", "short", confirm=True, actor="Test Person", adapter=ad)
    approved = json.loads((out / "publishing/metadata.json").read_text())["formats"]["short"]["instagram"]
    assert res["remote_id"] == "M1" and res["sent"]["caption"] == approved["caption"]
    assert res["account"]["id"] == ACCOUNTS["shrotihost"]["instagram"] and sw.prod.get(pid)["state"] == "PUBLISHED"
    assert ("GET", ACCOUNTS["shrotihost"]["instagram"]) == fake.paths()[0]              # "who am I" first
    yt, yfake = _yt(sw)
    res = publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person", adapter=yt)
    body = yfake.bodies[0]
    snip = json.loads((out / "publishing/metadata.json").read_text())["formats"]["short"]["youtube"]["snippet"]
    assert body["snippet"] == snip and body["snippet"]["categoryId"] == "28" and body["snippet"]["tags"]
    assert body["status"]["privacyStatus"] == "private" and body["status"]["containsSyntheticMedia"] is True
    assert [m for m, _ in yfake.calls] == ["POST", "GET", "POST", "PUT"]               # token, channel, session, bytes
    with pytest.raises(ApprovalError) as e:
        publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person", adapter=_yt(sw)[0])
    assert "already published" in e.value.message
    st = service.publication_status(pid, prod=sw.prod)
    assert {(p["platform"], p["status"]) for p in st["publications"]} == {("instagram", "PUBLISHED"), ("youtube", "PUBLISHED")}


def test_instagram_refuses_landscape(sw):
    pid, _ = _ready(sw, fmt="landscape", size=(640, 360), seconds=12.0)
    ad, fake = _ig(sw)
    with pytest.raises(ApprovalError) as e:
        publishing.publish(sw.prod, pid, "instagram", "landscape", confirm=True, actor="Test Person", adapter=ad)
    assert "9:16" in e.value.message and fake.calls == [] and sw.prod.get(pid)["state"] == "APPROVED"


def test_brand_video_never_goes_to_another_brands_account(sw):
    """A Shroti Host video with credentials that belong to the ACME channel / IG account is refused before
    any byte is uploaded, and the production stays APPROVED."""
    pid, _ = _ready(sw)
    yt, yfake = _yt(sw, channel=ACCOUNTS["acme-demo"]["youtube"])          # token is ACME's channel
    with pytest.raises(AccountMismatch):
        publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person", adapter=yt)
    assert not any(m == "PUT" or "upload" in u for m, u in yfake.calls)
    ig, ifake = _ig(sw, ig_user=ACCOUNTS["acme-demo"]["instagram"])         # secrets point at ACME's IG user
    with pytest.raises(AccountMismatch):
        publishing.publish(sw.prod, pid, "instagram", "short", confirm=True, actor="Test Person", adapter=ig)
    assert ifake.calls == []                                                 # refused before any request
    ig, _ = _ig(sw)
    ig.http = lambda m, u, h=None, d=None: (200, {}, json.dumps({"id": "999", "username": "someone-else"}).encode())
    with pytest.raises(AccountMismatch):                                     # the API says the token acts for 999
        publishing.publish(sw.prod, pid, "instagram", "short", confirm=True, actor="Test Person", adapter=ig)
    assert sw.prod.get(pid)["state"] == "APPROVED"
    with sw.reg.conn() as c:
        assert c.execute("SELECT count(*) FROM publications WHERE platform!='export'").fetchone()[0] == 0
    with pytest.raises(AccountMismatch):                                     # service-level brand check too
        service.publish(pid, "youtube", "short", "Test Person", brand_id="acme-demo", prod=sw.prod, adapter=_yt(sw)[0])


def test_per_brand_secrets_and_expected_account_required(sw, monkeypatch):
    pid, _ = _ready(sw)
    with pytest.raises(NotConfigured):                                       # no .pipeline/secrets/shrotihost/youtube.json
        publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person")
    legacy = sw.ws / "secrets/youtube.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{}")
    with pytest.raises(NotConfigured) as e:
        publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person")
    assert "legacy global" in e.value.message
    monkeypatch.setattr(publishing, "expected_account", lambda b, p: None)
    with pytest.raises(NotConfigured) as e:
        publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person", adapter=_yt(sw)[0])
    assert "publishing.accounts" in e.value.message
    with pytest.raises(ApprovalError):
        publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="  ", adapter=_yt(sw)[0])


def test_publish_at_and_thumbnail(sw):
    pid, out = make_production(sw)
    M.draft(sw.prod, pid, provider="template", publish_at="2099-01-01T10:00:00+05:30", set_thumbnail=True)
    approve(sw, pid)
    yt, fake = _yt(sw)
    res = publishing.publish(sw.prod, pid, "youtube", "short", confirm=True, actor="Test Person", adapter=yt)
    st = fake.bodies[0]["status"]
    assert st["publishAt"] == "2099-01-01T10:00:00+05:30" and st["privacyStatus"] == "private"
    assert res["thumbnail"] == {"set": True} and any("thumbnails" in u for _, u in fake.calls)
