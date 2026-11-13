"""CLI for the hybrid creative engine.

    python -m pipeline.creative demo --brief projects/<brand>/briefs/<name>.json --out output/creative-eval/<name> [--provider none|mock|ollama] [--pick c2]
    python -m pipeline.creative templates [--brand <id>] [--product "WordPress Hosting"]

`demo` writes concepts.json / concepts.md, then the selected concept's storyboard, project config and reports
(claims, review, creative-plan, rules + sync, copy-sources, storyboard-preview.md). Exit code 3 = produced but
BLOCKED for review (e.g. the brief price is not a verified price)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..errors import PipelineError


def _demo(a) -> int:
    from . import build_storyboard, generate_concepts
    brief = json.loads(Path(a.brief).read_text(encoding="utf-8"))
    provider = a.provider or brief.get("provider") or "ollama"
    out = Path(a.out)
    res = generate_concepts(brief, brief.get("request"), provider=provider, out_dir=out)
    if not res["concepts"]:
        print("no concept passed the rules:", json.dumps(res["rejected"], indent=1, ensure_ascii=False))
        return 2
    pick = a.pick or res["recommended"]
    concept = next((c for c in res["concepts"] if c["id"] == pick), None)
    if concept is None:
        print(f"no concept {pick!r}; available {[c['id'] for c in res['concepts']]}")
        return 2
    sb, project, rep = build_storyboard(res["brief"], concept, provider=provider, out_dir=out)
    m = rep["price"].get("mismatch")
    print(f"brand {rep['brand']} · industry {rep['industry']} · provider {rep['provider'].get('provider')} · path {rep['path']}")
    print(f"concepts: " + "; ".join(f"{c['id']} {c['name']} [{' → '.join(c['templates'])}]" for c in res["concepts"]))
    print(f"selected {concept['id']} {concept['name']}: {len(sb['scenes'])} scenes, est {rep['check']['estimate_s']} s")
    if m:
        print(f"PRICE: brief {m['brief_price']} is not verified -> using {m['plan']} {m['used_price']} ({m['fact_id']})")
    bad = [r for r in rep["rules"] if r["status"] == "FAIL"]
    warn = [r for r in rep["rules"] if r["status"] == "WARN"]
    print(f"rules: {len(rep['rules']) - len(bad) - len(warn)}/{len(rep['rules'])} PASS" + (f"; FAIL {[r['id'] for r in bad]}" if bad else "")
          + (f"; WARN {[r['id'] for r in warn]}" if warn else ""))
    print("copy: " + ", ".join(f"{k}={v['narration']}" for k, v in rep["copy_sources"].items()))
    print(f"review: {rep['review']['status']}")
    for r in rep["review"]["reasons"][:5]:
        print("  -", r)
    print("files:", ", ".join(Path(f).name for f in list(res["files"].values()) + list(rep["files"].values())), "in", out)
    return 3 if rep["review"]["blocking"] else 0


def _templates(a) -> int:
    from ..intelligence.brief import parse_brief
    from ..intelligence.facts import load_facts
    from .director import studio
    b, _ = parse_brief({"brand": a.brand, "product": a.product, **({"brand_id": a.brand_id} if a.brand_id else {})})
    st = studio(b, load_facts(b["brand_id"]))
    for t in st.lib.values():
        kind = "generic" if t.generic else st.pack.id
        print(f"{t.id:26} {kind:12} {t.role:8} hero={t.hero:16} support={t.support:13} backdrops={'/'.join(t.backdrops):16} "
              f"{'available' if t.available(st.pf) else '-'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.creative")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="brief -> 3 concepts -> selected storyboard + reports")
    d.add_argument("--brief", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--provider", choices=["none", "mock", "ollama"])
    d.add_argument("--pick", help="concept id (default: the recommended one)")
    t = sub.add_parser("templates", help="list the template catalogue for a brand + product")
    t.add_argument("--brand", required=True, help="brand name as in the brief, e.g. 'ACME Hosting'")
    t.add_argument("--brand-id", dest="brand_id")
    t.add_argument("--product", required=True)
    a = ap.parse_args(argv)
    try:
        return _demo(a) if a.cmd == "demo" else _templates(a)
    except PipelineError as e:
        print(f"error: {e.message}" + (f"\n{e.detail}" if getattr(e, "detail", None) else ""), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
