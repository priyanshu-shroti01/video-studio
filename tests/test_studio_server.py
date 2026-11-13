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
def test_token_is_exchanged_for_httponly_samesite_cookie(studio):
    srv, _ = studio
    assert req(srv, "GET", "/", cookie=False)[0] == 401
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
