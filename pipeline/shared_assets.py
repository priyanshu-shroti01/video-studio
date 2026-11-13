"""Shared, licensed files every brand may use (public/shared/**, records in public/shared/assets.json).

Third-party product icons (e.g. WordPress) are looked up by product name so a scene shows the real icon only
when a licensed file and a trademark note exist; otherwise the engine falls back to a neutral initial."""
from __future__ import annotations

import json
from functools import lru_cache

from .paths import ROOT

REGISTRY = ROOT / "public/shared/assets.json"


@lru_cache(maxsize=1)
def _records() -> list[dict]:
    if not REGISTRY.exists():
        return []
    return json.loads(REGISTRY.read_text()).get("assets", [])


def app_icon(app: str) -> dict | None:
    """{asset, bg} for an app/product name ("WordPress"), or None if no licensed icon is registered."""
    key = app.strip().lower()
    for r in _records():
        if r.get("app", "").lower() == key and (ROOT / "public" / r["path"]).exists() and r.get("license"):
            return {"asset": r["path"], **({"bg": r["tileColor"]} if r.get("tileColor") else {})}
    return None
