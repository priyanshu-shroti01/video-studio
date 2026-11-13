"""Low-cost storyboard preview: one still per scene from ESTIMATED timings (no TTS, no full render),
built with the same timeline code as production renders, plus a contact sheet. Used to review and
choose concepts before spending a full render."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import procs
from . import render as R
from .config import load_project
from .jobs import Registry
from .paths import ROOT, atomic_write_json, rel
from .scheduler import HeavyWork
from .timeline import build_timeline, estimated_timing


def _times(o) -> list[float]:
    from .contract import TIME_KEYS
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if (k in TIME_KEYS or k == "keyTimes") and isinstance(v, (int, float)):
                out.append(float(v))
            elif k == "keyTimes" and isinstance(v, list):
                out += [float(x) for x in v if isinstance(x, (int, float))]
            else:
                out += _times(v)
    elif isinstance(o, list):
        for v in o:
            out += _times(v)
    return out


def storyboard_stills(prod_dir: Path, fmt: str | None = None, log=lambda m: None) -> dict:
    cfg, _ = load_project(rel(prod_dir / "project.json"))
    fmt = fmt or cfg["formats"][0]
    cfg = {**cfg, "formats": [fmt]}
    tm = estimated_timing(cfg["storyboard"])
    tl = build_timeline(cfg, tm)
    out = prod_dir / "preview"
    out.mkdir(parents=True, exist_ok=True)
    props_f = out / f"props-{fmt}.json"
    atomic_write_json(props_f, tl.props[fmt])
    bundle = R.ensure_bundle(log)
    R.ensure_chromium()
    stills = []
    t0 = time.time()
    with HeavyWork(Registry(), "background", ref=f"preview:{prod_dir.name}", log=log):
        for i, s in enumerate(tl.resolved):
            # sample when the scene has settled: after its LATEST resolved event (counter ends, keystrokes,
            # per-item/per-word reveals, button states), not merely after each block first appears
            last = max(_times(s["blocks"]) + [s["start"]])
            t = min(s["end"] - 0.25, max(s["start"] + 0.5, last + 0.6))
            frame = min(tl.frames - 1, int(t * tl.fps))
            png = out / f"scene{i + 1:02d}-{s['id']}.png"
            procs.run([*R.remotion_bin(), "still", str(bundle), "Storyboard", str(png), f"--props={props_f}",
                       f"--frame={frame}", "--log=error", "--overwrite"], cwd=ROOT, timeout=180, stall_timeout=120)
            stills.append({"scene": s["id"], "purpose": s["purpose"], "frame": frame, "png": rel(png)})
    cols = 5 if fmt == "short" else 3
    sheet = out / "contact-sheet.jpg"
    procs.run(["ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(out / "scene*.png"), "-vf",
               f"scale={360 if fmt == 'short' else 480}:-2,tile={cols}x{-(-len(stills) // cols)}:padding=8:color=0x16161c",
               "-frames:v", "1", "-q:v", "3", str(sheet)], timeout=120)
    info = {"format": fmt, "estimated": True, "duration_estimate_s": round(tl.duration, 1), "stills": stills,
            "contact_sheet": rel(sheet), "seconds": round(time.time() - t0, 1),
            "note": "Timings are estimates (no voice yet); the final render re-times everything to the real narration."}
    atomic_write_json(out / "preview.json", info)
    return info
