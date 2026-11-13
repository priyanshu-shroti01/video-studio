"""python -m pipeline.intelligence <command>

  concepts   --brief brief.json [--request "..."] [--provider ollama|mock|none] --out DIR
  storyboard --brief brief.json (--concepts DIR/concepts.json --pick N | --concept concept.json) [--provider ...] --out DIR
  demo       [--provider ...] [--pick N] --out DIR          brief -> concepts -> storyboard for the built-in demo brief
  facts      --brand <id> [--refresh] [--claim "₹39"] [--out DIR]
  verify     --storyboard sb.json [--brief brief.json]       fact-check an existing storyboard
  bench      [--model ID] [--concepts 8] [--storyboards 3] [--out DIR] [--allow-contention]
  registry                                                   model registry + local availability
  runtime    start|stop|status                               loopback-only Ollama server (stops only what it started)

Exit codes: 0 ok · 1 error · 2 bad input · 3 output produced but BLOCKED for review (claims need owner review)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..errors import PipelineError


def _load(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _prov(name: str):
    return None if name == "none" else name


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.intelligence", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("concepts", "storyboard", "demo"):
        s = sub.add_parser(name)
        s.add_argument("--brief"); s.add_argument("--request")
        s.add_argument("--provider", default="ollama", choices=["ollama", "mock", "none"])
        s.add_argument("--out", required=True); s.add_argument("--facts")
        if name in ("storyboard", "demo"):
            s.add_argument("--concepts"); s.add_argument("--concept"); s.add_argument("--pick", type=int, default=1)
            s.add_argument("--name"); s.add_argument("--repairs", type=int, default=2)
    f = sub.add_parser("facts"); f.add_argument("--brand", required=True); f.add_argument("--refresh", action="store_true")
    f.add_argument("--claim", action="append", default=[]); f.add_argument("--out")
    v = sub.add_parser("verify"); v.add_argument("--storyboard", required=True); v.add_argument("--brief"); v.add_argument("--brand", required=True)
    b = sub.add_parser("bench"); b.add_argument("--model"); b.add_argument("--concepts", type=int, default=8)
    b.add_argument("--storyboards", type=int, default=3); b.add_argument("--out", default="output/eval-llm")
    b.add_argument("--allow-contention", action="store_true"); b.add_argument("--force-memory", action="store_true")
    sub.add_parser("registry")
    r = sub.add_parser("runtime"); r.add_argument("action", choices=["start", "stop", "status"])
    a = ap.parse_args(argv)
    try:
        return _run(a)
    except PipelineError as e:
        _print({"ok": False, "error": e.to_dict()})
        return e.exit_code


def _run(a) -> int:
    from . import api
    from .bench import DEMO_BRIEF, DEMO_REQUEST
    if a.cmd in ("concepts", "storyboard", "demo"):
        brief = _load(a.brief) if a.brief else (DEMO_BRIEF if a.cmd == "demo" else None)
        if brief is None:
            raise PipelineError("--brief is required")
        request = a.request or (DEMO_REQUEST if a.cmd == "demo" and not a.brief else brief.pop("request", None) if isinstance(brief, dict) else None)
        if a.cmd == "concepts":
            res = api.generate_concepts(brief, request, provider=_prov(a.provider), out_dir=a.out, facts=a.facts)
            _print({"ok": True, "path": res["path"], "distinct": res["distinctness"]["all_distinct"], "files": res["files"],
                    "concepts": [{"id": c["id"], "name": c["name"], "pattern": c["pattern"], "hook": c["hook"], "source": c["source"]}
                                 for c in res["concepts"]], "brief_needs_review": [c["text"] for c in res["brief_claims"]["needs_review"]]})
            return 0
        if a.cmd == "demo" or (a.cmd == "storyboard" and not (a.concepts or a.concept)):
            res = api.generate_concepts(brief, request, provider=_prov(a.provider), out_dir=a.out, facts=a.facts)
            concept, b = res["concepts"][a.pick - 1], res["brief"]
        else:
            concept = _load(a.concept) if a.concept else _load(a.concepts)["concepts"][a.pick - 1]
            b = brief if not a.concepts else _load(a.concepts).get("brief", brief)
        sb, project, rep = api.build_storyboard(b, concept, request=request, provider=_prov(a.provider), out_dir=a.out,
                                                facts=a.facts, name=a.name, max_repairs=a.repairs)
        _print({"ok": True, "path": rep["path"], "concept": concept["id"], "review": rep["review"]["status"],
                "validation_errors": rep["check"]["errors"], "estimate_s": rep["check"]["estimate_s"],
                "needs_review": [c["text"] for c in rep["review"]["needs_review"]], "files": rep["files"]})
        return 3 if rep["review"]["blocking"] else 0
    if a.cmd == "facts":
        from .facts import load_facts, refresh
        fb = load_facts(a.brand)
        if not a.refresh:
            _print({"brand": fb.brand_id, "facts": len(fb.facts), "fetched_at": fb.fetched_at, "not_found": fb.not_found,
                    "categories": sorted({f["category"] for f in fb.facts})})
            return 0
        rep = refresh(fb, claims=a.claim, out_dir=a.out)
        _print(rep)
        return 0 if rep["status"] == "OK" else 3
    if a.cmd == "verify":
        from .brief import parse_brief
        from .claims import verify_storyboard
        from .facts import load_facts
        brief = parse_brief(_load(a.brief))[0] if a.brief else None
        rep = verify_storyboard(_load(a.storyboard), load_facts(a.brand), brief)
        _print({k: rep[k] for k in ("summary", "blocking", "needs_review")})
        return 3 if rep["blocking"] else 0
    if a.cmd == "bench":
        from .bench import run_bench
        from .registry import load_registry
        model = a.model or load_registry()["default"]
        res = run_bench(model, n_concepts=a.concepts, n_storyboards=a.storyboards, out_dir=a.out,
                        allow_contention=a.allow_contention, skip_if_low_memory=not a.force_memory)
        _print({"status": res["status"], "reason": res.get("reason"), "summary": res.get("summary"), "file": res["file"]})
        return 0 if res["status"] in ("OK", "SKIPPED") else 1
    if a.cmd == "registry":
        from .registry import with_local_availability
        _print(with_local_availability())
        return 0
    if a.cmd == "runtime":
        from .providers import OllamaRuntime
        rt = OllamaRuntime()
        _print(getattr(rt, a.action)())
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
