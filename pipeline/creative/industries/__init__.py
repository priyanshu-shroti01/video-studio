"""Industry packs: the industry-specific half of the creative system.

A pack supplies product families (how a brief's product maps onto the fact base), the fact ids that gate
statements (renewal, money-back, comparisons...), fact-bound feature labels and their spoken cue words, the
industry's own scene templates, industry copy (which takes precedence over the generic copy bank) and the
narrative blueprints. A brand selects its pack with brands/<id>/brand.json creative.industry."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from ...errors import ConfigError


@dataclass
class Pack:
    id: str
    name: str
    families: list[dict]                       # {"id", "match": regex | None (default), "product", "label", "icon", "period"?, "plans"?}
    fact_ids: dict[str, str]                   # role -> fact id
    gated_roles: tuple[str, ...]
    features: dict[str, tuple]                 # key -> (label, icon, fact id, families | None, allow-role | None)
    feature_cues: dict[str, list[str]]
    templates: list = field(default_factory=list)
    bank: dict = field(default_factory=dict)
    blueprints: list[dict] = field(default_factory=list)
    plan_features: Callable = None             # (ctx) -> [(text, icon, source, cues)]
    plan_detail: Callable = None               # (ctx, plan) -> (text, source) | None
    compare_rows: Callable = None              # (ctx, plans, anchors) -> [price-compare rows]
    checklist_keys: Callable = None            # (family) -> [feature keys]
    cta_sub_keys: list[str] = field(default_factory=list)
    banned: list[str] = field(default_factory=list)
    style: str = ""
    term_roles: dict[str, str] = field(default_factory=dict)   # copy term -> fact role that must be allowed
    priced: bool = True                        # False: the product has no plans/prices (no pricing scene, no plan facts)

    def unbacked_terms(self, text: str, allow: dict) -> list[str]:
        low = text.lower()
        return [t for t, r in self.term_roles.items() if t.lower() in low and not allow.get(r, False)]

    def family_of(self, product: str) -> dict:
        t = (product or "").lower()
        default = None
        for f in self.families:
            if f.get("match") is None:
                default = default or f
            elif re.search(f["match"], t):
                return f
        if default is None:
            raise ConfigError(f"industry pack {self.id!r}: product {product!r} matches no product family")
        return default


def get_pack(industry: str) -> Pack:
    from . import software, web_hosting
    packs = {web_hosting.PACK.id: web_hosting.PACK, software.PACK.id: software.PACK}
    if industry not in packs:
        raise ConfigError(f"no industry pack {industry!r} (available: {sorted(packs)}); add pipeline/creative/industries/<pack>.py")
    return packs[industry]
