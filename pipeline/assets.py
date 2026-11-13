"""Asset registry: every file a video uses gets an id (sha256), type, source, licence, attribution and
usage references. Licences are looked up, never assumed: sound effects take their licence from the
opus-sound-layer manifest (library.json) by Freesound id / Kenney pack, brand files from
brands/<brand>/assets.json and public/shared/assets.json, music from audio/music/licenses.json. Anything else is 'UNKNOWN'."""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from .errors import AssetError
from .paths import ROOT, rel, sha256_file

TYPES = {".svg": "svg", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".mp3": "mp3",
         ".wav": "wav", ".mp4": "mp4", ".mov": "mov", ".webm": "webm", ".woff2": "font", ".ttf": "font", ".otf": "font", ".flac": "flac",
         ".ogg": "ogg", ".m4a": "m4a"}
MAGIC = {"png": b"\x89PNG", "jpeg": b"\xff\xd8\xff", "webp": b"RIFF", "wav": b"RIFF", "font": None}
SVG_FORBIDDEN = re.compile(r"<script|<foreignObject|\son\w+\s*=|javascript:|(?:xlink:)?href\s*=\s*[\"'](?:https?:|//|data:text)",
                           re.I)
LIB = ROOT / "skills/opus-sound-layer/scripts/library.json"

SCHEMA = """CREATE TABLE IF NOT EXISTS assets (
  sha256 TEXT PRIMARY KEY, path TEXT NOT NULL, type TEXT, bytes INTEGER, source TEXT, license TEXT,
  attribution TEXT, created_at REAL, last_seen REAL, refs_json TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS assets_path ON assets(path);"""


def asset_type(p: Path) -> str:
    t = TYPES.get(p.suffix.lower())
    if not t:
        raise AssetError(f"unsupported asset format: {p.name}")
    return t


def check_svg(p: Path) -> None:
    text = p.read_text(encoding="utf-8", errors="replace")
    if "<svg" not in text[:2000]:
        raise AssetError(f"not an SVG document: {rel(p)}")
    m = SVG_FORBIDDEN.search(text)
    if m:
        raise AssetError(f"unsafe SVG content in {rel(p)}: {m.group(0)!r} (scripts/handlers/external refs are not allowed)")


def validate_file(p: Path) -> str:
    """Existence, non-empty, known format, magic bytes / decodability. Returns the asset type."""
    if not p.exists():
        raise AssetError(f"missing asset: {rel(p)}")
    if p.stat().st_size == 0:
        raise AssetError(f"empty asset: {rel(p)}")
    t = asset_type(p)
    head = p.read_bytes()[:16]
    if t == "svg":
        check_svg(p)
    elif t == "font":
        if head[:4] not in (b"wOF2", b"wOFF", b"\x00\x01\x00\x00", b"OTTO", b"true"):
            raise AssetError(f"corrupt font: {rel(p)}")
    elif MAGIC.get(t) and not head.startswith(MAGIC[t]):
        raise AssetError(f"{rel(p)} does not look like a {t} file")
    if t in ("mp3", "wav", "mp4", "mov", "webm", "flac", "ogg", "m4a"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            raise AssetError(f"corrupt or undecodable media: {rel(p)}", detail=r.stderr[-300:])
    return t


_lib_cache: dict | None = None


def _library() -> dict:
    global _lib_cache
    if _lib_cache is None:
        _lib_cache = {"fs": {}, "packs": {}}
        if LIB.exists():
            lib = json.loads(LIB.read_text())
            for it in lib.get("freesound", []):
                _lib_cache["fs"][str(it["id"])] = it
            for pk in lib.get("packs", []):
                _lib_cache["packs"][pk["name"]] = pk
    return _lib_cache


def license_for(p: Path) -> tuple[str, str, str]:
    """-> (source, license, attribution)"""
    r = rel(p)
    if r.startswith("audio/kit/"):
        m = re.search(r"/fs-(\d+)-", r)
        if m and m.group(1) in _library()["fs"]:
            it = _library()["fs"][m.group(1)]
            return (it.get("landing") or it.get("url", "freesound"), it.get("license", "UNKNOWN").upper(),
                    f"\"{it.get('title', '')}\" by {it.get('creator', '?')}")
        m = re.search(r"/kenney-([a-z-]+?)-", r)
        if m:
            for name, pk in _library()["packs"].items():
                if m.group(1).startswith(name):
                    return pk.get("landing", "kenney.nl"), pk.get("license", "UNKNOWN").upper(), pk.get("credit", "Kenney")
        return "audio/kit", "UNKNOWN", ""
    for reg in [ROOT / "public/shared/assets.json", *(ROOT / "brands").glob("*/assets.json")]:
        if not reg.exists():
            continue
        data = json.loads(reg.read_text())
        for a in data.get("assets", []):
            if r == a["path"] or r == f"public/{a['path']}":
                return a.get("source", ""), a.get("license", "UNKNOWN"), a.get("attribution", "")
    if r.startswith("audio/music/"):
        from .music import record_for
        rec = record_for(p)
        if rec:
            return rec.get("landing_url", ""), rec.get("license", "UNKNOWN"), rec.get("attribution", "")
    music_reg = ROOT / "audio/music/licenses.json"
    if r.startswith("audio/music/") and music_reg.exists():
        data = json.loads(music_reg.read_text())
        if p.name in data:
            e = data[p.name]
            return e.get("source", ""), e.get("license", "UNKNOWN"), e.get("attribution", "")
    return "local", "UNKNOWN", ""


class AssetRegistry:
    def __init__(self, registry):
        self.reg = registry
        with self.reg.conn() as c:
            c.executescript(SCHEMA)

    def register(self, p: Path, ref: str | None = None) -> dict:
        t = validate_file(p)
        h = sha256_file(p)
        src, lic, attr = license_for(p)
        now = time.time()
        with self.reg.conn() as c:
            row = c.execute("SELECT refs_json, path FROM assets WHERE sha256=?", (h,)).fetchone()
            refs = json.loads(row["refs_json"]) if row else []
            if ref and ref not in refs:
                refs.append(ref)
            if row:
                c.execute("UPDATE assets SET last_seen=?, refs_json=? WHERE sha256=?", (now, json.dumps(refs[-50:]), h))
            else:
                c.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (h, rel(p), t, p.stat().st_size, src, lic, attr, now, now, json.dumps(refs)))
        return {"id": h[:16], "sha256": h, "path": rel(p), "type": t, "bytes": p.stat().st_size, "source": src,
                "license": lic, "attribution": attr}

    def duplicates(self) -> list[tuple[str, list[str]]]:
        """Same bytes registered under different paths (sha256 is the key, so compare current files)."""
        seen: dict[str, list[str]] = {}
        with self.reg.conn() as c:
            rows = c.execute("SELECT path FROM assets").fetchall()
        for r in rows:
            p = ROOT / r["path"]
            if p.exists():
                seen.setdefault(sha256_file(p), []).append(r["path"])
        return [(h, ps) for h, ps in seen.items() if len(ps) > 1]

    def scan(self, roots: list[str]) -> dict:
        ok, bad = 0, []
        for r in roots:
            base = ROOT / r
            for p in sorted(base.rglob("*")) if base.exists() else []:
                if p.is_file() and p.suffix.lower() in TYPES and "/_raw/" not in str(p) and not p.name.startswith("."):
                    try:
                        self.register(p)
                        ok += 1
                    except AssetError as e:
                        bad.append(str(e))
        with self.reg.conn() as c:
            lic = {r[0]: r[1] for r in c.execute("SELECT license, COUNT(*) FROM assets GROUP BY license").fetchall()}
        return {"registered": ok, "invalid": bad, "licenses": lic}
