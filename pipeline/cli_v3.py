"""v0.3.0 CLI commands: productions, review/approval, export/publish, backup, scheduler, music.
Registered by pipeline/cli.py. Approval and publishing always need a named human (--reviewer/--actor)
and publishing needs --confirm; nothing here publishes on its own."""
from __future__ import annotations

import json
from pathlib import Path


def register(sub) -> dict:
    s = sub.add_parser("production", help="brief -> concepts -> storyboard -> preview -> render -> approval")
    ps = s.add_subparsers(dest="pcmd", required=True)
    x = ps.add_parser("create"); x.add_argument("--brief", required=True)
    x.add_argument("--brand", help="brand id (default: resolved from the brief's brand name or domain)")
    x.add_argument("--name")
    for name in ("concepts", "preview", "show", "run-job"):
        x = ps.add_parser(name); x.add_argument("--id", required=True)
    x = ps.add_parser("select"); x.add_argument("--id", required=True); x.add_argument("--concept", required=True)
    x = ps.add_parser("render"); x.add_argument("--id", required=True); x.add_argument("--wait", action="store_true")
    x.add_argument("--skip-preview-review", metavar="REASON", help="render without a human preview approval (audited, "
                                                                   "adds a blocking review flag)")
    x.add_argument("--actor", default="operator")
    x = ps.add_parser("approve-preview"); x.add_argument("--id", required=True); x.add_argument("--reviewer", required=True)
    x.add_argument("--note", default="")
    x = ps.add_parser("list"); x.add_argument("--limit", type=int, default=20)

    r = sub.add_parser("review", help="list or resolve review flags")
    rs = r.add_subparsers(dest="rcmd", required=True)
    x = rs.add_parser("flags"); x.add_argument("--id", required=True)
    x = rs.add_parser("resolve"); x.add_argument("--id", required=True); x.add_argument("--flag", type=int, required=True)
    x.add_argument("--reviewer", required=True); x.add_argument("--note", required=True)

    x = sub.add_parser("approve", help="explicit human approval of the current package")
    x.add_argument("--id", required=True); x.add_argument("--reviewer", required=True); x.add_argument("--note", default="")
    x.add_argument("--package-hash", help="hash you reviewed (from APPROVAL_PACKAGE.md); refuses if it changed")
    for name in ("reject", "request-changes"):
        x = sub.add_parser(name); x.add_argument("--id", required=True); x.add_argument("--reviewer", required=True)
        x.add_argument("--note", required=True)
    x = sub.add_parser("export", help="ready-to-upload package for an APPROVED production (no network)")
    x.add_argument("--id", required=True); x.add_argument("--format", default="short"); x.add_argument("--actor", default="operator")
    x = sub.add_parser("publish", help="upload an APPROVED production to a configured platform (needs --confirm)")
    x.add_argument("--id", required=True); x.add_argument("--platform", required=True, choices=["youtube", "instagram", "export"])
    x.add_argument("--format", default="short"); x.add_argument("--actor", required=True)
    x.add_argument("--confirm", action="store_true")
    x = sub.add_parser("studio", help="start the local Video Studio (127.0.0.1 only)")
    x.add_argument("--port", type=int, default=8765); x.add_argument("--open", action="store_true")
    x.add_argument("--new-token", action="store_true", help="rotate the session token (logs out open browser tabs)")
    sub.add_parser("backup", help="online backup of the job registry")
    sub.add_parser("scheduler", help="show the heavy-workload queue")
    x = sub.add_parser("music", help="list the licensed music library")
    x.add_argument("--verify", action="store_true")
    x = sub.add_parser("archive", help="hide productions/jobs from lists and the dashboard; files move to output/_archive (reversible)")
    x.add_argument("--production", action="append", default=[]); x.add_argument("--job", action="append", default=[])
    x.add_argument("--all-except", action="append", default=[], metavar="PRODUCTION", help="archive everything except these productions")
    x.add_argument("--actor", required=True, help="the person asking for it"); x.add_argument("--note", default="")
    sub.add_parser("video-out", help="refresh video-out/ (finished videos by brand: for-review / approved)")
    b = sub.add_parser("brand", help="list brands, or onboard a new website as a draft brand")
    bs = b.add_subparsers(dest="bcmd", required=True)
    x = bs.add_parser("list"); x.add_argument("--all", action="store_true", help="include hidden test brands")
    x = bs.add_parser("init", help="draft brands/<id> + facts skeleton from the site's home page (never overwrites)")
    x.add_argument("--id", required=True); x.add_argument("--site", required=True); x.add_argument("--name")
    x.add_argument("--industry", default="general", help="e.g. web-hosting (selects the creative template pack)")
    return {"production": cmd_production, "review": cmd_review, "approve": cmd_approve, "reject": cmd_decide,
            "request-changes": cmd_decide, "export": cmd_export, "publish": cmd_publish, "backup": cmd_backup,
            "scheduler": cmd_scheduler, "music": cmd_music, "studio": cmd_studio, "brand": cmd_brand, "archive": cmd_archive, "video-out": cmd_video_out, **_social_register(sub),
            **_component_register(sub)}


def _component_register(sub) -> dict:
    from .creative import components          # `video-pipeline component list|approve|reject` (human decisions, audited)
    return components.register(sub)


def _social_register(sub) -> dict:
    from .social import cli as social_cli          # `video-pipeline social ...` (pipeline/social/cli.py)
    return social_cli.register(sub)


def _print(a, obj, human=None):
    print(json.dumps(obj, indent=1, default=str) if a.json or human is None else human)


def cmd_production(a) -> int:
    from . import api
    if a.pcmd == "create":
        brief = json.loads(Path(a.brief).read_text())
        from .brands import resolve_brand
        p = api.create_production(a.brand or resolve_brand(brief.get("brand", "")), brief, a.name)
        _print(a, p, f"created production {p['id']} ({p['state']}) -> {p['dir']}")
    elif a.pcmd == "concepts":
        res = api.generate_concepts(a.id)
        _print(a, res, "\n".join(f"  {c['id']}: {c.get('name') or c.get('title', '')} [{c.get('pattern', '')}]\n"
                                 f"      hook: {(c.get('hook') or {}).get('text', c.get('hook', '')) if isinstance(c.get('hook'), dict) else c.get('hook', '')}"
                                 for c in res.get("concepts", [])) or json.dumps(res)[:500])
    elif a.pcmd == "select":
        res = api.select_concept(a.id, a.concept)
        _print(a, {"scenes": len(res["storyboard"]["scenes"]), "reports": list(res["reports"])},
               f"storyboard ready: {len(res['storyboard']['scenes'])} scenes")
    elif a.pcmd == "preview":
        res = api.preview(a.id)
        g = res["gate"]
        _print(a, res, f"preview: {res['contact_sheet']} ({len(res['stills'])} stills, {res['seconds']}s)\n"
                       f"quality gate: {g['status']}\n" + "\n".join(f"  {c['status']:<4} {c['id']}: {c['detail'][:140]}"
                                                                   for c in g["checks"]))
    elif a.pcmd == "approve-preview":
        res = api.approve_preview(a.id, a.reviewer, a.note)
        _print(a, res, f"preview approved by {a.reviewer} (gate {res['gate']}); full render allowed for this storyboard")
    elif a.pcmd == "render":
        res = api.start_render(a.id, wait=a.wait, skip_preview_review=a.skip_preview_review, actor=a.actor)
        _print(a, res, f"render job {res['job_id']} {'finished' if a.wait else 'started in background'}")
    elif a.pcmd == "run-job":
        api.run_production_job(a.id)
    elif a.pcmd == "show":
        p = api.production(a.id)
        if a.json:
            _print(a, p)
        else:
            print(f"{p['id']}  {p['brand']}  {p['name']}  state={p['state']}  job={p['job_id']}  approval_valid={p['approval_valid']}")
            for f in p["flags"]:
                print(f"  [{'x' if f['status'] == 'resolved' else ' '}] #{f['id']} {f['severity']:<8} {f['kind']}: {f['message'][:110]}")
    elif a.pcmd == "list":
        from .productions import Productions
        for p in Productions().list(a.limit):
            print(f"{p['id']}  {p['state']:<18} {p['brand']:<12} {p['name']}")
    return 0


def cmd_review(a) -> int:
    from .productions import Productions
    prod = Productions()
    if a.rcmd == "flags":
        fl = prod.flags(a.id)
        _print(a, fl, "\n".join(f"#{f['id']} [{f['status']}] {f['severity']} {f['kind']}: {f['message']}" for f in fl))
    else:
        prod.resolve_flag(a.id, a.flag, a.reviewer, a.note)
        print(f"flag #{a.flag} resolved by {a.reviewer}")
    return 0


def cmd_approve(a) -> int:
    from .productions import Productions
    res = Productions().approve(a.id, a.reviewer, a.note, expected_hash=a.package_hash)
    _print(a, res, f"APPROVED by {a.reviewer} (package {res['package_hash'][:16]}…). Nothing was published.")
    return 0


def cmd_decide(a) -> int:
    from .productions import Productions
    decision = "REJECTED" if a.cmd == "reject" else "CHANGES_REQUESTED"
    Productions().decide(a.id, decision, a.reviewer, a.note)
    print(f"{a.id}: {decision}")
    return 0


def cmd_export(a) -> int:
    from . import publishing
    from .productions import Productions
    res = publishing.export(Productions(), a.id, a.format, a.actor)
    _print(a, res, f"export package: {res['dir']} (+ {res['zip']}). Nothing was uploaded.")
    return 0


def cmd_publish(a) -> int:
    from . import publishing
    from .productions import Productions
    res = publishing.publish(Productions(), a.id, a.platform, a.format, confirm=a.confirm, actor=a.actor)
    _print(a, res, json.dumps(res))
    return 0


def cmd_backup(a) -> int:
    from .jobs import db_path
    from .migrations import backup
    p = backup(db_path(), "manual")
    _print(a, {"backup": str(p)}, f"backup written: {p}")
    return 0


def cmd_scheduler(a) -> int:
    from .jobs import Registry
    from .scheduler import load_config, queue
    q = queue(Registry())
    _print(a, {"config": load_config(), "queue": q},
           "\n".join(f"{r['state']:<8} {r['kind']:<10} p{r['priority']} pid={r['pid']} {r['job_ref']}" for r in q) or "idle")
    return 0


def cmd_music(a) -> int:
    from .music import tracks, verify_library
    ts = tracks()
    if a.verify:
        probs = verify_library()
        _print(a, {"problems": probs}, "music library OK" if not probs else "\n".join(probs))
        return 1 if probs else 0
    _print(a, ts, "\n".join(f"{'OK ' if t.get('publishable') and t.get('brandSafe', True) else 'NO '} "
                            f"{','.join(t.get('moods') or []):<28} {t['file'][:48]:<48} {t['license']}" for t in ts))
    return 0


def cmd_archive(a) -> int:
    from . import archive as AR
    from .jobs import Registry
    from .video_out import sync
    reg = Registry()
    if not (a.production or a.job or a.all_except):
        raise SystemExit("nothing to archive: pass --production, --job or --all-except")
    res = {"productions": [], "jobs": [], "skipped": []}
    if a.all_except:
        res = AR.archive_all_except(reg, a.all_except, a.actor, a.note)
    for p in a.production:
        res["productions"].append(AR.archive_production(reg, p, a.actor, a.note))
    for j in a.job:
        res["jobs"].append(AR.archive_job(reg, j, a.actor, a.note))
    vo = sync(reg)
    _print(a, {**res, "video_out": vo},
           f"archived {len(res['productions'])} production(s) and {len(res['jobs'])} loose job(s) -> output/_archive/ "
           f"({AR.archive_size_mb()} MB there; delete it for good with: rm -rf output/_archive)"
           + "".join(f"\n  skipped {x}" for x in res.get("skipped", []))
           + f"\nvideo-out: {len(vo['videos'])} video(s)")
    return 0


def cmd_video_out(a) -> int:
    from .video_out import sync
    r = sync()
    _print(a, r, "video-out/\n" + "\n".join(f"  {v}" for v in r["videos"]) if r["videos"] else "video-out/ (no finished videos)")
    return 0


def cmd_brand(a) -> int:
    from . import api
    if a.bcmd == "list":
        rows = api.brand_overview(include_hidden=a.all)
        _print(a, rows, "\n".join(f"  {b['id']:<14} {b['name']:<22} {b['status']:<6} facts={b['facts']:<4} "
                                   f"youtube={'yes' if b['accounts']['youtube'] else 'no'} instagram={'yes' if b['accounts']['instagram'] else 'no'}"
                                   + (f"  ! {'; '.join(b['review'])}" if b["review"] else "") for b in rows))
        return 0
    from .brand_init import init_brand
    r = init_brand(a.id, a.site, a.name, a.industry)
    _print(a, r, f"drafted brand {r['brand']} ({r['name']}) from {r['site']}\n  files: {', '.join(r['files'])}\n"
                 + "".join(f"  review: {x}\n" for x in r["review"])
                 + (f"  validation errors: {r['validation_errors']}\n" if r["validation_errors"] else "")
                 + f"  next: verify facts with `uv run python -m pipeline.intelligence facts --brand {r['brand']} --refresh`")
    return 0


def cmd_studio(a) -> int:
    from studio import serve
    serve(a.port, open_browser=a.open, new_token=a.new_token)
    return 0
