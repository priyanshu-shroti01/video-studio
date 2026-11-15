"""Local Video Studio HTTP server: auth, DNS-rebinding/Host checks, JSON-only writes, file confinement,
and the full brief -> storyboard -> (simulated render) -> review -> approve -> export workflow over HTTP.
Nothing here renders, calls an LLM or touches the network."""
import http.client
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import pytest

from pipeline import api
from pipeline.errors import PipelineError
from pipeline.paths import OUTPUT_DIR, ROOT
from studio import server as S

STORYBOARD = {"version": 1, "title": "Studio test", "scenes": [
    {"id": "hook", "purpose": "hook", "narration": "Fast hosting for your website.",
     "blocks": [{"type": "headline", "size": "xl", "words": "Fast hosting", "at": "@word:Fast"}]},
    {"id": "cta", "purpose": "cta", "brandBar": True, "narration": "Start today at shrotihost.in.",
     "blocks": [{"type": "logo", "variant": "onDark", "width": 720},
                {"type": "cta", "text": "Get started", "url": "shrotihost.in", "urlAt": "@end-1.0"}]}]}


@pytest.fixture
def studio(registry, monkeypatch):
    import pipeline.productions as P
    base = OUTPUT_DIR / f"studio-test-{uuid.uuid4().hex[:8]}"     # inside output/ so safe_output_file serves it
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", base / "productions")
    srv = S.make_server(0)
    srv.quiet = True
    srv.start_background()
    yield srv, base
    srv.shutdown()
    srv.server_close()
    shutil.rmtree(base, ignore_errors=True)


def req(srv, method, path, body=None, *, cookie=True, host=None, ctype="application/json", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    h = {"Host": host if host is not None else f"127.0.0.1:{srv.port}", **(headers or {})}
    if cookie is True:
        h["Cookie"] = f"{S.COOKIE}={srv.token}"
    elif isinstance(cookie, str):
        h["Cookie"] = cookie
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h["Content-Type"] = ctype
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        js = json.loads(raw) if raw else None
    except ValueError:
        js = None
    return r.status, dict(r.getheaders()), js, raw


# ---- authentication ------------------------------------------------------------------------------
def test_opening_the_address_signs_in_without_a_token_but_other_sites_cannot(studio):
    """The dashboard opens in any browser at http://127.0.0.1:<port>/ (no token in the URL). A navigation that
    another website starts gets no cookie, and the API stays closed without the cookie."""
    srv, _ = studio
    assert srv.url == f"http://127.0.0.1:{srv.port}/" and "token" not in srv.url
    for site in (None, "none"):
        st, h, _, _ = req(srv, "GET", "/", cookie=False, headers={"Sec-Fetch-Site": site} if site else None)
        assert st in (200, 503)
        ck = h.get("Set-Cookie", "")
        assert f"{S.COOKIE}={srv.token}" in ck and "HttpOnly" in ck and "SameSite=Strict" in ck
    for site in ("cross-site", "same-site"):
        st, h, _, _ = req(srv, "GET", "/", cookie=False, headers={"Sec-Fetch-Site": site})
        assert st == 403 and "Set-Cookie" not in h
    st, h, _, _ = req(srv, "GET", "/", cookie=False, headers={"Origin": "https://evil.example"})
    assert st == 403 and "Set-Cookie" not in h
    assert req(srv, "GET", "/api/dashboard", cookie=False)[0] == 401
    assert req(srv, "GET", "/", cookie=False, host="evil.example")[0] == 421


def test_token_is_exchanged_for_httponly_samesite_cookie(studio):
    srv, _ = studio
    assert req(srv, "GET", "/?token=wrong", cookie=False)[0] == 403
    st, h, _, _ = req(srv, "GET", f"/?token={srv.token}", cookie=False)
    assert st == 303 and h["Location"] == "/"
    ck = h["Set-Cookie"]
    assert f"{S.COOKIE}={srv.token}" in ck and "HttpOnly" in ck and "SameSite=Strict" in ck
    st, h, _, raw = req(srv, "GET", "/")
    if (S.DIST_DIR / "app.js").exists():
        assert st == 200 and b'id="root"' in raw
    else:
        assert st == 503
    csp = h["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert h["X-Content-Type-Options"] == "nosniff"


def test_every_api_call_needs_the_token(studio):
    srv, _ = studio
    for path in ("/api/dashboard", "/api/productions", "/api/jobs", "/api/storyboard/schema",
                 "/files/public/brands/shrotihost/logos/icon.svg", "/static/app.js"):
        assert req(srv, "GET", path, cookie=False)[0] == 401, path
        assert req(srv, "GET", path, cookie=f"{S.COOKIE}=not-the-token")[0] == 401, path
    st, _, js, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "x"}}, cookie=False)
    assert st == 401 and js["error"]["code"] == "UNAUTHORIZED"
    assert req(srv, "GET", "/api/session")[0] == 200
    assert req(srv, "GET", "/api/session", cookie=False, headers={"Authorization": f"Bearer {srv.token}"})[0] == 200


def test_wrong_host_header_is_rejected(studio):
    srv, _ = studio
    for host in ("evil.example", f"evil.example:{srv.port}", f"127.0.0.1:{srv.port + 1}", f"192.168.1.5:{srv.port}", ""):
        assert req(srv, "GET", "/api/session", host=host)[0] == 421, host
    assert req(srv, "GET", "/api/session", host=f"localhost:{srv.port}")[0] == 200


def test_writes_must_be_same_origin_json(studio):
    srv, _ = studio
    body = {"brand": "shrotihost", "brief": {"product": "x"}}
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        st, _, js, _ = req(srv, "POST", "/api/productions", json.dumps(body).encode(), ctype=ctype)
        assert st == 415 and js["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE", ctype
    assert req(srv, "POST", "/api/productions", body, headers={"Origin": "https://evil.example"})[0] == 403
    assert req(srv, "POST", "/api/productions", body, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert req(srv, "POST", "/api/productions", b"{not json")[0] == 400
    st, h, _, _ = req(srv, "OPTIONS", "/api/productions", headers={"Origin": "https://evil.example"})
    assert st == 405 and not any(k.lower().startswith("access-control") for k in h)
    assert req(srv, "DELETE", "/api/productions")[0] == 405


# ---- file serving --------------------------------------------------------------------------------
def test_file_serving_is_confined_to_output_and_public(studio, tmp_path):
    srv, base = studio
    (base / "job/video").mkdir(parents=True)
    ok = base / "job/video/final-short.mp4"
    ok.write_bytes(b"0123456789" * 100)
    (base / "job/secrets").mkdir()
    (base / "job/secrets/token.txt").write_text("s3cret")
    (base / "job/escape.txt").symlink_to(ROOT / "pyproject.toml")
    rel = base.relative_to(ROOT)
    st, h, _, raw = req(srv, "GET", f"/files/{rel}/job/video/final-short.mp4")
    assert st == 200 and raw == ok.read_bytes() and h["X-Content-Type-Options"] == "nosniff"
    assert h["Content-Security-Policy"].startswith("sandbox")
    st, h, _, raw = req(srv, "GET", f"/files/{rel}/job/video/final-short.mp4", headers={"Range": "bytes=10-19"})
    assert st == 206 and raw == b"0123456789" and h["Content-Range"] == "bytes 10-19/1000"
    assert req(srv, "GET", "/files/public/brands/shrotihost/logos/icon.svg")[0] == 200
    refused = ["pyproject.toml", "pipeline/api.py", "studio/server.py", ".pipeline/registry.db", ".pipeline/secrets/youtube.json",
               "output/../pyproject.toml", "output/%2e%2e/pyproject.toml", "public/../pipeline/paths.py",
               f"{rel}/job/secrets/token.txt", f"{rel}/job/escape.txt", "%2Fetc%2Fpasswd", "/etc/passwd",
               str(tmp_path / "x.txt"), "output/.hidden", "output/%00x"]
    for p in refused:
        st, _, _, raw = req(srv, "GET", f"/files/{p}")
        assert st in (403, 404), (p, st)
        assert b"s3cret" not in raw and b"[project]" not in raw
    for p in ("../server.py", "..%2Fserver.py", "app.js%00", "x.html"):
        assert req(srv, "GET", f"/static/{p}")[0] == 404, p


# ---- workflow ------------------------------------------------------------------------------------
def _simulate_completed_job(base: Path, pid: str) -> Path:
    """What api.run_production_job does after a real render (files as in tests/test_v030_core.py)."""
    from pipeline.jobs import Registry
    from pipeline.productions import Productions, flags_from_job
    reg = Registry()
    job = reg.create("studio-demo", f"k{time.time()}", {}, None, base / "jobs")
    out = Path(job["output_dir"])
    for d in ("video", "publishing", "captions", "reports", "assets", "previews/short"):
        (out / d).mkdir(parents=True, exist_ok=True)
    (out / "video/final-short.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + os.urandom(2048))
    (out / "publishing/thumbnail.png").write_bytes(b"\x89PNG" + os.urandom(64))
    (out / "publishing/title.txt").write_text("Fast hosting\n")
    (out / "publishing/description.md").write_text("Desc\n")
    (out / "publishing/hashtags.txt").write_text("#hosting #India\n")
    (out / "captions/captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nFast hosting\n")
    (out / "reports/qa-report.json").write_text(json.dumps({"status": "PASS", "formats": [
        {"format": "short", "counts": {"PASS": 1, "WARN": 1, "FAIL": 0},
         "checks": [{"id": "file.nonempty", "status": "PASS", "detail": "ok"},
                    {"id": "audio.loudness", "status": "WARN", "detail": "-15.2 LUFS"}]}]}))
    (out / "reports/QA_REPORT.md").write_text("ok")
    (out / "reports/audio-report.json").write_text(json.dumps({"mix": {"integrated_lufs": -14.0, "true_peak_dbtp": -1.6}}))
    (out / "assets/manifest.json").write_text(json.dumps({"assets": [{"path": "audio/music/x.mp3", "license": "CC0"}]}))
    for s in ["PREPARING", "GENERATING_AUDIO", "BUILDING_TIMELINE", "RENDERING", "POST_PROCESSING", "QA", "COMPLETED"]:
        reg.transition(job["id"], s)
    reg.update(job["id"], qa_status="PASS")
    prod = Productions(reg)
    prod.transition(pid, "RENDERING")
    prod.update(pid, job_id=job["id"])
    prod.transition(pid, "QA_COMPLETE")
    flags_from_job(prod, pid, out)
    return out


class _NoYouTube:
    def __init__(self, *a, **k):
        from pipeline.publishing import NotConfigured
        raise NotConfigured("YouTube is not configured (test)")


def test_end_to_end_workflow_over_http(studio, monkeypatch):
    srv, base = studio
    from pipeline import publishing
    monkeypatch.setattr(publishing, "YouTubeAdapter", _NoYouTube)      # never reach a real account

    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "studio-e2e",
                                                         "brief": {"product": "NVMe hosting", "format": "short", "duration_seconds": 30}})
    assert st == 200 and p["state"] == "DRAFT", p
    pid = p["id"]
    assert req(srv, "POST", "/api/productions", {"brand": "other-brand", "brief": {"product": "x"}})[0] == 400
    assert req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "x", "duration_seconds": "9"}})[0] == 400

    bad = json.loads(json.dumps(STORYBOARD))
    bad["scenes"][0]["blocks"][0]["at"] = "@word:nothere"
    st, _, js, _ = req(srv, "PUT", f"/api/productions/{pid}/storyboard", {"storyboard": bad})
    assert st == 422 and any("scenes[0]" in e and "nothere" in e for e in js["error"]["errors"]), js
    st, _, js, _ = req(srv, "POST", f"/api/productions/{pid}/storyboard/validate", {"storyboard": bad})
    assert st == 200 and js["errors"]

    st, _, js, _ = req(srv, "PUT", f"/api/productions/{pid}/storyboard", {"storyboard": STORYBOARD})
    assert st == 200 and len(js["hash"]) == 64, js
    assert req(srv, "PUT", f"/api/productions/{pid}/storyboard", {"storyboard": STORYBOARD})[0] == 200   # keeps history
    st, _, d, _ = req(srv, "GET", f"/api/productions/{pid}")
    assert d["state"] == "STORYBOARD_READY" and d["storyboard"]["scenes"][0]["id"] == "hook" and len(d["history"]) == 1
    assert d["published"] is False

    out = _simulate_completed_job(base, pid)
    assert req(srv, "POST", f"/api/productions/{pid}/approve", {"reviewer": "Priyanshu"})[0] == 409   # QA_COMPLETE
    st, _, m, _ = req(srv, "POST", f"/api/productions/{pid}/package", {})
    assert st == 200 and m["published"] is False
    st, _, d, _ = req(srv, "GET", f"/api/productions/{pid}")
    assert d["state"] == "AWAITING_APPROVAL"
    blocking = [f for f in d["flags"] if f["severity"] == "blocking" and f["status"] == "open"]
    assert {"human:pronunciation", "human:final-watch"} <= {f["kind"] for f in blocking}

    assert req(srv, "POST", f"/api/productions/{pid}/approve", {"reviewer": ""})[0] == 400
    st, _, js, _ = req(srv, "POST", f"/api/productions/{pid}/approve", {"reviewer": "Priyanshu"})
    assert st == 409 and js["error"]["code"] == "APPROVAL_BLOCKED"
    f0 = blocking[0]["id"]
    assert req(srv, "POST", f"/api/productions/{pid}/flags/{f0}/resolve", {"reviewer": "Priyanshu", "note": ""})[0] == 400
    assert req(srv, "POST", f"/api/productions/{pid}/flags/{f0}/resolve", {"reviewer": "", "note": "ok"})[0] == 400
    for f in blocking:
        st, _, js, _ = req(srv, "POST", f"/api/productions/{pid}/flags/{f['id']}/resolve", {"reviewer": "Priyanshu", "note": "checked"})
        assert st == 200, js
    assert req(srv, "POST", f"/api/productions/{pid}/approve", {"reviewer": "Priyanshu", "packageHash": "0" * 64})[0] == 409
    st, _, js, _ = req(srv, "POST", f"/api/productions/{pid}/approve", {"reviewer": "Priyanshu", "note": "ok",
                                                                         "packageHash": m["package_hash"]})
    assert st == 200 and js["published"] is False, js
    st, _, d, _ = req(srv, "GET", f"/api/productions/{pid}")
    assert d["state"] == "APPROVED" and d["approval_valid"] and d["publications"] == []       # approval never publishes

    st, _, o, _ = req(srv, "GET", f"/api/productions/{pid}/outputs")
    assert st == 200 and o["videos"][0]["path"].startswith("output/") and o["transcript"].startswith("Fast hosting")
    assert req(srv, "GET", "/files/" + o["videos"][0]["path"])[0] == 200

    # publish: explicit confirmation, actor and the typed production id are all required
    pub = f"/api/productions/{pid}/publish"
    for body in ({"platform": "youtube", "actor": "Priyanshu", "typedProductionId": pid},
                 {"platform": "youtube", "actor": "Priyanshu", "typedProductionId": pid, "confirm": "true"},
                 {"platform": "youtube", "actor": "Priyanshu", "confirm": True},
                 {"platform": "youtube", "actor": "Priyanshu", "confirm": True, "typedProductionId": pid[:-1]},
                 {"platform": "youtube", "confirm": True, "typedProductionId": pid},
                 {"platform": "tiktok", "actor": "Priyanshu", "confirm": True, "typedProductionId": pid}):
        st, _, js, _ = req(srv, "POST", pub, body)
        assert st == 400, (body, js)
    st, _, js, _ = req(srv, "POST", pub, {"platform": "youtube", "actor": "Priyanshu", "confirm": True, "typedProductionId": pid})
    assert st == 412 and js["error"]["code"] == "PUBLISH_NOT_CONFIGURED"
    st, _, d, _ = req(srv, "GET", f"/api/productions/{pid}")
    assert d["publications"] == [] and d["state"] == "APPROVED" and d["published"] is False

    assert req(srv, "POST", f"/api/productions/{pid}/export", {"actor": "Priyanshu"})[0] == 400      # no confirm
    st, _, ex, _ = req(srv, "POST", f"/api/productions/{pid}/export", {"actor": "Priyanshu", "confirm": True})
    assert st == 200 and (ROOT / ex["zip"]).exists(), ex
    st, _, d, _ = req(srv, "GET", f"/api/productions/{pid}")
    assert d["state"] == "APPROVED" and d["published"] is False and [x["status"] for x in d["publications"]] == ["EXPORTED"]
    assert d["exports"] and d["exports"][0]["platform_metadata"]["youtube"]["status"]["privacyStatus"] == "private"

    # any change after approval is caught when the production is loaded
    (out / "publishing/title.txt").write_text("Edited after approval\n")
    st, _, d, _ = req(srv, "GET", f"/api/productions/{pid}")
    assert d["state"] == "AWAITING_APPROVAL" and d["approval"] is None and not d["approval_valid"]
    assert req(srv, "POST", f"/api/productions/{pid}/export", {"actor": "Priyanshu", "confirm": True, "format": "short"})[0] == 409


def _wait(srv, tid, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, _, t, _ = req(srv, "GET", f"/api/tasks/{tid}")
        assert st == 200
        if t["status"] != "running":
            return t
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_creative_engine_failure_is_reported_and_manual_storyboard_still_works(studio, monkeypatch):
    srv, _ = studio

    def boom(pid):
        raise PipelineError("local model unavailable", detail="ollama is not running")
    monkeypatch.setattr(api, "generate_concepts", boom)
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "Hosting"}})
    pid = p["id"]
    st, _, js, _ = req(srv, "POST", f"/api/productions/{pid}/concepts", {})
    assert st == 200
    t = _wait(srv, js["task"]["id"])
    assert t["status"] == "failed" and t["error"]["message"] == "local model unavailable"
    # render is refused before a storyboard exists (reported through the task, server stays responsive)
    st, _, js, _ = req(srv, "POST", f"/api/productions/{pid}/render", {})
    t = _wait(srv, js["task"]["id"])
    assert t["status"] == "failed" and "cannot render" in t["error"]["message"]
    assert req(srv, "PUT", f"/api/productions/{pid}/storyboard", {"storyboard": STORYBOARD})[0] == 200


def test_read_endpoints(studio):
    srv, _ = studio
    st, _, d, _ = req(srv, "GET", "/api/dashboard")
    assert st == 200 and {"jobs", "productions", "storage", "memory", "scheduler", "tasks"} <= set(d)
    st, _, sc, _ = req(srv, "GET", "/api/storyboard/schema")
    assert st == 200 and "cta" in sc["blockTypes"] and "hook" in sc["purposes"]
    st, _, a, _ = req(srv, "GET", "/api/assets?brand=shrotihost")
    assert st == 200 and "assets" in a and "music" in a
    st, _, b, _ = req(srv, "GET", "/api/brands")
    assert st == 200 and any(x["id"] == "shrotihost" for x in b)
    assert req(srv, "GET", "/api/productions/P20260101-000000-abcde")[0] == 404
    assert req(srv, "GET", "/api/productions/../../etc")[0] == 404
    assert req(srv, "GET", "/api/jobs/20260101-000000-abcdef/monitor")[0] == 404


def test_brief_keeps_flexible_length_and_extra_format(studio):
    srv, base = studio
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "flex-brief",
                                                         "brief": {"product": "NVMe hosting", "format": "short", "duration_seconds": 80,
                                                                   "duration_flexible": True, "formats": ["short", "landscape"]}})
    assert st == 200, p
    from pipeline import api
    brief = api.Productions().get(p["id"])["brief"]
    assert brief["duration_flexible"] is True and brief["formats"] == ["short", "landscape"]
    assert req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "x", "formats": ["square"]}})[0] == 400
    assert req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "x", "duration_flexible": "yes"}})[0] == 400


def test_brief_keeps_the_generate_components_option(studio):
    """The New Production form's "Generate new components" sends components: "generate"; the server keeps it."""
    srv, base = studio
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "gen-brief",
                                                         "brief": {"product": "NVMe hosting", "format": "short", "components": "generate"}})
    assert st == 200, p
    from pipeline import api
    assert api.Productions().get(p["id"])["brief"]["components"] == "generate"
    assert req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "x", "components": "random"}})[0] == 400


# ---- Phase 2: add a website, facts review, library actions, setup -------------------------------------
FAKE_HOME = (b'<html><head><title>Zed Tools | Home</title><meta name="theme-color" content="#3366ff"></head>'
             b'<body><a href="/pricing">Pricing</a><a href="/features">Features</a><p>Zed Pro costs $9 a month.</p></body></html>')


@pytest.fixture
def temp_brand(monkeypatch):
    """A brand id whose files are removed afterwards (brand init writes into brands/, public/brands/, knowledge/)."""
    from pipeline import brand_init
    bid = f"zzst{uuid.uuid4().hex[:6]}"
    calls = []

    def fake_get(url, timeout=30.0):
        calls.append(url)
        return FAKE_HOME, "text/html"
    monkeypatch.setattr(brand_init, "_get", fake_get)        # never reach the network
    yield bid, calls
    for d in (ROOT / "brands" / bid, ROOT / "public/brands" / bid, ROOT / "knowledge" / bid, ROOT / "output/facts-refresh" / bid):
        shutil.rmtree(d, ignore_errors=True)


NEW_POSTS = ["/api/brands", "/api/brands/shrotihost/facts/refresh", "/api/brands/shrotihost/facts/confirm",
             "/api/setup/check", "/api/productions/P20260101-000000-abcde/archive",
             "/api/productions/P20260101-000000-abcde/mark-published"]


def test_new_write_endpoints_keep_the_security_rules(studio):
    srv, _ = studio
    for path in NEW_POSTS:
        assert req(srv, "POST", path, {}, cookie=False)[0] == 401, path
        assert req(srv, "POST", path, {}, headers={"Origin": "https://evil.example"})[0] == 403, path
        assert req(srv, "POST", path, {}, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403, path
        assert req(srv, "POST", path, b"{}", ctype="text/plain")[0] == 415, path
    for path in ("/api/industries", "/api/brands/shrotihost", "/api/brands/shrotihost/facts"):
        assert req(srv, "GET", path, cookie=False)[0] == 401, path
    assert req(srv, "GET", "/api/brands/../etc/facts")[0] == 404
    assert req(srv, "GET", "/api/brands/nosuchbrand/facts")[0] == 404


def test_add_a_website_runs_brand_init_as_a_task(studio, temp_brand):
    srv, _ = studio
    bid, calls = temp_brand
    st, _, inds, _ = req(srv, "GET", "/api/industries")
    assert st == 200 and {"web-hosting", "software"} <= {i["id"] for i in inds}
    for body in ({"industry": "software"},                                         # no site
                 {"site": "http://zed.example", "industry": "software"},           # not https
                 {"site": "https://zed.example", "industry": "bakery"},            # unknown pack
                 {"site": "https://zed.example", "industry": "software", "id": "Bad Id!"},
                 {"site": "https://zed.example", "industry": "software", "id": "../x"}):
        assert req(srv, "POST", "/api/brands", body)[0] == 400, body
    assert req(srv, "POST", "/api/brands", {"site": "https://shrotihost.in", "industry": "web-hosting", "id": "shrotihost"})[0] == 409
    assert calls == []                                                             # refused before any fetch

    st, _, js, _ = req(srv, "POST", "/api/brands", {"site": "zed.example", "industry": "software", "id": bid, "name": "Zed Tools"})
    assert st == 200 and js["brand"] == bid, js
    t = _wait(srv, js["task"]["id"])
    assert t["status"] == "done" and t["kind"] == "brand-init", t
    r = t["result"]
    assert r["brand"] == bid and r["draft"]["status"] == "draft" and r["draft"]["colors"]["brand"].lower() == "#3366ff"
    assert r["draft"]["logo"].startswith("public/brands/") and "pricing" in r["draft"]["fact_pages"]
    assert calls and calls[0] == "https://zed.example/"
    st, _, f, _ = req(srv, "GET", f"/api/brands/{bid}/facts")
    assert st == 200 and f["exists"] and f["facts"] == []                          # nothing invented from the page
    assert req(srv, "POST", f"/api/brands/{bid}/facts/refresh", {})[0] == 409      # nothing to re-check yet
    assert req(srv, "POST", "/api/brands", {"site": "zed.example", "industry": "software", "id": bid})[0] == 409


def test_facts_review_never_verifies_by_itself(studio, temp_brand, monkeypatch):
    srv, _ = studio
    bid, _ = temp_brand
    from pipeline.intelligence import facts as F
    st, _, js, _ = req(srv, "POST", "/api/brands", {"site": "zed.example", "industry": "software", "id": bid})
    assert _wait(srv, js["task"]["id"])["status"] == "done"
    path = ROOT / "knowledge" / bid / "facts.json"
    d = json.loads(path.read_text())
    base = {"category": "price", "product": "all", "value": {"amount": 9}, "keywords": [], "source_kind": "visible-text",
            "source_url": "https://zed.example/", "fetched_at": "2026-11-14T00:00:00Z", "volatile": False}
    d["facts"] = [{**base, "id": "pro.price", "claim": "Zed Pro costs $9 a month", "excerpt": "Zed Pro costs $9 a month."},
                  {**base, "id": "pro.gone", "claim": "Zed Pro has 99 seats", "excerpt": "99 seats included"},
                  {**base, "id": "pro.draft", "claim": "Zed Pro is $9", "excerpt": "Zed Pro costs $9", "status": "NEEDS_REVIEW"}]
    path.write_text(json.dumps(d))
    monkeypatch.setattr(F, "fetch", lambda url, timeout=45.0: FAKE_HOME.decode())

    st, _, js, _ = req(srv, "POST", f"/api/brands/{bid}/facts/refresh", {})
    assert st == 200
    t = _wait(srv, js["task"]["id"])
    assert t["status"] == "done" and t["result"]["stale"] == ["pro.gone"], t
    st, _, f, _ = req(srv, "GET", f"/api/brands/{bid}/facts")
    status = {x["id"]: x["status"] for x in f["facts"]}
    assert status == {"pro.price": "verified", "pro.gone": "stale", "pro.draft": "NEEDS_REVIEW"}, status   # excerpt found, still NOT verified
    assert json.loads(path.read_text())["facts"] == d["facts"]                     # the re-check never edits facts.json

    url = f"/api/brands/{bid}/facts/confirm"
    for body in ({"factId": "pro.draft", "reviewer": "Priyanshu"},                 # no deliberate confirm
                 {"factId": "pro.draft", "reviewer": "Priyanshu", "confirm": "true"},
                 {"factId": "pro.draft", "reviewer": "  ", "confirm": True},       # reviewer required
                 {"factId": "pro.draft", "confirm": True},
                 {"reviewer": "Priyanshu", "confirm": True}):
        assert req(srv, "POST", url, body)[0] == 400, body
    assert req(srv, "POST", url, {"factId": "nope", "reviewer": "Priyanshu", "confirm": True})[0] == 404
    assert json.loads(path.read_text())["facts"] == d["facts"]

    st, _, js, _ = req(srv, "POST", url, {"factId": "pro.draft", "reviewer": "Priyanshu", "note": "seen on the home page", "confirm": True})
    assert st == 200 and js["status"] == "verified", js
    saved = {x["id"]: x for x in json.loads(path.read_text())["facts"]}
    assert saved["pro.draft"]["status"] == "verified" and saved["pro.draft"]["verified_by"]["reviewer"] == "Priyanshu"
    assert saved["pro.draft"]["human_checks"][0]["note"] == "seen on the home page"
    assert "human_checks" not in saved["pro.price"] and "status" not in saved["pro.gone"]      # only the clicked fact changed
    from pipeline.jobs import Registry
    with Registry().conn() as c:
        rows = c.execute("SELECT actor, action, subject FROM audit_log WHERE action='facts.human-check'").fetchall()
    assert [tuple(r) for r in rows] == [("Priyanshu", "facts.human-check", f"{bid}:pro.draft")]


def test_archive_needs_a_name_and_hides_the_production(studio, monkeypatch):
    srv, base = studio
    import pipeline.archive as A
    monkeypatch.setattr(A, "ARCHIVE_DIR", base / "_archive")
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "to-archive", "brief": {"product": "NVMe hosting"}})
    pid = p["id"]
    url = f"/api/productions/{pid}/archive"
    assert req(srv, "POST", url, {"actor": "Priyanshu"})[0] == 400                 # no confirm
    assert req(srv, "POST", url, {"confirm": True})[0] == 400                      # no name
    assert req(srv, "POST", url, {"confirm": True, "actor": ""})[0] == 400
    st, _, js, _ = req(srv, "POST", url, {"confirm": True, "actor": "Priyanshu", "note": "old test"})
    assert st == 200 and js["moved_to"].startswith("output/"), js
    assert pid not in {x["id"] for x in req(srv, "GET", "/api/productions")[2]}
    assert (base / "_archive" / "productions").exists()


def test_i_posted_it_on_records_a_person_s_post_after_approval_only(studio, monkeypatch):
    srv, base = studio
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "posted",
                                                         "brief": {"product": "NVMe hosting", "format": "short", "duration_seconds": 30}})
    pid = p["id"]
    url = f"/api/productions/{pid}/mark-published"
    good = {"platform": "linkedin", "url": "https://www.linkedin.com/posts/x-123", "actor": "Priyanshu", "confirm": True}
    for bad in ({**good, "actor": ""}, {**good, "confirm": False}, {**good, "url": "http://x.example/p"},
                {**good, "url": "not a link"}, {**good, "platform": "Linked In!"}, {**good, "format": "square"}):
        assert req(srv, "POST", url, bad)[0] == 400, bad
    st, _, js, _ = req(srv, "POST", url, good)
    assert st == 409, js                                                           # not approved: the publish gate refuses
    assert req(srv, "PUT", f"/api/productions/{pid}/storyboard", {"storyboard": STORYBOARD})[0] == 200
    _simulate_completed_job(base, pid)
    st, _, m, _ = req(srv, "POST", f"/api/productions/{pid}/package", {})
    d = req(srv, "GET", f"/api/productions/{pid}")[2]
    for f in d["flags"]:
        if f["status"] == "open":
            req(srv, "POST", f"/api/productions/{pid}/flags/{f['id']}/resolve", {"reviewer": "Priyanshu", "note": "checked"})
    assert req(srv, "POST", f"/api/productions/{pid}/approve", {"reviewer": "Priyanshu", "packageHash": m["package_hash"]})[0] == 200
    st, _, js, _ = req(srv, "POST", url, good)
    assert st == 200 and js["state"] == "PUBLISHED" and js["platform"] == "linkedin", js
    assert req(srv, "POST", url, good)[0] == 409                                   # no duplicate record
    d = req(srv, "GET", f"/api/productions/{pid}")[2]
    assert d["published"] is True and [x["remote_id"] for x in d["publications"] if x["status"] == "PUBLISHED"] == [good["url"]]


def test_setup_checklist_explains_each_doctor_check(studio, monkeypatch):
    srv, _ = studio
    from pipeline import cli
    import pipeline.intelligence.registry as R

    def fake_doctor(a):
        assert a.json is True
        print(json.dumps({"ok": False, "host": {"model": "test"}, "checks": [
            {"check": "ffmpeg", "ok": True, "critical": True, "detail": "ffmpeg 9"},
            {"check": "chromium", "ok": False, "critical": True, "detail": "missing"},
            {"check": "voice.kokoro", "ok": False, "critical": True, "detail": "2/18 files ['MISSING']"},
            {"check": "benchmark", "ok": False, "critical": False, "detail": "not run yet"}]}))
        return 1
    monkeypatch.setattr(cli, "cmd_doctor", fake_doctor)
    monkeypatch.setattr(R, "with_local_availability", lambda *a, **k: {"default": "m:1", "models": [{"id": "m:1", "local_available": False}]})
    st, _, js, _ = req(srv, "POST", "/api/setup/check", {})
    assert st == 200
    t = _wait(srv, js["task"]["id"])
    assert t["status"] == "done", t
    checks = {c["check"]: c for c in t["result"]["checks"]}
    assert t["result"]["ok"] is False
    assert checks["ffmpeg"]["status"] == "ok" and checks["ffmpeg"]["fix"] is None
    assert checks["chromium"]["status"] == "missing" and "remotion browser ensure" in checks["chromium"]["fix"]
    assert checks["voice.kokoro"]["status"] == "missing" and checks["voice.kokoro"]["label"].startswith("Voices")
    assert checks["benchmark"]["status"] == "optional"
    assert checks["llm.model"]["status"] == "optional" and "ollama pull m:1" in checks["llm.model"]["fix"]


def test_errors_carry_hint_and_action(studio, monkeypatch):
    srv, _ = studio

    class Hinted(PipelineError):
        code = "PREVIEW_STALE"

        def to_dict(self):
            return {**super().to_dict(), "hint": "The storyboard changed since the preview.", "action": "rebuild-preview"}
    monkeypatch.setattr(api, "approve_preview", lambda pid, r, n: (_ for _ in ()).throw(Hinted("preview is out of date")))
    monkeypatch.setattr(api, "generate_concepts", lambda pid: (_ for _ in ()).throw(Hinted("model busy")))
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "NVMe hosting"}})
    st, _, js, _ = req(srv, "POST", f"/api/productions/{p['id']}/approve-preview", {"reviewer": "Priyanshu"})
    assert st == 400 and js["error"]["hint"].startswith("The storyboard") and js["error"]["action"] == "rebuild-preview", js
    st, _, js, _ = req(srv, "POST", f"/api/productions/{p['id']}/concepts", {})
    t = _wait(srv, js["task"]["id"])
    assert t["status"] == "failed" and t["error"]["action"] == "rebuild-preview" and t["error"]["hint"], t


def test_archive_list_and_restore_keep_the_security_rules(studio):
    srv, _ = studio
    path = "/api/archive/restore"
    assert req(srv, "POST", path, {}, cookie=False)[0] == 401
    assert req(srv, "POST", path, {}, headers={"Origin": "https://evil.example"})[0] == 403
    assert req(srv, "POST", path, {}, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert req(srv, "POST", path, b"{}", ctype="text/plain")[0] == 415
    assert req(srv, "GET", "/api/archive", cookie=False)[0] == 401


def test_archive_restore_round_trip_over_http(studio, monkeypatch):
    srv, base = studio
    import pipeline.archive as A
    import pipeline.video_out as VO
    monkeypatch.setattr(A, "ARCHIVE_DIR", base / "_archive")
    monkeypatch.setattr(VO, "OUT", base / "video-out")
    monkeypatch.setattr(VO, "INDEX", base / "video-out" / ".index.json")
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "to-restore", "brief": {"product": "NVMe hosting"}})
    pid = p["id"]
    assert req(srv, "POST", f"/api/productions/{pid}/archive", {"confirm": True, "actor": "Priyanshu"})[0] == 200
    st, _, arch, _ = req(srv, "GET", "/api/archive")
    assert st == 200 and [x["id"] for x in arch["productions"]] == [pid] and arch["productions"][0]["blocked"] is None
    url = "/api/archive/restore"
    for bad in ({"productionId": pid, "actor": "Priyanshu"},                             # no confirm
                {"productionId": pid, "confirm": True},                                  # no name
                {"productionId": pid, "confirm": True, "actor": "  "},
                {"confirm": True, "actor": "Priyanshu"},                                 # nothing to restore
                {"productionId": "../../etc", "confirm": True, "actor": "Priyanshu"},
                {"productionId": pid, "jobId": "20260101-000000-abcdef", "confirm": True, "actor": "Priyanshu"}):
        assert req(srv, "POST", url, bad)[0] == 400, bad
    assert req(srv, "POST", url, {"productionId": "P20260101-000000-abcde", "confirm": True, "actor": "Priyanshu"})[0] == 404
    orig = base / "productions" / pid
    orig.mkdir(parents=True)                                                             # original place taken
    st, _, js, _ = req(srv, "POST", url, {"productionId": pid, "confirm": True, "actor": "Priyanshu"})
    assert st == 409 and "already exists" in js["error"]["message"], js
    orig.rmdir()
    st, _, js, _ = req(srv, "POST", url, {"productionId": pid, "confirm": True, "actor": "Priyanshu", "note": "needed again"})
    assert st == 200 and js["restored_to"].startswith("output/"), js
    assert pid in {x["id"] for x in req(srv, "GET", "/api/productions")[2]}
    assert req(srv, "GET", "/api/archive")[2]["productions"] == []
    assert req(srv, "POST", url, {"productionId": pid, "confirm": True, "actor": "Priyanshu"})[0] == 409   # not archived any more


def test_preview_voice_route_runs_a_task_and_switches_the_player_to_voice_timing(studio, monkeypatch, tmp_path):
    """POST /preview-voice synthesises through the render's TTS path (mocked here) inside the scheduler's 'tts' slot;
    player-props then carry real voice timing and a voiceover the /files/ route serves (with Range for seeking)."""
    srv, _ = studio
    from pipeline import tts
    import pipeline.scheduler as Sch
    grants = []

    class FakeHeavy:
        def __init__(self, reg, kind, ref="", **kw):
            self.kind = kind

        def __enter__(self):
            grants.append(self.kind)
            return Sch.Grant(1, self.kind, 0.0, 4096.0)

        def __exit__(self, *exc):
            return False
    monkeypatch.setattr(Sch, "HeavyWork", FakeHeavy)
    monkeypatch.setattr(tts, "synthesize_from_config", lambda text, v, **kw: tts.synthesize(
        text, provider="mock", voice=v["voice"], cache_dir=tmp_path / "tts", pronunciation=v.get("pronunciation")))
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "pvoice-http", "brief": {"product": "NVMe hosting"}})
    pid = p["id"]
    assert req(srv, "POST", f"/api/productions/{pid}/preview-voice", {})[0] == 404          # no storyboard yet
    assert req(srv, "PUT", f"/api/productions/{pid}/storyboard", {"storyboard": STORYBOARD})[0] == 200
    st, _, s0, _ = req(srv, "GET", f"/api/productions/{pid}/preview-voice")
    assert st == 200 and s0["ready"] is False and s0["audio"] is None
    assert req(srv, "GET", f"/api/productions/{pid}/player-props")[2]["timing"] == "estimated"

    st, _, js, _ = req(srv, "POST", f"/api/productions/{pid}/preview-voice", {})
    assert st == 200 and js["task"]["kind"] == "preview-voice", js
    for _ in range(300):
        t = req(srv, "GET", f"/api/tasks/{js['task']['id']}")[2]
        if t["status"] != "running":
            break
        time.sleep(0.1)
    assert t["status"] == "done", t
    assert grants == ["tts"] and t["result"]["cached"] is False

    st, _, pp, _ = req(srv, "GET", f"/api/productions/{pid}/player-props")
    assert st == 200 and pp["timing"] == "voice" and pp["audio"]["url"] == t["result"]["audio"]["url"]
    assert req(srv, "GET", f"/api/productions/{pid}/preview-voice")[2]["ready"] is True
    st, h, _, raw = req(srv, "GET", pp["audio"]["url"], headers={"Range": "bytes=0-99"})
    assert st == 206 and len(raw) == 100 and raw[:4] == b"RIFF" and h.get("Accept-Ranges") == "bytes"
    assert req(srv, "GET", pp["audio"]["url"], cookie=False)[0] == 401
    assert req(srv, "POST", f"/api/productions/{pid}/preview-voice", b"x", ctype="text/plain")[0] in (400, 403, 415)
    assert req(srv, "GET", "/api/productions/P20260101-000000-abcde/preview-voice")[0] == 404


# ---- Home: project cards ----------------------------------------------------------------------------------
def test_home_cards_show_a_thumbnail_the_status_inputs_and_where_a_person_posted(studio):
    srv, base = studio
    assert req(srv, "GET", "/api/productions/cards", cookie=False)[0] == 401
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "card-test",
                                                         "brief": {"product": "NVMe hosting", "format": "landscape"}})
    pid = p["id"]

    def card():
        st, _, cards, _ = req(srv, "GET", "/api/productions/cards")
        assert st == 200
        return next(c for c in cards if c["id"] == pid)
    c = card()
    assert c["state"] == "DRAFT" and c["brand"] == "shrotihost" and c["name"] == "card-test" and c["format"] == "landscape"
    assert c["thumbnail"] is None and c["has_concepts"] is False and c["posted"] == [] and c["preview_approved"] is False
    assert "dir" not in c and "brief_json" not in c and "job_dir" not in c

    pdir = ROOT / p["dir"]                                   # first preview still becomes the thumbnail
    (pdir / "preview").mkdir(parents=True, exist_ok=True)
    (pdir / "preview/scene02-b.png").write_bytes(b"\x89PNG" + os.urandom(16))
    (pdir / "preview/scene01-a.png").write_bytes(b"\x89PNG" + os.urandom(16))
    c = card()
    assert c["thumbnail"].startswith("output/") and c["thumbnail"].endswith("preview/scene01-a.png")
    assert req(srv, "GET", "/files/" + c["thumbnail"])[0] == 200

    assert req(srv, "PUT", f"/api/productions/{pid}/storyboard", {"storyboard": STORYBOARD})[0] == 200
    out = _simulate_completed_job(base, pid)                  # the rendered video's thumbnail wins
    c = card()
    assert c["thumbnail"].endswith("publishing/thumbnail.png") and c["job_state"] == "COMPLETED" and c["state"] == "QA_COMPLETE"
    assert (ROOT / c["thumbnail"]) == out / "publishing/thumbnail.png"

    st, _, m, _ = req(srv, "POST", f"/api/productions/{pid}/package", {})
    d = req(srv, "GET", f"/api/productions/{pid}")[2]
    for f in d["flags"]:
        if f["status"] == "open":
            req(srv, "POST", f"/api/productions/{pid}/flags/{f['id']}/resolve", {"reviewer": "Priyanshu", "note": "checked"})
    assert req(srv, "POST", f"/api/productions/{pid}/approve", {"reviewer": "Priyanshu", "packageHash": m["package_hash"]})[0] == 200
    assert card()["state"] == "APPROVED" and card()["posted"] == []          # approving posts nothing
    good = {"platform": "linkedin", "url": "https://www.linkedin.com/posts/x-1", "actor": "Priyanshu", "confirm": True}
    assert req(srv, "POST", f"/api/productions/{pid}/mark-published", good)[0] == 200
    c = card()
    assert c["state"] == "PUBLISHED" and c["posted"] == ["linkedin"]


def test_built_bundle_has_the_home_and_create_a_video_pages():
    """Smoke check of the built frontend (studio/web/dist, built by `uv run python -m studio.build`)."""
    js = S.DIST_DIR / "app.js"
    if not js.exists():
        pytest.skip("frontend not built")
    src = js.read_text(encoding="utf-8")
    for s in ("/api/productions/cards", "Create a video", "Let the story decide", "Pick an idea", "Approve preview",
              "Make the video", "Approve the video", "I posted it on", "Overview", "Needs your review", "Ready to post",
              "/api/help/ask", "studio.help.open", "Close help"):
        assert s in src, s
    assert "home" in src and "create" in src
    css = (S.DIST_DIR / "app.css").read_text(encoding="utf-8")
    assert ".pgrid" in css and ".wsteps" in css and ".help-fab" in css and ".help-panel" in css


# ---- suggested facts (pipeline/fact_extract.py) ------------------------------------------------------------
CAND_POSTS = ["/api/brands/shrotihost/candidates/extract", "/api/brands/shrotihost/candidates/confirm",
              "/api/brands/shrotihost/candidates/reject"]


def test_candidate_routes_keep_the_security_rules(studio):
    srv, _ = studio
    for path in CAND_POSTS:
        assert req(srv, "POST", path, {}, cookie=False)[0] == 401, path
        assert req(srv, "POST", path, {}, headers={"Origin": "https://evil.example"})[0] == 403, path
        assert req(srv, "POST", path, {}, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403, path
        assert req(srv, "POST", path, b"{}", ctype="text/plain")[0] == 415, path
    assert req(srv, "GET", "/api/brands/shrotihost/candidates", cookie=False)[0] == 401
    assert req(srv, "GET", "/api/brands/nosuchbrand/candidates")[0] == 404
    assert req(srv, "POST", "/api/brands/nosuchbrand/candidates/extract", {})[0] == 404


def test_suggested_facts_need_a_person_to_become_facts(studio, temp_brand, monkeypatch):
    srv, _ = studio
    bid, _ = temp_brand
    from pipeline.intelligence import facts as F
    st, _, js, _ = req(srv, "POST", "/api/brands", {"site": "zed.example", "industry": "software", "id": bid})
    t = _wait(srv, js["task"]["id"])
    assert t["status"] == "done" and t["result"]["suggested_facts"] == 1, t
    facts_path = ROOT / "knowledge" / bid / "facts.json"
    st, _, c, _ = req(srv, "GET", f"/api/brands/{bid}/candidates")
    assert st == 200 and len(c["candidates"]) == 1, c
    cand = c["candidates"][0]
    assert cand["status"] == "NEEDS_REVIEW" and cand["value"] == {"amount": 9, "currency": "USD", "period": "month"}
    assert cand["excerpt"] == "Zed Pro costs $9 a month." and cand["excerpt"][slice(*cand["highlight"])] == "$9 a month"
    assert json.loads(facts_path.read_text())["facts"] == []                       # suggestions are not facts

    url = f"/api/brands/{bid}/candidates/confirm"
    cid = cand["candidate_id"]
    for body in ({"candidateId": cid, "reviewer": "Priyanshu"},                     # no deliberate confirm
                 {"candidateId": cid, "reviewer": "Priyanshu", "confirm": "true"},
                 {"candidateId": cid, "reviewer": " ", "confirm": True},
                 {"reviewer": "Priyanshu", "confirm": True}):
        assert req(srv, "POST", url, body)[0] == 400, body
    assert req(srv, "POST", url, {"candidateId": "cnope", "reviewer": "Priyanshu", "confirm": True})[0] == 404
    monkeypatch.setattr(F, "fetch", lambda u, timeout=45.0: FAKE_HOME.decode().replace("$9", "$12"))
    assert req(srv, "POST", url, {"candidateId": cid, "reviewer": "Priyanshu", "confirm": True})[0] == 409   # page changed
    assert json.loads(facts_path.read_text())["facts"] == []
    monkeypatch.setattr(F, "fetch", lambda u, timeout=45.0: FAKE_HOME.decode())
    st, _, r, _ = req(srv, "POST", url, {"candidateId": cid, "reviewer": "Priyanshu", "note": "home page", "confirm": True})
    assert st == 200 and r["status"] == "verified", r
    saved = json.loads(facts_path.read_text())["facts"]
    assert len(saved) == 1 and saved[0]["verified_by"]["reviewer"] == "Priyanshu" and saved[0]["excerpt"] == cand["excerpt"]
    st, _, f, _ = req(srv, "GET", f"/api/brands/{bid}/facts")
    assert [x["status"] for x in f["facts"]] == ["verified"]
    assert req(srv, "GET", f"/api/brands/{bid}/candidates")[2]["candidates"] == []

    # find facts again (background task): the confirmed fact is not suggested twice
    home = FAKE_HOME.replace(b"</body>", b"<p>Includes 5 projects and a 30-day money-back guarantee.</p></body>")
    from pipeline import brand_init
    monkeypatch.setattr(brand_init, "_get", lambda u, timeout=30.0: (home, "text/html"))
    st, _, js, _ = req(srv, "POST", f"/api/brands/{bid}/candidates/extract", {})
    t = _wait(srv, js["task"]["id"])
    assert st == 200 and t["status"] == "done" and t["kind"] == "facts-extract", t
    cands = req(srv, "GET", f"/api/brands/{bid}/candidates")[2]["candidates"]
    assert {x["kind"] for x in cands} == {"projects", "money_back"}, cands

    rej = f"/api/brands/{bid}/candidates/reject"
    one = cands[0]["candidate_id"]
    assert req(srv, "POST", rej, {"candidateId": one})[0] == 400                     # reviewer required
    assert req(srv, "POST", rej, {"candidateId": one, "reviewer": "Priyanshu", "note": "not a plan feature"})[0] == 200
    assert req(srv, "POST", rej, {"candidateId": one, "reviewer": "Priyanshu"})[0] == 404
    left = req(srv, "GET", f"/api/brands/{bid}/candidates")[2]
    assert [x["candidate_id"] for x in left["candidates"]] != [one] and left["rejected"][0]["reviewer"] == "Priyanshu"
    assert len(json.loads(facts_path.read_text())["facts"]) == 1                    # rejecting adds nothing
    from pipeline.jobs import Registry
    with Registry().conn() as con:
        rows = con.execute("SELECT actor, action FROM audit_log WHERE action LIKE 'facts.candidate-%' ORDER BY id").fetchall()
    assert [tuple(x) for x in rows] == [("Priyanshu", "facts.candidate-confirm"), ("Priyanshu", "facts.candidate-reject")]


def test_brief_keeps_the_quality_preset(studio):
    srv, base = studio
    st, _, p, _ = req(srv, "POST", "/api/productions", {"brand": "shrotihost", "name": "q-brief",
                                                         "brief": {"product": "NVMe hosting", "format": "short", "quality": "smooth"}})
    assert st == 200, p
    from pipeline import api
    assert api.Productions().get(p["id"])["brief"]["quality"] == "smooth"
    assert req(srv, "POST", "/api/productions", {"brand": "shrotihost", "brief": {"product": "x", "quality": "8k"}})[0] == 400


def test_header_values_with_line_breaks_are_refused_and_static_names_are_bounded(studio):
    srv, _ = studio
    import pytest
    h = S.Handler.__new__(S.Handler)
    with pytest.raises(ValueError):
        h._headers(200, "text/plain\r\nX-Evil: 1", 0)
    with pytest.raises(ValueError):
        h._headers(200, "text/plain", 0, {"Content-Disposition": "inline\nSet-Cookie: x=1"})
    assert req(srv, "GET", "/static/" + "-" * 5000 + ".js")[0] == 404


# ---- help chat (pipeline/help_chat.py; the model is a stand-in, nothing loads an LLM) ----------------------------
def test_help_route_keeps_the_security_rules(studio):
    srv, _ = studio
    path = "/api/help/ask"
    body = {"question": "How do I add my website?"}
    assert req(srv, "POST", path, body, cookie=False)[0] == 401
    assert req(srv, "POST", path, body, headers={"Origin": "https://evil.example"})[0] == 403
    assert req(srv, "POST", path, body, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert req(srv, "POST", path, json.dumps(body).encode(), ctype="text/plain")[0] == 415
    assert req(srv, "POST", path, body, host="evil.example")[0] == 421
    assert req(srv, "GET", path)[0] == 405


class _HelpModel:
    """Stand-in for the local model: records each request, answers with a fixed how-to sentence."""
    name = "mock"

    def __init__(self):
        self.asked = []

    def available(self):
        return True, "ok"

    def generate_json(self, **kw):
        from pipeline.intelligence.providers import GenResult, GenStats
        self.asked.append(kw)
        return GenResult({"answer": "Open Websites & facts, then Add a website.", "covered": True}, "", GenStats("mock", "m"), [])

    def unload(self):
        pass


def test_help_route_caps_input_and_answers_plainly(studio, monkeypatch):
    from pipeline import help_chat as H
    model = _HelpModel()
    monkeypatch.setattr(H, "_provider", lambda: model)
    srv, _ = studio
    st, _, js, _ = req(srv, "POST", "/api/help/ask", {"question": "x" * (H.MAX_QUESTION + 1)})
    assert st == 400 and "too long" in js["error"]["message"]
    st, _, js, _ = req(srv, "POST", "/api/help/ask",
                       {"question": "ok", "history": [{"role": "user", "content": "x"}] * (H.MAX_HISTORY + 1)})
    assert st == 400 and "full" in js["error"]["message"]
    assert model.asked == []
    st, _, js, _ = req(srv, "POST", "/api/help/ask", {"question": "How do I add my website?", "page": "Home"})
    assert st == 200 and js["status"] == "ok" and js["message"].startswith("Open Websites") and js["sources"]
    assert "The user is on: Home" in model.asked[0]["system"]

    def boom(*a, **k):
        raise RuntimeError("internal detail that must not reach the page")
    monkeypatch.setattr(H, "answer", boom)
    st, _, js, raw = req(srv, "POST", "/api/help/ask", {"question": "hello"})
    assert st == 200 and js == {"status": "error", "message": H.FAILED, "sources": []}
    assert b"internal detail" not in raw and b"Traceback" not in raw


def test_help_route_is_paused_while_a_video_renders(studio, registry, monkeypatch):
    from pipeline import help_chat as H

    def no_model():
        raise AssertionError("the model must not be touched during a render")
    monkeypatch.setattr(H, "_provider", no_model)
    with registry.conn() as c:
        c.execute("INSERT INTO sched_queue (kind,priority,pid,job_ref,state,enqueued_at,granted_at,heartbeat) "
                  "VALUES ('render',1,?,'job','granted',?,?,?)", (os.getpid(), time.time(), time.time(), time.time()))
    srv, _ = studio
    st, _, js, _ = req(srv, "POST", "/api/help/ask", {"question": "Why did my render fail?"})
    assert st == 200 and js["status"] == "paused" and js["message"] == H.PAUSED_RENDER
