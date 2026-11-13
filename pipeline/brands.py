"""Brand profiles and isolation.

brands/<id>/theme.json   design tokens the engine draws with (colours, fonts, logos, captions, sfx conventions)
brands/<id>/brand.json   profile: watermark policy, intro/outro, publishing defaults, allowed asset roots
brands/<id>/assets.json  licence records for the brand's own files
public/brands/<id>/      the brand's files (logos, fonts, product UI, screenshots)

Isolation rule: a production for brand A may reference only public/brands/A/** and shared, licensed
roots (public/shared/**, audio/kit, audio/music). Validation rejects anything else, so one brand's
logo or screenshots can never leak into another brand's video."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import ConfigError
from .paths import ROOT, safe_name, safe_path

BRANDS_DIR = ROOT / "brands"
SHARED_ROOTS = ("public/shared/", "audio/kit/", "audio/music/")
WATERMARK_POLICIES = {"none", "brand", "custom", "platform"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def list_brands() -> list[str]:
    return sorted(p.name for p in BRANDS_DIR.iterdir() if (p / "theme.json").exists() and not p.name.startswith("_"))


def is_hidden(brand: str) -> bool:
    """Test/fixture brands (brand.json "hidden": true) stay usable by exact id but never appear in lists."""
    try:
        return bool(load_profile(brand).get("hidden"))
    except Exception:  # noqa: BLE001
        return False


def visible_brands() -> list[str]:
    return [b for b in list_brands() if not is_hidden(b)]


def resolve_brand(ref: str) -> str:
    """Brand id from an id, a display name ("Shroti Host") or a domain ("shrotihost.in"). Raises ConfigError if none
    or several brands match, so a brief can never silently land on the wrong brand."""
    key = re.sub(r"[^a-z0-9.]", "", (ref or "").lower()).removeprefix("www.")
    hits = []
    for b in list_brands():
        prof = load_profile(b)
        bid = re.sub(r"[^a-z0-9.]", "", b)            # ids are compared normalised, like the reference
        if prof.get("hidden") and ref.strip().lower() != b:   # hidden test brands: exact id only
            continue
        site = re.sub(r"^https?://(www\.)?", "", prof.get("website", "") or "").strip("/").lower()
        names = {bid, re.sub(r"[^a-z0-9]", "", prof.get("name", "").lower()), site, site.split(".")[0] if site else ""}
        if key and key in names - {""}:
            hits.append(b)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ConfigError(f"no brand matches {ref!r}; known brands: {list_brands()} (add one: video-pipeline brand init)")
    raise ConfigError(f"{ref!r} matches several brands {hits}; pass --brand <id>")


def load_profile(brand: str) -> dict:
    safe_name(brand)
    f = BRANDS_DIR / brand / "brand.json"
    prof = json.loads(f.read_text()) if f.exists() else {}
    prof.setdefault("id", brand)
    prof.setdefault("assetRoots", [f"public/brands/{brand}/"])
    prof.setdefault("watermark", {"policy": "none"})
    prof.setdefault("publishing", {})
    return prof


def load_pronunciation(brand: str) -> dict[str, str]:
    """brands/<id>/pronunciation.json -> {display: spoken} (brand names, domains, product names)."""
    f = BRANDS_DIR / safe_name(brand) / "pronunciation.json"
    if not f.exists():
        return {}
    return {e["display"]: e["spoken"] for e in json.loads(f.read_text()).get("entries", [])}


def asset_allowed(brand: str, path: str, profile: dict | None = None) -> bool:
    p = path.replace("\\", "/").lstrip("/")
    if not p.startswith(("public/", "audio/")):
        p = "public/" + p                                       # theme/engine paths are public-relative
    roots = (profile or load_profile(brand))["assetRoots"]
    return any(p.startswith(r) for r in roots) or p.startswith(SHARED_ROOTS)


def svg_aspect(path: Path) -> float | None:
    head = path.read_text(errors="replace")[:4000]
    m = re.search(r'viewBox\s*=\s*"\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', head)
    if m and float(m.group(2)):
        return float(m.group(1)) / float(m.group(2))
    return None


def validate_brand(brand: str, theme: dict) -> list[str]:
    """Static brand checks: colour tokens, fonts and logos exist inside the brand's roots, logo aspect
    declared in the theme matches the SVG, watermark policy is valid."""
    errs, prof = [], load_profile(brand)
    for k, v in theme.get("colors", {}).items():
        if isinstance(v, str) and v.startswith("#") and not HEX.match(v):
            errs.append(f"colour {k}={v} is not #RRGGBB")
    paths = [theme["logo"][k] for k in ("onDark", "onLight", "mark")] + \
            [f["src"] for fam in theme["fonts"].values() for f in fam["files"]]
    for p in paths:
        if not asset_allowed(brand, p, prof):
            errs.append(f"asset {p} is outside brand '{brand}' roots {prof['assetRoots']} (cross-brand isolation)")
        try:
            safe_path(Path("public") / p, must_exist=True)
        except Exception as e:  # noqa: BLE001
            errs.append(str(e))
    full = ROOT / "public" / theme["logo"]["onDark"]
    if full.exists() and full.suffix == ".svg":
        a = svg_aspect(full)
        if a and abs(a - theme["logo"]["aspect"]) / a > 0.05:
            errs.append(f"theme logo.aspect {theme['logo']['aspect']} != SVG viewBox aspect {a:.3f} (would distort the logo)")
    wm = prof.get("watermark", {})
    if wm.get("policy", "none") not in WATERMARK_POLICIES:
        errs.append(f"watermark policy {wm.get('policy')!r} not in {sorted(WATERMARK_POLICIES)}")
    if wm.get("policy") == "custom" and not wm.get("asset"):
        errs.append("watermark policy 'custom' needs an asset")
    if wm.get("asset") and not asset_allowed(brand, wm["asset"], prof):
        errs.append(f"watermark asset {wm['asset']} is outside the brand's roots")
    if not 0.05 <= float(wm.get("opacity", 0.85)) <= 1:
        errs.append("watermark opacity must be between 0.05 and 1")
    return errs


def referenced_assets(storyboard: dict) -> list[str]:
    """Every file path a storyboard's blocks point at (image/device/custom assets)."""
    out = []

    def rec(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("asset", "src", "image", "screenshot") and isinstance(v, str):
                    out.append(v)
                else:
                    rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(storyboard)
    return out
