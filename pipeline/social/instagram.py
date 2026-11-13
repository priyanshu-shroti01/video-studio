"""Instagram Reels through the official Instagram Platform content-publishing API, resumable upload of a
LOCAL file. Only ever called by publishing.publish(), behind publishing.gate().

Verified against the Meta docs on 2026-11-13 (URLs in docs/SOCIAL_PUBLISHING.md):
  * Resumable upload ("upload_type=resumable") is available only for apps that use Facebook Login for
    Business: host graph.facebook.com for the API and rupload.facebook.com for the bytes. Instagram Login
    (graph.instagram.com) can only publish video from a public `video_url`, which this local-first pipeline
    does not have, so that host is refused with an explanation.
  * Flow: POST /<IG_ID>/media (media_type=REELS, upload_type=resumable, caption, share_to_feed,
    thumb_offset | cover_url) -> {id, uri}; POST <uri> with headers `Authorization: OAuth <token>`,
    `offset: 0`, `file_size: <bytes>` and the raw bytes; GET /<container>?fields=status_code until FINISHED
    (ERROR / EXPIRED fail; Meta suggests polling once a minute for up to 5 minutes); POST
    /<IG_ID>/media_publish creation_id=<container>; GET /<media>?fields=permalink.
  * Rate limit: GET /<IG_ID>/content_publishing_limit?fields=quota_usage,config ("currently 50" per 24 h
    in the endpoint reference; the overview page says 100 — we trust the live `config.quota_total`).
  * Permissions (Facebook Login for Business): instagram_basic, instagram_content_publish,
    pages_read_engagement (+ ads_management / ads_read when the Page role comes from Business Manager).

Secrets: .pipeline/secrets/<brand>/instagram.json (0600):
  {"ig_user_id": "...", "access_token": "...", "api_host": "graph.facebook.com", "api_version": "v27.0",
   "token_expires_at": "2027-01-10T00:00:00Z", "app_id": "...", "app_secret": "..."}
The token is never logged, printed or put in a URL (it travels in the Authorization header)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..errors import PipelineError
from .brandcfg import NotConfigured, read_secrets, secrets_file, write_secrets

FB_HOST, IG_HOST = "graph.facebook.com", "graph.instagram.com"
RUPLOAD_HOST = "rupload.facebook.com"
DEFAULT_VERSION = "v27.0"


class InstagramError(PipelineError):
    code = "INSTAGRAM_FAILED"


def _urllib(method, url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


class InstagramAdapter:
    platform = "instagram"

    def __init__(self, brand: str | None = None, cfg_path: Path | None = None, http=None, sleep=time.sleep,
                 poll_interval: float = 60.0, poll_timeout: float = 300.0):
        if cfg_path is None:
            if not brand:
                raise NotConfigured("Instagram adapter needs the production's brand")
            cfg_path = secrets_file(brand, "instagram")
        self.cfg_path = cfg_path
        self.cfg = read_secrets(cfg_path, {"ig_user_id", "access_token"}, "Instagram")
        self.host = self.cfg.get("api_host", FB_HOST)
        self.version = self.cfg.get("api_version", DEFAULT_VERSION)
        if self.host == IG_HOST:
            raise NotConfigured("api_host graph.instagram.com (Instagram Login) cannot upload a local file: Meta offers "
                                "resumable uploads only to Facebook Login for Business apps (graph.facebook.com). "
                                "See docs/SOCIAL_SETUP.md")
        if self.host != FB_HOST:
            raise NotConfigured(f"unsupported api_host {self.host!r} (use {FB_HOST})")
        self.http = http or _urllib
        self.sleep, self.poll_interval, self.poll_timeout = sleep, poll_interval, poll_timeout
        self.sent: list[dict] = []                         # what left the machine (no token)

    # -- low level ------------------------------------------------------------------------------
    @property
    def ig_user_id(self) -> str:
        return str(self.cfg["ig_user_id"])

    def _auth(self) -> dict:
        return {"Authorization": f"OAuth {self.cfg['access_token']}"}

    def _url(self, path: str, params: dict | None = None) -> str:
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        return f"https://{self.host}/{self.version}/{path.lstrip('/')}{q}"

    def _call(self, method: str, path: str, params: dict | None = None, form: dict | None = None) -> dict:
        url = self._url(path, params)
        body = urllib.parse.urlencode({k: v for k, v in (form or {}).items() if v is not None}).encode() if form else None
        hdr = {**self._auth(), **({"Content-Type": "application/x-www-form-urlencoded"} if body else {})}
        self.sent.append({"method": method, "url": url, "fields": sorted((form or {}).keys())})
        st, _, raw = self.http(method, url, hdr, body)
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        if st >= 400 or "error" in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            raise InstagramError(f"Instagram API {method} {path.split('?')[0]} failed (HTTP {st}): "
                                 f"{err.get('message', 'no message')} [code {err.get('code')}]")
        return data

    # -- steps ----------------------------------------------------------------------------------
    def account(self) -> dict:
        """The Instagram professional account these credentials act for."""
        d = self._call("GET", self.ig_user_id, {"fields": "id,username"})
        return {"id": str(d.get("id")), "username": d.get("username")}

    def publishing_limit(self) -> dict:
        d = self._call("GET", f"{self.ig_user_id}/content_publishing_limit", {"fields": "quota_usage,config"})
        row = (d.get("data") or [{}])[0]
        cfg = row.get("config") or {}
        return {"quota_usage": int(row.get("quota_usage", 0)), "quota_total": int(cfg.get("quota_total", 50)),
                "quota_duration": int(cfg.get("quota_duration", 86400))}

    def create_container(self, meta: dict) -> tuple[str, str]:
        form = {"media_type": "REELS", "upload_type": "resumable", "caption": meta["caption"],
                "share_to_feed": "true" if meta.get("share_to_feed", True) else "false"}
        if meta.get("cover_url"):
            form["cover_url"] = meta["cover_url"]
        elif meta.get("thumb_offset_ms") is not None:
            form["thumb_offset"] = str(int(meta["thumb_offset_ms"]))
        if meta.get("is_ai_generated"):
            form["is_ai_generated"] = "true"
        d = self._call("POST", f"{self.ig_user_id}/media", form=form)
        cid, uri = str(d.get("id") or ""), d.get("uri") or ""
        if not cid or not uri:
            raise InstagramError("Instagram did not return a resumable upload session (id + uri)")
        host = urllib.parse.urlparse(uri).hostname
        if host != RUPLOAD_HOST or urllib.parse.urlparse(uri).scheme != "https":
            raise InstagramError(f"refusing to send the token to an unexpected upload host {host!r}")
        return cid, uri

    def upload_bytes(self, uri: str, video: Path) -> None:
        data = Path(video).read_bytes()
        hdr = {**self._auth(), "offset": "0", "file_size": str(len(data))}
        self.sent.append({"method": "POST", "url": uri, "headers": ["Authorization", "offset", "file_size"],
                          "bytes": len(data)})
        st, _, raw = self.http("POST", uri, hdr, data)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        if st >= 400 or not body.get("success"):
            dbg = body.get("debug_info") or {}
            raise InstagramError(f"Instagram upload failed (HTTP {st}): {dbg.get('message') or body.get('message') or 'no message'}")

    def wait_finished(self, cid: str) -> dict:
        t0, waited = time.monotonic(), 0.0
        while True:
            d = self._call("GET", cid, {"fields": "id,status,status_code,video_status"})
            code = d.get("status_code")
            if code in ("FINISHED", "PUBLISHED"):
                return d
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram container {cid} is {code}: {d.get('status') or 'no detail'}")
            if max(waited, time.monotonic() - t0) + self.poll_interval > self.poll_timeout:
                raise InstagramError(f"Instagram container {cid} still {code or 'IN_PROGRESS'} after "
                                     f"{self.poll_timeout:.0f} s; it expires after 24 h if not published")
            self.sleep(self.poll_interval)
            waited += self.poll_interval

    def publish_container(self, cid: str) -> str:
        d = self._call("POST", f"{self.ig_user_id}/media_publish", form={"creation_id": cid})
        if not d.get("id"):
            raise InstagramError("media_publish returned no media id")
        return str(d["id"])

    def permalink(self, media_id: str) -> str | None:
        try:
            return self._call("GET", media_id, {"fields": "id,permalink"}).get("permalink")
        except InstagramError:
            return None

    def comment(self, media_id: str, text: str) -> str | None:
        return self._call("POST", f"{media_id}/comments", form={"message": text}).get("id")

    # -- full flow ------------------------------------------------------------------------------
    def upload_reel(self, video: Path, meta: dict, before_bytes=None) -> dict:
        lim = self.publishing_limit()
        if lim["quota_usage"] >= lim["quota_total"]:
            raise InstagramError(f"Instagram publishing limit reached: {lim['quota_usage']}/{lim['quota_total']} posts in "
                                 f"the last {lim['quota_duration'] // 3600} h; try again later")
        cid, uri = self.create_container(meta)
        if before_bytes:
            before_bytes()                              # last content-hash check right before bytes leave
        self.upload_bytes(uri, video)
        self.wait_finished(cid)
        mid = self.publish_container(cid)
        res = {"id": mid, "container_id": cid, "permalink": self.permalink(mid), "limit_before": lim}
        if meta.get("first_comment"):
            try:
                res["first_comment_id"] = self.comment(mid, meta["first_comment"])
            except InstagramError as e:
                res["first_comment_error"] = e.message
        return res


def refresh_token(brand: str, cfg_path: Path | None = None, http=None) -> dict:
    """Refresh/extend the long-lived token in the brand's instagram.json (run by a person; network).

    Facebook Login for Business (graph.facebook.com): a long-lived USER token lasts ~60 days and is extended by
    exchanging it again (GET /oauth/access_token?grant_type=fb_exchange_token; needs app_id + app_secret).
    A Page token derived from a long-lived user token has no expiry date. Instagram Login tokens
    (graph.instagram.com) are refreshed with GET /refresh_access_token?grant_type=ig_refresh_token once they are
    at least 24 h old (valid 60 days from refresh). Returns only the new expiry, never the token."""
    path = cfg_path or secrets_file(brand, "instagram")
    cfg = read_secrets(path, {"access_token"}, "Instagram")
    http = http or _urllib
    host, ver = cfg.get("api_host", FB_HOST), cfg.get("api_version", DEFAULT_VERSION)
    if host == IG_HOST:
        url = f"https://{IG_HOST}/refresh_access_token?" + urllib.parse.urlencode(
            {"grant_type": "ig_refresh_token", "access_token": cfg["access_token"]})
    else:
        if not cfg.get("app_id") or not cfg.get("app_secret"):
            raise NotConfigured("refreshing a Facebook Login token needs app_id and app_secret in instagram.json")
        url = f"https://{FB_HOST}/{ver}/oauth/access_token?" + urllib.parse.urlencode(
            {"grant_type": "fb_exchange_token", "client_id": cfg["app_id"], "client_secret": cfg["app_secret"],
             "fb_exchange_token": cfg["access_token"]})
    st, _, raw = http("GET", url, {}, None)
    try:
        d = json.loads(raw or b"{}")
    except ValueError:
        d = {}
    if st >= 400 or not d.get("access_token"):
        raise InstagramError(f"token refresh failed (HTTP {st}): {(d.get('error') or {}).get('message', 'no message')}")
    cfg["access_token"] = d["access_token"]
    exp = d.get("expires_in")
    cfg["token_expires_at"] = ((datetime.now(timezone.utc) + timedelta(seconds=int(exp))).strftime("%Y-%m-%dT%H:%M:%SZ")
                               if exp else None)
    cfg["token_refreshed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_secrets(path, cfg)
    return {"token_expires_at": cfg["token_expires_at"], "host": host}
