#!/usr/bin/env python3
"""Build the local music library from CC0 recordings (explicit, one-off network operation).

Searches Openverse (public API, no key) with generic mood keywords only — no project data — and keeps
a track only if BOTH Openverse and the source landing page say CC0. Every kept track gets a full
licence record in audio/music/library.json. Re-runnable; existing files are not re-downloaded.

  uv run python scripts/fetch_music.py --per-mood 1 --max-mb 120
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC = ROOT / "audio/music"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
MOODS = {  # mood -> search terms (generic, no project data)
    "corporate": ["corporate background music", "business background"],
    "technology": ["technology background music", "electronic ambient loop"],
    "cinematic": ["cinematic background", "cinematic ambient"],
    "energetic": ["upbeat electronic loop", "energetic background music"],
    "minimal": ["minimal ambient music", "minimal piano"],
    "calm": ["calm ambient music", "soft piano background"],
    "promotional": ["upbeat background music", "happy background music"],
    "educational": ["light background music", "soft acoustic background"],
}


def get(url: str, timeout=60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search(q: str) -> list[dict]:
    # Freesound items carry no Openverse "category", so music is identified by title/tags instead
    qs = urllib.parse.urlencode({"q": q, "license": "cc0", "page_size": 20})  # anonymous limit
    data = json.loads(get(f"https://api.openverse.org/v1/audio/?{qs}"))
    return data.get("results", [])


MUSIC_WORDS = re.compile(r"music|loop|track|beat|song|melod|piano|synth|guitar|electronic|corporate|cinematic|"
                         r"instrumental|soundtrack|chill|lofi|lo-fi|ambient-music|background", re.I)
NOT_MUSIC = re.compile(r"field.?recording|soundscape|ambience|nature|birds?|street|traffic|rain|wind|crowd|"
                       r"voice|speech|footsteps|sfx|sound.?effect|foley", re.I)


def is_music(r: dict) -> bool:
    text = " ".join([r.get("title") or ""] + [t["name"] for t in (r.get("tags") or [])])
    return bool(MUSIC_WORDS.search(text)) and not NOT_MUSIC.search(text)


def landing_says_cc0(url: str) -> bool:
    try:
        html = get(url, timeout=30).decode("utf-8", "replace")
    except Exception:
        return False
    return bool(re.search(r"Creative Commons 0|CC0 1\.0|publicdomain/zero/1\.0|Public Domain Dedication", html, re.I))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-mood", type=int, default=1)
    ap.add_argument("--max-mb", type=float, default=120)
    a = ap.parse_args()
    lib_f = MUSIC / "library.json"
    lib = json.loads(lib_f.read_text()) if lib_f.exists() else {"tracks": []}
    have = {t["source_id"] for t in lib["tracks"]}
    used_mb = sum((MUSIC / t["file"]).stat().st_size for t in lib["tracks"] if (MUSIC / t["file"]).exists()) / 1e6
    for mood, queries in MOODS.items():
        got = sum(1 for t in lib["tracks"] if t["moods"][0] == mood)
        for q in queries:
            if got >= a.per_mood:
                break
            results = None
            for attempt in range(2):
                try:
                    results = search(q)
                    break
                except Exception as e:
                    print(f"search failed for {q!r}: {e}", file=sys.stderr)
                    if "429" in str(e) and attempt == 0:
                        time.sleep(90)  # anonymous rate limit
            time.sleep(10)  # be polite to the public API
            if not results:
                continue
            for r in results:
                if got >= a.per_mood:
                    break
                dur = (r.get("duration") or 0) / 1000
                ft = (r.get("filetype") or "").lower()
                if r.get("license") != "cc0" or r["id"] in have or not (30 <= dur <= 300) or ft not in ("mp3", "wav", "flac", "ogg"):
                    continue
                if (r.get("filesize") or 0) / 1e6 > 25 or not is_music(r):
                    continue
                if not landing_says_cc0(r["foreign_landing_url"]):
                    print(f"  skip {r['title']!r}: landing page does not confirm CC0")
                    continue
                try:
                    blob = get(r["url"], timeout=120)
                except Exception as e:
                    print(f"  skip {r['title']!r}: download failed ({e})")
                    continue
                if used_mb + len(blob) / 1e6 > a.max_mb:
                    print("  budget reached"); break
                slug = re.sub(r"[^a-z0-9]+", "-", r["title"].lower()).strip("-")[:40] or "track"
                name = f"{mood}-{slug}.{ft}"
                (MUSIC / name).write_bytes(blob)
                used_mb += len(blob) / 1e6
                lib["tracks"].append({
                    "id": f"{mood}-{slug}", "file": name, "title": r["title"], "creator": r.get("creator") or "unknown",
                    "source": r.get("source") or r.get("provider"), "source_id": r["id"],
                    "landing_url": r["foreign_landing_url"], "download_url": r["url"],
                    "license": "CC0-1.0", "license_url": r.get("license_url"), "license_verified": [
                        "openverse:cc0", "landing-page:cc0"], "attribution_required": False,
                    "attribution": f"\"{r['title']}\" by {r.get('creator') or 'unknown'} ({r.get('source')}), CC0",
                    "moods": [mood], "search_query": q, "tags": [t["name"] for t in (r.get("tags") or [])][:15],
                    "genres": r.get("genres") or [], "duration_s": round(dur, 2), "sha256": hashlib.sha256(blob).hexdigest(),
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "publishable": True,
                    "usage_restrictions": "none (CC0); do not claim authorship of the recording"})
                have.add(r["id"]); got += 1
                print(f"  + {mood:<12} {r['title'][:50]!r} by {r.get('creator')} ({dur:.0f}s, {len(blob)/1e6:.1f} MB)")
        lib_f.write_text(json.dumps(lib, indent=1, ensure_ascii=False))
    print(f"library: {len(lib['tracks'])} tracks, {used_mb:.1f} MB")


if __name__ == "__main__":
    main()
