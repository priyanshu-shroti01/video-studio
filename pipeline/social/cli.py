"""`video-pipeline social ...`: routing plans, metadata drafting, keyword research, publication status,
account status and the Instagram token refresh. Publishing itself stays in `video-pipeline publish`."""
from __future__ import annotations

import json


def register(sub) -> dict:
    s = sub.add_parser("social", help="platform routing, YouTube/Instagram metadata, keyword research")
    ss = s.add_subparsers(dest="scmd", required=True)
    x = ss.add_parser("plan", help="which platforms each rendered video can go to, and why (offline)")
    x.add_argument("--id", required=True)
    x = ss.add_parser("draft", help="write publishing/metadata.json before approval (local LLM or template)")
    x.add_argument("--id", required=True)
    x.add_argument("--provider", default="ollama", choices=["ollama", "template", "mock"])
    x.add_argument("--keyword", help="primary search keyword (default: the brand profile's product keyword)")
    x.add_argument("--publish-at", help="YouTube schedule, ISO 8601 with timezone (forces privacy private)")
    x.add_argument("--set-thumbnail", action="store_true", help="also set publishing/thumbnail.png via thumbnails.set")
    x.add_argument("--reopen-review", action="store_true",
                   help="withdraw a valid approval first (a human decision; needs --actor)")
    x.add_argument("--actor", default="")
    x = ss.add_parser("keywords", help="search-demand research (NETWORK, opt-in): sends only generic seed phrases")
    x.add_argument("--id")
    x.add_argument("--brand")
    x.add_argument("--seed", action="append", default=[], help="extra generic seed phrase (lowercase words)")
    x.add_argument("--youtube-api", action="store_true", help="also use YouTube Data API search.list (needs api_key)")
    x.add_argument("--network", action="store_true", help="required: confirms you want to send the seeds online")
    x = ss.add_parser("status", help="approvals and publications of a production")
    x.add_argument("--id", required=True)
    x = ss.add_parser("list", help="publishable productions grouped by brand")
    x.add_argument("--brand")
    x = ss.add_parser("accounts", help="expected accounts and whether credentials exist (offline, no secrets shown)")
    x.add_argument("--brand", required=True)
    x = ss.add_parser("token-refresh", help="extend the brand's long-lived Instagram token (NETWORK)")
    x.add_argument("--brand", required=True)
    return {"social": cmd_social}


def _p(a, obj, human: str | None = None) -> None:
    print(json.dumps(obj, indent=1, default=str, ensure_ascii=False) if a.json or human is None else human)


def cmd_social(a) -> int:
    from . import service
    if a.scmd == "plan":
        res = service.plan_platforms(a.id)
        lines = [f"{res['production']} ({res['brand']}, {res['state']})"]
        for fmt, pl in res["plans"].items():
            if "error" in pl:
                lines.append(f"  {fmt}: {pl['error']}")
                continue
            v = pl["video"]
            lines.append(f"  {fmt}: {v['width']}x{v['height']} {v['duration_s']:.1f}s {v['orientation']}")
            lines += [f"    -> {d['platform']} ({d['kind']}): {d['reason']}" for d in pl["destinations"]]
            lines += [f"    x  {r['platform']}: {'; '.join(r['reasons'])}" for r in pl["rejected"]]
            lines += [f"    ! {s}" for s in pl["suggestions"]]
        _p(a, res, "\n".join(lines))
    elif a.scmd == "draft":
        if a.reopen_review:
            from ..productions import Productions
            from .metadata import reopen_review
            reopen_review(Productions(), a.id, a.actor)
        res = service.draft_metadata(a.id, provider=a.provider, keyword=a.keyword, publish_at=a.publish_at,
                                     set_thumbnail=a.set_thumbnail)
        v = res["validation"]
        lines = [f"metadata v{res['version']} ({res['source']}) -> {res['path']}  validation {v['status']}"]
        for fmt, f in res["formats"].items():
            lines.append(f"  {fmt}: YouTube \"{f['youtube_title']}\"; Instagram "
                         f"{'caption drafted' if f['instagram'] else 'not routed: ' + '; '.join(f['instagram_refused'] or [])}")
            for plat in ("youtube", "instagram"):
                r = v["formats"].get(fmt, {}).get(plat)
                if r:
                    lines += [f"    {plat} ERROR {e}" for e in r["errors"]] + [f"    {plat} warn  {w}" for w in r["warnings"]]
        lines.append("Nothing was published. The metadata is part of the approval package: review it, then approve.")
        _p(a, res, "\n".join(lines))
    elif a.scmd == "keywords":
        if not a.network:
            print("keyword research sends generic seed phrases to Google/YouTube; re-run with --network to confirm")
            return 2
        res = service.keyword_research(production_id=a.id, brand_id=a.brand, extra_seeds=a.seed,
                                       use_youtube_api=a.youtube_api)
        lines = ["outgoing queries:"] + [f"  {q['url']}" for q in res["queries"]]
        lines += ["top phrases:"] + [f"  {r['phrase']} (seeds {r['seeds']}, pos {r['best_position']})" for r in res["ranked"][:15]]
        lines += [f"note: {n}" for n in res["notes"]]
        _p(a, res, "\n".join(lines))
    elif a.scmd == "status":
        _p(a, service.publication_status(a.id))
    elif a.scmd == "list":
        res = service.list_publishable(a.brand)
        lines = []
        for g in res["brands"]:
            lines.append(f"[{g['brand']}]")
            for p in g["productions"]:
                m = p["metadata"] or {}
                lines.append(f"  {p['id']}  {p['state']:<17} {','.join(p['formats']):<16} metadata="
                             f"{m.get('validation', 'none')}  {p['name']}")
        _p(a, res, "\n".join(lines) or "nothing rendered yet")
    elif a.scmd == "accounts":
        from .brandcfg import account_status
        _p(a, account_status(a.brand))
    elif a.scmd == "token-refresh":
        from .instagram import refresh_token
        _p(a, refresh_token(a.brand))
    return 0
