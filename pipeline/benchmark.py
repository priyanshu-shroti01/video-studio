"""Sustained-throughput benchmark for this machine.

Optimises for *sustained* frames/second WITHOUT memory swapping or Chromium instability — not for
the largest worker count. For each (format, encoder, Chromium tabs) we render a realistic storyboard
segment several times back-to-back and record wall time, frames/s, peak RSS of the whole process
tree, swap growth, page-outs and failures. A configuration is eligible only if every run succeeded,
swap did not grow, and page-outs stayed negligible; the recommendation is the eligible configuration
whose *worst* run is fastest, then nudged down one step if it is within 5% of a smaller setting
(headroom is worth more than a marginal gain)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import render as R
from .errors import PipelineError
from .paths import ROOT, STATE_DIR, atomic_write_json, sha256_file
from .system import host_info, mem_snapshot

HEADROOM_RULE = 0.90
FIXTURES = {"short": ROOT / "src/engine/fixtures/sample-short.json",
            "landscape": ROOT / "src/engine/fixtures/sample-landscape.json"}


def run_benchmark(*, formats, workers, seconds, repeats, encoders, echo=print) -> dict:
    bundle = R.ensure_bundle(echo)
    R.ensure_chromium()
    work = STATE_DIR / "bench"
    work.mkdir(parents=True, exist_ok=True)
    results = []
    for fmt in formats:
        props_f = FIXTURES[fmt]
        props = json.loads(props_f.read_text())
        frames = min(int(seconds * props["fps"]), props["durationInFrames"])
        for enc in encoders:
            for w in workers:
                runs = []
                for rep in range(repeats):
                    out = work / f"{fmt}-{enc}-{w}-{rep}.mp4"
                    chunks = work / f"chunks-{fmt}-{enc}-{w}-{rep}"
                    s = R.RenderSettings(encoder=enc, concurrency=w, chunk_frames=frames, retries=0,
                                         stall_timeout=180, timeout_per_chunk=1800)
                    m0 = mem_snapshot()
                    t0 = time.time()
                    ok, err, rss = True, None, 0.0
                    try:
                        r = R.render_format(props_file=props_f, props_hash=f"bench-{time.time()}", fmt=fmt,
                                            total_frames=frames, fps=props["fps"], out=out, chunks_dir=chunks, s=s,
                                            bundle=bundle, should_cancel=lambda: False, log=lambda m: None)
                        rss = max(c.peak_rss_mb for c in r.chunks)
                        enc_used = r.encoder
                    except PipelineError as e:
                        ok, err, enc_used = False, e.message, enc
                    dt = time.time() - t0
                    m1 = mem_snapshot()
                    run = {"ok": ok, "seconds": round(dt, 2), "fps": round(frames / dt, 2) if ok else 0,
                           "peak_rss_mb": round(rss), "swap_delta_mb": round(m1.swap_used_mb - m0.swap_used_mb, 1),
                           "pageouts_delta": m1.pageouts - m0.pageouts, "available_mb_after": round(m1.available_mb),
                           "encoder_used": enc_used, "error": err}
                    runs.append(run)
                    echo(f"{fmt:<9} {enc:<12} tabs={w:<2} run {rep + 1}: "
                         + (f"{run['fps']:6.1f} fps  {dt:5.1f}s  rss {run['peak_rss_mb']:5d} MB  "
                            f"swapΔ {run['swap_delta_mb']:+.0f} MB  pageoutsΔ {run['pageouts_delta']}" if ok else f"FAILED: {err}"))
                    for f in (out,):
                        f.unlink(missing_ok=True)
                    for f in chunks.glob("*"):
                        f.unlink()
                    chunks.rmdir()
                    time.sleep(2)  # let memory settle between runs
                eligible = all(r["ok"] for r in runs) and all(r["swap_delta_mb"] <= 16 for r in runs) and \
                    all(r["pageouts_delta"] <= 500 for r in runs)
                results.append({"format": fmt, "encoder": enc, "workers": w, "frames": frames, "runs": runs,
                                "worst_fps": min(r["fps"] for r in runs), "mean_fps": round(sum(r["fps"] for r in runs) / len(runs), 2),
                                "peak_rss_mb": max(r["peak_rss_mb"] for r in runs), "eligible": eligible})
    recommended = {}
    for fmt in formats:
        for enc in encoders:
            cands = sorted((r for r in results if r["format"] == fmt and r["encoder"] == enc and r["eligible"]),
                           key=lambda r: r["workers"])
            if not cands:
                continue
            best = max(cands, key=lambda r: r["worst_fps"])
            for c in cands:  # prefer fewer tabs when within 10% (memory headroom > marginal speed; v0.2 showed
                # 8 tabs turning unstable under memory pressure, and short benchmarks can't show long-render behaviour)
                if c["workers"] < best["workers"] and c["worst_fps"] >= HEADROOM_RULE * best["worst_fps"]:
                    best = c
                    break
            recommended.setdefault(fmt, {})[enc] = {"concurrency": best["workers"], "worst_fps": best["worst_fps"],
                                                     "peak_rss_mb": best["peak_rss_mb"]}
        if fmt in recommended:
            pick = max(recommended[fmt].values(), key=lambda r: r["worst_fps"])
            enc_pick = next(k for k, v in recommended[fmt].items() if v is pick)
            recommended[fmt] = {"encoder": enc_pick, **pick, "by_encoder": dict(recommended[fmt])}
    rep = {"host": host_info().__dict__, "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "bundle": bundle.name,
           "fixtures": {k: sha256_file(v)[:12] for k, v in FIXTURES.items() if k in formats},
           "settings": {"seconds": seconds, "repeats": repeats, "workers": workers, "encoders": encoders},
           "results": results, "recommended": recommended,
           "rule": "eligible = all runs OK, swap growth <= 16 MB, page-outs <= 500 pages; pick best worst-case fps, "
                   "prefer fewer tabs within 10%"}
    # merge: keep recommendations for formats not measured in this run, keep a history of runs
    try:
        prev = json.loads(R.BENCH_FILE.read_text())
    except (OSError, ValueError):
        prev = {}
    merged_rec = {**prev.get("recommended", {}), **recommended}
    history = prev.get("history", []) + [{k: rep[k] for k in ("date", "settings", "results", "recommended")}]
    atomic_write_json(R.BENCH_FILE, {**rep, "recommended": merged_rec, "history": history[-10:]})
    return {**rep, "recommended": merged_rec}
