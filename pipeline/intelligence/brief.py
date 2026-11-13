"""Product brief: schema, validation, normalisation, and extraction of requirements from the free-text
request ("Create a 35-second premium YouTube Short ... Show a compelling problem, a product demonstration,
an animated pricing comparison and a strong CTA.")."""
from __future__ import annotations

import copy
import re

from ..errors import ConfigError
from ..schema import validate

FORMATS = ["short", "landscape"]
GOALS = ["conversions", "awareness", "education", "engagement", "retention", "launch"]
REQUIREMENTS = ["problem", "demonstration", "pricing-comparison", "pricing", "cta", "testimonial", "tutorial",
                "feature-list", "myth", "before-after"]

BRIEF_SCHEMA = {
    "type": "object",
    "required": ["brand", "product"],
    "additionalProperties": False,
    "properties": {
        "brand": {"type": "string", "minLength": 1, "maxLength": 80},
        "product": {"type": "string", "minLength": 1, "maxLength": 120},
        "price": {"type": ["string", "null"], "maxLength": 60},
        "audience": {"type": "string", "maxLength": 160},
        "format": {"type": "string", "enum": FORMATS},
        "formats": {"type": "array", "items": {"type": "string", "enum": FORMATS}, "minItems": 1, "maxItems": 2},  # render several
        "duration_seconds": {"type": "integer", "minimum": 10, "maximum": 180},
        "duration_flexible": {"type": "boolean"},   # let the story set the length (hybrid engine: up to the Shorts limit)
        # hybrid engine: "generate" lets the composer design new scene graphics (docs/CREATIVE_SYSTEM.md); default "templates"
        "components": {"type": "string", "enum": ["templates", "generate"]},
        "goal": {"type": "string", "maxLength": 60},
        "cta": {"type": "string", "maxLength": 60},
        "tone": {"type": "string", "maxLength": 120},
        "voice": {"type": "string", "maxLength": 60},
        "request": {"type": "string", "maxLength": 2000},
        "requirements": {"type": "array", "items": {"type": "string", "enum": REQUIREMENTS}},
        "platform": {"type": "string", "maxLength": 40},
        "brand_id": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_-]{0,40}$"},
        "url": {"type": "string", "maxLength": 120},
        "notes": {"type": "string", "maxLength": 2000},
    },
}

_REQ_PATTERNS = [
    ("problem", r"\bproblem\b|pain[- ]point|frustrat"),
    ("demonstration", r"\bdemo(nstration)?\b|walk-?through|show (how|the product)"),
    ("pricing-comparison", r"pric\w* comparison|compar\w* (the )?pric|price vs|pricing table|vs\.? (other|competitor)"),
    ("pricing", r"\bpric(e|ing)\b"),
    ("cta", r"\bcta\b|call to action"),
    ("testimonial", r"testimonial|review"),
    ("tutorial", r"tutorial|how[- ]to|step[- ]by[- ]step"),
    ("myth", r"\bmyth"),
    ("before-after", r"before.{0,12}after"),
]


def parse_price(s: str | None) -> dict | None:
    """'₹39/month' -> {'amount': 39, 'currency': 'INR', 'period': 'month', 'text': '₹39/month'}"""
    if not s:
        return None
    m = re.search(r"(₹|rs\.?|inr|\$|usd|€|eur)?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:rupees)?\s*(?:/|per|a)?\s*(mo|month|yr|year|annum)?",
                  s, re.I)
    if not m:
        return None
    cur = (m.group(1) or "₹").lower()
    currency = {"$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR"}.get(cur, "INR")
    per = (m.group(3) or "month").lower()
    return {"amount": float(m.group(2).replace(",", "")) if "." in m.group(2) else int(m.group(2).replace(",", "")),
            "currency": currency, "period": "year" if per in ("yr", "year", "annum") else "month", "text": s.strip()}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())[:40] or "brand"


def parse_brief(data: dict, request: str | None = None) -> tuple[dict, list[str]]:
    """Validate + normalise. Returns (brief, warnings). Raises ConfigError listing every problem."""
    if not isinstance(data, dict):
        raise ConfigError("brief must be a JSON object")
    b = copy.deepcopy(data)
    if request:
        b["request"] = request
    if isinstance(b.get("format"), str):
        b["format"] = b["format"].strip().lower()
    if isinstance(b.get("duration_seconds"), float) and b["duration_seconds"].is_integer():
        b["duration_seconds"] = int(b["duration_seconds"])
    errs = validate(b, BRIEF_SCHEMA, "$brief")
    if errs:
        raise ConfigError("brief is invalid", detail="\n".join(errs))
    warnings: list[str] = []
    text = b.get("request", "")
    low = text.lower()
    # fill from the request sentence, never silently override explicit fields
    m = re.search(r"(\d{1,3})\s*[- ]?(?:second|sec|s\b)", low)
    if m:
        d = int(m.group(1))
        if "duration_seconds" not in b:
            b["duration_seconds"] = d
        elif b["duration_seconds"] != d:
            warnings.append(f"request says {d}s but duration_seconds is {b['duration_seconds']}; using {b['duration_seconds']}")
    if "format" not in b:
        b["format"] = "short" if re.search(r"\bshorts?\b|reel|tiktok|vertical|9:16", low) else "landscape" if \
            re.search(r"landscape|16:9|youtube video", low) else "short"
    if "platform" not in b:
        b["platform"] = "youtube-shorts" if re.search(r"youtube short", low) else ("youtube" if "youtube" in low else
                                                                                  "shorts" if b["format"] == "short" else "web")
    if "tone" not in b:
        tones = [w for w in ("premium", "playful", "bold", "friendly", "calm", "urgent", "technical", "confident") if w in low]
        b["tone"] = ", ".join(tones) if tones else "confident, friendly"
    reqs = list(b.get("requirements", []))
    for name, pat in _REQ_PATTERNS:
        if re.search(pat, low) and name not in reqs:
            if name == "pricing" and "pricing-comparison" in reqs:
                continue
            reqs.append(name)
    if b.get("cta") and "cta" not in reqs:
        reqs.append("cta")
    b["requirements"] = reqs
    b.setdefault("duration_seconds", 35 if b["format"] == "short" else 75)
    b.setdefault("goal", "conversions")
    b.setdefault("audience", "")
    b.setdefault("cta", "Get started")
    if not b.get("brand_id"):
        try:
            from ..brands import resolve_brand
            b["brand_id"] = resolve_brand(b["brand"])          # by id, display name or domain
        except ConfigError:
            b["brand_id"] = slug(b["brand"])                    # unknown brand: facts lookup will say so
    if b["format"] == "short" and not 15 <= b["duration_seconds"] <= 60:
        warnings.append(f"a Short of {b['duration_seconds']}s is outside the 15–60 s range")
    if b.get("goal", "").lower() not in GOALS:
        warnings.append(f"goal {b['goal']!r} is not one of {GOALS}; treated as free text")
    pr = parse_price(b.get("price"))
    if b.get("price") and pr is None:
        warnings.append(f"could not parse price {b['price']!r}")
    b["price_parsed"] = pr
    return b, warnings


def brief_claims(brief: dict) -> list[dict]:
    """Claims the brief itself makes (to be verified against facts like everything else)."""
    out = []
    if brief.get("price"):
        out.append({"scope": "brief.price", "text": f"{brief['product']} at {brief['price']}"})
    if brief.get("request"):
        out.append({"scope": "brief.request", "text": brief["request"]})
    return out
