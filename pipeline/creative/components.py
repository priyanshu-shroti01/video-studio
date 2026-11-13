"""Generated components: per-production store, human approval, and the brand component library.

  output/productions/<P>/components/<id>.json      every component the composer generated for the production's concepts,
                                                    with its scores, the template baseline and the alternates
  output/productions/<P>/components/selected.json  the components the selected concept's storyboard uses
  output/productions/<P>/components/decisions.json append-only log of human decisions (approve / reject)
  brands/<brand>/components/<name>.json            the brand library: designs a person approved. The director may reuse
                                                    them for later productions (subject to freshness)

Approving and rejecting are human decisions: the CLI needs `--reviewer` (the person) and every decision is written to
the registry's audit log. Nothing here approves on its own, and nothing is deleted or overwritten: an existing library
entry is never replaced (pick another `--name`)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..errors import NotFound, PipelineError
from ..paths import ROOT, atomic_write_json, rel, safe_name

BRANDS_DIR = ROOT / "brands"
RESERVED = {"selected.json", "decisions.json"}
DECISIONS = ("approve", "reject")


def library_dir(brand: str) -> Path:
    return BRANDS_DIR / safe_name(brand) / "components"


def library(brand: str) -> list[dict]:
    """Approved designs of a brand (sorted by name). Invalid files are skipped, never fatal."""
    d = library_dir(brand)
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(e, dict) and isinstance(e.get("design"), dict) and e.get("name"):
            out.append(e)
    return out


# ---- production store ------------------------------------------------------------------------------------
def save_generated(prod_dir: Path, brand: str, concepts: list[dict]) -> list[str]:
    """Write every generated component of the concepts to <prod>/components/<id>.json. -> written paths"""
    out_dir = Path(prod_dir) / "components"
    paths = []
    for c in concepts:
        for r in c.get("components", []):
            if not r.get("id"):
                continue
            rec = {**{k: v for k, v in r.items() if k != "recipe"}, "brand": brand, "production": Path(prod_dir).name,
                   "recipe": r.get("recipe")}
            p = out_dir / f"{safe_name(r['id'])}.json"
            atomic_write_json(p, rec)
            paths.append(rel(p))
    return paths


def save_selected(prod_dir: Path, concept: dict) -> None:
    ids = [r["id"] for r in concept.get("components", []) if r.get("selected") and r.get("id")]
    if ids or (Path(prod_dir) / "components").is_dir():
        atomic_write_json(Path(prod_dir) / "components" / "selected.json", {"concept": concept.get("id"), "components": ids})


def _prod_dir(production: str) -> tuple[Path, str]:
    from ..jobs import Registry
    from ..productions import Productions
    p = Productions(Registry()).get(production)
    return Path(p["dir"]), p["brand"]


def _decisions(d: Path) -> list[dict]:
    f = d / "components" / "decisions.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("decisions", []) if f.exists() else []
    except (OSError, ValueError):
        return []


def _used_in_storyboard(d: Path) -> set[str]:
    try:
        sb = json.loads((d / "storyboard.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {b.get("design", {}).get("component") for s in sb.get("scenes", []) for b in s.get("blocks", [])
            if b.get("type") == "composition"} - {None}


def list_components(production: str) -> list[dict]:
    d, _ = _prod_dir(production)
    cdir = d / "components"
    if not cdir.is_dir():
        return []
    dec = {}
    for x in _decisions(d):
        dec[x["component"]] = x
    used = _used_in_storyboard(d)
    out = []
    for f in sorted(cdir.glob("*.json")):
        if f.name in RESERVED:
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        last = dec.get(r.get("id"))
        out.append({"id": r.get("id"), "concept": r.get("concept"), "scene": r.get("scene"), "replaces": r.get("replaces"),
                    "design": r.get("design", {}).get("signature"), "total": (r.get("scores") or {}).get("total"),
                    "template_total": (r.get("template_score") or {}).get("total"), "selected_by_director": r.get("selected", False),
                    "in_storyboard": r.get("id") in used,
                    "decision": f"{last['decision']} by {last['reviewer']}" if last else "pending", "file": rel(f)})
    return out


def _load(d: Path, cid: str) -> dict:
    f = d / "components" / f"{safe_name(cid)}.json"
    if not f.exists() or f.name in RESERVED:
        raise NotFound(f"no generated component {cid!r} in {rel(d)}/components")
    return json.loads(f.read_text(encoding="utf-8"))


def _record(d: Path, entry: dict) -> None:
    f = d / "components" / "decisions.json"
    log = _decisions(d)
    log.append(entry)
    atomic_write_json(f, {"decisions": log})


def library_entry(rec: dict, name: str, reviewer: str, note: str) -> dict:
    d = rec["design"]
    from .composer import STRUCTURES
    return {"name": name, "design": {k: d[k] for k in ("structure", "variant", "motion", "signature")},
            "fits": list(STRUCTURES[d["structure"]].fits) if d["structure"] in STRUCTURES else [rec.get("content", {}).get("kind")],
            "params": rec.get("params") or {}, "canvas": rec.get("canvas"), "scores": rec.get("scores"),
            "example": rec.get("block"),
            "approval": {"production": rec.get("production"), "component": rec["id"], "concept": rec.get("concept"),
                         "scene": rec.get("scene"), "reviewer": reviewer, "note": note,
                         "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}}


def decide(production: str, cid: str, decision: str, reviewer: str, note: str = "", name: str | None = None) -> dict:
    """A named person approves (copy into the brand library) or rejects one generated component. Audited."""
    if decision not in DECISIONS:
        raise PipelineError(f"decision must be one of {DECISIONS}")
    if not reviewer or not reviewer.strip():
        raise PipelineError("a component decision needs the reviewer's name (--reviewer)")
    d, brand = _prod_dir(production)
    rec = _load(d, cid)
    if rec.get("brand") and rec["brand"] != brand:
        raise PipelineError(f"component {cid} belongs to brand {rec['brand']!r}, the production to {brand!r}")
    prev = [x for x in _decisions(d) if x["component"] == cid]
    if prev and prev[-1]["decision"] == decision:
        raise PipelineError(f"component {cid} is already {decision}d (by {prev[-1]['reviewer']})")
    from ..jobs import Registry
    out = {"component": cid, "decision": decision, "reviewer": reviewer.strip(), "note": note,
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if decision == "approve":
        lname = name or re.sub(r"[^a-z0-9-]+", "-", rec["design"]["signature"].lower()).strip("-")
        safe_name(lname)
        dest = library_dir(brand) / f"{lname}.json"
        if dest.exists():
            raise PipelineError(f"brand library already has {rel(dest)}; choose another --name (entries are never overwritten)")
        atomic_write_json(dest, library_entry(rec, lname, reviewer.strip(), note))
        out["library"] = rel(dest)
    _record(d, out)
    Registry().audit(reviewer.strip(), f"component.{decision}", production,
                     {"component": cid, "design": rec["design"].get("signature"), "note": note, **({"library": out["library"]} if "library" in out else {})})
    return out


# ---- CLI (registered by pipeline/cli_v3.py) ----------------------------------------------------------------
def register(sub) -> dict:
    c = sub.add_parser("component", help="generated components: list, or a person's approve / reject into the brand library")
    cs = c.add_subparsers(dest="ccmd", required=True)
    x = cs.add_parser("list")
    x.add_argument("--production", required=True)
    for name in DECISIONS:
        x = cs.add_parser(name, help=f"{name} a generated component (human decision, audited)")
        x.add_argument("--production", required=True); x.add_argument("--id", required=True)
        x.add_argument("--reviewer", required=True, help="the person making the decision"); x.add_argument("--note", default="")
        if name == "approve":
            x.add_argument("--name", help="library entry name (default: the design signature)")
    return {"component": cmd_component}


def cmd_component(a) -> int:
    if a.ccmd == "list":
        rows = list_components(a.production)
        if a.json:
            print(json.dumps(rows, indent=1))
        elif not rows:
            print(f"no generated components for {a.production} (brief option \"components\": \"generate\")")
        else:
            for r in rows:
                print(f"{r['id']}  {r['concept']}/{r['scene']}  {r['design']} (replaces {r['replaces']})  score {r['total']} vs "
                      f"template {r['template_total']}  {'IN STORYBOARD' if r['in_storyboard'] else 'selected' if r['selected_by_director'] else 'alternative'}"
                      f"  [{r['decision']}]")
        return 0
    res = decide(a.production, a.id, a.ccmd, a.reviewer, a.note, getattr(a, "name", None))
    print(json.dumps(res, indent=1) if a.json else f"{a.id}: {a.ccmd}d by {res['reviewer']}" + (f" -> {res['library']}" if "library" in res else ""))
    return 0
