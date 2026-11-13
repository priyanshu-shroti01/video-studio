"""Per-brand social configuration and per-brand secrets.

Everything brand-specific (voice, link, CTA, hashtag sets, keyword seeds, expected accounts) lives in
brands/<id>/brand.json under "publishing". Code only holds brand-neutral defaults.

Secrets live in .pipeline/secrets/<brand_id>/{youtube,instagram}.json (file 0600, directory 0700).
A legacy global .pipeline/secrets/youtube.json is never used: it could post one brand's video to
another brand's channel. `secrets_file()` explains how to migrate it."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConfigError, PipelineError
from ..paths import STATE_DIR, safe_name

SECRETS_ROOT = STATE_DIR / "secrets"
PLATFORMS = ("youtube", "instagram")
# Generic engagement-bait tags. They say nothing about the video and are never added.
BANNED_HASHTAGS = {"#fyp", "#foryou", "#foryoupage", "#viral", "#explore", "#explorepage", "#trending", "#reels",
                   "#reelsinstagram", "#instagood", "#likeforlike", "#follow", "#followme", "#shorts", "#youtubeshorts"}


class NotConfigured(PipelineError):
    code, exit_code = "PUBLISH_NOT_CONFIGURED", 2


class AccountMismatch(PipelineError):
    code, exit_code = "PUBLISH_ACCOUNT_MISMATCH", 6


@dataclass
class BrandSocial:
    brand_id: str
    name: str
    link: str
    domain: str
    voice: str
    language: str
    region: str
    category_id: str
    ai_disclosure: bool
    cta: dict
    hashtags: dict
    products: list[dict]
    accounts: dict
    privacy_default: str
    knowledge: str | None
    banned: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def product_for(self, product_text: str) -> dict:
        """Best product entry for a brief's product name (first `match` hit wins); a neutral default otherwise."""
        low = f" {product_text.lower()} "
        for p in self.products:
            if any(m.lower() in low for m in p.get("match", [])):
                return p
        name = product_text.strip() or self.name
        return {"id": "default", "match": [], "factProduct": None, "primaryKeyword": name,
                "keywordSeeds": [], "tags": [name], "highlightFactIds": [], "hashtags": {}}

    def expected_account(self, platform: str) -> str | None:
        a = self.accounts.get(platform) or {}
        v = a.get("channel_id") if platform == "youtube" else a.get("ig_user_id")
        return str(v) if v else None


def load(brand_id: str) -> BrandSocial:
    from ..brands import load_profile
    prof = load_profile(safe_name(brand_id))
    pub = prof.get("publishing", {})
    soc = pub.get("social", {})
    link = soc.get("link") or prof.get("website") or ""
    domain = re.sub(r"^https?://", "", link).strip("/").split("/")[0]
    name = prof.get("name", brand_id)
    return BrandSocial(
        brand_id=brand_id, name=name, link=link, domain=domain,
        voice=soc.get("voice", "Clear, specific and honest. No hype, no fake urgency, no unsupported superlatives."),
        language=soc.get("language", "en"), region=soc.get("region", "US"), category_id=str(soc.get("categoryId", "28")),
        ai_disclosure=bool(soc.get("aiDisclosure", True)),
        cta={"youtube": f"Learn more at {link}" if link else "", "instagram": "Link in bio", **soc.get("cta", {})},
        hashtags={"youtube": [], "instagram": [], **soc.get("hashtags", {})},
        products=list(soc.get("products", [])), accounts=dict(pub.get("accounts", {})),
        privacy_default=pub.get("privacyDefault", "private"), knowledge=prof.get("knowledge"),
        banned=[*soc.get("bannedPhrases", []), *(prof.get("creative") or {}).get("banned", [])], raw=soc)


def load_brand_facts(cfg: BrandSocial):
    from ..intelligence.facts import empty_facts, load_facts
    from ..paths import safe_path
    try:
        return load_facts(cfg.brand_id, safe_path(cfg.knowledge)) if cfg.knowledge else load_facts(cfg.brand_id)
    except ConfigError:
        return empty_facts(cfg.brand_id, cfg.name)


# ---- secrets ------------------------------------------------------------------------------------------
def secrets_dir(brand_id: str) -> Path:
    return SECRETS_ROOT / safe_name(brand_id)


def secrets_file(brand_id: str, platform: str) -> Path:
    if platform not in PLATFORMS:
        raise ValueError(platform)
    f = secrets_dir(brand_id) / f"{platform}.json"
    legacy = SECRETS_ROOT / f"{platform}.json"
    if not f.exists() and legacy.exists():
        raise NotConfigured(
            f"found the legacy global {legacy.name}, which is not tied to a brand and is never used. If it belongs "
            f"to brand {brand_id!r}: mkdir -p -m 700 .pipeline/secrets/{brand_id} && mv .pipeline/secrets/{legacy.name} "
            f".pipeline/secrets/{brand_id}/ && chmod 600 .pipeline/secrets/{brand_id}/{legacy.name}")
    return f


def read_secrets(path: Path, required: set[str], label: str) -> dict:
    """Load a secrets file, enforcing owner-only permissions. Never echoes values."""
    if not path.exists():
        raise NotConfigured(f"{label} is not configured (no {path.name} in {path.parent.name}/); see docs/SOCIAL_SETUP.md")
    if os.stat(path).st_mode & 0o077:
        raise NotConfigured(f"{path.name} must be private to you (chmod 600)")
    if path.parent != SECRETS_ROOT and SECRETS_ROOT in path.parents and os.stat(path.parent).st_mode & 0o077:
        raise NotConfigured(f"the secrets directory {path.parent.name}/ must be private to you (chmod 700)")
    try:
        cfg = json.loads(path.read_text())
    except ValueError as e:
        raise NotConfigured(f"{path.name} is not valid JSON") from e
    missing = sorted(k for k in required if not cfg.get(k))
    if missing:
        raise NotConfigured(f"{path.name} is missing {missing}")
    return cfg


def write_secrets(path: Path, cfg: dict) -> None:
    """Atomic owner-only write (used by token helpers)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def account_status(brand_id: str) -> dict:
    """Offline view: expected accounts from brand.json and whether a secrets file exists (values never shown)."""
    cfg = load(brand_id)
    out = {}
    for p in PLATFORMS:
        try:
            f = secrets_file(brand_id, p)
            configured, note = f.exists(), ""
        except NotConfigured as e:
            configured, note = False, e.message
        out[p] = {"expected_account": cfg.expected_account(p), "credentials_file": configured,
                  **({"note": note} if note else {})}
    return out
