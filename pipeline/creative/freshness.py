"""Freshness memory: what a brand's earlier productions already showed, so new ones do not look alike.

From each of the brand's productions under output/productions/ (archived ones live under output/_archive/ and are never
read) it collects the scene templates, hero block types, backdrops, blueprint and generated-component designs
(`composition` blocks: structure / variant / motion signature) that ended up in the storyboard. Usage is
recency-weighted: the newest production counts 1, the one before ½, then ¼ … (productions are ordered by id, which
starts with their creation time, so the order never depends on file times). A key's penalty is 1 − e^(−usage): 0 for
something never used, ≈ 0.39 after one recent use, → 1 with heavy reuse.

The director (only with the brief option `"components": "generate"`) uses it to prefer templates, blueprints, backdrops
and generated designs the brand has not used lately; concepts.md reports a freshness line per concept. With no history
every penalty is 0, so the result is exactly the deterministic default ordering."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import OUTPUT_DIR

PRODUCTIONS_DIR = OUTPUT_DIR / "productions"
DECAY = 0.5                 # weight of each older production relative to the next newer one
MAX_PRODUCTIONS = 12        # older productions weigh < 0.0005 and are ignored
KINDS = ("template", "hero", "backdrop", "blueprint", "signature", "structure")


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def production_brand(d: Path) -> str | None:
    """Brand id of a production directory: project.json, else brief.json brand_id, else resolved from its name."""
    proj = _read(d / "project.json") or {}
    if isinstance(proj.get("brand"), str):
        return proj["brand"]
    brief = _read(d / "brief.json") or {}
    if isinstance(brief.get("brand_id"), str):
        return brief["brand_id"]
    if isinstance(brief.get("brand"), str):
        try:
            from ..brands import resolve_brand
            return resolve_brand(brief["brand"])
        except Exception:  # noqa: BLE001 - an unknown brand is simply not this brand
            return None
    return None


def production_record(d: Path) -> dict | None:
    """What one production showed: templates, heroes, backdrops, blueprint, component signatures / structures."""
    sb = _read(d / "storyboard.json")
    if not sb or not isinstance(sb.get("scenes"), list):
        return None
    from .rules import hero_of
    rec: dict[str, list[str]] = {k: [] for k in KINDS}
    for s in sb["scenes"]:
        if not isinstance(s, dict) or not isinstance(s.get("blocks"), list):
            continue
        h = hero_of(s)
        if h:
            rec["hero"].append(h)
        if isinstance(s.get("backdrop"), str):
            rec["backdrop"].append(s["backdrop"])
        for b in s["blocks"]:
            if isinstance(b, dict) and b.get("type") == "composition" and isinstance(b.get("design"), dict):
                dz = b["design"]
                if dz.get("signature"):
                    rec["signature"].append(dz["signature"])
                if dz.get("structure"):
                    rec["structure"].append(dz["structure"])
    plan = _read(d / "concepts" / "creative-plan.json") or {}
    cid = (plan.get("concept") or {}).get("id")
    doc = _read(d / "concepts" / "concepts.json") or {}
    concept = next((c for c in doc.get("concepts", []) if isinstance(c, dict) and c.get("id") == cid), None) if cid else None
    if concept:
        rec["template"] = [t for t in concept.get("templates", []) if isinstance(t, str)]
        if isinstance(concept.get("blueprint"), str):
            rec["blueprint"] = [concept["blueprint"]]
    return rec


@dataclass
class Freshness:
    brand: str
    productions: list[str] = field(default_factory=list)          # newest first
    usage: dict[str, dict[str, float]] = field(default_factory=lambda: {k: {} for k in KINDS})

    @classmethod
    def empty(cls, brand: str) -> "Freshness":
        return cls(brand)

    def weight(self, kind: str, key: str | None) -> float:
        return self.usage.get(kind, {}).get(key, 0.0) if key else 0.0

    def penalty(self, kind: str, key: str | None) -> float:
        return round(1.0 - math.exp(-self.weight(kind, key)), 4)

    def template_penalty(self, template_id: str, hero: str | None = None) -> float:
        return round(max(self.penalty("template", template_id), 0.6 * self.penalty("hero", hero)), 4)

    def design_penalty(self, signature: str | None, structure: str | None = None) -> float:
        return round(max(self.penalty("signature", signature), 0.6 * self.penalty("structure", structure)), 4)

    def backdrop_penalty(self, backdrop: str | None) -> float:
        return self.penalty("backdrop", backdrop)

    def concept_report(self, concept: dict) -> dict:
        """Freshness of a planned concept: mean over scenes of 1 − max(template / generated design, ⅓ backdrop)."""
        scores, repeats = [], []
        comps = {c["scene"]: c for c in concept.get("components", []) if c.get("selected")}
        for sp in concept.get("scene_plan", []):
            comp = comps.get(sp["scene"])
            if comp:
                d = comp["design"]
                p = self.design_penalty(d.get("signature"), d.get("structure"))
                what = f"generated {d.get('signature')}"
            else:
                p = self.penalty("template", sp["template"])
                what = sp["template"]
            pb = self.backdrop_penalty(sp.get("backdrop")) / 3
            scores.append(1 - max(p, pb))
            if p >= 0.3:
                repeats.append(what)
        score = round(sum(scores) / len(scores), 2) if scores else 1.0
        bp = self.penalty("blueprint", concept.get("blueprint"))
        line = (f"{score:.2f} over {len(self.productions)} earlier {self.brand} production(s)"
                + (f"; repeats {', '.join(dict.fromkeys(repeats))}" if repeats else "; nothing repeated")
                + (f"; blueprint used recently ({bp:.2f})" if bp >= 0.3 else ""))
        return {"score": score, "repeats": list(dict.fromkeys(repeats)), "blueprint_penalty": bp, "history": len(self.productions),
                "line": line}

    def as_dict(self) -> dict:
        return {"brand": self.brand, "productions": self.productions,
                "usage": {k: dict(sorted(v.items())) for k, v in self.usage.items() if v}}


def load(brand: str, *, root: Path | None = None, exclude: set[str] | list[str] | tuple = ()) -> Freshness:
    """Recency-weighted usage over the brand's productions (deterministic; empty history -> every penalty 0)."""
    root = Path(root) if root is not None else PRODUCTIONS_DIR
    fr = Freshness(brand)
    if not root.is_dir():
        return fr
    dirs = sorted((d for d in root.iterdir() if d.is_dir() and d.name not in set(exclude)), key=lambda d: d.name, reverse=True)
    recs = []
    for d in dirs:
        if production_brand(d) != brand:
            continue
        r = production_record(d)
        if r is not None:
            recs.append((d.name, r))
        if len(recs) >= MAX_PRODUCTIONS:
            break
    for i, (pid, r) in enumerate(recs):
        w = DECAY ** i
        fr.productions.append(pid)
        for kind, keys in r.items():
            u = fr.usage.setdefault(kind, {})
            for k in keys:
                u[k] = round(u.get(k, 0.0) + w, 6)
    return fr
