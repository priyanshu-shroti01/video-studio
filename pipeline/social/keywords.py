"""Keyword / search-demand research (opt-in, network). It shows what people type into YouTube search;
it does NOT predict or guarantee ranking.

Privacy: the ONLY text sent is generic seed phrases from brands/<id>/brand.json
("publishing.social.products[].keywordSeeds") or extra seeds a person typed that pass `generic_seed()`
(short, lowercase words only, no URLs/emails/numbers). Briefs, narration, titles and project data are never
sent. Every outgoing request is returned in `queries` (API keys redacted). Results are cached for 24 h in
.pipeline/cache/keywords/ so repeated drafts do not re-query.

Sources
  suggest   https://suggestqueries.google.com/complete/search?client=youtube&ds=yt&hl=..&gl=..&q=..
            (the autocomplete endpoint YouTube's search box uses; unofficial and undocumented, may change)
  api       optional YouTube Data API v3 search.list (type=video, regionCode, relevanceLanguage) + videos.list
            for the top results' titles/tags/views. Needs "api_key" in .pipeline/secrets/<brand>/youtube.json.
            Quota (docs 2026-11-13): search.list = 1 unit in its own "Search Queries" bucket (100 calls/day);
            videos.list = 1 unit of the 10,000/day bucket. (Older docs: search.list = 100 units.)
Instagram has no public trends or keyword API, so there is nothing to query for it."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from ..paths import CACHE_DIR, atomic_write_json
from .brandcfg import NotConfigured, load, read_secrets, secrets_file

SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
TTL_S = 24 * 3600
SEED_RE = re.compile(r"^[a-z][a-z ]{2,58}[a-z]$")
UA = "Mozilla/5.0 (compatible; video-pipeline keyword research)"


def cache_dir():
    return CACHE_DIR / "keywords"


def generic_seed(s: str) -> str | None:
    """A seed is sendable only if it is a short generic phrase: lowercase letters and spaces, 1-6 words."""
    s = re.sub(r"\s+", " ", (s or "").strip().lower())
    if not SEED_RE.match(s) or len(s.split()) > 6:
        return None
    return s


def seeds_for(brand: str, product: str | None = None) -> list[str]:
    cfg = load(brand)
    entries = [cfg.product_for(product)] if product else cfg.products
    out = []
    for e in entries:
        for s in e.get("keywordSeeds", []):
            g = generic_seed(s)
            if g and g not in out:
                out.append(g)
    return out


def _get(url: str, timeout: float = 15.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _cached(key_url: str, fetch, http, ttl: float, now: float):
    f = cache_dir() / (hashlib.sha256(key_url.encode()).hexdigest()[:32] + ".json")
    try:
        d = json.loads(f.read_text())
        if now - d["fetched_at"] < ttl:
            return d["data"], True
    except (OSError, ValueError, KeyError):
        pass
    data = fetch(http)
    cache_dir().mkdir(parents=True, exist_ok=True)
    atomic_write_json(f, {"url": key_url, "fetched_at": now, "data": data})
    return data, False


def _parse_suggest(raw: bytes) -> list[str]:
    t = raw.decode("utf-8", "replace").strip()
    if not t.startswith("["):
        a, b = t.find("("), t.rfind(")")
        t = t[a + 1:b] if a >= 0 and b > a else "[]"
    d = json.loads(t)
    items = d[1] if isinstance(d, list) and len(d) > 1 else []
    return [i[0] if isinstance(i, list) else str(i) for i in items]


def research(brand: str, *, product: str | None = None, extra_seeds: list[str] | None = None, use_api: bool = False,
             http=None, ttl: float = TTL_S, max_api_seeds: int = 2, api_key: str | None = None) -> dict:
    cfg = load(brand)
    seeds = seeds_for(brand, product)
    rejected = []
    for s in extra_seeds or []:
        g = generic_seed(s)
        if g and g not in seeds:
            seeds.append(g)
        elif not g:
            rejected.append(s[:60])
    http = http or _get
    hl, gl = cfg.language, cfg.region.lower()
    now = time.time()
    res = {"brand": brand, "seeds": seeds, "rejected_seeds": rejected, "queries": [], "suggestions": {}, "api": {},
           "offline": False, "cached": 0, "quota_units": {"search_queries_bucket": 0, "default_bucket": 0},
           "notes": ["Keyword/search-demand research: shows what people search for, not a ranking guarantee.",
                     "Instagram has no public trends or keyword API; nothing was queried for Instagram.",
                     "Only the seed phrases above were sent; no brief, narration or project data."]}
    if rejected:
        res["notes"].append(f"{len(rejected)} extra seed(s) were not generic (lowercase words only, 1-6 words) and were NOT sent")
    for s in seeds:
        url = SUGGEST_URL + "?" + urllib.parse.urlencode({"client": "youtube", "ds": "yt", "hl": hl, "gl": gl, "q": s})
        res["queries"].append({"service": "youtube-suggest", "url": url})
        try:
            data, hit = _cached(url, lambda h, u=url: _parse_suggest(h(u)[1]), http, ttl, now)
            res["cached"] += hit
            res["suggestions"][s] = data
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            res["offline"] = True
            res["suggestions"][s] = []
            res.setdefault("errors", []).append(f"{s}: {type(e).__name__}")
    if use_api:
        key = api_key
        if key is None:
            try:
                key = read_secrets(secrets_file(brand, "youtube"), {"api_key"}, "YouTube API key")["api_key"]
            except NotConfigured as e:
                res["notes"].append(f"YouTube Data API skipped: {e.message}")
        if key:
            for s in seeds[:max_api_seeds]:
                q = {"part": "snippet", "type": "video", "maxResults": 10, "q": s, "regionCode": cfg.region.upper(),
                     "relevanceLanguage": hl}
                shown = SEARCH_URL + "?" + urllib.parse.urlencode({**q, "key": "REDACTED"})
                url = SEARCH_URL + "?" + urllib.parse.urlencode({**q, "key": key})
                res["queries"].append({"service": "youtube-data-api search.list", "url": shown})
                try:
                    data, hit = _cached(shown, lambda h, u=url: _api_search(h, u, key), http, ttl, now)
                    res["cached"] += hit
                    if not hit:
                        res["quota_units"]["search_queries_bucket"] += 1
                        res["quota_units"]["default_bucket"] += 1 if data.get("ids") else 0
                    res["api"][s] = data["videos"]
                    if data.get("ids"):
                        res["queries"].append({"service": "youtube-data-api videos.list",
                                               "url": VIDEOS_URL + "?part=snippet,statistics&id=" + ",".join(data["ids"]) + "&key=REDACTED"})
                except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
                    res["offline"] = True
                    res["api"][s] = []
                    res.setdefault("errors", []).append(f"api {s}: {type(e).__name__}")
    if res["offline"]:
        res["notes"].append("Offline or blocked: no live data for some seeds (empty results). Drafting still works.")
    res["ranked"] = _rank(res)
    return res


def _api_search(http, url: str, key: str) -> dict:
    st, raw = http(url)
    d = json.loads(raw)
    ids = [i["id"]["videoId"] for i in d.get("items", []) if i.get("id", {}).get("videoId")]
    vids = []
    if ids:
        st, raw = http(VIDEOS_URL + "?" + urllib.parse.urlencode({"part": "snippet,statistics", "id": ",".join(ids), "key": key}))
        for v in json.loads(raw).get("items", []):
            vids.append({"title": v["snippet"].get("title"), "channel": v["snippet"].get("channelTitle"),
                         "tags": (v["snippet"].get("tags") or [])[:15],
                         "views": int((v.get("statistics") or {}).get("viewCount", 0) or 0)})
    return {"ids": ids, "videos": vids}


def _rank(res: dict) -> list[dict]:
    """Phrases ordered by how many seeds' autocomplete lists they appear in (a rough demand signal)."""
    score: dict[str, dict] = {}
    for seed, items in res["suggestions"].items():
        for pos, s in enumerate(items):
            e = score.setdefault(s, {"phrase": s, "seeds": 0, "best_position": pos})
            e["seeds"] += 1
            e["best_position"] = min(e["best_position"], pos)
    return sorted(score.values(), key=lambda e: (-e["seeds"], e["best_position"], len(e["phrase"])))[:25]
