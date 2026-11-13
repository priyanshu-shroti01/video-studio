#!/usr/bin/env python3
"""Get a YouTube refresh token for ONE brand with Google's loopback flow (Desktop OAuth client + PKCE) and
store it in .pipeline/secrets/<brand>/youtube.json (file 0600, directory 0700). Run it yourself:

    uv run python scripts/youtube_oauth.py --brand shrotihost --client-secrets ~/Downloads/client_secret_XXXX.json

What it does (developers.google.com/identity/protocols/oauth2/native-app):
  1. starts a one-shot HTTP listener on http://127.0.0.1:<random port> (loopback redirect; OOB is retired),
  2. opens https://accounts.google.com/o/oauth2/v2/auth with PKCE (S256), a random `state`,
     access_type=offline, prompt=consent and the scopes below. Sign in with the Google account that owns
     THIS brand's channel (pick the brand channel if the account has several),
  3. exchanges the code at https://oauth2.googleapis.com/token,
  4. asks channels.list(mine=true) which channel the token belongs to and prints its id/title, so you can put
     that id into brands/<brand>/brand.json -> publishing.accounts.youtube.channel_id.
Tokens are never printed or logged. Nothing else is sent anywhere.

Scopes: youtube.upload (videos.insert, thumbnails.set) + youtube.readonly (channels.list mine=true for the
account check). Note: while the OAuth consent screen is in "Testing", Google expires refresh tokens after 7 days;
publish the consent screen ("In production") for a long-lived token."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _post(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b"{}")
        raise SystemExit(f"token exchange failed (HTTP {e.code}): {body.get('error')} {body.get('error_description', '')}")


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _wait_for_code(state: str, timeout: float) -> tuple[http.server.HTTPServer, dict]:
    box: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            box.update({k: v[0] for k, v in q.items()})
            ok = q.get("state", [""])[0] == state and "code" in q
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(("Done. You can close this tab and return to the terminal." if ok else
                              "Authorisation failed or state mismatch. Return to the terminal.").encode())
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *a):          # keep the code out of the terminal
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    srv.timeout = timeout
    return srv, box


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", required=True, help="brand id (brands/<id>/)")
    ap.add_argument("--client-secrets", required=True, help="client_secret_*.json of a Google Cloud *Desktop app* OAuth client")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted"], help="default upload privacy")
    ap.add_argument("--api-key", action="store_true", help="also prompt (hidden) for a YouTube Data API key (keyword research)")
    ap.add_argument("--force", action="store_true", help="replace an existing youtube.json for this brand")
    ap.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()
    if not a.brand or set(a.brand) - SAFE or a.brand.startswith((".", "-")):
        raise SystemExit("invalid brand id")
    if not (ROOT / "brands" / a.brand / "brand.json").exists():
        raise SystemExit(f"no brands/{a.brand}/brand.json")
    dst_dir = ROOT / ".pipeline" / "secrets" / a.brand
    dst = dst_dir / "youtube.json"
    if dst.exists() and not a.force:
        raise SystemExit(f"{dst.relative_to(ROOT)} exists; pass --force to replace it")
    cs = json.loads(Path(a.client_secrets).expanduser().read_text())
    client = cs.get("installed") or {}
    if not client.get("client_id"):
        raise SystemExit("not a Desktop-app client file (expected an 'installed' section); create an OAuth client of type "
                         "'Desktop app' in Google Cloud Console")
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    srv, box = _wait_for_code(state, a.timeout)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "access_type": "offline",
        "prompt": "consent"})
    print(f"Opening the Google sign-in page for brand '{a.brand}'. If no browser opens, visit:\n\n{url}\n")
    print("Sign in with the account that owns THIS brand's YouTube channel.")
    webbrowser.open(url)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    t.join(a.timeout)
    srv.server_close()
    if box.get("state") != state or "code" not in box:
        raise SystemExit(f"no authorisation received ({box.get('error', 'timeout or state mismatch')})")
    form = {"code": box["code"], "client_id": client["client_id"], "redirect_uri": redirect,
            "grant_type": "authorization_code", "code_verifier": verifier}
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    tok = _post(TOKEN_URL, form)
    if not tok.get("refresh_token"):
        raise SystemExit("Google returned no refresh token (revoke the app's access at myaccount.google.com/permissions "
                         "and run again)")
    ch = (_get(CHANNELS_URL, tok["access_token"]).get("items") or [{}])[0]
    cfg = {"client_id": client["client_id"], "refresh_token": tok["refresh_token"], "privacyStatus": a.privacy,
           "brand": a.brand, "channel_id_at_setup": ch.get("id")}
    if client.get("client_secret"):
        cfg["client_secret"] = client["client_secret"]
    if a.api_key:
        k = getpass.getpass("YouTube Data API key (hidden, Enter to skip): ").strip()
        if k:
            cfg["api_key"] = k
    dst_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(dst_dir.parent, 0o700)
    os.chmod(dst_dir, 0o700)
    fd = os.open(dst.with_suffix(".tmp"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=1)
    os.replace(dst.with_suffix(".tmp"), dst)
    os.chmod(dst, 0o600)
    print(f"\nSaved {dst.relative_to(ROOT)} (mode 600). Token values were not printed.")
    print(f"Authorised channel: {ch.get('id')}  \"{(ch.get('snippet') or {}).get('title', '?')}\"")
    prof = json.loads((ROOT / "brands" / a.brand / "brand.json").read_text())
    exp = (((prof.get("publishing") or {}).get("accounts") or {}).get("youtube") or {}).get("channel_id")
    if not exp:
        print(f"Next: set brands/{a.brand}/brand.json publishing.accounts.youtube.channel_id to \"{ch.get('id')}\" "
              "(publishing refuses until it is set).")
    elif exp != ch.get("id"):
        print(f"WARNING: brand.json expects channel {exp}, but you authorised {ch.get('id')}. Publishing will be "
              "REFUSED. Re-run and pick the right channel.", file=sys.stderr)
        return 1
    else:
        print("Matches brands/<brand>/brand.json publishing.accounts.youtube.channel_id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
