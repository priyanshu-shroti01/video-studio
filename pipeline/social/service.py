"""Social service layer shared by the CLI (`video-pipeline social ...`) and the MCP server.
Read-only helpers never touch the network; drafting uses the local LLM only; publishing goes through
pipeline.publishing.publish() and therefore gate()."""
from __future__ import annotations

import json
from pathlib import Path

from ..errors import PipelineError
from ..paths import rel
from ..productions import Productions
from . import brandcfg, routing

LISTED_STATES = ("QA_COMPLETE", "AWAITING_APPROVAL", "APPROVED", "PUBLISHING", "PUBLISHED")


def _prod(prod: Productions | None) -> Productions:
    return prod or Productions()


def _check_brand(p: dict, brand_id: str | None) -> None:
    if brand_id and brand_id != p["brand"]:
        raise brandcfg.AccountMismatch(f"production {p['id']} belongs to brand {p['brand']!r}, not {brand_id!r}")


def _job_out(prod: Productions, p: dict) -> Path | None:
    if not p.get("job_id"):
        return None
    try:
        return Path(prod.reg.get(p["job_id"])["output_dir"])
    except PipelineError:
        return None


def list_publishable(brand_id: str | None = None, prod: Productions | None = None, limit: int = 200) -> dict:
    """Productions that have a rendered package, grouped by brand (offline)."""
    prod = _prod(prod)
    groups: dict[str, dict] = {}
    for row in prod.list(limit):
        if row["state"] not in LISTED_STATES or (brand_id and row["brand"] != brand_id):
            continue
        p = prod.get(row["id"])
        out = _job_out(prod, p)
        fmts = sorted(f.stem.removeprefix("final-") for f in (out / "video").glob("final-*.mp4")) if out else []
        meta = None
        if out and (out / "publishing/metadata.json").exists():
            try:
                d = json.loads((out / "publishing/metadata.json").read_text())
                meta = {"version": d.get("version"), "source": d.get("source"),
                        "validation": (d.get("validation") or {}).get("status")}
            except ValueError:
                meta = {"error": "unreadable"}
        with prod.reg.conn() as c:
            pubs = [dict(r) for r in c.execute("SELECT platform,status,remote_id FROM publications WHERE production_id=? "
                                               "AND platform!='export' ORDER BY id", (row["id"],))]
        g = groups.setdefault(row["brand"], {"brand": row["brand"], "accounts": _accounts(row["brand"]), "productions": []})
        g["productions"].append({"id": row["id"], "name": row["name"], "state": row["state"], "formats": fmts,
                                 "metadata": meta, "publications": pubs,
                                 "publishable_now": row["state"] in ("APPROVED", "PUBLISHED")})
    return {"brands": list(groups.values())}


def _accounts(brand: str) -> dict:
    try:
        return brandcfg.account_status(brand)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def plan_platforms(pid: str, prod: Productions | None = None) -> dict:
    prod = _prod(prod)
    p = prod.get(pid)
    out = _job_out(prod, p)
    if not out:
        raise PipelineError(f"production {pid} has no render job yet")
    plans = {}
    for v in sorted((out / "video").glob("final-*.mp4")):
        fmt = v.stem.removeprefix("final-")
        try:
            plans[fmt] = routing.plan_file(v, fmt)
            plans[fmt]["video"]["path"] = rel(v)
        except routing.ProbeError as e:
            plans[fmt] = {"format": fmt, "error": e.message}
    return {"production": pid, "brand": p["brand"], "state": p["state"], "plans": plans,
            "accounts": _accounts(p["brand"]),
            "note": "Routing is computed from the real files (ffprobe). Publishing still needs human approval and an "
                    "explicit request per platform."}


def draft_metadata(pid: str, *, brand_id: str | None = None, provider: str = "ollama", keyword: str | None = None,
                   publish_at: str | None = None, set_thumbnail: bool = False, prod: Productions | None = None) -> dict:
    from .metadata import draft
    prod = _prod(prod)
    _check_brand(prod.get(pid), brand_id)
    return draft(prod, pid, provider=provider, keyword=keyword, publish_at=publish_at, set_thumbnail=set_thumbnail)


def keyword_research(*, production_id: str | None = None, brand_id: str | None = None, extra_seeds: list[str] | None = None,
                     use_youtube_api: bool = False, prod: Productions | None = None, http=None) -> dict:
    from .keywords import research
    product = None
    if production_id:
        p = _prod(prod).get(production_id)
        _check_brand(p, brand_id)
        brand_id = p["brand"]
        product = (p.get("brief") or {}).get("product")     # used locally to pick the seed list; never sent
    if not brand_id:
        raise PipelineError("keyword research needs a production_id or a brand_id")
    return research(brand_id, product=product, extra_seeds=extra_seeds, use_api=use_youtube_api, http=http)


def publication_status(pid: str, prod: Productions | None = None) -> dict:
    prod = _prod(prod)
    p = prod.get(pid)
    with prod.reg.conn() as c:
        pubs = [dict(r) for r in c.execute("SELECT id,platform,status,content_hash,remote_id,created_at,finished_at,error "
                                           "FROM publications WHERE production_id=? ORDER BY id", (pid,))]
        appr = [dict(r) for r in c.execute("SELECT id,decision,reviewer,created_at,invalidated_at,invalidated_reason "
                                           "FROM approvals WHERE production_id=? ORDER BY id", (pid,))]
    valid = None
    if p.get("job_id") and p["state"] in ("APPROVED", "PUBLISHING", "PUBLISHED"):
        a = prod.current_approval(pid)
        valid = bool(a and a["valid"])
    open_flags = [{"id": f["id"], "severity": f["severity"], "kind": f["kind"], "message": f["message"][:200]}
                  for f in prod.flags(pid, "open")]
    return {"production": pid, "brand": p["brand"], "state": p["state"], "approval_valid": valid, "approvals": appr,
            "publications": pubs, "open_flags": open_flags}


def publish(pid: str, platform: str, fmt: str, actor: str, *, brand_id: str | None = None,
            prod: Productions | None = None, adapter=None) -> dict:
    """Human-requested publish (the caller must have been asked by the person to publish THIS production to
    THIS platform). Goes through publishing.publish -> gate()."""
    from .. import publishing
    prod = _prod(prod)
    _check_brand(prod.get(pid), brand_id)
    return publishing.publish(prod, pid, platform, fmt, confirm=True, actor=actor, adapter=adapter)
