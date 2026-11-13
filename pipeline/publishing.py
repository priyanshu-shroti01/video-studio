"""Publishing adapters behind one gate. Nothing here runs automatically: every publish is an explicit
call (CLI `publish --confirm`, a Studio button with a confirmation dialog, or an MCP publish tool that a
person asked for) that must pass `gate()`:

  1. the production is APPROVED by a named reviewer (or already PUBLISHED to another platform with the
     same, still-valid approval),
  2. the approval is still valid (sha256 of every approved file unchanged — otherwise it is invalidated),
     which covers the published metadata (title, description, hashtags, thumbnail, publishing/metadata.json),
  3. the render job's QA report is complete and not FAIL,
  4. the exact file being sent hashes to the value in the approved package.

`publish()` then also requires a destination account that belongs to the production's brand:
brands/<brand>/brand.json "publishing.accounts" names the expected YouTube channel_id / Instagram
ig_user_id, the credentials come from .pipeline/secrets/<brand>/, and the platform's own answer to "who am
I" must match before any video byte is sent. One brand's video can never go to another brand's account.

Adapters:
  export     ready-to-upload folder + zip with checksums and platform metadata (no network). Does not
             change the production to PUBLISHED (nothing left the machine).
  youtube    official YouTube Data API v3 (resumable upload; optional publishAt and thumbnails.set).
  instagram  official Instagram Platform API, Reels via resumable upload (pipeline/social/instagram.py).
Never exercised against the real services by the automated tests (fake transports only).
"""
from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .errors import PipelineError
from .paths import STATE_DIR, atomic_write_json, rel, sha256_file
from .productions import ApprovalError, Productions
from .social.brandcfg import AccountMismatch, NotConfigured, read_secrets, secrets_file

SECRETS = STATE_DIR / "secrets"
PUBLISH_FROM = ("APPROVED", "PUBLISHED")       # PUBLISHED: another platform may still receive the approved video
__all__ = ["NotConfigured", "AccountMismatch", "gate", "export", "publish", "YouTubeAdapter"]


def gate(prod: Productions, pid: str, platform: str, fmt: str) -> dict:
    p = prod.get(pid)
    if p["state"] not in PUBLISH_FROM:
        raise ApprovalError(f"production is {p['state']}: publishing requires an explicit APPROVED decision")
    a = prod.check_approval(pid)
    if not a or not a["valid"]:
        raise ApprovalError("approval is missing or was invalidated by a content change; re-review required")
    job = prod.reg.get(p["job_id"])
    if job["qa_status"] not in ("PASS", "WARN"):
        raise ApprovalError(f"QA status is {job['qa_status']}")
    out = Path(job["output_dir"])
    video = out / "video" / f"final-{fmt}.mp4"
    approved = json.loads((Path(p["dir"]) / "approval/approval-manifest.json").read_text())["files"]
    key = f"video/{video.name}"
    if key not in approved or not video.exists() or sha256_file(video) != approved[key]["sha256"]:
        raise ApprovalError(f"{key} does not match the approved content hash")
    return {"production": p, "approval": a, "video": video, "job_out": out, "content_hash": approved[key]["sha256"],
            "approved_files": approved, "brand": p["brand"]}


def _record(prod: Productions, pid: str, platform: str, status: str, approval_id: int, h: str,
            remote_id: str | None = None, error: str | None = None) -> int:
    with prod.reg.conn() as c:
        return c.execute("INSERT INTO publications (production_id,platform,status,approval_id,content_hash,remote_id,"
                         "created_at,finished_at,error) VALUES (?,?,?,?,?,?,?,?,?)",
                         (pid, platform, status, approval_id, h, remote_id, time.time(), time.time(), error)).lastrowid


def _begin(prod: Productions, pid: str, platform: str, approval_id: int, h: str) -> int:
    """Claim the (production, platform, content) slot: refuses a duplicate or concurrent upload."""
    with prod.reg.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT status FROM publications WHERE production_id=? AND platform=? AND content_hash=? AND "
                      "status IN ('PUBLISHED','IN_PROGRESS')", (pid, platform, h)).fetchone()
        if r:
            c.execute("ROLLBACK")
            raise ApprovalError(f"this video is already {r['status'].lower().replace('_', ' ')} on {platform}; "
                                "refusing a duplicate upload")
        rid = c.execute("INSERT INTO publications (production_id,platform,status,approval_id,content_hash,created_at) "
                        "VALUES (?,?,?,?,?,?)", (pid, platform, "IN_PROGRESS", approval_id, h, time.time())).lastrowid
        c.execute("COMMIT")
    return rid


def _finish(prod: Productions, rid: int, status: str, remote_id: str | None = None, error: str | None = None) -> None:
    with prod.reg.conn() as c:
        c.execute("UPDATE publications SET status=?, remote_id=?, error=?, finished_at=? WHERE id=?",
                  (status, remote_id, error, time.time(), rid))


def expected_account(brand: str, platform: str) -> str | None:
    """The account id brands/<brand>/brand.json says this brand publishes to."""
    from .social.brandcfg import load
    return load(brand).expected_account(platform)


def social_metadata(job_out: Path) -> dict | None:
    from .social.metadata import load_metadata
    return load_metadata(job_out)


def _approved_file(g: dict, name: str) -> Path:
    f = g["job_out"] / name
    ent = g["approved_files"].get(name)
    if not ent or not f.exists() or sha256_file(f) != ent["sha256"]:
        raise ApprovalError(f"{name} is not part of the approved package (or changed)")
    return f


def export(prod: Productions, pid: str, fmt: str = "short", actor: str = "operator") -> dict:
    g = gate(prod, pid, "export", fmt)
    out = g["job_out"]
    dst = Path(g["production"]["dir"]) / "export" / f"{fmt}-{g['content_hash'][:12]}"
    if dst.exists():
        raise PipelineError(f"export already exists: {rel(dst)}")
    dst.mkdir(parents=True)
    files = {"video.mp4": g["video"], "thumbnail.png": out / "publishing/thumbnail.png",
             "title.txt": out / "publishing/title.txt", "description.md": out / "publishing/description.md",
             "hashtags.txt": out / "publishing/hashtags.txt", "captions.srt": out / "captions/captions.srt",
             "credits.json": out / "assets/manifest.json", "metadata.json": out / "publishing/metadata.json"}
    sums = {}
    for name, src in files.items():
        if src.exists():
            shutil.copy2(src, dst / name)
            sums[name] = sha256_file(dst / name)
    title = (dst / "title.txt").read_text().strip()
    desc = (dst / "description.md").read_text().strip()
    tags = (dst / "hashtags.txt").read_text().split()
    doc = social_metadata(out)
    entry = ((doc or {}).get("formats") or {}).get(fmt) or {}
    yt = entry.get("youtube")
    youtube = ({"snippet": yt["snippet"], "status": yt["status"], "short": yt.get("kind") == "short"} if yt else
               {"snippet": {"title": title[:100], "description": desc[:5000],
                            "tags": [t.lstrip("#") for t in tags][:30], "categoryId": "28"},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                           "containsSyntheticMedia": True}, "short": fmt == "short"})
    if entry.get("instagram"):
        instagram = entry["instagram"]
    elif entry.get("instagram_refused"):
        instagram = {"refused": entry["instagram_refused"]}
    elif fmt == "short":
        instagram = {"caption": (title + "\n\n" + desc)[:2200 - 200] + "\n" + " ".join(tags[:5]), "format": "reels",
                     "note": "legacy caption: run `video-pipeline social draft` before approval for a proper Reels caption"}
    else:
        instagram = {"refused": ["landscape video never goes to Instagram; render the 9:16 'short' format for Reels"]}
    atomic_write_json(dst / "platform-metadata.json", {
        "youtube": youtube, "instagram": instagram,
        "note": "containsSyntheticMedia=true: narration is synthetic (local TTS). Keep this disclosure."})
    atomic_write_json(dst / "SHA256SUMS.json", sums)
    z = dst.with_suffix(".zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for f in sorted(dst.iterdir()):
            zf.write(f, f.name)
    _record(prod, pid, "export", "EXPORTED", g["approval"]["id"], g["content_hash"])
    prod.reg.audit(actor, "publish.export", pid, {"dir": rel(dst), "hash": g["content_hash"]})
    return {"dir": rel(dst), "zip": rel(z), "sha256": sums}


def _http(method, url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


class YouTubeAdapter:
    """Official YouTube Data API v3. Per-brand credentials in .pipeline/secrets/<brand>/youtube.json (0600):
    {"client_id": "...", "client_secret": "... (optional for Desktop clients)", "refresh_token": "...",
     "privacyStatus": "private"}. Get the refresh token with scripts/youtube_oauth.py (docs/SOCIAL_SETUP.md).

    Quota (verified 2026-11-13, developers.google.com/youtube/v3/determine_quota_cost): videos.insert is 1 unit
    in its own "Video Uploads" bucket (100 uploads/day); channels.list and videos.list 1 unit and thumbnails.set
    ~50 units from the 10,000/day general bucket."""
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
    CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
    THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
    platform = "youtube"

    def __init__(self, cfg_path: Path | None = None, http=None, *, brand: str | None = None, sleep=time.sleep):
        if cfg_path is None:
            if not brand:
                raise NotConfigured("YouTube adapter needs the production's brand (per-brand credentials)")
            cfg_path = secrets_file(brand, "youtube")
        self.cfg = read_secrets(cfg_path, {"client_id", "refresh_token"}, "YouTube")
        self.http = http or _http
        self.sleep = sleep
        self._token: str | None = None
        self.sent: list[dict] = []

    @staticmethod
    def _urllib(method, url, headers=None, data=None):          # kept for callers of the v0.3.0 API
        return _http(method, url, headers, data)

    def _access_token(self) -> str:
        if self._token:
            return self._token
        form = {"client_id": self.cfg["client_id"], "refresh_token": self.cfg["refresh_token"], "grant_type": "refresh_token"}
        if self.cfg.get("client_secret"):
            form["client_secret"] = self.cfg["client_secret"]
        st, _, body = self.http("POST", self.TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"},
                                urllib.parse.urlencode(form).encode())
        try:
            tok = json.loads(body or b"{}").get("access_token")
        except ValueError:
            tok = None
        if st >= 400 or not tok:
            raise NotConfigured(f"YouTube token refresh failed (HTTP {st}); re-run scripts/youtube_oauth.py "
                                "(refresh tokens of OAuth apps in 'Testing' status expire after 7 days)")
        self._token = tok
        return tok

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def account(self) -> dict:
        """The channel these credentials upload to (channels.list mine=true, 1 unit)."""
        st, _, body = self.http("GET", self.CHANNELS_URL, self._auth(), None)
        items = (json.loads(body or b"{}") if st < 400 else {}).get("items") or []
        if not items:
            raise NotConfigured(f"could not read the authorised YouTube channel (HTTP {st})")
        return {"id": items[0]["id"], "title": (items[0].get("snippet") or {}).get("title")}

    def upload(self, video: Path, meta: dict) -> str:
        token = self._access_token()
        meta = json.loads(json.dumps(meta))
        st_ = meta.setdefault("status", {})
        if st_.get("publishAt"):
            st_["privacyStatus"] = "private"                     # YouTube requires private for scheduling
        else:
            wanted = self.cfg.get("privacyStatus") or st_.get("privacyStatus") or "private"
            # "public" only when the person set it explicitly in their credentials file
            st_["privacyStatus"] = wanted if wanted in ("private", "unlisted") or self.cfg.get("privacyStatus") == "public" else "private"
        self.sent.append({"method": "POST", "url": self.UPLOAD_URL, "body": meta})
        st, hdr, _ = self.http("POST", self.UPLOAD_URL, {"Authorization": f"Bearer {token}",
                                                          "Content-Type": "application/json; charset=UTF-8",
                                                          "X-Upload-Content-Type": "video/mp4"}, json.dumps(meta).encode())
        loc = hdr.get("Location") or hdr.get("location")
        if not loc:
            raise PipelineError(f"YouTube did not return an upload session (HTTP {st})")
        data = video.read_bytes()
        self.sent.append({"method": "PUT", "url": "<resumable session>", "bytes": len(data)})
        st, _, body = self.http("PUT", loc, {"Content-Type": "video/mp4"}, data)
        if st not in (200, 201):
            raise PipelineError(f"YouTube upload failed (HTTP {st})")
        return json.loads(body)["id"]

    def wait_processed(self, video_id: str, timeout: float = 600, interval: float = 20) -> str:
        t0 = time.monotonic()
        while True:
            st, _, body = self.http("GET", f"{self.VIDEOS_URL}?part=processingDetails&id={urllib.parse.quote(video_id)}",
                                    self._auth(), None)
            items = (json.loads(body or b"{}") if st < 400 else {}).get("items") or []
            status = ((items[0].get("processingDetails") or {}).get("processingStatus") if items else None) or "unknown"
            if status in ("succeeded", "failed", "terminated") or time.monotonic() - t0 + interval > timeout:
                return status
            self.sleep(interval)

    def set_thumbnail(self, video_id: str, png: Path) -> dict:
        """thumbnails.set after processing (custom thumbnails need a verified channel; ~50 units)."""
        status = self.wait_processed(video_id)
        if status != "succeeded":
            return {"set": False, "reason": f"video processing is {status}; set the thumbnail later in YouTube Studio"}
        st, _, body = self.http("POST", f"{self.THUMB_URL}?videoId={urllib.parse.quote(video_id)}&uploadType=media",
                                {**self._auth(), "Content-Type": "image/png"}, png.read_bytes())
        if st >= 400:
            msg = (json.loads(body or b"{}").get("error") or {}).get("message", "") if body else ""
            return {"set": False, "reason": f"HTTP {st}: {msg or 'thumbnails.set failed'} (custom thumbnails need a "
                                            "verified channel)"}
        return {"set": True}


def _youtube_meta(g: dict, doc: dict | None, fmt: str) -> tuple[dict, dict]:
    entry = ((doc or {}).get("formats") or {}).get(fmt) or {}
    yt = entry.get("youtube")
    if yt:
        meta = {"snippet": dict(yt["snippet"]), "status": dict(yt["status"])}
        meta["status"]["selfDeclaredMadeForKids"] = False
        meta["status"]["containsSyntheticMedia"] = True
        return meta, {"source": "publishing/metadata.json", "set_thumbnail": bool(yt.get("set_thumbnail")),
                      "kind": yt.get("kind")}
    meta = {"snippet": {"title": (g["job_out"] / "publishing/title.txt").read_text().strip()[:100],
                        "description": (g["job_out"] / "publishing/description.md").read_text()[:5000]},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
    return meta, {"source": "title.txt + description.md (no metadata.json)", "set_thumbnail": False, "kind": None}


def _check_metadata(doc: dict | None, fmt: str) -> None:
    if doc and (doc.get("validation") or {}).get("status") == "FAIL":
        raise ApprovalError("publishing/metadata.json failed validation; redraft it before approval")


def _verify_account(ad, brand: str, platform: str) -> dict:
    exp = expected_account(brand, platform)
    key = "channel_id" if platform == "youtube" else "ig_user_id"
    if not exp:
        raise NotConfigured(f"brands/{brand}/brand.json has no publishing.accounts.{platform}.{key}: the expected "
                            f"{platform} account for brand {brand!r} must be set before publishing (docs/SOCIAL_SETUP.md)")
    if platform == "instagram" and str(getattr(ad, "ig_user_id", exp)) != exp:
        raise AccountMismatch(f"the Instagram credentials are for account {ad.ig_user_id}, but brand {brand!r} publishes "
                              f"only to {exp}; refusing")
    acct = ad.account()
    if str(acct.get("id")) != exp:
        raise AccountMismatch(f"the {platform} credentials belong to account {acct.get('id')} "
                              f"({acct.get('title') or acct.get('username') or '?'}), not brand {brand!r}'s account {exp}; "
                              "refusing to publish")
    return acct


def publish(prod: Productions, pid: str, platform: str, fmt: str, *, confirm: bool, actor: str,
            adapter=None) -> dict:
    """Explicit, human-confirmed publish to an external platform. Returns what was sent."""
    if not confirm:
        raise ApprovalError("publishing requires explicit confirmation (--confirm)")
    if not (actor or "").strip():
        raise ApprovalError("publishing needs the name of the person who asked for it (--actor)")
    if platform == "export":
        return export(prod, pid, fmt, actor)
    if platform not in ("youtube", "instagram"):
        raise NotConfigured(f"no adapter for {platform!r}; use the export package")
    g = gate(prod, pid, platform, fmt)
    brand = g["brand"]
    doc = social_metadata(g["job_out"])
    _check_metadata(doc, fmt)
    if platform == "instagram":
        from .social import routing
        info = routing.probe(g["video"])
        probs = routing.instagram_problems(info)
        if probs:
            raise ApprovalError("not publishable to Instagram Reels: " + "; ".join(probs))
        ig = (((doc or {}).get("formats") or {}).get(fmt) or {}).get("instagram")
        if not ig:
            raise ApprovalError("no approved Instagram caption: run `video-pipeline social draft` before approval")
        meta, extra = dict(ig), {"source": "publishing/metadata.json"}
        if adapter is None:
            from .social.instagram import InstagramAdapter
            adapter = InstagramAdapter(brand=brand)
    else:
        meta, extra = _youtube_meta(g, doc, fmt)
        pa = meta["status"].get("publishAt")
        if pa and datetime.fromisoformat(pa.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ApprovalError("the approved publishAt time has passed; redraft the schedule and re-approve")
        if adapter is None:
            adapter = YouTubeAdapter(brand=brand)
    acct = _verify_account(adapter, brand, platform)
    was = g["production"]["state"]
    rid = _begin(prod, pid, platform, g["approval"]["id"], g["content_hash"])
    if was == "APPROVED":
        prod.transition(pid, "PUBLISHING", actor=actor)

    def recheck():
        if sha256_file(g["video"]) != g["content_hash"]:   # re-check right before bytes leave the machine
            raise ApprovalError("video changed during publishing")

    result: dict = {"platform": platform, "format": fmt, "brand": brand, "account": acct,
                    "content_hash": g["content_hash"], "metadata_source": extra["source"]}
    try:
        recheck()
        if platform == "instagram":
            r = adapter.upload_reel(g["video"], meta, before_bytes=recheck)
            remote = r["id"]
            result.update({"remote_id": remote, "permalink": r.get("permalink"),
                           "sent": {"caption": meta["caption"], "share_to_feed": meta.get("share_to_feed", True),
                                    "thumb_offset_ms": meta.get("thumb_offset_ms"), "cover_url": meta.get("cover_url"),
                                    "is_ai_generated": meta.get("is_ai_generated"), "first_comment": meta.get("first_comment"),
                                    "bytes": g["video"].stat().st_size},
                           **{k: r[k] for k in ("limit_before", "first_comment_error") if k in r}})
        else:
            remote = adapter.upload(g["video"], meta)
            result.update({"remote_id": remote, "url": f"https://www.youtube.com/watch?v={remote}",
                           "sent": {**meta, "bytes": g["video"].stat().st_size}})
    except Exception as e:
        _finish(prod, rid, "FAILED", error=str(e))
        if was == "APPROVED":
            prod.transition(pid, "APPROVED", actor="system", note=f"publish failed: {e}")
        prod.reg.audit(actor, f"publish.{platform}.failed", pid, {"error": str(e)[:300], "format": fmt})
        raise
    _finish(prod, rid, "PUBLISHED", remote_id=remote)
    if was == "APPROVED":
        prod.transition(pid, "PUBLISHED", actor=actor, note=f"{platform}:{remote}")
    prod.reg.audit(actor, f"publish.{platform}", pid, {"remote_id": remote, "format": fmt, "account": acct.get("id"),
                                                       "hash": g["content_hash"]})
    if platform == "youtube" and extra.get("set_thumbnail") and hasattr(adapter, "set_thumbnail"):
        try:
            result["thumbnail"] = adapter.set_thumbnail(remote, _approved_file(g, "publishing/thumbnail.png"))
        except Exception as e:  # noqa: BLE001 - the video is up; report, don't fail
            result["thumbnail"] = {"set": False, "reason": str(e)[:200]}
    return result
