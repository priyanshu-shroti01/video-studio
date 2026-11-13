"""Metadata drafting: template + local-LLM paths, validation (lengths, hashtags, invented claims, caps,
cliches), chapters, consistency with title/description/hashtags, and the before-approval rule."""
import json
import os
import time

import pytest

from _social_fixtures import approve, make_production, sw  # noqa: F401
from pipeline.intelligence.providers import MockProvider
from pipeline.social import metadata as M


def _doc(out):
    return json.loads((out / "publishing/metadata.json").read_text())


def test_template_draft_is_valid_and_consistent(sw):
    pid, out = make_production(sw)
    res = M.draft(sw.prod, pid, provider="template")
    assert res["source"] == "template" and res["validation"]["status"] == "PASS", res["validation"]
    d = _doc(out)
    assert d["version"] == 1 and d["brand"] == "shrotihost" and d["schema"] == M.SCHEMA_ID
    yt = d["formats"]["short"]["youtube"]
    sn = yt["snippet"]
    assert len(sn["title"]) <= 100 and "WordPress Hosting in India" in sn["title"][:60]
    assert "₹69/month" in sn["title"]                                     # verified price only
    assert 0 <= sn["description"].find("shrotihost.in") <= 150
    assert sn["categoryId"] == "28" and sn["defaultLanguage"] == "en" and sn["defaultAudioLanguage"] == "en"
    assert M.tags_length(sn["tags"]) <= 500 and sn["tags"]
    assert yt["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    assert len(yt["hashtags"]) == 3 and yt["chapters"] is None             # Shorts: no chapters
    assert sn["description"].count('"Pop" by someone') == 1                # licence credits kept, de-duplicated
    ig = d["formats"]["short"]["instagram"]
    assert ig and len(ig["caption"]) <= 2200 and "Link in bio" in ig["caption"]
    assert len(ig["caption"].split("\n")[0]) <= 125 and 3 <= len(ig["hashtags"]) <= 5
    assert not {h.lower() for h in ig["hashtags"]} & {"#fyp", "#viral", "#explore"}
    assert ig["share_to_feed"] is True and ig["thumb_offset_ms"] >= 0
    # the legacy files mirror metadata.json
    assert (out / "publishing/title.txt").read_text().strip() == sn["title"]
    assert (out / "publishing/description.md").read_text() == sn["description"]
    assert (out / "publishing/hashtags.txt").read_text().split() == yt["hashtags"]
    hist = list((out / "publishing/history").glob("*/title.txt"))
    assert hist and hist[0].read_text().strip() == "Render title"           # render's original kept
    assert M.draft(sw.prod, pid, provider="template")["version"] == 2


def test_draft_rebuilds_package_and_metadata_is_approved_content(sw):
    pid, out = make_production(sw)
    M.draft(sw.prod, pid, provider="template")
    from pathlib import Path
    man = json.loads((Path(sw.prod.get(pid)["dir"]) / "approval/approval-manifest.json").read_text())
    assert "publishing/metadata.json" in man["files"]
    approve(sw, pid)                                                       # reviewer approves the drafted package
    assert sw.prod.check_approval(pid)["valid"]
    doc = _doc(out)
    doc["formats"]["short"]["youtube"]["snippet"]["title"] = "Edited after approval"
    (out / "publishing/metadata.json").write_text(json.dumps(doc))
    assert sw.prod.check_approval(pid) is None and sw.prod.get(pid)["state"] == "AWAITING_APPROVAL"


def test_draft_refused_after_approval(sw):
    pid, out = make_production(sw)
    approve(sw, pid)
    before = (out / "publishing/title.txt").read_text()
    with pytest.raises(M.MetadataLocked) as e:
        M.draft(sw.prod, pid, provider="template")
    assert "approval would be invalidated: request changes first" in e.value.message
    assert (out / "publishing/title.txt").read_text() == before and not (out / "publishing/metadata.json").exists()
    assert sw.prod.get(pid)["state"] == "APPROVED"


def test_reopen_review_is_an_explicit_human_action(sw):
    pid, _ = make_production(sw)
    approve(sw, pid)
    with pytest.raises(M.MetadataLocked):
        M.reopen_review(sw.prod, pid, "")
    M.reopen_review(sw.prod, pid, "Test Reviewer")
    assert sw.prod.get(pid)["state"] == "AWAITING_APPROVAL" and sw.prod.current_approval(pid) is None
    assert M.draft(sw.prod, pid, provider="template")["validation"]["status"] == "PASS"


def test_landscape_gets_chapters_and_no_instagram(sw):
    pid, out = make_production(sw, fmt="landscape", size=(640, 360), seconds=60.0)
    res = M.draft(sw.prod, pid, provider="template")
    assert res["validation"]["status"] == "PASS", res["validation"]
    f = _doc(out)["formats"]["landscape"]
    ch = f["youtube"]["chapters"]
    assert ch[0]["time"] == "0:00" and len(ch) >= 3
    starts = [c["start_s"] for c in ch] + [60.0]
    assert all(b - a >= 10 for a, b in zip(starts, starts[1:]))
    assert "Chapters:\n0:00 " in f["youtube"]["snippet"]["description"]
    assert f["instagram"] is None and "9:16" in f["instagram_refused"][0]
    assert f["youtube"]["kind"] == "video"


def test_short_landscape_skips_chapters(sw):
    pid, out = make_production(sw, fmt="landscape", size=(640, 360), seconds=12.0)
    M.draft(sw.prod, pid, provider="template")
    y = _doc(out)["formats"]["landscape"]["youtube"]
    assert y["chapters"] is None and "skipped" in y["chapters_note"]


def _entries(sw):
    pid, _ = make_production(sw)
    ctx = M.context(sw.prod, pid)
    copy = M.template_copy(ctx)
    return ctx, M.youtube_entry(ctx, "short", copy, M.primary_keyword(ctx), None, False), M.instagram_entry(ctx, "short", copy)


def test_validation_rejects_invented_price_and_claims(sw):
    ctx, yt, ig = _entries(sw)
    kw = M.primary_keyword(ctx)
    assert M.validate_youtube(ctx, yt, kw)["status"] == "PASS"
    yt["snippet"]["title"] = "WordPress Hosting in India from ₹39/month | Shroti Host"
    r = M.validate_youtube(ctx, yt, kw)
    assert r["status"] == "FAIL" and any("₹39/month" in e for e in r["errors"])
    ig["caption"] = "The fastest hosting in India, guaranteed.\n\nLink in bio\n\n#ShrotiHost #WebHosting #WordPressTips"
    r = M.validate_instagram(ctx, ig)
    assert r["status"] == "FAIL" and any("fastest" in e for e in r["errors"])


def test_validation_limits_hashtags_caps_and_cliches(sw):
    ctx, yt, ig = _entries(sw)
    kw = M.primary_keyword(ctx)
    bad = json.loads(json.dumps(yt))
    bad["snippet"]["title"] = "x" * 101
    bad["snippet"]["tags"] = ["wordpress hosting tag"] * 30
    bad["snippet"]["tags"] = [f"wordpress hosting {i:02d}" for i in range(30)]
    bad["hashtags"] = ["#ShrotiHost", "#WebHosting", "#WordPressHosting", "#fyp"]
    errs = " | ".join(M.validate_youtube(ctx, bad, kw)["errors"])
    assert "title is 101" in errs and "tags total" in errs and "4 hashtags" in errs and "#fyp" in errs
    bad = json.loads(json.dumps(yt))
    bad["snippet"]["description"] = "Visit our site.\n" + "pad " * 50 + "https://shrotihost.in"
    assert any("first 150" in e for e in M.validate_youtube(ctx, bad, kw)["errors"])
    bad = json.loads(json.dumps(ig))
    bad["caption"] = "UNLEASH THE POWER of hosting, a real game changer.\n\n" + "a" * 2200 + "\n\n#ShrotiHost #viral"
    errs = " | ".join(M.validate_instagram(ctx, bad)["errors"])
    assert "max 2200" in errs and "link in bio" in errs and "#viral" in errs and "cliche" in errs and "ALL-CAPS" in errs
    bad = json.loads(json.dumps(ig))
    bad["caption"] = ig["caption"] + " #a1 #b2 #c3"
    assert any("more than 5" in e for e in M.validate_instagram(ctx, bad)["errors"])
    bad = json.loads(json.dumps(yt))
    bad["status"]["publishAt"] = "2020-01-01T00:00:00Z"
    assert any("past" in e for e in M.validate_youtube(ctx, bad, kw)["errors"])


def _good_copy(**over):
    c = {"title": "WordPress Hosting in India for your first website", "hook": "Starting your first WordPress site?",
         "summary": "One-click WordPress install, LiteSpeed Cache and AccelerateWP are built specifically for WordPress.",
         "ig_hook": "Your first WordPress site, without the setup headache.",
         "ig_body": "One-click WordPress install.\n\nEvery plan renews at the listed price.",
         "first_comment": "", "tags": ["wordpress hosting india", "wordpress for beginners"]}
    c.update(over)
    return c


def test_local_llm_copy_is_used_when_valid(sw):
    pid, out = make_production(sw)
    mock = MockProvider(responder=lambda task, ctx, msgs: _good_copy())
    res = M.draft(sw.prod, pid, provider=mock, reg=sw.reg)
    assert res["source"] == "llm" and res["validation"]["status"] == "PASS", res["llm"]["log"]
    assert _doc(out)["formats"]["short"]["youtube"]["snippet"]["title"] == _good_copy()["title"]
    assert mock.calls and mock.calls[0]["task"] == "social_metadata"


def test_llm_invented_price_falls_back_to_template(sw):
    pid, out = make_production(sw)
    mock = MockProvider(responder=lambda task, ctx, msgs: _good_copy(title="WordPress Hosting in India at just ₹39/month",
                                                                     tags=["wordpress hosting", "fastest hosting"]))
    res = M.draft(sw.prod, pid, provider=mock, reg=sw.reg)
    assert res["source"] == "llm+template" and len(mock.calls) == 2       # one repair attempt, then per-field fallback
    assert any("₹39" in p for e in res["llm"]["log"] for p in e.get("problems", []))
    title = (out / "publishing/title.txt").read_text()
    assert "₹39" not in title and title.startswith("WordPress Hosting in India from ₹69/month")   # template title
    yt = _doc(out)["formats"]["short"]["youtube"]
    assert _good_copy()["summary"] in yt["snippet"]["description"]          # verified LLM fields are kept
    assert "fastest hosting" not in yt["snippet"]["tags"] and "wordpress hosting" in [t.lower() for t in yt["snippet"]["tags"]]
    mock = MockProvider(responder=lambda task, ctx, msgs: {k: "The fastest hosting, guaranteed for 30 days." for k in M.COPY_FIELDS} | {"tags": []})
    assert M.draft(sw.prod, pid, provider=mock, reg=sw.reg)["source"] == "template"   # nothing usable: all template


def test_llm_unavailable_or_render_running_uses_template(sw):
    pid, _ = make_production(sw)

    class Down(MockProvider):
        def available(self):
            return False, "Ollama server is not running"
    res = M.draft(sw.prod, pid, provider=Down(), reg=sw.reg)
    assert res["source"] == "template" and res["llm"]["log"][0]["event"] == "llm_unavailable"
    with sw.reg.conn() as c:
        c.execute("INSERT INTO sched_queue (kind,priority,pid,job_ref,state,enqueued_at,granted_at,heartbeat) "
                  "VALUES ('render',1,?,'J1','granted',?,?,?)", (os.getpid(), time.time(), time.time(), time.time()))
    mock = MockProvider(responder=lambda *a: _good_copy())
    res = M.draft(sw.prod, pid, provider=mock, reg=sw.reg)
    assert res["source"] == "template" and res["llm"]["log"][0]["event"] == "llm_skipped" and not mock.calls


def test_brand_neutral_defaults_for_a_brand_without_social_config(sw):
    pid, out = make_production(sw, brand="acme-demo", product="Widgets")
    res = M.draft(sw.prod, pid, provider="template")
    d = _doc(out)
    assert d["brand"] == "acme-demo" and "Shroti" not in json.dumps(d["formats"])
    assert res["formats"]["short"]["youtube_title"]


HUMAN = {"title": "WordPress Hosting in India: Start with ₹69/month",
         "hook": "Setting up WordPress by hand can cost you a weekend. Shroti Host installs it in one click.",
         "summary": "Managed WordPress hosting, tuned to run fast. WP Starter is ₹69/month with free SSL and daily backups.",
         "ig_hook": "Your WordPress site, live in one click.",
         "ig_body": "WP Starter: ₹69/month with free SSL and daily backups.\nSame price on renewal. 24/7 support.",
         "first_comment": "", "tags": ["one click wordpress install"]}


def test_human_copy_gets_the_same_checks_and_is_recorded_as_human(sw):
    pid, out = make_production(sw)
    res = M.draft(sw.prod, pid, copy=HUMAN)
    assert res["source"] == "human" and res["validation"]["status"] == "PASS", res["validation"]
    d = _doc(out)
    assert d["llm"]["requested"] == "human"
    assert d["formats"]["short"]["instagram"]["caption"].startswith("Your WordPress site, live in one click.")


def test_human_copy_with_an_invented_claim_is_refused_not_replaced(sw):
    pid, out = make_production(sw)
    with pytest.raises(Exception, match="human copy failed"):
        M.draft(sw.prod, pid, copy={**HUMAN, "summary": "WP Starter is ₹39/month, the cheapest in India."})
    assert not (out / "publishing/metadata.json").exists()
