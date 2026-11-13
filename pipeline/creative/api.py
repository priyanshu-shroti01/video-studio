"""Public API (mirrors pipeline.intelligence.api so the workflow can switch with one import):

    generate_concepts(brief, request=None, *, provider="ollama"|"mock"|"none", out_dir=None, n=3) -> dict
    build_storyboard(brief, concept, *, request=None, provider=..., out_dir=None) -> (storyboard, project_config, reports)

Hybrid: the LLM (optional, local) picks hooks and proposes copy; templates compose the scenes; facts supply
every label and number; Python owns timing. Works fully with provider None / "none"."""
from __future__ import annotations

import copy as _copy
import json
import re
import time
from pathlib import Path

from ..errors import ConfigError
from ..paths import ROOT
from ..intelligence.api import _theme_preset
from ..intelligence.brief import parse_brief
from ..intelligence.claims import verify_brief
from ..intelligence.facts import FactBase, empty_facts, load_facts
from ..intelligence.preview import creative_plan as _creative_plan, preview_markdown
from ..intelligence.providers import OllamaProvider, Provider
from ..storyboard import validate_storyboard
from . import copywriter
from .claims_v2 import verify
from ..brands import load_profile
from .copybank import word_count
from .director import Studio, compose, direct, distinct, plan_concept, publishing as make_publishing, studio
from .rules import check_rules, estimate_seconds, failed, layout_overflows, sync_report, windows

MUSIC_MOODS = ["cinematic", "corporate", "technology", "energetic", "minimal", "educational", "calm", "promotional"]
PIPELINE_KEYS = ("provider",)
SFX_V2 = {"kinetic-text": "pop per word", "terminal": "key clicks while typing, ding on ok", "logo-sting": "impact + shimmer",
          "install-flow": "tick per step, success on done", "domain-input": "key clicks, ding, click", "dashboard": "whoosh",
          "server-stack": "appear per node", "plan-card": "ticks while counting", "price-compare": "ding per row",
          "feature-compare": "ding per row, impact on highlight", "progress": "pop per step", "scroll-demo": "whoosh",
          "device": "whoosh", "counter": "ticks", "outro": "shimmer on URL"}


def _provider(p) -> Provider | None:
    if p is None or p == "none":
        return None
    if isinstance(p, Provider):
        return p
    if p == "mock":
        return copywriter.mock_provider()
    if p == "ollama":
        return OllamaProvider()
    raise ConfigError(f"unknown provider {p!r} (use 'ollama', 'mock' or 'none')")


def _brief(brief, request=None) -> tuple[dict, list[str]]:
    if isinstance(brief, dict) and "price_parsed" in brief and "brand_id" in brief:
        return brief, []
    b = {k: v for k, v in brief.items() if k not in PIPELINE_KEYS}
    return parse_brief(b, request)


def _facts(brief: dict, facts) -> FactBase:
    if isinstance(facts, FactBase):
        return facts
    try:
        return load_facts(brief["brand_id"], facts)
    except ConfigError:
        return empty_facts(brief["brand_id"], brief["brand"])


def _write(out: Path, name: str, obj) -> str:
    out.mkdir(parents=True, exist_ok=True)
    p = out / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return str(p)


# ---- concepts ----------------------------------------------------------------------------------------
def generate_concepts(brief: dict, request: str | None = None, *, provider="ollama", out_dir: str | Path | None = None,
                      n: int = 3, facts=None) -> dict:
    t0 = time.time()
    b, warnings = _brief(brief, request)
    fb = _facts(b, facts)
    st = studio(b, fb)
    pf = st.pf
    prov = _provider(provider)
    log: list = []
    if st.generate:                      # the LLM may propose component STRUCTURES (names only), never geometry
        st.provider, st.component_log = prov, log
    concepts, rejected = direct(st, n)
    choices = copywriter.choose_hooks(prov, b, concepts, log, voice=st.brand.voice)
    bps = {x["id"]: x for x in st.pack.blueprints}
    for i, c in enumerate(concepts):
        ch = choices[c["id"]]
        if ch["source"] == "llm" and ch["choice"] != c["hook_variant"]:
            avoid = {"hook": {o["hook_template"] for o in concepts if o is not c}, "demo": {o["demo_template"] for o in concepts if o is not c},
                     "pricing": {o["pricing_template"] for o in concepts if o is not c}}
            nc, bad, why = plan_concept(bps[c["blueprint"]], st, i, avoid, hook_variant=ch["choice"])
            if nc is not None and nc["hook_variant"] == ch["choice"] and nc["templates"] == c["templates"]:
                nc["hook_source"] = "llm"
                concepts[i] = nc
            else:
                ch["source"], ch["reason"] = "bank", f"model's hook {ch['choice']!r} rejected: {why or 'does not fit the duration window'}"
        concepts[i]["hook_choice"] = choices[c["id"]]
    if prov is not None:
        prov.unload()
    pairs = [distinct(a, c) for k, a in enumerate(concepts) for c in concepts[k + 1:]]
    res = {"engine": "pipeline.creative", "brand": st.brand.id, "industry": st.pack.id, "brief": b, "brief_warnings": warnings, "price": pf.report(),
           "brief_claims": verify_brief(b, fb), "concepts": concepts, "rejected": rejected, "distinctness": pairs,
           "recommended": concepts[0]["id"] if concepts else None, "provider": prov.info() if prov else {"provider": "none"},
           "log": log, "elapsed_s": round(time.time() - t0, 2)}
    if out_dir:
        out = Path(out_dir)
        res["files"] = {"concepts.json": _write(out, "concepts.json", res), "concepts.md": _write(out, "concepts.md", concepts_markdown(res))}
    return res


def concepts_markdown(res: dict) -> str:
    b, cs, pr = res["brief"], res["concepts"], res["price"]
    L = [f"# Concepts — {b['brand']} · {b['product']}", "",
         f"Engine: `pipeline.creative` (templates compose, facts label, Python times; LLM: {res['provider'].get('provider')}). "
         f"Recommended: **{res['recommended']}**.", ""]
    if pr.get("mismatch"):
        m = pr["mismatch"]
        L += [f"> **Brief price not verified:** {m['brief_price']} is not a price on the site. Every concept uses the verified "
              f"**{m['plan']} {m['used_price']}** (`{m['fact_id']}`); the brief price is never rendered. Owner must confirm.", ""]
    head = "| | " + " | ".join(f"**{c['id']} · {c['name']}**" for c in cs) + " |"
    L += [head, "|---|" + "---|" * len(cs)]
    rows = [("pattern", lambda c: c["pattern_name"]), ("hook", lambda c: f"“{c['hook']}” ({c['hook_template']}, {c['hook_choice']['source']})"),
            ("templates", lambda c: " → ".join(c["templates"])), ("demo", lambda c: c["demo_template"]),
            ("pricing", lambda c: f"{c['pricing_treatment']} ({c['pricing_template']})"),
            ("hero blocks", lambda c: ", ".join(c["visual_approach"]["hero_blocks"])),
            ("backdrop rhythm", lambda c: " · ".join(c["visual_approach"]["backdrop_rhythm"])),
            ("pacing", lambda c: f"{c['pacing']['label']}: {c['pacing']['scene_count']} scenes, ~{c['pacing']['est_seconds']} s"),
            ("music", lambda c: c["music_mood"]), ("CTA", lambda c: f"{c['cta_treatment']['style']} ({c['cta_treatment']['template']})"),
            ("rules", lambda c: f"{sum(r['status'] == 'PASS' for r in c['rules'])}/{len(c['rules'])} pass")]
    if any("components" in c for c in cs):                       # "components": "generate"
        rows += [("generated", lambda c: "; ".join(f"{r['scene']}: {r['design']['signature']} replaces {r['replaces']} "
                                                   f"({r['scores']['total']:.2f} vs {r['template_score']['total']:.2f})"
                                                   for r in c["components"] if r["selected"]) or "none (templates kept)"),
                 ("freshness", lambda c: (c.get("freshness") or {}).get("line", "—"))]
    if all(c.get("pricing_template") is None for c in cs):        # unpriced product: no pricing row
        rows = [r for r in rows if r[0] != "pricing"]
    for k, f in rows:
        L.append(f"| {k} | " + " | ".join(str(f(c)).replace("|", "/") for c in cs) + " |")
    L += ["", "## Loglines"] + [f"- **{c['id']} {c['name']}:** {c['logline']}" for c in cs]
    L += ["", "## Distinctness"] + [f"- {p['a']} vs {p['b']}: differs on {', '.join(k for k, v in p['differs'].items() if v)}; "
                                     f"template overlap {p['template_jaccard']}" for p in res["distinctness"]]
    if res["rejected"]:
        L += ["", "## Rejected sequences"] + [f"- {r['blueprint']}: {r['reason']}" for r in res["rejected"]]
    return "\n".join(L) + "\n"


# ---- storyboard --------------------------------------------------------------------------------------
def _bank_copies(concept: dict, st: Studio) -> dict[str, dict]:
    out = {}
    for sp in concept["scene_plan"]:
        vs = st.variants(sp["template"])
        v = next((x for x in vs if x["id"] == sp["variant"]), None)
        if v is None:
            raise ConfigError(f"concept {concept.get('id')}: copy variant {sp['variant']!r} is not available for {sp['template']}")
        out[sp["scene"]] = v
    return out


def _slots(concept: dict, st: Studio, copies: dict, anchors: dict) -> list[dict]:
    vals = st.pf.bound()
    slots = []
    for sp in concept["scene_plan"]:
        t = st.lib[sp["template"]]
        A = anchors[sp["scene"]]
        req = list(dict.fromkeys(u["word"] for u in A.used if u["word"] and not u["word"].startswith("<")))
        nums = {float(vals[k]) for k in t.binds if isinstance(vals.get(k), (int, float))} | {float(x) for x in t.numbers}
        nums |= copywriter.numbers_in(copies[sp["scene"]]["narration"])
        alts = [v for v in st.variants(t.id) if v["id"] != sp["variant"] and t.words[0] <= word_count(v["narration"]) <= t.words[1]]
        slots.append({"scene": sp["scene"], "role": sp["role"], "template": t.id, "describe": t.describe, "words": t.words,
                      "headline": t.headline, "bank": copies[sp["scene"]], "alternatives": alts, "required_words": req,
                      "allowed_numbers": sorted(nums)})
    return slots


def _scene_ok(concept, st: Studio, scene_id: str, cand: dict, bank_anchors: dict, copies: dict) -> list[str]:
    """Build the whole storyboard with this one scene's LLM copy and check alignment, claims, labels and sync."""
    trial = {**copies, scene_id: cand}
    sb, ctx, anchors = compose(concept, st, trial)
    probs = []
    bank_hits = {u["element"] for u in bank_anchors[scene_id].used if u["word"]}
    new_hits = {u["element"] for u in anchors[scene_id].used if u["word"]}
    lost = sorted(bank_hits - new_hits)
    if lost:
        probs.append(f"beats lose their spoken word: {lost}")
    one = {"scenes": [s for s in sb["scenes"] if s["id"] == scene_id]}
    sy = sync_report(one)
    probs += sy["gap_violations"] + sy["number_violations"]
    cl = verify(one, st.fb, st.tb)
    probs += [f"claim {c['text']!r}: {c.get('reason', '')}" for c in cl["needs_review"]]
    errs, _ = validate_storyboard(sb)
    probs += errs[:3]
    return probs


def build_storyboard(brief: dict, concept: dict, *, request: str | None = None, provider="ollama", out_dir: str | Path | None = None,
                     facts=None, name: str | None = None) -> tuple[dict, dict, dict]:
    t0 = time.time()
    b, warnings = _brief(brief, request)
    fb = _facts(b, facts)
    st = studio(b, fb)
    pf, tb = st.pf, st.tb
    concept = _copy.deepcopy(concept)
    if concept.get("industry") and concept["industry"] != st.pack.id:
        raise ConfigError(f"concept {concept.get('id')} was made for industry {concept['industry']!r}, brand uses {st.pack.id!r}")
    prov = _provider(provider)
    log: list = []
    copies = _bank_copies(concept, st)
    bank_sb, _ctx0, bank_anchors = compose(concept, st, copies)
    sources = {sp["scene"]: {"template": sp["template"], "narration": "bank", "headline": "bank" if st.lib[sp["template"]].headline else None,
                             "variant": sp["variant"], "reasons": []} for sp in concept["scene_plan"]}
    if prov is not None:
        slots = _slots(concept, st, copies, bank_anchors)
        examples = [v["narration"] for sp in concept["scene_plan"] for v in st.variants(sp["template"])[:1]]
        props = copywriter.rewrite(prov, tb, concept, slots, examples, log, voice=st.brand.voice, style=st.pack.style)
        accepted = {}
        for s in slots:
            sid = s["scene"]
            prop = props.get(sid)
            if not prop:
                sources[sid]["reasons"].append("no LLM proposal" if props else "LLM unavailable or failed")
                continue
            sources[sid]["proposal"] = {k: v for k, v in prop.items() if k != "extra_keys"}
            reasons = []
            if prop.get("extra_keys"):
                reasons.append(f"ignored extra fields {prop['extra_keys']} (labels come only from templates/facts)")
            narr = re.sub(r"\s+", " ", str(prop.get("narration") or "")).strip()
            head = (re.sub(r"\s+", " ", str(prop.get("headline") or "")).strip() or None) if s.get("headline") else None
            if narr == s["bank"]["narration"] and (head or None) == (s["bank"].get("headline") if s.get("headline") else None):
                sources[sid]["reasons"].append("model returned the copy-bank line unchanged")
                continue
            probs = copywriter.validate_line(s, narr, head, fb=fb, brief=tb, domain=pf.domain, banned=st.banned)
            probs += [f"names {t!r}, which this brand's facts do not back" for t in st.pack.unbacked_terms(narr, pf.allow)]
            if not probs:
                cand = {"id": "llm", "narration": narr}
                if head:
                    cand["headline"] = head
                    cand["emphasis"] = [head.split()[-1]]
                probs = _scene_ok(concept, st, sid, cand, bank_anchors, copies)
            if probs:
                sources[sid]["reasons"] += reasons + probs
                continue
            accepted[sid] = cand
            sources[sid].update({"narration": "llm", "headline": "llm" if head else sources[sid]["headline"], "reasons": reasons})
        # duration window: revert the LLM lines that moved the length most until it fits
        trial = {**copies, **accepted}
        (d_lo, d_hi), _ = windows(st.brief)
        while accepted:
            sb_try, _, _ = compose(concept, st, trial)
            if d_lo <= estimate_seconds(sb_try) <= d_hi:
                break
            worst = max(accepted, key=lambda k: abs(word_count(accepted[k]["narration"]) - word_count(copies[k]["narration"])))
            accepted.pop(worst)
            trial = {**copies, **accepted}
            sources[worst].update({"narration": "bank", "headline": "bank" if sources[worst]["headline"] else None,
                                   "reasons": sources[worst]["reasons"] + [f"reverted to keep the video inside {d_lo:g}–{d_hi:g} s"]})
        copies = trial
        prov.unload()
    sb, ctx, anchors = compose(concept, st, copies)
    pub = make_publishing(st, concept)
    prof_tags = (load_profile(st.brand.id).get("publishing") or {}).get("hashtags") or []
    pub["hashtags"] = list(dict.fromkeys(list(prof_tags) + pub["hashtags"]))[:8]
    claims = verify(sb, fb, tb, pub)
    sync = sync_report(sb)
    rules = check_rules(sb, pf=pf, claims=claims, labels=ctx.labels, sync=sync, brief=st.brief,
                        layout=layout_overflows(sb, st.brand.id, b.get("format", "short")))
    errors, sb_warnings = validate_storyboard(sb)
    theme, preset, preset_name = _theme_preset(b)
    plan = _creative_plan(b, {**concept, "music_mood": concept.get("music_mood") if concept.get("music_mood") in MUSIC_MOODS else "technology"},
                          sb, pub, theme, preset, fb)
    outro = next((x for s in sb["scenes"] for x in s["blocks"] if x["type"] in ("outro", "cta")), None)
    if outro:
        plan["cta"] = {"text": outro.get("cta") or outro.get("text"), "url": outro.get("url"), "treatment": concept["cta_treatment"]["style"]}
    for row, s in zip(plan["sfx"]["per_scene"], sb["scenes"]):
        row["sfx"] = [f"{x['type']}: {SFX_V2.get(x['type'], '—')}" if x["type"] in SFX_V2 else y for x, y in zip(s["blocks"], row["sfx"])] + row["sfx"][len(s["blocks"]):]
    brief_claims = verify_brief(b, fb)
    for c in brief_claims["needs_review"]:
        c["rendered"] = False
        if pf.mismatch:
            c["resolution"] = f"not rendered; the video shows the verified {pf.mismatch['plan']} {pf.mismatch['used_price']} ({pf.mismatch['fact_id']})"
    bad_rules = failed(rules)
    reasons = []
    if pf.mismatch:
        m = pf.mismatch
        reasons.append(f"brief price {m['brief_price']} is not on the site; the video uses the verified {m['plan']} {m['used_price']} "
                       f"({m['fact_id']}). Owner must confirm the price before publishing.")
    if not fb.facts:
        reasons.append(f"no verified fact base for brand {b['brand_id']!r}")
    for c in claims["needs_review"]:
        reasons.append(f"{c['text']!r} ({c['origin']}) in {c['scope']}: {c.get('reason', 'unverified')}")
    for r in bad_rules:
        reasons.append(f"rule {r['id']} failed: {r['detail']}")
    blocking = bool(pf.mismatch or claims["needs_review"] or bad_rules or errors or not fb.facts)
    n_llm = sum(1 for v in sources.values() if v["narration"] == "llm")
    path = "creative:bank" if n_llm == 0 else f"creative:llm({n_llm}/{len(sources)} scenes)"
    review = {"status": "BLOCKED" if blocking else "READY_FOR_HUMAN_REVIEW", "blocking": blocking, "reasons": reasons,
              "needs_review": claims["needs_review"], "price_check": pf.report(), "facts_file": str(fb.path) if fb.path else None,
              "facts_fetched_at": fb.fetched_at, "produced_by": path,
              "note": "The video may be rendered for review, but must not be published while blocking is true."}
    est = estimate_seconds(sb)
    chk = {"errors": errors, "warnings": sb_warnings, "estimate_s": est, "target_s": b.get("duration_seconds", 35), "claims": claims}
    pname = name or f"{b['brand_id']}-" + re.sub(r"[^a-z0-9]+", "-", concept.get("name", "concept").lower()).strip("-")[:40]
    pname = re.sub(r"[^A-Za-z0-9._-]", "-", pname)[:100]
    project = {"$comment": f"generated by pipeline.creative ({path}); review status: {review['status']}", "name": pname,
               "preset": preset_name, "formats": list(dict.fromkeys([b.get("format", "short"), *(b.get("formats") or [])])),
               "brand": b["brand_id"], "storyboard": sb,
               "audio": {"music": None}, "publishing": plan["publishing"]}
    if b.get("voice") and re.match(r"^[A-Za-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z]+Neural$", b["voice"]):
        project["voice"] = {"voice": b["voice"]}
    reports = {"path": path, "engine": "pipeline.creative", "brand": st.brand.id, "industry": st.pack.id, "claims": claims, "brief_claims": brief_claims, "review": review,
               "creative_plan": plan, "copy_sources": sources, "rules": rules, "sync": sync, "price": pf.report(),
               "labels": ctx.labels, "check": {k: v for k, v in chk.items() if k != "claims"},
               "beats": {sid: A.used for sid, A in anchors.items()}, "concept": concept, "brief": b, "brief_warnings": warnings,
               "provider": prov.info() if prov else {"provider": "none"}, "log": log, "elapsed_s": round(time.time() - t0, 2)}
    if out_dir:
        out = Path(out_dir)
        sb_path = out / f"{pname}.storyboard.json"
        files = {"storyboard": _write(out, sb_path.name, sb)}
        try:
            project["storyboard"] = str(sb_path.resolve().relative_to(ROOT))
        except ValueError:
            pass
        files["project"] = _write(out, f"{pname}.json", project)
        files["claims"] = _write(out, "claims.json", {"storyboard": claims, "brief": brief_claims})
        files["review"] = _write(out, "review.json", review)
        files["creative_plan"] = _write(out, "creative-plan.json", plan)
        files["rules"] = _write(out, "rules.json", {"rules": rules, "sync": sync})
        files["copy_sources"] = _write(out, "copy-sources.json", sources)
        files["preview"] = _write(out, "storyboard-preview.md", preview_markdown(b, concept, sb, chk, plan, path, review)
                                  + rules_markdown(rules, sources))
        files["log"] = _write(out, "generation-log.json", {k: reports[k] for k in ("path", "check", "log", "provider", "elapsed_s", "beats")})
        reports["files"] = files
    return sb, project, reports


def rules_markdown(rules: list[dict], sources: dict) -> str:
    L = ["", "## Creative rules"] + [f"- {'✓' if r['status'] == 'PASS' else '✗'} **{r['id']}** — {r['rule']}" +
                                     (f" ({r['detail']})" if r["detail"] else "") for r in rules]
    L += ["", "## Copy sources (LLM vs copy bank)"]
    for sid, s in sources.items():
        L.append(f"- `{sid}` ({s['template']}): narration **{s['narration']}**" + (f", headline **{s['headline']}**" if s["headline"] else "") +
                 (f" — {'; '.join(s['reasons'][:3])}" if s["reasons"] else ""))
    return "\n".join(L) + "\n"
