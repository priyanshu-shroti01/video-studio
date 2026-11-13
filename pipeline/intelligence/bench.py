"""Benchmark a local model on THIS machine: load time, prompt latency, tokens/s, peak RSS of the runtime,
swap delta, page-outs, JSON-schema validity over N generations, and an automatic quality rubric.
Raw results -> <out_dir>/bench-<model>-<ts>.json (+ .md); the registry gets the summary."""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import time
from pathlib import Path

from ..system import mem_snapshot
from .brief import parse_brief
from .claims import verify_concept
from .concepts import SYSTEM as CONCEPT_SYSTEM, _concept_prompt, _normalize_llm_concept, concept_schema, distinctness
from .facts import load_facts
from .patterns import rank_patterns
from .planner import template_concept
from .providers import LLMError, OllamaProvider, RSSSampler, _http, ollama_processes
from .registry import model_entry, save_benchmark
from .storyboard_gen import build_storyboard

DEMO_BRIEF = {"brand": "Shroti Host", "product": "WordPress Hosting", "price": "₹39/month", "audience": "Website beginners",
              "format": "short", "duration_seconds": 35, "goal": "Conversions", "cta": "Get Started"}
DEMO_REQUEST = ("Create a 35-second premium YouTube Short promoting Shroti Host WordPress Hosting at ₹39/month. Target beginners. "
                "Show a compelling problem, a product demonstration, an animated pricing comparison and a strong CTA.")
HEAVY = r"chrome-headless-shell|kokoro|piper|whisper|pipeline\.voice\.evaluate|remotion render|ffmpeg"


def contention() -> list[dict]:
    """Heavy processes that would distort (or be hurt by) a benchmark: pid, %cpu, rss, command."""
    out = subprocess.run(["ps", "-axo", "pid=,pcpu=,rss=,command="], capture_output=True, text=True).stdout
    procs = []
    for line in out.splitlines():
        p = line.strip().split(None, 3)
        if len(p) == 4 and re.search(HEAVY, p[3]) and "pgrep" not in p[3] and "zsh -c" not in p[3]:
            procs.append({"pid": int(p[0]), "cpu_pct": float(p[1]), "rss_mb": round(int(p[2]) / 1024), "cmd": p[3][:90]})
    return procs


def busy(procs: list[dict], cpu_threshold: float = 20.0) -> list[dict]:
    return [p for p in procs if p["cpu_pct"] >= cpu_threshold]


def hook_score(hook: str) -> int:
    """0-3: length 5-12 words; speaks to the viewer (you/your/imperative); has tension (question, contrast, myth, number)."""
    words = re.findall(r"[\w'₹]+", hook)
    s = int(5 <= len(words) <= 12)
    s += int(bool(re.search(r"\b(you|your|you're)\b", hook, re.I)) or bool(re.match(r"^(stop|think|meet|launch|pick|imagine|new)\b", hook, re.I)))
    s += int("?" in hook or bool(re.search(r"\b(myth|before|after|stuck|stop|not|never|shouldn't|why)\b|\d", hook, re.I)))
    return s


def _stat(xs):
    xs = [x for x in xs if x is not None]
    return {"mean": round(statistics.mean(xs), 3), "min": round(min(xs), 3), "max": round(max(xs), 3), "n": len(xs)} if xs else None


def run_bench(model: str, *, n_concepts: int = 8, n_storyboards: int = 3, out_dir: str | Path = "output/eval-llm",
              allow_contention: bool = False, skip_if_low_memory: bool = True) -> dict:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    ent = model_entry(model) or {}
    res: dict = {"model": model, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "registry_entry": ent.get("id"),
                 "machine": _machine(), "contention_before": contention()}
    hot = busy(res["contention_before"])
    if hot and not allow_contention:
        res.update(status="SKIPPED", reason=f"heavy processes running (would distort results): {[p['cmd'][:50] for p in hot]}")
        return _save(res, out_dir, model, ts)
    prov = OllamaProvider(model, headroom_mb=400)
    ok, why = prov.available()
    if not ok:
        res.update(status="SKIPPED", reason=why)
        return _save(res, out_dir, model, ts)
    res["runtime_version"] = prov.runtime.version()
    try:
        _http(f"{prov.host}/api/show", {"model": model}, timeout=20)
        res["metadata_loadable"] = True
    except Exception as e:  # noqa: BLE001
        res["metadata_loadable"] = f"no: {e}"
    for m in _http(f"{prov.host}/api/ps", timeout=5).get("models", []):     # start cold
        _http(f"{prov.host}/api/generate", {"model": m["name"], "keep_alive": 0}, timeout=30)
    time.sleep(1.0)
    m0 = mem_snapshot()
    res["mem_before"] = m0.__dict__
    need = prov.required_mb + prov.headroom_mb
    if m0.available_mb < need and skip_if_low_memory:
        res.update(status="SKIPPED", reason=f"memory guard: {m0.available_mb:.0f} MB available < {need:.0f} MB needed "
                                             f"(swap already {m0.swap_used_mb:.0f} MB); not loading to avoid heavy swapping")
        return _save(res, out_dir, model, ts)
    brief, _ = parse_brief(DEMO_BRIEF, DEMO_REQUEST)
    fb = load_facts(brief["brand_id"])
    gens, concepts, storyboards = [], [], []
    with RSSSampler(0.2) as rss:
        # cold load (tiny prompt)
        t0 = time.time()
        try:
            r = prov.generate_json(system="Reply with JSON.", messages=[{"role": "user", "content": 'Return {"ok": true}'}],
                                   schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
                                   task="probe", temperature=0, seed=1, max_tokens=20, keep_alive="120s")
            res["load"] = {"load_s": round(r.stats.load_s, 2), "first_request_wall_s": round(time.time() - t0, 2)}
        except LLMError as e:
            res.update(status="FAILED", reason=f"load failed: {e.message}")
            return _save(res, out_dir, model, ts)
        res["rss_after_load_mb"] = round(sum(p["rss_mb"] for p in ollama_processes()))
        res["mem_after_load"] = mem_snapshot().__dict__
        ranked = rank_patterns(brief)
        trio: list[dict] = []
        for i in range(n_concepts):
            if i % 3 == 0:
                trio = []
            allowed = [p for p in ranked if p not in {c["pattern"] for c in trio}][:4]
            avoid = list(trio)
            g = _one(prov, "concept", CONCEPT_SYSTEM, _concept_prompt(brief, fb, allowed, avoid), concept_schema(allowed, avoid), seed=100 + i,
                     max_tokens=700)
            if g["valid"]:
                c = _normalize_llm_concept(g.pop("data"), len(concepts) + 1, brief)
                cl = verify_concept(c, fb, brief)
                g["quality"] = {"hook": c["hook"], "hook_score": hook_score(c["hook"]), "pattern": c["pattern"],
                                "invented_claims": [x["text"] for x in cl["needs_review"] if x["origin"] == "generated"],
                                "claims_total": cl["summary"]["total"]}
                concepts.append(c)
                trio.append(c)
            gens.append(g)
        for i in range(n_storyboards):
            concept = concepts[i] if i < len(concepts) else template_concept(brief, fb, ranked[i % len(ranked)], i + 1)
            t0 = time.time()
            r = build_storyboard(brief, concept, fb, prov, seed=300 + 13 * i)
            calls = [e for e in r["log"] if e["event"] in ("scene_generated", "publishing_generated")]
            for e in calls:   # every model call counts towards JSON validity + speed
                gens.append({"task": "scene" if e["event"] == "scene_generated" else "publishing", "parsed": True,
                             "valid": not e["schema_errors"], "schema_errors": e["schema_errors"], "stats": e["stats"],
                             "storyboard": i, "problems": e.get("problems", e.get("invented", []))})
            errs = [e for e in r["log"] if e["event"] == "llm_error"]
            for e in errs:
                gens.append({"task": "scene", "parsed": False, "valid": False, "error": e["error"], "storyboard": i})
            chk = r["check"]
            storyboards.append({"concept": concept["id"], "pattern": concept["pattern"], "path": r["path"], "scene_sources": r["scene_sources"],
                                "publishing_source": r["publishing_source"], "wall_s": round(time.time() - t0, 1), "calls": len(calls) + len(errs),
                                "validate_errors": len(chk["errors"]), "estimate_s": chk["estimate_s"], "duration_ok": not chk["duration_error"],
                                "missing_requirements": chk["coverage"]["missing"], "invented_claims": [x["text"] for x in chk["invented"]],
                                "brief_flags": sorted({x["text"] for x in chk["claims"]["needs_review"] if x["origin"] == "brief"}),
                                "narration": [s["narration"] for s in r["storyboard"]["scenes"]]})
        prov.unload()
        time.sleep(1.5)
    m1 = mem_snapshot()
    res["mem_after"] = m1.__dict__
    res["contention_after"] = contention()
    res["generations"] = gens
    res["storyboards"] = storyboards
    ok_g = [g for g in gens if g.get("stats")]
    trios = [concepts[k:k + 3] for k in range(0, len(concepts) - 2, 3)]  # approx. (invalid gens shift trios)
    res["summary"] = {
        "status": "OK",
        "generations": len(gens),
        "json_parse_ok": sum(g["parsed"] for g in gens), "schema_valid": sum(g["valid"] for g in gens),
        "schema_validity_rate": round(sum(g["valid"] for g in gens) / max(1, len(gens)), 3),
        "load_s": res["load"]["load_s"],
        "prompt_tokens_per_s": _stat([g["stats"]["prompt_tokens"] / g["stats"]["prompt_s"] for g in ok_g if g["stats"]["prompt_s"]]),
        "prompt_latency_s": _stat([g["stats"]["prompt_s"] for g in ok_g]),
        "output_tokens_per_s": _stat([g["stats"]["tokens_per_s"] for g in ok_g]),
        "wall_s": {"concept": _stat([g["stats"]["wall_s"] for g in ok_g if g["task"] == "concept"]),
                   "scene": _stat([g["stats"]["wall_s"] for g in ok_g if g["task"] == "scene"])},
        "peak_rss_mb": round(rss.peak_mb), "swap_delta_mb": round(m1.swap_used_mb - m0.swap_used_mb, 1),
        "pageouts_delta": m1.pageouts - m0.pageouts,
        "available_mb_before": round(m0.available_mb), "available_mb_after_load": round(res["mem_after_load"]["available_mb"]),
        "quality": {
            "hook_score_mean_0_3": _stat([g["quality"]["hook_score"] for g in gens if g.get("quality", {}).get("hook_score") is not None]),
            "concepts_with_invented_claims": sum(bool(g.get("quality", {}).get("invented_claims")) for g in gens if g["task"] == "concept"),
            "storyboards": len(storyboards),
            "storyboards_valid": sum(sb["validate_errors"] == 0 for sb in storyboards),
            "storyboards_all_llm_scenes": sum("template" not in sb["scene_sources"] for sb in storyboards),
            "scenes_llm_first_try": sum(x == "llm" for sb in storyboards for x in sb["scene_sources"]),
            "scenes_llm_after_repair": sum(x.startswith("llm+") for sb in storyboards for x in sb["scene_sources"]),
            "scenes_template_fallback": sum(x == "template" for sb in storyboards for x in sb["scene_sources"]),
            "storyboards_duration_ok": sum(sb["duration_ok"] for sb in storyboards),
            "storyboards_with_invented_claims": sum(bool(sb["invented_claims"]) for sb in storyboards),
            "storyboard_wall_s": _stat([sb["wall_s"] for sb in storyboards]),
            "distinctness_min_per_trio": [distinctness(t)["min_score"] for t in trios],
        },
        "contention": [p["cmd"][:60] for p in busy(res["contention_before"] + res["contention_after"])],
    }
    res["status"] = "OK"
    save_benchmark(model, {k: res["summary"][k] for k in ("schema_validity_rate", "load_s", "output_tokens_per_s", "prompt_latency_s",
                                                         "peak_rss_mb", "swap_delta_mb", "pageouts_delta", "generations")}
                   | {"measured_at": res["started_at"], "raw": f"bench-{_safe(model)}-{ts}.json"},
                   memory_required_mb=res["summary"]["peak_rss_mb"])
    return _save(res, out_dir, model, ts)


def _one(prov: OllamaProvider, task: str, system: str, prompt: str, schema: dict, *, seed: int, max_tokens: int, timeout: float = 240) -> dict:
    g = {"task": task, "seed": seed, "parsed": False, "valid": False}
    t0 = time.time()
    try:
        r = prov.generate_json(system=system, messages=[{"role": "user", "content": prompt}], schema=schema, task=task,
                               temperature=0.8 if task == "concept" else 0.6, seed=seed, max_tokens=max_tokens, timeout=timeout,
                               retries=0, keep_alive="120s")
    except LLMError as e:
        g.update(error=e.message, wall_s=round(time.time() - t0, 2))
        return g
    g.update(parsed=True, valid=not r.schema_errors, schema_errors=r.schema_errors[:5], stats=r.stats.as_dict(), data=r.data,
             raw_chars=len(r.raw))
    if not g["valid"]:
        g.pop("data")
    return g


def _machine() -> dict:
    from ..system import host_info
    h = host_info()
    return {"model": h.model, "perf_cores": h.perf_cores, "eff_cores": h.eff_cores, "mem_gb": h.mem_gb}


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def _save(res: dict, out_dir: Path, model: str, ts: str) -> dict:
    p = out_dir / f"bench-{_safe(model)}-{ts}.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    res["file"] = str(p)
    return res
