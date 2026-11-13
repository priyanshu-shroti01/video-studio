"""Shared fixtures for tests/test_social_*.py: temp productions with REAL (tiny) videos inside the
workspace tmp dir, temp brand profiles with expected accounts, temp per-brand secrets, fake HTTP.
No test here ever talks to a network."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS = {"shrotihost": {"youtube": "UC_SHROTI_TEST", "instagram": "17841400000000001"},
            "acme-demo": {"youtube": "UC_ACME_TEST", "instagram": "17841400000000002"}}

SHORT_SCENES = [
    {"id": "hook", "purpose": "hook", "narration": "New to WordPress? Your first website shouldn't feel this hard."},
    {"id": "turn", "purpose": "turn", "narration": "Meet Shroti Host. WordPress, tuned to run fast."},
    {"id": "cta", "purpose": "cta", "narration": "Get started at shrotihost.in."},
]
LONG_SCENES = SHORT_SCENES[:1] + [
    {"id": "problem", "purpose": "problem", "narration": "Slow pages and surprise renewals make it harder."},
    {"id": "turn", "purpose": "turn", "narration": "Meet Shroti Host."},
    {"id": "journey", "purpose": "journey", "narration": "Pick a plan, add your domain and launch."},
    {"id": "resolution", "purpose": "resolution", "narration": "Your site is live."},
    {"id": "cta", "purpose": "cta", "narration": "Get started at shrotihost.in."},
]
LONG_SPANS = [[0.1, 8.0], [9.0, 19.0], [20.0, 30.0], [31.0, 45.0], [46.0, 52.0], [53.0, 59.0]]


def make_mp4(path: Path, w: int, h: int, seconds: float, fps: int = 30) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=navy:s={w}x{h}:r={fps}:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={seconds}:r=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def _secret(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps(data))
    os.chmod(path, 0o600)
    return path


@pytest.fixture
def sw(registry, monkeypatch):
    """Social workspace: temp brands (with expected accounts), productions dir, secrets root and caches,
    all under .pipeline/tmp (inside the workspace, as safe_path requires)."""
    import pipeline.brands as B
    import pipeline.productions as P
    import pipeline.scheduler as S
    import pipeline.social.brandcfg as BC
    import pipeline.social.keywords as K
    from pipeline.paths import TMP_DIR
    from pipeline.productions import Productions
    ws = TMP_DIR / f"test-social-{uuid.uuid4().hex[:8]}"
    for b in ("shrotihost", "acme-demo"):
        shutil.copytree(ROOT / "brands" / b, ws / "brands" / b)
        f = ws / "brands" / b / "brand.json"
        prof = json.loads(f.read_text())
        prof.setdefault("publishing", {})["accounts"] = {
            "youtube": {"channel_id": ACCOUNTS[b]["youtube"]}, "instagram": {"ig_user_id": ACCOUNTS[b]["instagram"]}}
        f.write_text(json.dumps(prof))
    monkeypatch.setattr(B, "BRANDS_DIR", ws / "brands")
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", ws / "productions")
    monkeypatch.setattr(BC, "SECRETS_ROOT", ws / "secrets")
    monkeypatch.setattr(K, "CACHE_DIR", ws / "cache")
    real = S.load_config
    monkeypatch.setattr(S, "load_config", lambda: {**real(), "min_available_mb": {**real()["min_available_mb"], "llm": 0}})
    ns = SimpleNamespace(ws=ws, reg=registry, prod=Productions(registry))
    ns.secret = lambda brand, platform, data: _secret(ws / "secrets" / brand / f"{platform}.json", data)
    yield ns
    shutil.rmtree(ws, ignore_errors=True)


def make_production(sw, brand: str = "shrotihost", fmt: str = "short", size=(360, 640), seconds: float = 6.0,
                    product: str = "WordPress Hosting") -> tuple[str, Path]:
    from pipeline.productions import flags_from_job
    reg, prod = sw.reg, sw.prod
    out = sw.ws / f"out-{uuid.uuid4().hex[:6]}"
    job = reg.create("demo", f"k{time.time()}{uuid.uuid4().hex}", {}, None, out)
    out = Path(job["output_dir"])
    for d in ("video", "publishing", "captions", "reports", "assets", "metadata"):
        (out / d).mkdir(parents=True, exist_ok=True)
    make_mp4(out / "video" / f"final-{fmt}.mp4", *size, seconds)
    (out / "publishing/thumbnail.png").write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(64))
    (out / "publishing/title.txt").write_text("Render title\n")
    (out / "publishing/description.md").write_text(
        "Render description\n\n---\nTranscript:\nhello\n\nSound effects:\n- \"Pop\" by someone — CC0 (https://freesound.org/x)\n"
        "- \"Pop\" by someone — CC0 (https://freesound.org/x)\n")
    (out / "publishing/hashtags.txt").write_text("#a #b\n")
    (out / "captions/captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    (out / "reports/qa-report.json").write_text(json.dumps({"status": "PASS", "formats": [
        {"format": fmt, "counts": {"PASS": 1, "WARN": 0, "FAIL": 0}, "checks": []}]}))
    (out / "reports/QA_REPORT.md").write_text("ok")
    (out / "reports/audio-report.json").write_text("{}")
    (out / "assets/manifest.json").write_text(json.dumps({"assets": [{"path": "audio/music/x.mp3", "license": "CC0"}]}))
    long = seconds > 30
    scenes = LONG_SCENES if long else SHORT_SCENES
    spans = LONG_SPANS if long else [[0.1, 2.0], [2.2, 4.0], [4.2, seconds - 0.2]]
    (out / "metadata/storyboard.json").write_text(json.dumps({"duration": seconds, "scenes": scenes}))
    (out / "metadata/timing.json").write_text(json.dumps({"duration": seconds, "scene_spans": spans}))
    (out / "metadata/production-config.json").write_text(json.dumps({"publishing": {}}))
    for s in ["PREPARING", "GENERATING_AUDIO", "BUILDING_TIMELINE", "RENDERING", "POST_PROCESSING", "QA", "COMPLETED"]:
        reg.transition(job["id"], s)
    reg.update(job["id"], qa_status="PASS")
    p = prod.create(brand, "demo", {"product": product, "audience": "Website beginners", "goal": "Conversions"})
    for s in ("STORYBOARD_READY", "RENDERING"):
        prod.transition(p["id"], s)
    prod.update(p["id"], job_id=job["id"])
    prod.transition(p["id"], "QA_COMPLETE")
    flags_from_job(prod, p["id"], out)
    prod.build_package(p["id"])
    return p["id"], out


def approve(sw, pid: str) -> None:
    from pipeline.productions import BLOCKING
    for f in sw.prod.flags(pid, "open"):
        if f["severity"] == BLOCKING:
            sw.prod.resolve_flag(pid, f["id"], "Test Reviewer", "checked in test")
    sw.prod.approve(pid, "Test Reviewer")


class FakeYouTube:
    """Fake YouTube transport: token, channels.list(mine), resumable session, upload, processing, thumbnail."""
    def __init__(self, channel_id: str = ACCOUNTS["shrotihost"]["youtube"]):
        self.channel_id, self.calls, self.bodies = channel_id, [], []

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append((method, url.split("?")[0]))
        if "oauth2" in url:
            return 200, {}, json.dumps({"access_token": "yt-access"}).encode()
        if "/channels" in url:
            return 200, {}, json.dumps({"items": [{"id": self.channel_id, "snippet": {"title": "Channel"}}]}).encode()
        if "upload/youtube/v3/videos" in url:
            self.bodies.append(json.loads(data))
            return 200, {"Location": "https://upload.example/session"}, b""
        if method == "PUT":
            return 201, {}, json.dumps({"id": "VID123"}).encode()
        if "/videos" in url:
            return 200, {}, json.dumps({"items": [{"processingDetails": {"processingStatus": "succeeded"}}]}).encode()
        if "thumbnails" in url:
            return 200, {}, b"{}"
        return 404, {}, b"{}"


class FakeInstagram:
    """Fake Graph API + rupload transport recording every request."""
    def __init__(self, ig_id: str = ACCOUNTS["shrotihost"]["instagram"], statuses=("IN_PROGRESS", "FINISHED"),
                 quota=(1, 50), upload_uri="https://rupload.facebook.com/ig-api-upload/v27.0/C1"):
        self.ig_id, self.statuses, self.quota, self.uri = ig_id, list(statuses), quota, upload_uri
        self.calls: list[dict] = []

    def __call__(self, method, url, headers=None, data=None):
        from urllib.parse import parse_qs, urlparse
        u = urlparse(url)
        form = {k: v[0] for k, v in parse_qs(data.decode()).items()} if data and u.hostname != "rupload.facebook.com" else {}
        self.calls.append({"method": method, "url": url, "path": u.path, "headers": dict(headers or {}), "form": form,
                           "bytes": len(data) if data and u.hostname == "rupload.facebook.com" else 0})
        p = u.path
        if u.hostname == "rupload.facebook.com":
            return 200, {}, b'{"success":true,"message":"Upload successful."}'
        if p.endswith("/content_publishing_limit"):
            return 200, {}, json.dumps({"data": [{"quota_usage": self.quota[0],
                                                  "config": {"quota_total": self.quota[1], "quota_duration": 86400}}]}).encode()
        if p.endswith("/media") and method == "POST":
            return 200, {}, json.dumps({"id": "C1", "uri": self.uri}).encode()
        if p.endswith("/media_publish"):
            return 200, {}, b'{"id":"M1"}'
        if p.endswith("/comments"):
            return 200, {}, b'{"id":"CM1"}'
        if p.endswith("/C1"):
            return 200, {}, json.dumps({"id": "C1", "status_code": self.statuses.pop(0) if self.statuses else "FINISHED"}).encode()
        if p.endswith("/M1"):
            return 200, {}, b'{"id":"M1","permalink":"https://www.instagram.com/reel/abc/"}'
        if p.endswith(f"/{self.ig_id}"):
            return 200, {}, json.dumps({"id": self.ig_id, "username": "brand"}).encode()
        return 404, {}, b'{"error":{"message":"unknown","code":100}}'

    def paths(self):
        return [(c["method"], c["path"].rsplit("/", 1)[-1] if "rupload" not in c["url"] else "rupload") for c in self.calls]
