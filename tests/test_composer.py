"""Component generator (pipeline/creative/composer.py), freshness memory, the `composition` block contract on the Python
side, generate-mode integration, the unchanged default path, and the human approve / reject CLI (temp dirs, fake
reviewers only). Nothing here renders; the layout checks use the engine's layout manifest (node, no browser)."""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from pipeline.contract import TIME_KEYS
from pipeline.creative import build_storyboard, components, composer, freshness, generate_concepts
from pipeline.creative.api import concepts_markdown
from pipeline.creative.director import build_scene, studio
from pipeline.creative.rules import hero_of
from pipeline.creative.templates import Ctx
from pipeline.errors import ConfigError
from pipeline.intelligence.brief import parse_brief
from pipeline.intelligence.facts import load_facts
from pipeline.intelligence.providers import MockProvider
from pipeline.storyboard import Resolver, SceneTiming, resolve_block, validate_storyboard
from pipeline.timing import Word

BRIEF = {"brand": "Shroti Host", "product": "WordPress Hosting", "price": "₹39/month", "audience": "Website beginners",
         "format": "short", "duration_seconds": 35, "goal": "Conversions", "cta": "Get Started",
         "request": "Create a 35-second premium YouTube Short promoting WordPress Hosting at ₹39/month. Target beginners. "
                    "Show a compelling problem, a product demonstration, an animated pricing comparison and a strong CTA."}


@pytest.fixture(scope="module")
def no_history(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(freshness, "PRODUCTIONS_DIR", tmp_path_factory.mktemp("no-productions"))
        yield


@pytest.fixture(scope="module")
def hosting():
    b, _ = parse_brief({**{k: BRIEF[k] for k in ("brand", "product", "format", "duration_seconds", "cta")}, "price": "₹69/month"})
    st = studio(b, load_facts(b["brand_id"]))
    ctx = Ctx(st.pf, st.fb, st.pack)
    scenes = {}
    for tid, bd in (("proof-server-stack", "grid"), ("proof-checklist-counter", "deep"), ("demo-install-flow", "light")):
        t = st.lib[tid]
        scenes[tid], _ = build_scene(t, t.role, f"s-{tid.split('-', 1)[1]}", st.variants(tid)[0], ctx, bd)
    return st, ctx, scenes


def _search(st, ctx, scene, seed=7, **kw):
    c = composer.content_of(scene)
    return composer.search(scene, c, labels=ctx.labels, brand_id=st.brand.id, seed=seed, template_id="t", **kw)


# ---- the block contract (Python side) --------------------------------------------------------------------------
NARR = "Fast storage and daily backups keep every site safe."


def _comp(**over):
    els = [{"id": "a", "kind": "shape", "shape": "circle", "box": [0.1, 0.1, 0.2, 0.2], "at": "@word:storage", "pulseAt": "@word:safe"},
           {"id": "b", "kind": "text", "text": "Daily backups", "role": "label", "box": [0.4, 0.4, 0.5, 0.1], "at": "@word:backups+0.1"},
           {"kind": "connector", "fromId": "a", "toId": "b", "box": [0, 0, 0, 0], "at": "@word:daily-0.2"},
           {"kind": "shape", "shape": "arc", "box": [0.6, 0.6, 0.3, 0.3], "sweep": 270, "start": 30, "at": "@word:Fast"},
           {"kind": "number", "to": 50, "suffix": " GB", "box": [0.1, 0.7, 0.4, 0.2], "at": "@word:storage", "countEnd": "@word:storage+0.8"}]
    b = {"type": "composition", "at": "@word:Fast", "canvas": {"tall": 1, "wide": 1.9}, "elements": els}
    b.update(over)
    return b


def _sb(block):
    return {"scenes": [{"id": "s1", "purpose": "point", "narration": NARR, "blocks": [block]}]}


def test_valid_composition_passes_and_is_a_hero():
    from pipeline.storyboard import HERO_BLOCKS
    assert validate_storyboard(_sb(_comp()))[0] == []
    assert "composition" in HERO_BLOCKS and hero_of({"blocks": [_comp(), {"type": "pill", "text": "x", "tone": "brand"}]}) == "composition"


@pytest.mark.parametrize("mutate,needle", [
    (lambda b: b["elements"][0].update(fill="#ff0044"), "not a theme colour token"),
    (lambda b: b["elements"][0].update(box=[0.9, 0.9, 0.3, 0.3]), "inside the 0..1 canvas"),
    (lambda b: b["elements"][2].update(toId="nobody"), "connector needs fromId/toId"),
    (lambda b: b["elements"][1].update(text=""), "non-empty 'text'"),
    (lambda b: b["elements"][1].update(role="headline"), ".role"),
    (lambda b: b["elements"][0].update(shape="star"), ".shape"),
    (lambda b: b["elements"][0].update(motion="spin"), ".motion"),
    (lambda b: b["elements"][4].pop("to"), "numeric 'to'"),
    (lambda b: b.update(canvas={"tall": 9}), "canvas"),
    (lambda b: b.update(elements=[]), "non-empty elements"),
    (lambda b: b["elements"][0].update(icon="unicorn"), "unknown icon"),
])
def test_invalid_compositions_are_rejected(mutate, needle):
    b = _comp()
    mutate(b)
    errs, _ = validate_storyboard(_sb(b))
    assert any(needle in e for e in errs), errs


def test_nested_element_times_resolve_and_geometry_numbers_do_not():
    assert {"at", "countEnd", "pulseAt"} <= TIME_KEYS and not {"start", "sweep", "box", "curve", "to", "from"} & TIME_KEYS
    words = [Word(w, 1.0 + 0.4 * i, 1.3 + 0.4 * i) for i, w in enumerate(NARR.split())]
    R = Resolver(SceneTiming("s1", 0.9, 6.0, 1.0, words[-1].end, words), {})
    out = resolve_block(_comp(), R, 0, 30)
    e = out["elements"]
    assert e[0]["at"] == 1.4 and e[0]["pulseAt"] == words[-1].start                 # "@word:storage", "@word:safe"
    assert e[1]["at"] == round(words[4].start + 0.1, 3) and e[2]["at"] == round(words[3].start - 0.2, 3)
    assert e[4]["countEnd"] == round(1.4 + 0.8, 3)
    assert e[3]["sweep"] == 270 and e[3]["start"] == 30 and e[3]["box"] == [0.6, 0.6, 0.3, 0.3]
    assert out["at"] == 1.0


def test_sync_rules_see_composition_numbers_and_events():
    from pipeline.creative.rules import sync_report
    from pipeline.sync_check import _numbers_shown
    early = _comp()
    early["elements"][4]["at"] = "@word:Fast"                       # 50 counted on the first word, spoken later? never
    rep = sync_report(_sb(early))
    assert rep["scenes"][0]["events"] >= 6
    resolved = resolve_block(early, Resolver(SceneTiming("s1", 0, 9, 0.1, 5, [Word(w, 0.1 + 0.4 * i, 0.4 + 0.4 * i)
                                                                                for i, w in enumerate(NARR.split())]), {}), 0, 30)
    assert ("50", resolved["elements"][4]["countEnd"]) in _numbers_shown(resolved, None, [])


# ---- freshness ---------------------------------------------------------------------------------------------
def _prod(root: Path, pid: str, brand: str, scenes: list[dict], templates=None, blueprint=None):
    d = root / pid
    (d / "concepts").mkdir(parents=True)
    (d / "project.json").write_text(json.dumps({"brand": brand}))
    (d / "storyboard.json").write_text(json.dumps({"scenes": scenes}))
    if templates:
        (d / "concepts" / "creative-plan.json").write_text(json.dumps({"concept": {"id": "c2"}}))
        (d / "concepts" / "concepts.json").write_text(json.dumps({"concepts": [{"id": "c1", "templates": ["x"]},
                                                                              {"id": "c2", "templates": templates, "blueprint": blueprint}]}))
    return d


def _scene(hero="server-stack", backdrop="grid", design=None):
    b = {"type": hero}
    if design:
        b = {"type": "composition", "design": design}
    return {"id": "s", "backdrop": backdrop, "blocks": [b, {"type": "pill"}]}


def test_freshness_with_no_history_is_neutral(tmp_path):
    fr = freshness.load("anybrand", root=tmp_path / "missing")
    assert fr.productions == [] and fr.penalty("template", "x") == 0 and fr.design_penalty("orbit/ring/pop", "orbit") == 0
    assert fr.concept_report({"scene_plan": [{"scene": "s1", "template": "t", "backdrop": "glow"}]})["score"] == 1.0


def test_freshness_is_recency_weighted_per_brand_and_deterministic(tmp_path):
    _prod(tmp_path, "P20260101-000000-aaaaa", "brand-a", [_scene("server-stack", "grid")], ["proof-server-stack"], "bp1")
    _prod(tmp_path, "P20260102-000000-bbbbb", "brand-a", [_scene(design={"structure": "orbit", "signature": "orbit/ring/pop"},
                                                                   backdrop="deep")], ["proof-server-stack", "cta-outro"], "bp2")
    _prod(tmp_path, "P20260103-000000-ccccc", "brand-b", [_scene("checklist", "glow")], ["proof-feature-checklist"], "bp1")
    (tmp_path / "P20260104-000000-ddddd").mkdir()                     # no storyboard: ignored
    fr = freshness.load("brand-a", root=tmp_path)
    assert fr.productions == ["P20260102-000000-bbbbb", "P20260101-000000-aaaaa"]           # newest first, brand-b excluded
    assert fr.weight("template", "proof-server-stack") == 1.5 and fr.weight("template", "cta-outro") == 1.0
    assert fr.weight("blueprint", "bp1") == 0.5 and fr.weight("hero", "server-stack") == 0.5
    assert fr.weight("signature", "orbit/ring/pop") == 1.0 and fr.weight("backdrop", "deep") == 1.0
    assert fr.penalty("template", "proof-server-stack") > fr.penalty("template", "cta-outro") > fr.penalty("template", "nothing") == 0
    assert 0.6 * fr.penalty("structure", "orbit") <= fr.design_penalty("orbit/spokes/draw", "orbit") < fr.design_penalty("orbit/ring/pop", "orbit")
    assert freshness.load("brand-a", root=tmp_path).as_dict() == fr.as_dict()
    assert freshness.load("brand-a", root=tmp_path, exclude={"P20260102-000000-bbbbb"}).productions == ["P20260101-000000-aaaaa"]
    rep = fr.concept_report({"blueprint": "bp1", "scene_plan": [{"scene": "s1", "template": "proof-server-stack", "backdrop": "grid"},
                                                                {"scene": "s2", "template": "new", "backdrop": "light"}]})
    assert "proof-server-stack" in rep["repeats"] and 0 < rep["score"] < 1 and rep["history"] == 2


# ---- composer: content, search, scoring -------------------------------------------------------------------------
def test_content_comes_only_from_the_template_hero(hosting):
    st, ctx, sc = hosting
    c = composer.content_of(sc["proof-server-stack"])
    assert c.kind == "stack" and c.hero_type == "server-stack" and 2 <= len(c.items) <= 4
    assert all(t in ctx.labels for t in c.texts())
    assert all(isinstance(i.at, str) and i.at.startswith("@word:") for i in c.items)
    cc = composer.content_of(sc["proof-checklist-counter"])
    assert cc.kind == "count" and cc.number["to"] and cc.absorbs                       # the checklist becomes satellites
    assert composer.content_of({"blocks": [{"type": "pill", "text": "x"}], "narration": "x"}) is None


def test_every_structure_builds_valid_blocks_for_both_canvases(hosting):
    st, ctx, sc = hosting
    seen = set()
    for scene in sc.values():
        c = composer.content_of(scene)
        for cd in composer.candidates_for(c, scene, seed=3):
            assert not cd.rejected, cd.rejected
            new = composer.replace_hero(scene, c, cd.block)
            assert validate_storyboard({"scenes": [new]})[0] == []
            assert all(e.get("text") in ctx.labels for e in cd.block["elements"] if e["kind"] == "text")
            assert all(k not in e for e in cd.block["elements"] for k in ("_item",))
            seen.add(cd.structure)
    assert {"ladder", "orbit", "grid", "network", "stacked", "funnel", "layers", "hero-number", "path"} <= seen


def test_search_is_deterministic_and_seeded(hosting, no_history):
    st, ctx, sc = hosting
    scene = sc["proof-server-stack"]
    a, b = _search(st, ctx, scene, seed=11), _search(st, ctx, scene, seed=11)
    key = lambda r: [(c.signature, c.source, json.dumps(c.params, sort_keys=True), c.total, c.rejected) for c in r.candidates]  # noqa: E731
    assert key(a) == key(b) and a.best.signature == b.best.signature and a.layout == "ok"
    assert a.best.total > 0 and not a.best.rejected and len(a.alternates()) >= 2
    assert len({x.structure for x in a.alternates()} | {a.best.structure}) == len(a.alternates()) + 1
    c = composer.content_of(scene)
    p1 = [cd.params for cd in composer.candidates_for(c, scene, seed=1)]
    p2 = [cd.params for cd in composer.candidates_for(c, scene, seed=2)]
    assert p1 != p2                                                     # the seed moves the arrangement parameters


def test_scoring_rejects_invented_labels(hosting):
    st, ctx, sc = hosting
    scene = sc["proof-server-stack"]
    c = composer.content_of(scene)
    good = composer.candidates_for(c, scene, seed=5)[0]
    bad = copy.deepcopy(good)
    next(e for e in bad.block["elements"] if e["kind"] == "text" and e["role"] == "label")["text"] = "Lightning fast servers"
    composer.score_candidates(scene, [good, bad], c, labels=ctx.labels, brand_id=st.brand.id)
    assert not any("invented" in r for r in good.rejected)
    assert any("invented label" in r and "Lightning fast servers" in r for r in bad.rejected)


def test_scoring_rejects_a_number_shown_before_it_is_spoken(hosting):
    st, ctx, sc = hosting
    scene = sc["proof-checklist-counter"]
    c = composer.content_of(scene)
    first = scene["narration"].split()[0].strip(".,")
    late = copy.deepcopy(c)
    late.number["at"] = f"@word:{first}"
    late.number["countEnd"] = f"@word:{first}+0.8"
    cands = [composer.Candidate("hero-number", "arc", {"ring": 0.55}, "cascade"), composer.Candidate("hero-number", "arc", {"ring": 0.55}, "cascade")]
    canvas = composer.canvas_for(scene, c)
    cands[0].block = composer.build_block(c, "hero-number", "arc", {"ring": 0.55}, "cascade", canvas, 1)
    cands[1].block = composer.build_block(late, "hero-number", "arc", {"ring": 0.55}, "cascade", canvas, 1)
    composer.score_candidates(scene, cands, c, labels=ctx.labels, brand_id=st.brand.id)
    assert not any("before it is spoken" in r for r in cands[0].rejected), cands[0].rejected
    assert any("number drawn before it is spoken" in r for r in cands[1].rejected)


def test_scoring_rejects_text_overflow(hosting, no_history):
    st, ctx, sc = hosting
    scene = copy.deepcopy(sc["proof-server-stack"])
    hero = next(b for b in scene["blocks"] if b["type"] == "server-stack")
    long = "Supercalifragilisticexpialidociousultramicroscopicstoragelayerwithoutanyspacesatall"
    hero["nodes"][1]["label"] = long
    labels = {**ctx.labels, long: "test"}
    res = composer.search(scene, composer.content_of(scene), labels=labels, brand_id=st.brand.id, seed=3, template_id="t")
    assert res.layout == "ok"
    over = [c for c in res.candidates if any("text overflow" in r for r in c.rejected)]
    assert over and res.best is None                                    # every structure shows every item
    assert res.rejected_counts().get("text overflow in the layout manifest", 0) >= 1


def test_llm_may_only_pick_structure_names(hosting, no_history):
    st, ctx, sc = hosting
    scene = sc["proof-server-stack"]
    c = composer.content_of(scene)
    prov = MockProvider(responder=lambda task, context, messages: {"structures": ["grid", "spaceship", "orbit"]})
    log: list = []
    picks = composer.llm_structures(prov, scene, c, ["grid", "orbit", "ladder"], log)
    assert picks == [] or picks == ["grid", "orbit"]                    # an out-of-list name fails the schema / is dropped
    prov_ok = MockProvider(responder=lambda task, context, messages: {"structures": ["grid", "orbit"]})
    assert composer.llm_structures(prov_ok, scene, c, ["grid", "orbit", "ladder"], log) == ["grid", "orbit"]
    assert prov_ok.calls[0]["task"] == "component_structure" and "box" not in json.dumps(prov_ok.calls[0]["messages"])

    class Broken(MockProvider):
        def generate_json(self, **kw):
            raise RuntimeError("model crashed")
    assert composer.llm_structures(Broken(), scene, c, ["grid"], log) == []
    assert composer.llm_structures(None, scene, c, ["grid"], log) == []
    res = _search(st, ctx, scene, provider=prov_ok)
    grid = [x for x in res.candidates if x.structure == "grid" and not x.rejected]
    assert grid and all(x.scores["bonus"] == composer.BONUS["llm_first"] for x in grid)


# ---- integration --------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def generated(no_history):
    return generate_concepts({**BRIEF, "components": "generate"}, provider="none")


def test_generate_mode_replaces_suitable_heroes_and_keeps_every_rule(generated):
    cs = generated["concepts"]
    assert len(cs) >= 2
    sel = [r for c in cs for r in c.get("components", []) if r["selected"]]
    assert sel, [r.get("reason") for c in cs for r in c.get("components", [])]
    for c in cs:
        assert not [r for r in c["rules"] if r["status"] == "FAIL"]
        assert "freshness" in c and c["freshness"]["history"] == 0
        for r in c.get("components", []):
            assert r["role"] in composer.SUITABLE_ROLES and r["searched"] > 0
            if r["selected"]:
                assert r["scores"]["total"] >= r["template_score"]["total"]
                assert r["design"]["structure"] in composer.STRUCTURES and r["id"].startswith("cmp-")
                assert next(sp for sp in c["scene_plan"] if sp["scene"] == r["scene"])["component"]["id"] == r["id"]
    md = concepts_markdown(generated)
    assert "| generated |" in md and "| freshness |" in md and "replaces" in md


def test_generated_concept_builds_a_storyboard_with_compositions(generated):
    c = next(c for c in generated["concepts"] if any(r["selected"] for r in c.get("components", [])))
    sb, project, rep = build_storyboard(generated["brief"], c, provider="none")
    assert validate_storyboard(sb)[0] == []
    assert not [r for r in rep["rules"] if r["status"] == "FAIL"], [r for r in rep["rules"] if r["status"] == "FAIL"]
    comps = [b for s in sb["scenes"] for b in s["blocks"] if b["type"] == "composition"]
    ids = {r["id"] for r in c["components"] if r["selected"]}
    assert comps and {b["design"]["component"] for b in comps} == ids
    for b in comps:                                                      # labels only from facts / copy
        assert all(rep["labels"].get(e["text"]) for e in b["elements"] if e["kind"] == "text")
    from pipeline.creative.rules import _resolved
    for _sc, st_, blocks in _resolved(sb):                              # nested times resolve on the timeline
        for b in blocks:
            if b["type"] == "composition":
                assert all(isinstance(e["at"], (int, float)) and st_.start - 0.2 <= e["at"] <= st_.end for e in b["elements"])


def test_default_path_never_touches_the_generator(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("generator used without \"components\": \"generate\"")
    monkeypatch.setattr(composer, "generate_components", boom)
    monkeypatch.setattr(composer, "apply_recipe", boom)
    monkeypatch.setattr(freshness, "load", boom)
    monkeypatch.setattr(components, "library", boom)
    a = generate_concepts(dict(BRIEF), provider="none")
    b = generate_concepts({**BRIEF, "components": "templates"}, provider="none")
    strip = lambda r: json.dumps(r["concepts"], sort_keys=True)  # noqa: E731
    assert strip(a) == strip(b)
    assert all("components" not in c and "freshness" not in c and "generated" not in c["visual_approach"] for c in a["concepts"])
    assert concepts_markdown(a) == concepts_markdown(b) and "| generated |" not in concepts_markdown(a)
    sb, _, _ = build_storyboard(a["brief"], a["concepts"][0], provider="none")
    assert not any(bl["type"] == "composition" for s in sb["scenes"] for bl in s["blocks"])


def test_freshness_moves_a_recently_used_blueprint_down(tmp_path, monkeypatch):
    default = generate_concepts(dict(BRIEF), provider="none")
    c1 = default["concepts"][0]
    sb, _, _ = build_storyboard(default["brief"], c1, provider="none")
    for pid in ("P20260101-000000-aaaaa", "P20260102-000000-bbbbb"):
        d = _prod(tmp_path, pid, "shrotihost", sb["scenes"])
        (d / "concepts" / "creative-plan.json").write_text(json.dumps({"concept": {"id": c1["id"]}}))
        (d / "concepts" / "concepts.json").write_text(json.dumps({"concepts": [c1]}))
    monkeypatch.setattr(freshness, "PRODUCTIONS_DIR", tmp_path)
    res = generate_concepts({**BRIEF, "components": "generate"}, provider="none")
    assert res["concepts"][0]["blueprint"] != c1["blueprint"]
    assert all(c["freshness"]["history"] == 2 for c in res["concepts"])
    again = [c for c in res["concepts"] if c["blueprint"] == c1["blueprint"]]
    for c in again:
        assert c["freshness"]["repeats"] and "blueprint used recently" in c["freshness"]["line"]


def test_brief_option_is_validated():
    assert parse_brief({**BRIEF, "components": "generate"})[0]["components"] == "generate"
    with pytest.raises(ConfigError):
        parse_brief({**BRIEF, "components": "sometimes"})


def test_studio_server_keeps_the_components_option(registry, tmp_path, monkeypatch):
    import pipeline.productions as P
    from studio import server as S
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", tmp_path / "productions")
    p = S.create_production({"brand": "shrotihost", "brief": {"product": "WordPress Hosting", "components": "generate"}})
    from pipeline import api
    assert api.Productions(registry).get(p["id"])["brief"]["components"] == "generate"
    q = S.create_production({"brand": "shrotihost", "brief": {"product": "WordPress Hosting", "components": "templates"}})
    assert "components" not in api.Productions(registry).get(q["id"])["brief"]
    with pytest.raises(S.BadRequest):
        S.create_production({"brand": "shrotihost", "brief": {"product": "x", "components": "always"}})


# ---- store + human decisions (temp dirs, fake reviewers) ---------------------------------------------------------
def _record(st, ctx, scene, concept_id="c1"):
    c = composer.content_of(scene)
    canvas = composer.canvas_for(scene, c)
    params = composer.STRUCTURES["grid"].params(random.Random(1))
    blk = composer.build_block(c, "grid", "tiles", params, "cascade", canvas, 9)
    recipe = {"structure": "grid", "variant": "tiles", "params": params, "motion": "cascade", "canvas": canvas, "seed": 9, "source": "generated"}
    recipe["id"] = composer.component_id("test", recipe)
    rec = {"id": recipe["id"], "concept": concept_id, "blueprint": "bp", "scene": scene["id"], "role": "proof", "template": "t",
           "replaces": c.hero_type, "content": {"kind": c.kind, "items": len(c.items)}, "design": blk["design"], "params": params,
           "canvas": canvas, "block": blk, "scores": {"total": 0.8}, "template_score": {"total": 0.7}, "selected": True, "recipe": recipe}
    return {"id": concept_id, "components": [rec]}, rec


@pytest.fixture
def prod(registry, tmp_path, monkeypatch, hosting):
    import pipeline.productions as P
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", tmp_path / "productions")
    monkeypatch.setattr(components, "BRANDS_DIR", tmp_path / "brands")
    st, ctx, sc = hosting
    p = P.Productions(registry).create("shrotihost", "component-test", {"product": "WordPress Hosting"})
    concept, rec = _record(st, ctx, sc["proof-server-stack"])
    paths = components.save_generated(Path(p["dir"]), "shrotihost", [concept])
    components.save_selected(Path(p["dir"]), concept)
    return p, rec, paths


def test_components_are_saved_with_scores(prod):
    p, rec, paths = prod
    d = Path(p["dir"]) / "components"
    saved = json.loads((d / f"{rec['id']}.json").read_text())
    assert saved["scores"]["total"] == 0.8 and saved["template_score"]["total"] == 0.7 and saved["production"] == p["id"]
    assert json.loads((d / "selected.json").read_text()) == {"concept": "c1", "components": [rec["id"]]}
    rows = components.list_components(p["id"])
    assert [r["id"] for r in rows] == [rec["id"]] and rows[0]["decision"] == "pending" and not rows[0]["in_storyboard"]


def test_cli_approve_copies_into_the_brand_library_and_audits(prod, registry, capsys, tmp_path):
    from pipeline.cli import main
    p, rec, _ = prod
    assert main(["component", "list", "--production", p["id"]]) == 0
    assert rec["id"] in capsys.readouterr().out
    assert main(["--json", "component", "approve", "--production", p["id"], "--id", rec["id"], "--reviewer", "Test Reviewer",
                 "--note", "fixture decision"]) == 0
    out = json.loads(capsys.readouterr().out)
    lib = tmp_path / "brands" / "shrotihost" / "components" / "grid-tiles-cascade.json"
    assert lib.exists() and out["library"].endswith("grid-tiles-cascade.json")
    entry = json.loads(lib.read_text())
    assert entry["design"]["signature"] == "grid/tiles/cascade" and entry["approval"]["reviewer"] == "Test Reviewer"
    assert entry["approval"]["component"] == rec["id"] and entry["example"]["type"] == "composition"
    with registry.conn() as c:
        rows = [dict(r) for r in c.execute("SELECT actor, action, subject FROM audit_log WHERE action LIKE 'component.%'")]
    assert rows == [{"actor": "Test Reviewer", "action": "component.approve", "subject": p["id"]}]
    assert main(["component", "approve", "--production", p["id"], "--id", rec["id"], "--reviewer", "Test Reviewer"]) != 0
    assert components.list_components(p["id"])[0]["decision"] == "approve by Test Reviewer"
    assert [e["name"] for e in components.library("shrotihost")] == ["grid-tiles-cascade"]


def test_cli_reject_is_recorded_and_the_library_is_never_overwritten(prod, registry, capsys, tmp_path):
    from pipeline.cli import main
    p, rec, _ = prod
    assert main(["component", "reject", "--production", p["id"], "--id", rec["id"], "--reviewer", "Other Reviewer", "--note", "too busy"]) == 0
    assert not (tmp_path / "brands" / "shrotihost" / "components").exists()
    dec = json.loads((Path(p["dir"]) / "components" / "decisions.json").read_text())["decisions"]
    assert [(d["decision"], d["reviewer"]) for d in dec] == [("reject", "Other Reviewer")]
    lib = tmp_path / "brands" / "shrotihost" / "components"
    lib.mkdir(parents=True)
    (lib / "grid-tiles-cascade.json").write_text("{}")
    assert main(["component", "approve", "--production", p["id"], "--id", rec["id"], "--reviewer", "Test Reviewer"]) != 0
    assert (lib / "grid-tiles-cascade.json").read_text() == "{}"
    assert main(["component", "approve", "--production", p["id"], "--id", rec["id"], "--reviewer", "Test Reviewer", "--name", "grid-two"]) == 0
    assert (lib / "grid-two.json").exists()
    assert main(["component", "approve", "--production", p["id"], "--id", "cmp-nope", "--reviewer", "Test Reviewer"]) != 0
    with pytest.raises(Exception):
        components.decide(p["id"], rec["id"], "reject", "   ")
    with registry.conn() as c:
        acts = [r[0] for r in c.execute("SELECT action FROM audit_log WHERE action LIKE 'component.%' ORDER BY id")]
    assert acts == ["component.reject", "component.approve"]


def test_an_approved_design_joins_the_search_for_later_productions(prod, hosting, monkeypatch):
    from pipeline.cli import main
    p, rec, _ = prod
    st, ctx, sc = hosting
    assert main(["component", "approve", "--production", p["id"], "--id", rec["id"], "--reviewer", "Test Reviewer"]) == 0
    lib = components.library("shrotihost")
    scene = sc["proof-server-stack"]
    cands = composer.candidates_for(composer.content_of(scene), scene, seed=4, library=lib)
    from_lib = [c for c in cands if c.source == "library:grid-tiles-cascade"]
    assert len(from_lib) == 1 and from_lib[0].params == rec["params"] and from_lib[0].signature == "grid/tiles/cascade"
    b, _ = parse_brief({**BRIEF, "components": "generate"})
    assert [e["name"] for e in studio(b, load_facts(b["brand_id"])).library] == ["grid-tiles-cascade"]


# ---- drawn-geometry checks: paths crossing text, label size, coverage, legibility on equal footing ----------------
def _mblock(texts, bbox=None):
    return {"bbox": bbox or {"x": 100, "y": 100, "w": 800, "h": 800},
            "texts": [{"text": t, "role": r, "fontSize": fs, "bbox": {"x": x, "y": y, "w": w, "h": h}} for t, r, fs, (x, y, w, h) in texts]}


def _two_nodes(curve=0.0):
    return {"type": "composition", "canvas": {"tall": 1, "wide": 1.9}, "elements": [
        {"id": "a", "kind": "shape", "shape": "circle", "box": [0.0, 0.45, 0.1, 0.1]},
        {"id": "b", "kind": "shape", "shape": "circle", "box": [0.9, 0.45, 0.1, 0.1]},
        {"kind": "connector", "fromId": "a", "toId": "b", "box": [0, 0, 0, 0], "curve": curve}]}


def test_a_connector_through_a_label_is_found_curves_included():
    blk = _two_nodes()
    across = _mblock([("Storyboard", "label", 40, (450, 480, 120, 40))])          # on the straight line y = 500
    aside = _mblock([("Storyboard", "label", 40, (450, 300, 120, 40))])
    assert composer.path_crossings(blk, across) and not composer.path_crossings(blk, aside)
    bent = _two_nodes(curve=0.5)                                    # a positive bend bows towards +y: its middle is near y = 580
    below = _mblock([("Storyboard", "label", 40, (450, 560, 120, 40))])
    assert composer.path_crossings(bent, below) and not composer.path_crossings(bent, across)
    assert not composer.path_crossings(blk, below)
    own = _mblock([("Node", "label", 40, (110, 485, 60, 30))])                       # text inside the connector's own node
    assert not composer.path_crossings(blk, own)
    ring = {"type": "composition", "elements": [{"id": "r", "kind": "shape", "shape": "ring", "box": [0.1, 0.1, 0.8, 0.8]}]}
    assert composer.path_crossings(ring, _mblock([("On the ring", "label", 40, (130, 480, 60, 40))]))
    assert not composer.path_crossings(ring, _mblock([("Inside", "label", 40, (450, 480, 100, 40))]))


def test_coverage_rewards_a_filled_hero_box():
    blk = {"type": "composition", "canvas": {"tall": 1}, "elements": [
        {"kind": "shape", "shape": "roundrect", "box": [0.0, 0.0, 1.0, 0.45]}, {"kind": "shape", "shape": "roundrect", "box": [0.0, 0.55, 1.0, 0.45]}]}
    full = composer.ink_coverage(blk, _mblock([]))
    sparse_blk = {"type": "composition", "canvas": {"tall": 1}, "elements": [{"kind": "icon", "icon": "zap", "box": [0.45, 0.45, 0.1, 0.1]}]}
    sparse = composer.ink_coverage(sparse_blk, _mblock([("AI proposes", "label", 30, (150, 150, 160, 36))]))
    assert full > 0.85 and sparse < 0.06
    assert composer.fill_score(sparse) == 0 and composer.fill_score(0.5) == 1 and composer.fill_score(full) < 1
    # balance = ½ drawn coverage + ½ arrangement: a sparse design stays below the template's presumed balance
    assert 0.5 * composer.fill_score(sparse) + 0.5 * 1.0 < composer.TEMPLATE_BALANCE


def test_legibility_judges_the_same_item_texts_in_template_and_candidate():
    items = ["Concepts", "Storyboard", "Quality checks"]
    tmpl = {"short": _mblock([("Production pipeline", "label", 18, (0, 0, 10, 10)), ("Concepts", "label", 36, (0, 0, 10, 10)),
                              ("Storyboard", "label", 36, (0, 0, 10, 10)), ("Quality", "label", 36, (0, 0, 10, 10)),
                              ("checks", "label", 36, (0, 0, 10, 10))])}
    cand = {"short": _mblock([("Concepts", "label", 36, (0, 0, 10, 10)), ("Storyboard", "label", 36, (0, 0, 10, 10)),
                              ("Quality checks", "label", 36, (0, 0, 10, 10))])}
    assert composer.item_px(tmpl["short"], items) == 36                              # the 18 px window title is chrome
    assert composer._legibility(tmpl, items) == composer._legibility(cand, items) > 0


def test_scoring_rejects_small_labels_and_crossing_connectors(hosting, no_history):
    st, ctx, sc = hosting
    scene = sc["proof-server-stack"]
    c = composer.content_of(scene)
    good = next(cd for cd in composer.candidates_for(c, scene, seed=5) if cd.structure == "layers" and cd.canvas["tall"] == 1.3)
    tiny = copy.deepcopy(good)
    for e in tiny.block["elements"]:                    # squeeze every label into a sliver: fitted to the role minimum
        if e["kind"] == "text" and e["role"] == "label":
            e["box"][3] = 0.025
            e.pop("wide", None)
    crossing = copy.deepcopy(good)
    labels = [e for e in crossing.block["elements"] if e["kind"] == "text" and e["role"] == "label"]
    nodes = [e for e in crossing.block["elements"] if e["kind"] == "shape" and e["id"].startswith("n")]
    crossing.block["elements"].append({"kind": "connector", "fromId": nodes[0]["id"], "toId": nodes[-1]["id"],
                                       "box": [0, 0, 0, 0], "at": labels[0]["at"], "stroke": "brand"})
    composer.score_candidates(scene, [good, tiny, crossing], c, labels=ctx.labels, brand_id=st.brand.id)
    assert not good.rejected, good.rejected
    assert good.scores["label_px"]["short"] >= composer.MIN_LABEL_PX["short"]
    assert good.scores["label_px"]["landscape"] >= composer.MIN_LABEL_PX["landscape"]
    assert any(r.startswith("labels too small") for r in tiny.rejected), tiny.rejected
    assert any("crosses" in r for r in crossing.rejected), crossing.rejected


def test_no_selected_component_draws_small_or_crossed_labels(generated):
    for c in generated["concepts"]:
        for r in c.get("components", []):
            if r["selected"]:
                assert all(px >= composer.MIN_LABEL_PX[f] for f, px in r["scores"]["label_px"].items() if px is not None)
                assert r["scores"]["balance"] >= composer.TEMPLATE_BALANCE


def test_a_card_never_scales_away_from_its_own_label():
    """Seen in the self-launch film: a status card scaled in on the last word while its tick and text did not."""
    from pipeline.creative.composer import apply_motion
    els = [{"id": "card", "kind": "shape", "shape": "roundrect", "box": [0, 0.8, 1, 0.2], "wide": [0, 0.8, 1, 0.2], "at": 1.0},
           {"id": "tick", "kind": "icon", "icon": "check", "box": [0.02, 0.83, 0.05, 0.06], "wide": [0.02, 0.83, 0.03, 0.06], "at": 1.0},
           {"id": "label", "kind": "text", "text": "Runs on one Mac", "role": "label", "box": [0.1, 0.82, 0.85, 0.1],
            "wide": [0.06, 0.82, 0.9, 0.1], "at": 1.0},
           {"id": "free", "kind": "shape", "shape": "rect", "box": [0, 0, 0.2, 0.2], "at": 0.5}]
    for scheme in ("cascade", "pop", "draw", "focus"):
        out = {e["id"]: e for e in apply_motion(els, scheme)}
        assert out["card"]["motion"] in ("fade", "fade-up"), scheme
        if out["card"]["motion"] == "fade-up":
            assert out["label"]["motion"] == "fade-up"
        assert out["label"]["motion"] in ("fade", "fade-up")
