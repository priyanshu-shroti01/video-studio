"""Local Video Studio HTTP server (stdlib only).

    uv run python -m studio.server [--port 8765] [--open]

Security model (local, single user):
  * binds 127.0.0.1 only; a random session token is printed once and exchanged for an HttpOnly,
    SameSite=Strict cookie (the token is never logged and the URL is redirected to drop it);
  * every /api, /files and /static request needs that cookie (or `Authorization: Bearer <token>`);
  * the Host header must be 127.0.0.1:<port> or localhost:<port> (DNS-rebinding defence), and a
    present Origin / Sec-Fetch-Site must be this origin;
  * POST/PUT bodies must be `application/json` (no form posts, so no CSRF via HTML forms), <= 4 MB;
  * strict CSP, no CORS headers, nosniff, no framing; user files are served sandboxed;
  * nothing here runs shell commands or opens arbitrary paths: files go through
    pipeline.api.safe_output_file (output/ and public/ only) and the built frontend in studio/web/dist;
  * every workflow action goes through pipeline/api.py, pipeline/productions.py or
    pipeline/publishing.py, which enforce validation, the approval gate and the publish gate.
    Nothing is published on a timer, on QA success or on approval: only POST .../publish with
    {confirm: true, actor, typedProductionId == id}.
"""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pipeline import api
from pipeline.errors import ConfigError, NotFound, PathError, PipelineError, StateError
from pipeline.paths import ROOT, rel

STUDIO_DIR = Path(__file__).resolve().parent
WEB_DIR = STUDIO_DIR / "web"
DIST_DIR = WEB_DIR / "dist"
COOKIE = "studio_session"
MAX_BODY = 4 * 1024 * 1024
PID_RE = r"P\d{8}-\d{6}-[0-9a-f]{5}"
JOB_RE = r"\d{8}-\d{6}-[0-9a-f]{6}"
TASK_RE = r"[0-9a-f]{12}"
PAGE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
FILE_CSP = "sandbox; default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; font-src 'self'"
TEXT_TYPES = {".srt": "text/plain; charset=utf-8", ".ass": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
              ".jsonl": "text/plain; charset=utf-8", ".json": "application/json", ".woff2": "font/woff2",
              ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8"}
BRIEF_FIELDS = {"product": 120, "price": 60, "audience": 160, "goal": 60, "tone": 120, "voice": 60, "cta": 60,
                "request": 2000, "notes": 2000, "url": 120, "platform": 40}


class BadRequest(PipelineError):
    code, exit_code = "BAD_REQUEST", 2


# ---- background tasks ------------------------------------------------------------------------------
class Tasks:
    """Long operations (concepts, storyboard generation, preview, render start, YouTube upload) run in
    daemon threads; the UI polls GET /api/tasks/<id>. One running task per (kind, production)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}

    def start(self, kind: str, pid: str, fn) -> dict:
        with self._lock:
            for t in self._tasks.values():
                if t["kind"] == kind and t["production"] == pid and t["status"] == "running":
                    raise StateError(f"a {kind} task is already running for {pid} (task {t['id']})")
            tid = uuid.uuid4().hex[:12]
            task = {"id": tid, "kind": kind, "production": pid, "status": "running", "started_at": time.time(),
                    "finished_at": None, "result": None, "error": None}
            self._tasks[tid] = task

        def run():
            try:
                res = fn()
                with self._lock:
                    task.update(status="done", result=res, finished_at=time.time())
            except PipelineError as e:
                with self._lock:
                    task.update(status="failed", error=e.to_dict(), finished_at=time.time())
            except Exception as e:  # noqa: BLE001 - surfaced to the UI verbatim
                with self._lock:
                    task.update(status="failed", finished_at=time.time(),
                                error={"code": type(e).__name__, "message": str(e) or type(e).__name__,
                                       "detail": traceback.format_exc(limit=4)})
        threading.Thread(target=run, name=f"studio-{kind}-{tid}", daemon=True).start()
        return dict(task)

    def get(self, tid: str) -> dict:
        with self._lock:
            if tid not in self._tasks:
                raise NotFound(f"no task {tid}")
            return dict(self._tasks[tid])

    def list(self, pid: str | None = None) -> list[dict]:
        with self._lock:
            ts = [dict(t) for t in self._tasks.values() if pid is None or t["production"] == pid]
        return sorted(ts, key=lambda t: -t["started_at"])


# ---- helpers -----------------------------------------------------------------------------------------
def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_text(p: Path, limit: int = 400_000) -> str | None:
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


def _tail(p: Path, n: int = 60) -> list[str]:
    t = _read_text(p, 2_000_000)
    return t.splitlines()[-n:] if t else []


_ROOT_PREFIX = str(ROOT) + os.sep


def _relify(o):
    """Absolute workspace paths -> workspace-relative (the UI builds /files/<rel> URLs from them)."""
    if isinstance(o, str):
        return o[len(_ROOT_PREFIX):] if o.startswith(_ROOT_PREFIX) else o
    if isinstance(o, dict):
        return {k: _relify(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_relify(v) for v in o]
    return o


def _str(body: dict, key: str, *, required: bool = True, limit: int = 200) -> str:
    v = body.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise BadRequest(f"'{key}' must be a string")
    v = v.strip()
    if required and not v:
        raise BadRequest(f"'{key}' is required")
    if len(v) > limit:
        raise BadRequest(f"'{key}' is too long (max {limit})")
    return v


def _productions():
    from pipeline.productions import Productions
    return Productions()


def destination_status(brand: str, platform: str) -> dict:
    """Is this brand's account for `platform` set up? Presence/permissions and the expected account id only;
    never reads secret values (pipeline/social/brandcfg.account_status). Each brand has its own accounts."""
    from pipeline.social.brandcfg import account_status
    try:
        st = account_status(brand).get(platform, {})
    except PipelineError as e:
        return {"configured": False, "reason": e.message}
    if not st.get("credentials_file"):
        return {"configured": False, "reason": st.get("note") or f"no .pipeline/secrets/{brand}/{platform}.json (see docs/SOCIAL_SETUP.md); use the export package"}
    if not st.get("expected_account"):
        return {"configured": False, "reason": f"brands/{brand}/brand.json has no publishing.accounts.{platform} id; "
                                               "uploads are refused until the expected account is set"}
    return {"configured": True, "reason": f"credentials present for account {st['expected_account']} (verified against the platform when you publish)"}


def youtube_status(brand: str = "") -> dict:   # kept for older callers
    return destination_status(brand, "youtube") if brand else {"configured": False, "reason": "no brand"}


# ---- service functions the Studio needs on top of pipeline/api.py ---------------------------------------
def production_detail(pid: str, tasks: Tasks | None = None) -> dict:
    """api.production + the files the editor/review screens need. Re-verifies the approval first
    (Productions.check_approval invalidates it if any approved file changed)."""
    prod = _productions()
    p0 = prod.get(pid)
    approval, approval_error = None, None
    if p0["job_id"]:
        try:
            approval = prod.check_approval(pid)
        except PipelineError as e:           # no package yet / no final video
            approval_error = e.message
    out = api.production(pid)
    d = Path(out["dir"])
    out["storyboard"] = _read_json(d / "storyboard.json")
    out["project"] = _read_json(d / "project.json")
    out["concepts"] = _read_json(d / "concepts/concepts.json")
    out["comparison_md"] = _read_text(d / "concepts/comparison.md") or _read_text(d / "concepts/concepts.md")
    out["claims_report"] = _read_json(d / "concepts/claims-report.json")
    out["preview"] = _read_json(d / "preview/preview.json")
    hist = d / "storyboard.history"
    out["history"] = sorted((rel(f) for f in hist.glob("*.json")), reverse=True) if hist.exists() else []
    out["approval"] = approval
    out["approval_error"] = approval_error
    out["approval_manifest"] = _read_json(d / "approval/approval-manifest.json")
    exp = d / "export"
    out["exports"] = [{"dir": rel(x), "zip": rel(x.with_suffix(".zip")) if x.with_suffix(".zip").exists() else None,
                       "platform_metadata": _read_json(x / "platform-metadata.json")}
                      for x in sorted(exp.iterdir()) if x.is_dir()] if exp.exists() else []
    out["published"] = any(r.get("status") == "PUBLISHED" for r in out.get("publications", []))
    out["render_log"] = _tail(d / "render.log", 40)
    out["tasks"] = tasks.list(pid) if tasks else []
    return _relify(out)


def production_outputs(pid: str) -> dict:
    """Everything Preview & QA and the Publishing Center show, read from the production's render job."""
    from pipeline.jobs import Registry
    p = _productions().get(pid)
    if not p["job_id"]:
        return {"job": None}
    reg = Registry()
    job = reg.get(p["job_id"])
    job.pop("config", None)
    out = Path(job["output_dir"])
    reports = {}
    for name in ("qa-report", "audio-report", "render-report", "branding-report", "visual-qa", "claims-report",
                 "alignment-report"):
        reports[name] = _read_json(out / "reports" / f"{name}.json")
    sb = _read_json(Path(p["dir"]) / "storyboard.json") or _read_json(out / "metadata/storyboard.source.json") or {}
    transcript = "\n".join(s.get("narration", "") for s in sb.get("scenes", []))
    title = (_read_text(out / "publishing/title.txt") or "").strip()
    desc = (_read_text(out / "publishing/description.md") or "").strip()
    tags = (_read_text(out / "publishing/hashtags.txt") or "").split()
    fmt_videos = sorted(out.glob("video/final-*.mp4"))
    return _relify({
        "job": job,
        "videos": [{"format": f.stem.replace("final-", ""), "path": rel(f), "mb": round(f.stat().st_size / 1e6, 1)}
                   for f in fmt_videos],
        "preview_mp4": rel(out / "previews/preview.mp4") if (out / "previews/preview.mp4").exists() else None,
        "contact_sheets": [rel(f) for f in sorted(out.glob("previews/*/contact-sheet.jpg"))],
        "frames": [rel(f) for f in sorted(out.glob("previews/*/frames/*.jpg"))][:40],
        "captions_srt": _read_text(out / "captions/captions.srt", 200_000),
        "captions_path": rel(out / "captions/captions.srt") if (out / "captions/captions.srt").exists() else None,
        "reports": reports,
        "qa_md": _read_text(out / "reports/QA_REPORT.md", 200_000),
        "pronunciation_md": _read_text(out / "reports/pronunciation-checklist.md", 100_000),
        "publishing": {"title": title, "description": desc, "hashtags": tags,
                       "thumbnail": rel(out / "publishing/thumbnail.png") if (out / "publishing/thumbnail.png").exists() else None},
        "credits": _read_json(out / "assets/manifest.json"),
        "transcript": transcript,
        "voiceover": rel(out / "audio/voiceover.wav") if (out / "audio/voiceover.wav").exists() else None,
        # Same mapping as pipeline.publishing.export, shown before export. The exported
        # platform-metadata.json (production_detail()["exports"]) is authoritative once it exists.
        "platform_preview": {
            "youtube": {"title": title[:100], "description": desc[:5000], "tags": [t.lstrip("#") for t in tags][:30],
                        "privacyStatus": "private", "containsSyntheticMedia": True},
            "instagram": {"caption": ((title + "\n\n" + desc)[:2200] + "\n" + " ".join(tags)).strip()}},
        "youtube": destination_status(p["brand"], "youtube"),
        "instagram": destination_status(p["brand"], "instagram"),
        "metadata": _read_json(out / "publishing/metadata.json"),
    })


def create_production(body: dict) -> dict:
    from pipeline.brands import list_brands
    from pipeline.config import load_theme
    brand = _str(body, "brand", limit=41)
    if brand not in list_brands():
        raise BadRequest(f"unknown brand {brand!r}")
    raw = body.get("brief")
    if not isinstance(raw, dict):
        raise BadRequest("'brief' must be an object")
    brief: dict = {}
    for k, limit in BRIEF_FIELDS.items():
        v = _str(raw, k, required=(k == "product"), limit=limit)
        if v:
            brief[k] = v
    fmt = raw.get("format", "short")
    if fmt not in ("short", "landscape"):
        raise BadRequest("'format' must be short or landscape")
    brief["format"] = fmt
    dur = raw.get("duration_seconds", 35)
    if not isinstance(dur, int) or isinstance(dur, bool) or not 10 <= dur <= 180:
        raise BadRequest("'duration_seconds' must be an integer between 10 and 180")
    brief["duration_seconds"] = dur
    if raw.get("duration_flexible") is not None:          # let the story set the length (hybrid engine)
        if not isinstance(raw["duration_flexible"], bool):
            raise BadRequest("'duration_flexible' must be true or false")
        if raw["duration_flexible"]:
            brief["duration_flexible"] = True
    if raw.get("formats") is not None:                    # render several formats, each composed for its frame
        fs = raw["formats"]
        if not isinstance(fs, list) or not fs or any(x not in ("short", "landscape") for x in fs) or len(fs) > 2:
            raise BadRequest("'formats' must be a list of short / landscape")
        brief["formats"] = list(dict.fromkeys([fmt, *fs]))
    if raw.get("components") is not None:                 # "generate": the composer designs new scene graphics
        if raw["components"] not in ("templates", "generate"):
            raise BadRequest("'components' must be 'templates' or 'generate'")
        if raw["components"] == "generate":
            brief["components"] = "generate"
    brief["brand"] = load_theme(brand).get("name", brand)
    brief["brand_id"] = brand
    name = _str(body, "name", required=False, limit=100) or None
    return _relify(api.create_production(brand, brief, name))


def save_storyboard(pid: str, body: dict) -> dict:
    sb = body.get("storyboard")
    if not isinstance(sb, dict):
        raise BadRequest("'storyboard' must be an object")
    return api.save_storyboard(pid, sb)


def validate_only(body: dict) -> dict:
    from pipeline.storyboard import validate_storyboard
    sb = body.get("storyboard")
    if not isinstance(sb, dict):
        raise BadRequest("'storyboard' must be an object")
    errs, warns = validate_storyboard(sb)
    return {"errors": errs, "warnings": warns}


def storyboard_schema() -> dict:
    """Vocabulary for the editor, read from the pipeline (so the UI follows contract changes)."""
    from pipeline.contract import BLOCK_TYPES, ICONS, TIME_KEYS, TONES
    from pipeline.storyboard import PURPOSES, SCENE_SCHEMA
    props = SCENE_SCHEMA["properties"]
    return {"blockTypes": sorted(BLOCK_TYPES), "purposes": PURPOSES, "tones": sorted(TONES), "icons": sorted(ICONS),
            "timeKeys": sorted(TIME_KEYS), "moods": props["mood"]["enum"], "transitions": props["transition"]["enum"],
            "layouts": props["layout"]["enum"], "wordsPerSecond": 2.33}


def build_package(pid: str) -> dict:
    prod = _productions()
    p = prod.get(pid)
    if p["state"] not in ("QA_COMPLETE", "AWAITING_APPROVAL"):
        raise StateError(f"the approval package can be (re)built only in QA_COMPLETE or AWAITING_APPROVAL, not {p['state']}")
    return _relify(prod.build_package(pid))


def resolve_flag(pid: str, flag_id: int, body: dict) -> dict:
    prod = _productions()
    prod.resolve_flag(pid, flag_id, _str(body, "reviewer", limit=80), _str(body, "note", limit=1000))
    return {"resolved": flag_id}


def approve(pid: str, body: dict) -> dict:
    h = _str(body, "packageHash", required=False, limit=64) or None
    res = _productions().approve(pid, _str(body, "reviewer", limit=80), _str(body, "note", required=False, limit=1000),
                                 expected_hash=h)
    return {**res, "published": False, "message": "Approved. Nothing has been published."}


def decide(pid: str, body: dict) -> dict:
    decision = body.get("decision")
    if decision not in ("REJECTED", "CHANGES_REQUESTED"):
        raise BadRequest("'decision' must be REJECTED or CHANGES_REQUESTED")
    _productions().decide(pid, decision, _str(body, "reviewer", limit=80), _str(body, "note", limit=1000))
    return {"decision": decision}


def _fmt(body: dict) -> str:
    fmt = body.get("format", "short")
    if fmt not in ("short", "landscape"):
        raise BadRequest("'format' must be short or landscape")
    return fmt


def export(pid: str, body: dict) -> dict:
    from pipeline import publishing
    if body.get("confirm") is not True:
        raise BadRequest("export needs {\"confirm\": true}")
    actor = _str(body, "actor", limit=80)
    return _relify(publishing.export(_productions(), pid, _fmt(body), actor))


def publish(pid: str, body: dict, tasks: Tasks) -> dict:
    """The ONLY path to an external platform. Requires confirm=true, a named actor and the production id
    typed by the human; the publish gate in pipeline.publishing re-checks approval and hashes."""
    from pipeline import publishing
    if body.get("confirm") is not True:
        raise BadRequest("publishing needs explicit confirmation: {\"confirm\": true}")
    actor = _str(body, "actor", limit=80)
    typed = body.get("typedProductionId")
    if not isinstance(typed, str) or not hmac.compare_digest(typed.strip(), pid):
        raise BadRequest("type the production id exactly to confirm publishing")
    platform = body.get("platform")
    if platform not in ("youtube", "export"):
        raise BadRequest("'platform' must be youtube or export")
    fmt = _fmt(body)
    prod = _productions()
    if platform == "export":
        return {"task": None, "result": _relify(publishing.publish(prod, pid, "export", fmt, confirm=True, actor=actor))}
    publishing.gate(prod, pid, platform, fmt)          # refuse early, synchronously, with the gate's reason
    publishing.YouTubeAdapter()                         # raises NotConfigured when credentials are absent
    return {"task": tasks.start("publish", pid, lambda: publishing.publish(_productions(), pid, platform, fmt,
                                                                          confirm=True, actor=actor))}


def cancel_job(job_id: str) -> dict:
    from pipeline.jobs import Registry
    return {"state": Registry().request_cancel(job_id)}


def jobs_list() -> list[dict]:
    from pipeline.jobs import Registry
    return Registry().list(60)


def productions_list() -> list[dict]:
    return _productions().list(200)


def _brand_q(h) -> str | None:
    from pipeline.brands import list_brands
    b = (h.query.get("brand") or "").strip()
    if not b:
        return None
    if b not in list_brands():
        raise NotFound(f"unknown brand {b!r}")
    return b


def approve_preview(pid: str, body: dict) -> dict:
    """Human preview review (same rule as the CLI): a named reviewer, a non-FAIL gate, the exact storyboard."""
    reviewer = str((body or {}).get("reviewer", "")).strip()
    return _relify(api.approve_preview(pid, reviewer, str((body or {}).get("note", ""))))


def brands() -> list[dict]:
    import urllib.parse as up
    out = []
    for b in api.brand_overview():
        site = b.get("website") or ""
        out.append({"id": b["id"], "name": b["name"], "brand": b["colour"], "status": b["status"],
                    "website": site or None, "domain": up.urlparse(site).netloc.removeprefix("www.") if site else None})
    return out


# ---- HTTP --------------------------------------------------------------------------------------------
class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int = 8765, token: str | None = None):
        super().__init__(("127.0.0.1", port), Handler)
        self.port = self.server_address[1]
        self.token = token or secrets.token_urlsafe(32)
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        self.tasks = Tasks()
        self.quiet = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def start_background(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, name="studio-http", daemon=True)
        t.start()
        return t


def _routes():
    P, J, T = PID_RE, JOB_RE, TASK_RE
    return [
        ("GET", r"/api/session", lambda h, m, b: {"ok": True, "version": api.__version__}),
        ("GET", r"/api/dashboard", lambda h, m, b: {**api.dashboard(_brand_q(h)), "tasks": h.server.tasks.list()[:20],
                                                   "failed_jobs": [j for j in jobs_list() if j["state"] == "FAILED"][:10]}),
        ("GET", r"/api/brands", lambda h, m, b: brands()),
        ("GET", r"/api/storyboard/schema", lambda h, m, b: storyboard_schema()),
        ("GET", r"/api/productions", lambda h, m, b: productions_list()),
        ("POST", r"/api/productions", lambda h, m, b: create_production(b)),
        ("GET", rf"/api/productions/({P})", lambda h, m, b: production_detail(m[1], h.server.tasks)),
        ("GET", rf"/api/productions/({P})/outputs", lambda h, m, b: production_outputs(m[1])),
        ("POST", rf"/api/productions/({P})/concepts",
         lambda h, m, b: {"task": h.server.tasks.start("concepts", m[1], lambda: api.generate_concepts(m[1]))}),
        ("POST", rf"/api/productions/({P})/select", lambda h, m, b: {"task": h.server.tasks.start(
            "storyboard", m[1], lambda cid=_str(b, "conceptId", limit=40): api.select_concept(m[1], cid))}),
        ("PUT", rf"/api/productions/({P})/storyboard", lambda h, m, b: save_storyboard(m[1], b)),
        ("POST", rf"/api/productions/({P})/storyboard/validate", lambda h, m, b: validate_only(b)),
        ("POST", rf"/api/productions/({P})/preview",
         lambda h, m, b: {"task": h.server.tasks.start("preview", m[1], lambda: api.preview(m[1]))}),
        ("POST", rf"/api/productions/({P})/approve-preview", lambda h, m, b: approve_preview(m[1], b)),
        ("POST", rf"/api/productions/({P})/render",
         lambda h, m, b: {"task": h.server.tasks.start("render", m[1], lambda: api.start_render(m[1]))}),
        ("POST", rf"/api/productions/({P})/package", lambda h, m, b: build_package(m[1])),
        ("POST", rf"/api/productions/({P})/flags/(\d{{1,9}})/resolve", lambda h, m, b: resolve_flag(m[1], int(m[2]), b)),
        ("POST", rf"/api/productions/({P})/approve", lambda h, m, b: approve(m[1], b)),
        ("POST", rf"/api/productions/({P})/decision", lambda h, m, b: decide(m[1], b)),
        ("POST", rf"/api/productions/({P})/export", lambda h, m, b: export(m[1], b)),
        ("POST", rf"/api/productions/({P})/publish", lambda h, m, b: publish(m[1], b, h.server.tasks)),
        ("GET", r"/api/publish/status", lambda h, m, b: {p: destination_status(_brand_q(h) or "", p) for p in ("youtube", "instagram")}),
        ("GET", r"/api/assets", lambda h, m, b: _relify(api.assets(h.query.get("brand") or None))),
        ("GET", r"/api/jobs", lambda h, m, b: jobs_list()),
        ("GET", rf"/api/jobs/({J})/monitor", lambda h, m, b: _relify(api.job_monitor(m[1]))),
        ("POST", rf"/api/jobs/({J})/cancel", lambda h, m, b: cancel_job(m[1])),
        ("GET", r"/api/tasks", lambda h, m, b: h.server.tasks.list()),
        ("GET", rf"/api/tasks/({T})", lambda h, m, b: _relify(h.server.tasks.get(m[1]))),
    ]


ROUTES = [(meth, re.compile(pat + r"$"), fn) for meth, pat, fn in _routes()]


def _status_for(e: PipelineError) -> int:
    from pipeline.productions import ApprovalError
    if isinstance(e, NotFound):
        return 404
    if isinstance(e, (ApprovalError, StateError)):
        return 409
    if isinstance(e, PathError):
        return 403
    if isinstance(e, (ConfigError, BadRequest)):
        return 422 if isinstance(e, ConfigError) else 400
    if e.code == "PUBLISH_NOT_CONFIGURED":
        return 412
    if e.message == "storyboard is invalid":
        return 422
    return 400


class Handler(BaseHTTPRequestHandler):
    server: StudioServer
    server_version = "LocalVideoStudio"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------------------------------
    def log_message(self, fmt, *args):  # never log query strings (the token travels in one, once)
        if not self.server.quiet:
            sys.stderr.write(f"[studio] {self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def log_request(self, code="-", size="-"):
        if isinstance(code, int) and code >= 400 or str(code).startswith(("4", "5")):
            self.log_message("%s %s", self.command, code)

    def _headers(self, status: int, ctype: str, length: int, extra: dict | None = None, csp: str = PAGE_CSP):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", csp)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None, csp: str = PAGE_CSP):
        if self.command in ("POST", "PUT") and not getattr(self, "_body_read", False):
            self.close_connection = True                 # unread request body: don't reuse the connection
            extra = {**(extra or {}), "Connection": "close"}
        self._headers(status, ctype, len(body), {"Cache-Control": "no-store", **(extra or {})}, csp)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, default=str, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, code: str, message: str, detail: str | None = None) -> None:
        err = {"code": code, "message": message, "detail": detail}
        if detail:
            err["errors"] = [l for l in detail.splitlines() if l.strip()]
        self._json(status, {"error": err})

    def _text(self, status: int, msg: str) -> None:
        self._send(status, msg.encode(), "text/plain; charset=utf-8")

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            c = SimpleCookie(raw)
        except Exception:  # noqa: BLE001
            return None
        return c[COOKIE].value if COOKIE in c else None

    def _authed(self) -> bool:
        tok = self._cookie_token()
        auth = self.headers.get("Authorization", "")
        if not tok and auth.startswith("Bearer "):
            tok = auth[7:].strip()
        return bool(tok) and hmac.compare_digest(tok.encode(), self.server.token.encode())

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "").strip().lower() in self.server.allowed_hosts

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.allowed_origins:
            return False
        site = self.headers.get("Sec-Fetch-Site")
        return site in (None, "same-origin", "none")

    # -- verbs ------------------------------------------------------------------------------------
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):           # no CORS, ever
        self._dispatch("OPTIONS")

    def _dispatch(self, method: str) -> None:
        try:
            self._dispatch_inner(method)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _dispatch_inner(self, method: str) -> None:
        self._body_read = False
        if not self._host_ok():
            self.close_connection = True
            return self._text(421, "Misdirected request: the Studio only answers to 127.0.0.1 / localhost.")
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if method not in ("GET", "HEAD", "POST", "PUT"):
            return self._text(405, "method not allowed")
        if path == "/" and method in ("GET", "HEAD"):
            return self._index()
        if not self._authed():
            if path.startswith("/api/"):
                return self._error(401, "UNAUTHORIZED", "missing or invalid session token: open the URL printed by the Studio")
            return self._text(401, "Unauthorized: open the URL printed in the terminal (it contains the session token).")
        if method in ("POST", "PUT"):
            if not self._origin_ok():
                return self._error(403, "CROSS_ORIGIN", "cross-origin requests are refused")
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._error(415, "UNSUPPORTED_MEDIA_TYPE", "POST/PUT bodies must be application/json")
        if path.startswith("/files/") and method in ("GET", "HEAD"):
            return self._file(urllib.parse.unquote(path[len("/files/"):]))
        if path.startswith("/static/") and method in ("GET", "HEAD"):
            return self._static(path[len("/static/"):])
        if path.startswith("/api/"):
            return self._api(method, path)
        return self._text(404, "not found")

    def _index(self) -> None:
        tok = self.query.get("token")
        if tok is not None:
            if not hmac.compare_digest(tok.encode(), self.server.token.encode()):
                return self._text(403, "Invalid token. Use the URL printed by the Studio when it started.")
            cookie = f"{COOKIE}={self.server.token}; HttpOnly; SameSite=Strict; Path=/"
            return self._send(303, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie})
        if not self._authed():
            return self._text(401, "Unauthorized: open the URL printed in the terminal (it contains the session token).")
        idx = WEB_DIR / "index.html"
        if not (DIST_DIR / "app.js").exists():
            return self._text(503, "The Studio frontend is not built. Run: uv run python -m studio.build")
        self._send(200, idx.read_bytes(), "text/html; charset=utf-8")

    def _static(self, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(js|css|map)", name):
            return self._text(404, "not found")
        f = (DIST_DIR / name).resolve()
        if f.parent != DIST_DIR.resolve() or not f.is_file():
            return self._text(404, "not found")
        ctype = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
                 "map": "application/json"}[name.rsplit(".", 1)[1]]
        self._send(200, f.read_bytes(), ctype)

    def _file(self, relpath: str) -> None:
        if not relpath or "\x00" in relpath or any(part.startswith(".") for part in Path(relpath).parts):
            return self._error(403, "PATH_REJECTED", "refused")
        try:
            f = api.safe_output_file(relpath)
        except PipelineError as e:
            return self._error(403 if not isinstance(e, NotFound) else 404, "PATH_REJECTED", e.message)
        if not f.is_file():
            return self._error(404, "NOT_FOUND", "not a file")
        ctype = TEXT_TYPES.get(f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/html") or ctype in ("application/xhtml+xml", "application/javascript", "text/javascript"):
            ctype = "text/plain; charset=utf-8"           # never serve user files as active content
        size = f.stat().st_size
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
        if m and (m[1] or m[2]):
            if m[1]:
                start = int(m[1])
                end = min(int(m[2]), size - 1) if m[2] else size - 1
            else:
                start = max(0, size - int(m[2]))
            if start > end or start >= size:
                self._headers(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"}, FILE_CSP)
                return
            status = 206
        extra = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-cache", "Content-Disposition": "inline"}
        if status == 206:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._headers(status, ctype, end - start + 1, extra, FILE_CSP)
        if self.command == "HEAD":
            return
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 16, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise BadRequest("bad Content-Length")
        if n > MAX_BODY:
            raise BadRequest(f"request body too large (max {MAX_BODY // 1024 // 1024} MB)")
        raw = self.rfile.read(n) if n else b"{}"
        self._body_read = True
        try:
            body = json.loads(raw or b"{}")
        except ValueError as e:
            raise BadRequest(f"body is not valid JSON: {e}")
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        return body

    def _api(self, method: str, path: str) -> None:
        if method == "HEAD":
            method = "GET"
        allowed = False
        for meth, rx, fn in ROUTES:
            m = rx.match(path)
            if not m:
                continue
            allowed = True
            if meth != method:
                continue
            try:
                body = self._body() if method in ("POST", "PUT") else {}
                return self._json(200, fn(self, m, body))
            except PipelineError as e:
                return self._error(_status_for(e), e.code, e.message, e.detail)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._error(500, type(e).__name__, str(e) or "internal error")
        if allowed:
            return self._error(405, "METHOD_NOT_ALLOWED", f"{method} not allowed on {path}")
        return self._error(404, "NOT_FOUND", f"no endpoint {path}")


# ---- entry points ----------------------------------------------------------------------------------
def make_server(port: int = 8765) -> StudioServer:
    return StudioServer(port)


TOKEN_FILE = Path(__file__).resolve().parent.parent / ".pipeline" / "studio" / "session-token"


def persistent_token(rotate: bool = False) -> str:
    """The Studio session token survives restarts, so an open browser tab keeps working after the Studio is
    restarted (a fresh token on every start logged every open tab out: "Dashboard unavailable").
    Stored in .pipeline/studio/session-token, mode 0600 (directory 0700); `--new-token` rotates it."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(TOKEN_FILE.parent, 0o700)
    if not rotate and TOKEN_FILE.exists() and not (os.stat(TOKEN_FILE).st_mode & 0o077):
        tok = TOKEN_FILE.read_text().strip()
        if len(tok) >= 32:
            return tok
    tok = secrets.token_urlsafe(32)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(tok)
    os.chmod(TOKEN_FILE, 0o600)
    return tok


def serve(port: int = 8765, open_browser: bool = False, new_token: bool = False) -> None:
    """Run the Studio until Ctrl-C. Called by `python -m studio.server` and `video-pipeline studio`."""
    srv = StudioServer(port, token=persistent_token(rotate=new_token))
    if not (DIST_DIR / "app.js").exists():
        print("warning: frontend not built; run `uv run python -m studio.build`", file=sys.stderr)
    print("Local Video Studio (nothing is published without your explicit confirmation)")
    print(f"  open: {srv.url}")
    print("  bound to 127.0.0.1 only; Ctrl-C to stop", flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(srv.url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="studio", description="Local Video Studio (127.0.0.1 only)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("STUDIO_PORT", 8765)))
    ap.add_argument("--open", action="store_true", help="open the browser")
    ap.add_argument("--new-token", action="store_true", help="rotate the session token (logs out open tabs)")
    a = ap.parse_args(argv)
    serve(a.port, open_browser=a.open, new_token=a.new_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
