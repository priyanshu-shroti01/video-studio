"""Brand creative profile: brands/<id>/brand.json "creative" section + the brand's verified facts.

Nothing brand-specific lives in pipeline/creative code. A brand opts in with:

    "creative": {
      "industry": "web-hosting",              # selects the industry pack (pipeline/creative/industries)
      "voice": "…",                           # house voice, shown to the LLM copy assistant
      "cta": "Get started",                   # default CTA when the brief has none
      "tagline": {"<family>": {"fact": "<fact id>"} | {"text": "…"}, "default": …},
      "banned": ["…"],                        # brand-specific banned words (on top of the generic list)
      "placeholderDomain": "yourbrand.in"     # illustrative UI domain (optional; default yourbrand.<brand tld>)
    }

The domain comes from the fact base (company.url) or the profile's website; it is required. URL cue words are
derived from it: the engine anchors on DISPLAY tokens (spoken-word timings are mapped back onto display tokens by
pipeline.voice.pronunciation / timing.map_to_display), so the cue is the domain's first label, whatever the
pronunciation dictionary makes the voice say."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..brands import load_profile
from ..errors import ConfigError
from ..intelligence.facts import FactBase
from ..paths import ROOT
from ..timing import tokenize


@dataclass
class BrandCreative:
    id: str
    name: str
    domain: str
    industry: str
    voice: str
    cta: str
    banned: list[str]
    tagline_spec: dict
    placeholder_domain: str
    extra: dict = field(default_factory=dict)

    @property
    def url_cue(self) -> str:
        """The word the URL beat anchors on: first label of the display domain ("example" for example.in)."""
        return self.domain.split(".")[0]

    @property
    def name_cue(self) -> str:
        return re.sub(r"[^\w]", "", self.name.split()[0]) if self.name.split() else self.name

    def tagline(self, family: str, fb: FactBase) -> tuple[str, str | None]:
        """(tagline text, source fact id or None)."""
        spec = self.tagline_spec.get(family) or self.tagline_spec.get("default") or {}
        if isinstance(spec, str):
            return spec, None
        if spec.get("fact"):
            f = fb.by_id(spec["fact"])
            if f:
                v = f.get("value", {})
                return (v.get("text") or f["claim"]), f["id"]
        return spec.get("text", ""), None


def load_brand(brand_id: str | None, fb: FactBase) -> BrandCreative:
    if not brand_id:
        raise ConfigError("no brand given: the brief must name its brand (there is no default brand)")
    if not (ROOT / "brands" / brand_id / "brand.json").exists():
        raise ConfigError(f"brand profile brands/{brand_id}/brand.json not found; create it (with a 'creative' section) first")
    prof = load_profile(brand_id)
    cr = prof.get("creative")
    if not isinstance(cr, dict) or not cr.get("industry"):
        raise ConfigError(f"brands/{brand_id}/brand.json has no creative.industry; add a 'creative' section "
                          f"(industry, voice, cta, tagline, banned) — see docs/CREATIVE_SYSTEM.md")
    domain = fb.domain() if fb.facts else ""
    if not domain:
        domain = re.sub(r"^https?://(www\.)?", "", prof.get("website", "") or (prof.get("outro") or {}).get("url", "")).strip("/")
    if not domain:
        raise ConfigError(f"brand {brand_id!r}: no domain in knowledge/{brand_id}/facts.json (company.url) or brand.json website")
    if len(tokenize(domain)) != 1:
        raise ConfigError(f"brand {brand_id!r}: domain {domain!r} must be a single token")
    tld = domain.rsplit(".", 1)[-1]
    return BrandCreative(id=brand_id, name=prof.get("name") or brand_id, domain=domain, industry=cr["industry"],
                         voice=cr.get("voice", ""), cta=cr.get("cta", "Get started"), banned=list(cr.get("banned", [])),
                         tagline_spec=cr.get("tagline", {}), placeholder_domain=cr.get("placeholderDomain") or f"yourbrand.{tld}",
                         extra={k: v for k, v in cr.items() if k not in ("industry", "voice", "cta", "banned", "tagline", "placeholderDomain")})
