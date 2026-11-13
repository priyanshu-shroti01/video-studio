"""video-pipeline — production CLI.

Exit codes: 0 ok · 1 failure · 2 invalid input/config · 3 QA failed · 4 not found · 5 duplicate job ·
130 cancelled."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from . import __version__
from .config import config_hash, load_project
from .contract import CONTRACT_VERSION, ts_contract_version
from .errors import PipelineError
from .jobs import Registry
from .paths import OUTPUT_DIR, ROOT, ensure_dirs, free_gb, rel


def _out(args, obj, human: str | None = None):
    if args.json:
        print(json.dumps(obj, indent=1, default=str))
    elif human is not None:
        print(human)


def _err(msg: str):
    print(msg, file=sys.stderr)


def _ver(cmd: list[str]) -> str | None:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (p.stdout or p.stderr).strip().splitlines()[0] if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def cmd_doctor(a) -> int:
    from . import render as R
    from .system import host_info, mem_snapshot
    checks = []

    def chk(name, ok, detail, critical=True):
        checks.append({"check": name, "ok": bool(ok), "critical": critical, "detail": detail})

    for tool, cmd in (("node", ["node", "--version"]), ("npm", ["npm", "--version"]), ("ffmpeg", ["ffmpeg", "-version"]),
                      ("ffprobe", ["ffprobe", "-version"]), ("uv", ["uv", "--version"])):
        v = _ver(cmd)
        chk(tool, v, v or "not found")
    try:
        from .voice.registry import status as voice_status
        groups: dict[str, list] = {}
        for group, path, state in voice_status():          # sha256-verified model files, per engine
            groups.setdefault(group, []).append(state)
        for group, states in sorted(groups.items()):
            bad = [s_ for s_ in states if s_ != "ok"]
            chk(f"voice.{group}", not bad, f"{len(states)} files sha256-verified (local, offline)" if not bad
                else f"{len(bad)}/{len(states)} files {sorted(set(bad))}", critical=group == "kokoro")
    except Exception as e:  # noqa: BLE001
        chk("voice", False, f"voice registry unavailable: {e}")
    try:
        import edge_tts
        chk("edge-tts (legacy)", True, f"{edge_tts.__version__}: ONLINE Microsoft service, opt-in only "
            "(voice.allowOnline)", critical=False)
    except ImportError:
        chk("edge-tts (legacy)", True, "not installed (optional)", critical=False)
    chk("remotion", (ROOT / "node_modules/.bin/remotion").exists(), "node_modules/.bin/remotion")
    cp = R.chromium_path()
    chk("chromium", cp, rel(cp) if cp else "missing: run `npx remotion browser ensure`")
    vt = R.ffmpeg_has_videotoolbox()
    chk("encoder.videotoolbox", vt, "h264_videotoolbox test encode OK" if vt else "unavailable -> x264 fallback", False)
    chk("encoder.x264", "libx264" in (_ver(["ffmpeg", "-hide_banner", "-encoders"]) or "") or
        subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout.count("libx264") > 0,
        "software fallback")
    tv = ts_contract_version()
    chk("contract", tv == CONTRACT_VERSION, f"python v{CONTRACT_VERSION} / engine v{tv}")
    kit = ROOT / "audio/kit/catalog.json"
    chk("sfx.kit", kit.exists(), "audio/kit/catalog.json" if kit.exists() else "missing: bash scripts/sound-layer.sh kit", False)
    f = free_gb()
    chk("disk", f >= 5, f"{f:.1f} GB free", f >= 2)
    m = mem_snapshot()
    chk("memory", m.available_mb > 2000, f"{m.available_mb:.0f} MB available, swap used {m.swap_used_mb:.0f} MB", False)
    bench = R.BENCH_FILE.exists()
    chk("benchmark", bench, "tuned concurrency from benchmark" if bench else "not run yet (conservative default: 4 tabs)", False)
    h = host_info()
    ok = all(c["ok"] for c in checks if c["critical"])
    if a.json:
        _out(a, {"ok": ok, "host": h.__dict__, "checks": checks})
    else:
        print(f"video-pipeline {__version__} on {h.model} ({h.perf_cores}P+{h.eff_cores}E cores, {h.mem_gb} GB)")
        for c in checks:
            mark = "OK  " if c["ok"] else ("FAIL" if c["critical"] else "WARN")
            print(f"  {mark} {c['check']:<22} {c['detail']}")
    return 0 if ok else 1


def cmd_validate(a) -> int:
    cfg, warns = load_project(a.config)
    _out(a, {"ok": True, "name": cfg["name"], "hash": config_hash(cfg), "warnings": warns},
         f"OK {cfg['name']} ({len(cfg['storyboard']['scenes'])} scenes, formats {cfg['formats']})" +
         "".join(f"\n  WARN {w}" for w in warns))
    return 0


def cmd_create(a) -> int:
    cfg, warns = load_project(a.config)
    reg = Registry()
    job = reg.create(cfg["name"], config_hash(cfg), cfg, rel(ROOT / a.config) if not os.path.isabs(a.config) else a.config,
                     OUTPUT_DIR, force=a.force)
    for w in warns:
        reg.event(job["id"], "warn", None, w)
    _out(a, {"job_id": job["id"], "state": job["state"], "output_dir": rel(job["output_dir"]), "warnings": warns},
         f"created job {job['id']} -> {rel(job['output_dir'])}" + "".join(f"\n  WARN {w}" for w in warns))
    if a.run:
        a.job_id = job["id"]
        return cmd_render(a)
    return 0


def _runner(reg, jid, a):
    from .runner import JobRunner
    return JobRunner(reg, jid, echo=(lambda m: None) if a.json or a.quiet else (lambda m: print(m, file=sys.stderr)))


def _sigterm_to_interrupt(*_):
    raise KeyboardInterrupt


def cmd_render(a) -> int:
    import signal
    signal.signal(signal.SIGTERM, _sigterm_to_interrupt)  # graceful: job -> CANCELLED, children killed
    reg = Registry()
    reg.recover_stale()
    job = reg.get(a.job_id)
    t0 = time.time()
    try:
        _runner(reg, a.job_id, a).run()
    finally:
        job = reg.get(a.job_id)
    _out(a, {"job_id": job["id"], "state": job["state"], "qa": job["qa_status"], "seconds": round(time.time() - t0, 1),
             "output_dir": rel(job["output_dir"])},
         f"{job['id']}: {job['state']} (QA {job['qa_status']}) in {time.time() - t0:.0f}s -> {rel(job['output_dir'])}")
    return 0


def cmd_retry(a) -> int:
    reg = Registry()
    reg.recover_stale()
    job = reg.get(a.job_id)
    if job["state"] not in ("FAILED", "CANCELLED"):
        _err(f"job {a.job_id} is {job['state']}; only FAILED or CANCELLED jobs can be retried")
        return 2
    return cmd_render(a)


def cmd_qa(a) -> int:
    from .runner import run_qa_only
    reg = Registry()
    rep = run_qa_only(reg, a.job_id, echo=(lambda m: None) if a.json else (lambda m: print(m, file=sys.stderr)))
    _out(a, rep, f"QA {rep['status']}: " + ", ".join(f"{r['format']} {r['status']} {r['counts']}" for r in rep["formats"]))
    return 0 if rep["status"] != "FAIL" else 3


def cmd_cancel(a) -> int:
    reg = Registry()
    r = reg.request_cancel(a.job_id)
    _out(a, {"job_id": a.job_id, "result": r}, f"{a.job_id}: {r}")
    return 0


def cmd_status(a) -> int:
    reg = Registry()
    stale = reg.recover_stale()
    if a.job_id:
        job = reg.get(a.job_id)
        job.pop("config", None)
        job["stages"] = reg.stages(a.job_id)
        job["events"] = reg.events(a.job_id, limit=a.events)
        if a.json:
            _out(a, job)
        else:
            print(f"{job['id']}  {job['name']}  {job['state']}  stage={job['stage']}  progress={job['progress'] or 0:.0%}"
                  f"  QA={job['qa_status']}  attempts={job['attempts']}")
            for s in job["stages"]:
                print(f"  {s['stage']:<18} {s['status']:<8} {s['seconds'] or 0:6.1f}s")
            if job["error"]:
                print(f"  error: {job['error'].get('code')}: {job['error'].get('message')}")
            for e in job["events"][-a.events:]:
                print(f"  {time.strftime('%H:%M:%S', time.localtime(e['ts']))} {e['level']:<5} {e['message']}")
        return 0
    jobs = reg.list(a.limit)
    if a.json:
        _out(a, {"jobs": jobs, "recovered_stale": stale})
    else:
        for s in stale:
            print(f"recovered stale job {s} -> FAILED (retry it)")
        for j in jobs:
            print(f"{j['id']}  {j['state']:<17} {j['name']:<28} QA={j['qa_status'] or '-':<5} "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(j['created_at']))}")
    return 0


def cmd_clean(a) -> int:
    from .runner import clean
    items = clean(Registry(), dry_run=not a.yes)
    total = sum(s for _, s in items)
    _out(a, {"dry_run": not a.yes, "items": items, "bytes": total},
         "\n".join(f"  {'would remove' if not a.yes else 'removed'} {p} ({s / 1e6:.1f} MB)" for p, s in items) +
         f"\n{'DRY RUN: ' if not a.yes else ''}{len(items)} item(s), {total / 1e6:.1f} MB"
         + ("" if a.yes else "  (re-run with --yes to delete)"))
    return 0


def cmd_assets(a) -> int:
    from .assets import AssetRegistry
    ar = AssetRegistry(Registry())
    rep = ar.scan(a.roots)
    dups = ar.duplicates()
    rep["duplicates"] = dups
    _out(a, rep, f"registered {rep['registered']} assets; licences {rep['licenses']}; "
                 f"{len(rep['invalid'])} invalid; {len(dups)} duplicate group(s)" +
         "".join(f"\n  INVALID {x}" for x in rep["invalid"]) + "".join(f"\n  DUP {ps}" for _, ps in dups))
    return 1 if rep["invalid"] else 0


def cmd_benchmark(a) -> int:
    from .benchmark import run_benchmark
    rep = run_benchmark(formats=a.formats, workers=a.workers, seconds=a.seconds, repeats=a.repeats,
                        encoders=a.encoders, echo=(lambda m: None) if a.json else (lambda m: print(m, file=sys.stderr)))
    _out(a, rep, json.dumps(rep["recommended"], indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="video-pipeline", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check tools, encoders, Chromium, disk and memory")
    s = sub.add_parser("validate", help="validate a project config + storyboard (no side effects)")
    s.add_argument("config")
    s = sub.add_parser("create", help="register a job from a project config")
    s.add_argument("--config", required=True)
    s.add_argument("--force", action="store_true", help="allow an identical second production")
    s.add_argument("--run", action="store_true", help="run it immediately")
    for name, hlp in (("render", "run/resume a job through all stages"), ("retry", "retry a FAILED/CANCELLED job"),
                      ("qa", "re-run QA on a job's finished videos"), ("cancel", "cancel a queued or running job")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--job-id", required=True)
    s = sub.add_parser("status", help="list jobs or show one job")
    s.add_argument("--job-id")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--events", type=int, default=15)
    s = sub.add_parser("clean", help="remove regenerable intermediates (dry run by default)")
    s.add_argument("--dry-run", action="store_true", default=True)
    s.add_argument("--yes", action="store_true", help="actually delete")
    s = sub.add_parser("assets", help="scan + validate + licence-check asset folders")
    s.add_argument("roots", nargs="*", default=["public/brand", "public/fonts", "audio/music", "audio/kit"])
    s = sub.add_parser("benchmark", help="measure sustained render throughput on this machine")
    s.add_argument("--formats", nargs="+", default=["short", "landscape"])
    s.add_argument("--workers", nargs="+", type=int, default=[2, 4, 6, 8])
    s.add_argument("--encoders", nargs="+", default=["videotoolbox", "x264"])
    s.add_argument("--seconds", type=float, default=20)
    s.add_argument("--repeats", type=int, default=2)
    from . import cli_v3
    v3 = cli_v3.register(sub)
    a = p.parse_args(argv)
    ensure_dirs()
    try:
        return {"doctor": cmd_doctor, "validate": cmd_validate, "create": cmd_create, "render": cmd_render,
                "retry": cmd_retry, "qa": cmd_qa, "cancel": cmd_cancel, "status": cmd_status, "clean": cmd_clean,
                "assets": cmd_assets, "benchmark": cmd_benchmark, **v3}[a.cmd](a)
    except PipelineError as e:
        if a.json:
            print(json.dumps({"ok": False, "error": e.to_dict()}, indent=1))
        else:
            _err(f"error [{e.code}]: {e.message}")
            if e.detail:
                _err("  " + e.detail.strip().replace("\n", "\n  ")[-3000:])
        return e.exit_code
    except KeyboardInterrupt:
        _err("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
