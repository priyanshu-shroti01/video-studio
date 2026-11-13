"""Director: brief -> genuinely different concepts (template SEQUENCES) -> storyboard.

A blueprint (from the industry pack) is a narrative pattern expressed as slots (role + candidate templates).
For a product, each slot takes the first available template that does not repeat the previous hero block,
avoiding the hook / demo / pricing templates other concepts already use; backdrops are chosen so no two
consecutive scenes share one. Copy-bank variants are then picked to fit the 30–35 s window, the bank storyboard
is built and the rules are run: a blueprint that fails any rule is rejected (recorded with the failed rules)."""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from ..intelligence.facts import FactBase
from .anchors import Anchors
from .brand import BrandCreative, load_brand
from .copybank import variants, word_count
from .industries import Pack, get_pack
from .product import ProductFacts, resolve_product, trusted_brief
from .rules import PAD, SCENE_GAP, WPS, check_rules, failed, layout_overflows, windows
from .templates import ROLE_PURPOSE, Ctx, SceneTemplate, library


@dataclass
class Studio:
    """Everything a build needs, resolved once: brief, facts, brand profile, industry pack, product, templates."""
    brief: dict
    fb: FactBase
    brand: BrandCreative
    pack: Pack
    pf: ProductFacts
    lib: dict[str, SceneTemplate]
    # brief option "components": "generate" (pipeline/creative/composer.py): generated components + freshness memory
    generate: bool = False
    fresh: object = None                       # freshness.Freshness (generate mode only)
    library: tuple = ()                        # human-approved component designs of the brand (brands/<id>/components/)
    provider: object = None                    # optional local LLM: may only propose component structures
    component_cache: dict | None = None
    fresh_sequencing: bool = True

    @property
    def tb(self) -> dict:
        return trusted_brief(self.brief, self.pf)

    def variants(self, template_id: str) -> list[dict]:
        return variants(template_id, self.pf, self.pack)

    @property
    def banned(self) -> list[str]:
        return list(self.pack.banned) + list(self.brand.banned)


def studio(brief: dict, fb: FactBase) -> Studio:
    brand = load_brand(brief.get("brand_id"), fb)
    pack = get_pack(brand.industry)
    pf = resolve_product(brief, fb, brand, pack)
    st = Studio(brief, fb, brand, pack, pf, library(pack))
    if brief.get("components") == "generate":
        from . import components, freshness
        st.generate, st.fresh, st.component_cache = True, freshness.load(brand.id), {}
        st.library = tuple(components.library(brand.id))
    return st


# ---- sequencing --------------------------------------------------------------------------------------
def instantiate(bp: dict, st: Studio, avoid: dict[str, set] | None = None) -> list[tuple[str, SceneTemplate]] | None:
    avoid = avoid or {}
    seq: list[tuple[str, SceneTemplate]] = []
    used: set[str] = set()
    for role, cands in bp["slots"]:
        ok = [st.lib[c] for c in cands if c in st.lib and st.lib[c].available(st.pf) and c not in used
              and (not seq or st.lib[c].hero != seq[-1][1].hero)]
        if not ok:
            return None
        key = {"hook": "hook", "pricing": "pricing"}.get(role) or ("demo" if role == "demo" and not any(r == "demo" for r, _ in seq) else None)
        pref = [t for t in ok if not key or t.id not in avoid.get(key, set())]
        cand = pref or ok
        if st.fresh is not None and st.fresh_sequencing:     # generate mode: recently used templates go last (stable)
            cand = sorted(cand, key=lambda x: round(st.fresh.template_penalty(x.id, x.hero), 3))
        t = cand[0]
        seq.append((role, t))
        used.add(t.id)
    return seq


def backdrops(seq: list[tuple[str, SceneTemplate]], fresh=None) -> list[str]:
    """Each scene's backdrop from its template's allowed set: no two consecutive equal, first choices preferred,
    as many different backdrops as possible (generate mode: then the least recently used ones)."""
    best, best_cost = None, None
    for combo in itertools.product(*[range(len(t.backdrops)) for _, t in seq]):
        bd = [t.backdrops[i] for (_, t), i in zip(seq, combo)]
        if any(bd[k] == bd[k + 1] for k in range(len(bd) - 1)):
            continue
        cost = (-len(set(bd)), round(sum(fresh.backdrop_penalty(x) for x in bd), 3) if fresh is not None else 0, sum(combo))
        if best_cost is None or cost < best_cost:
            best, best_cost = bd, cost
    return best or [t.backdrops[0] for _, t in seq]


def scene_ids(seq) -> list[str]:
    return [f"s{k + 1}-{t.id.split('-', 1)[1][:24]}".rstrip("-") for k, (_, t) in enumerate(seq)]


def estimate(words: int, n: int) -> float:
    """Quick video-length estimate before a storyboard exists: speech at the measured rate, ~0.3 s of
    punctuation pauses and a gap per scene, the trailing pad and the 0.7 s end tail (matches rules.estimate_seconds
    within ~0.5 s on real renders)."""
    return round(words / WPS + (SCENE_GAP + 0.3) * n + PAD + 0.7, 1)


def fit_variants(seq, st: Studio, target: float, hook_variant: str | None, pref: int) -> list[dict] | str:
    """One bank variant per scene so the estimate lands in the window, closest to the aim (or a reason)."""
    opts = []
    for k, (role, t) in enumerate(seq):
        vs = [v for v in st.variants(t.id) if t.words[0] <= word_count(v["narration"]) <= t.words[1]]
        if k == 0 and hook_variant:
            vs = [v for v in vs if v["id"] == hook_variant] or vs
        if not vs:
            return f"no copy-bank line for {t.id} fits its {t.words[0]}–{t.words[1]} word budget for this product"
        opts.append(vs)
    (d_lo, d_hi), _ = windows(st.brief)
    aim = max(d_lo + 0.5, min(target, d_hi) - 1.5)
    best, best_cost = None, 1e9
    n = len(seq)
    holds = sum(HOLD_AFTER.get(t.hero, 0.0) for _, t in seq)    # payoff holds play after the last word
    for combo in itertools.product(*[range(len(o)) for o in opts]):
        words = sum(word_count(opts[k][i]["narration"]) for k, i in enumerate(combo))
        est = estimate(words, n) + holds
        if not d_lo <= est <= d_hi:
            continue
        cost = abs(est - aim) + 0.35 * sum(1 for k, i in enumerate(combo) if i != pref % len(opts[k]))
        if cost < best_cost:
            best, best_cost = combo, cost
    if best is None:
        return f"no copy-bank combination fits {d_lo:g}–{d_hi:g} s"
    return [opts[k][i] for k, i in enumerate(best)]


# ---- composition -------------------------------------------------------------------------------------
HOLD_AFTER = {"install-flow": 1.3, "domain-input": 0.9}   # seconds of picture after the last word


def build_scene(t: SceneTemplate, role: str, sid: str, copy: dict, ctx: Ctx, backdrop: str) -> tuple[dict, Anchors]:
    A = Anchors(copy["narration"])
    blocks = t.build(ctx, A, copy)
    mood = t.mood or ("danger" if role == "problem" else "brand" if role in ("turn", "cta") else None)
    sc = {"id": sid, "purpose": ROLE_PURPOSE[role], "narration": copy["narration"], "backdrop": backdrop, "camera": t.camera,
          "motion": t.motion, "transition": t.transition, "blocks": blocks}
    if mood:
        sc["mood"] = mood
    if t.hero in HOLD_AFTER:          # the payoff lands on the last words: let it play before the cut
        sc["holdAfter"] = HOLD_AFTER[t.hero]
    sc.update(footage_split(blocks))
    return sc, A


FOOTAGE_SPLIT = 0.66      # 16:9: the recording's column share; it then fills the content height (Shorts stay stacked)


def footage_split(blocks: list[dict]) -> dict:
    """A recording plus one message reads best side by side in 16:9: the recording in a wide column, the message
    beside it. Stacked, a 1.6:1 recording is height-bound to ~45% of the frame width. Shorts ignore 'split'."""
    if len(blocks) != 2 or [b["type"] for b in blocks].count("footage") != 1:
        return {}
    first = blocks[0]["type"] == "footage"
    return {"layout": "split", "splitAt": 1, "splitRatio": FOOTAGE_SPLIT if first else round(1 - FOOTAGE_SPLIT, 2)}


def compose(concept: dict, st: Studio, copies: dict[str, dict]) -> tuple[dict, Ctx, dict]:
    """Storyboard from the concept's template sequence + one copy per scene. -> (storyboard, ctx, anchors per scene)"""
    ctx = Ctx(st.pf, st.fb, st.pack)
    scenes, anchors = [], {}
    revealed = False
    for k, sp in enumerate(concept["scene_plan"]):
        t = st.lib[sp["template"]]
        sc, A = build_scene(t, sp["role"], sp["scene"], copies[sp["scene"]], ctx, sp["backdrop"])
        if sp.get("component"):            # a generated component replaces the template hero (composer.py)
            from .composer import apply_recipe
            sc = apply_recipe(sc, sp["component"])
        branded = any(b["type"] in ("logo", "cta", "logo-sting", "outro") for b in sc["blocks"])
        sc["brandBar"] = revealed and not branded and sc["purpose"] != "cta"
        revealed = revealed or any(b["type"] in ("logo-sting", "logo") for b in sc["blocks"])
        if k == 0:
            sc["transition"] = "fade"
        scenes.append(sc)
        anchors[sp["scene"]] = A
    structure = list(dict.fromkeys(s["purpose"] for s in scenes))
    sb = {"version": 1, "title": f"{st.pf.brand} — {concept['name']}", "structure": structure, "scenes": scenes}
    return sb, ctx, anchors


def hook_options(seq, st: Studio, tags: list[str]) -> list[dict]:
    t = seq[0][1]
    vs = st.variants(t.id)
    vs.sort(key=lambda v: 0 if set(v.get("tags", [])) & set(tags) else 1)
    return [{"id": v["id"], "text": v["narration"], "tags": v.get("tags", []), "template": t.id} for v in vs]


def plan_concept(bp: dict, st: Studio, idx: int, avoid: dict, hook_variant: str | None = None
                 ) -> tuple[dict | None, list[dict] | None, str | None]:
    """-> (concept, failed rules, rejection reason)"""
    seq = instantiate(bp, st, avoid)
    if seq is None:
        return None, None, "no available template for a slot (product family / missing facts)"
    bds = backdrops(seq, st.fresh if st.fresh_sequencing else None)
    ids = scene_ids(seq)
    opts = hook_options(seq, st, bp["hook_tags"])
    hv = hook_variant or (opts[0]["id"] if opts else None)
    chosen = fit_variants(seq, st, float(st.brief.get("duration_seconds") or 35), hv, idx)
    if isinstance(chosen, str):
        return None, None, chosen
    plan = [{"scene": sid, "role": role, "template": t.id, "backdrop": bd, "variant": v["id"]}
            for sid, (role, t), bd, v in zip(ids, seq, bds, chosen)]
    words = sum(word_count(v["narration"]) for v in chosen)
    pricing = next((t for r, t in seq if r == "pricing"), None)
    concept = {
        "id": f"c{idx + 1}", "blueprint": bp["id"], "industry": st.pack.id, "name": bp["name"], "pattern": bp["pattern"],
        "pattern_name": bp["pattern_name"], "logline": bp["logline"], "templates": [t.id for _, t in seq], "scene_plan": plan,
        "hook_template": seq[0][1].id, "hook_options": opts, "hook_variant": chosen[0]["id"], "hook": chosen[0]["narration"],
        "hook_source": "bank",
        "demo_template": next((t.id for r, t in seq if r == "demo"), None),
        "pricing_template": pricing.id if pricing else None, "pricing_treatment": pricing.name if pricing else None,
        "visual_approach": {"hero_blocks": [t.hero for _, t in seq], "backdrop_rhythm": bds,
                            "cameras": [t.camera for _, t in seq], "motion": [t.motion for _, t in seq]},
        "pacing": {**bp["pacing"], "scene_count": len(seq), "words": words, "est_seconds": round(estimate(words, len(seq)) + sum(HOLD_AFTER.get(t.hero, 0.0) for _, t in seq), 1),
                   "words_per_second": WPS},
        "music_mood": bp["music"], "animation_style": "template-composed",
        "cta_treatment": {"style": bp["cta_style"], "template": seq[-1][1].id, "text": st.pf.cta, "url": st.pf.domain},
    }
    sb, ctx, _ = compose(concept, st, {p["scene"]: v for p, v in zip(plan, chosen)})
    from .claims_v2 import verify
    claims = verify(sb, st.fb, st.tb)
    rules = check_rules(sb, pf=st.pf, claims=claims, labels=ctx.labels, brief=st.brief,
                        layout=layout_overflows(sb, st.brand.id, st.brief.get("format", "short")))
    concept["rules"] = rules
    concept["block_types"] = sorted({b["type"] for s in sb["scenes"] for b in s["blocks"]})
    bad = failed(rules)
    if not bad and st.generate:            # generated components, kept only while every rule still passes
        from .composer import generate_components
        rules = generate_components(concept, st, {p["scene"]: v for p, v in zip(plan, chosen)})
        bad = failed(rules)
    return (concept if not bad else None), bad, ("rules failed: " + "; ".join(f"{r['id']} ({r['detail']})" for r in bad) if bad else None)


# ---- distinctness ------------------------------------------------------------------------------------
AXES = ("pattern", "hook_template", "demo_template", "pricing_template", "backdrop_rhythm", "pacing")


def distinct(a: dict, b: dict) -> dict:
    d = {"pattern": a["pattern"] != b["pattern"], "hook_template": a["hook_template"] != b["hook_template"],
         "demo_template": a["demo_template"] != b["demo_template"],
         "pricing_template": a["pricing_template"] != b["pricing_template"] or a["pricing_template"] is None,
         "backdrop_rhythm": a["visual_approach"]["backdrop_rhythm"] != b["visual_approach"]["backdrop_rhythm"],
         "pacing": a["pacing"]["label"] != b["pacing"]["label"]}
    sa, sb_ = set(a["templates"]), set(b["templates"])
    jac = round(len(sa & sb_) / len(sa | sb_), 2)
    return {"a": a["id"], "b": b["id"], "differs": d, "template_jaccard": jac, "ok": all(d.values()) and jac <= 0.6}


def rank(brief: dict, pack: Pack) -> list[dict]:
    """Blueprints ordered by fit to the brief's requirements (stable)."""
    reqs = set(brief.get("requirements") or [])
    goal = (brief.get("goal") or "").lower()

    def score(bp):
        roles = [r for r, _ in bp["slots"]]
        s = (2 if "problem" in reqs and "problem" in roles else 0) + (1 if "demonstration" in reqs and "demo" in roles else 0)
        s += 2 if goal.startswith("educ") and bp["pattern"].startswith("tutorial") else 0
        return s
    return sorted(pack.blueprints, key=lambda b: (-score(b), pack.blueprints.index(b)))


def direct(st: Studio, n: int = 3) -> tuple[list[dict], list[dict]]:
    """-> (concepts, rejected)"""
    concepts, rejected = [], []
    avoid: dict[str, set] = {"hook": set(), "demo": set(), "pricing": set()}
    ranked = rank(st.brief, st.pack)
    if st.fresh is not None:               # generate mode: blueprints used lately move down (brief fit still leads)
        ranked = sorted(ranked, key=lambda b: ranked.index(b) + 3 * st.fresh.penalty("blueprint", b["id"]))
    for bp in ranked:
        if len(concepts) >= n:
            break
        c, bad, why = plan_concept(bp, st, len(concepts), avoid)
        if c is None and st.fresh is not None and st.fresh_sequencing:   # fresher templates broke it: the pack's order
            st.fresh_sequencing = False
            c, bad, why = plan_concept(bp, st, len(concepts), avoid)
            st.fresh_sequencing = True
        if c is None:
            rejected.append({"blueprint": bp["id"], "reason": why, "failed_rules": bad or []})
            continue
        clash = [d for d in (distinct(c, o) for o in concepts) if not d["ok"]]
        if clash:
            same = sorted({k for d in clash for k, v in d["differs"].items() if not v})
            rejected.append({"blueprint": bp["id"], "reason": f"too similar to an earlier concept (same {', '.join(same) or 'templates'})",
                             "distinctness": clash})
            continue
        concepts.append(c)
        avoid["hook"].add(c["hook_template"]); avoid["demo"].add(c["demo_template"])
        if c["pricing_template"]:
            avoid["pricing"].add(c["pricing_template"])
    return concepts, rejected


def publishing(st: Studio, concept: dict) -> dict:
    pf = st.pf
    if pf.featured is None:                    # unpriced product: name, tagline and link
        title = f"{pf.brand}" + (f": {pf.tagline}" if pf.tagline else "")
        desc = (f"{pf.tagline}\n" if pf.tagline else "") + f"https://{pf.display_url or pf.domain}"
        tags = ["#" + re.sub(r"\W", "", w.title()) for w in (pf.family_label, pf.brand)]
        return {"title": title[:100], "description": desc, "hashtags": list(dict.fromkeys(tags))}
    price = f"{pf.money(pf.price)}{pf.per_short}"
    lead = f"{pf.family_label} from {price}" if pf.featured is pf.plans[0] else f"{pf.featured.name} at {price}"
    title = f"{lead}" + (" — same price on renewal" if pf.allow.get("renewal") else "") + f" | {pf.brand}"
    feats = [f[1] for f in Ctx(pf, st.fb, st.pack).features(st.pack.cta_sub_keys + st.pack.checklist_keys(pf.family))][:3]
    desc = f"{pf.featured.name} by {pf.brand}" + (f": {', '.join(feats)}." if feats else ".") + \
        (" Every plan renews at the listed price." if pf.allow.get("renewal") else "") + f"\nhttps://{pf.domain}"
    tags = ["#" + re.sub(r"\W", "", w.title()) for w in (pf.family_label, pf.brand)]
    return {"title": title[:100], "description": desc, "hashtags": list(dict.fromkeys(tags))}
