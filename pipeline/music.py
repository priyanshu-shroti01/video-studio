"""Local music library with licence records and mood-based selection.

audio/music/library.json holds every track's source, licence (verified twice when fetched by
scripts/fetch_music.py), attribution, moods, tags, duration and sha256. audio/music/licenses.json holds
records for hand-added files (e.g. the synthetic test tone, which is marked not publishable).

Projects may set `"audio": {"music": "mood:corporate"}`; the choice is deterministic for a given
library, so config hashes and caches stay stable."""
from __future__ import annotations

import json
from pathlib import Path

from .errors import AssetError, ConfigError
from .paths import ROOT, sha256_file

MUSIC_DIR = ROOT / "audio/music"
MOODS = ["cinematic", "corporate", "technology", "energetic", "minimal", "educational", "calm", "promotional"]
RELATED = {"promotional": ["energetic", "corporate"], "technology": ["corporate", "minimal"],
           "educational": ["calm", "minimal"], "cinematic": ["minimal", "calm"], "corporate": ["technology", "promotional"],
           "energetic": ["promotional", "technology"], "minimal": ["calm", "technology"], "calm": ["minimal", "educational"]}


def tracks() -> list[dict]:
    out = []
    lib = MUSIC_DIR / "library.json"
    if lib.exists():
        out += json.loads(lib.read_text()).get("tracks", [])
    reg = MUSIC_DIR / "licenses.json"
    if reg.exists():
        for name, rec in json.loads(reg.read_text()).items():
            if not any(t["file"] == name for t in out):
                out.append({"id": Path(name).stem, "file": name, "title": name, "moods": rec.get("moods", []),
                            "license": rec.get("license", "UNKNOWN"), "attribution": rec.get("attribution", ""),
                            "landing_url": rec.get("source", ""), "publishable": rec.get("publishable", False),
                            "duration_s": None})
    return out


def record_for(path: Path) -> dict | None:
    for t in tracks():
        if (MUSIC_DIR / t["file"]).resolve() == Path(path).resolve():
            return t
    return None


def is_publishable(t: dict) -> bool:
    lic = (t.get("license") or "UNKNOWN").upper()
    return bool(t.get("publishable")) and lic not in ("UNKNOWN", "") and "TEST" not in lic


def select(mood: str, duration: float, *, publishable_only: bool = True) -> dict:
    if mood not in MOODS:
        raise ConfigError(f"unknown music mood {mood!r}; choose one of {MOODS}")
    cands = [t for t in tracks() if (MUSIC_DIR / t["file"]).exists() and (is_publishable(t) or not publishable_only)
             and t.get("brandSafe", True)]
    if not cands:
        raise AssetError("music library has no publishable tracks (run scripts/fetch_music.py or add licensed music)")

    def score(t):
        m = t.get("moods") or []
        s = 0 if mood in m else (1 if any(r in m for r in RELATED.get(mood, [])) else 2)
        d = t.get("duration_s") or 0
        return (s, 0 if d >= duration else 1, t["id"])        # prefer no looping, then a stable tie-break
    best = sorted(cands, key=score)[0]
    if score(best)[0] == 2:
        raise AssetError(f"no track for mood {mood!r} (or related moods) in the library")
    return best


def resolve(music: str | None, duration_hint: float = 35.0) -> tuple[str | None, dict | None]:
    """'mood:X' -> (relative file path, record); a path -> (path, record or None)."""
    if not music:
        return None, None
    if music.startswith("mood:"):
        t = select(music[5:], duration_hint)
        return f"audio/music/{t['file']}", t
    p = ROOT / music
    return music, record_for(p)


def verify_library() -> list[str]:
    """Integrity: every track exists and matches its recorded sha256; every record has a licence."""
    problems = []
    for t in tracks():
        f = MUSIC_DIR / t["file"]
        if not f.exists():
            problems.append(f"missing file {t['file']}")
        elif t.get("sha256") and sha256_file(f) != t["sha256"]:
            problems.append(f"{t['file']} does not match its recorded sha256")
        if not t.get("license") or t["license"] == "UNKNOWN":
            problems.append(f"{t['file']} has no licence record")
    return problems
