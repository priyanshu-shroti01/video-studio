#!/usr/bin/env python3
"""Objective creative metrics for a rendered video (used to compare creative approaches fairly).

  uv run python scripts/creative_metrics.py <video.mp4> [<storyboard.json>] [--label NAME]

Per frame (1 fps): content density = share of pixels on edges/UI (gradient magnitude above a threshold, which
backdrop glows and dot grids don't reach) and luma spread. Across frames: how many frames are "empty"
(density < 2%), and visual variety = mean perceptual distance between consecutive scene frames (64x36 grey
thumbnails). From the storyboard: scenes, blocks, distinct block types, blocks per scene, product-demo blocks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

DEMO_BLOCKS = {"plans", "domain-input", "terminal", "dashboard", "device", "scroll-demo", "browser", "server-stack", "install-flow",
               "plan-card", "price-compare", "feature-compare"}


def frames(video: Path, fps: float = 1.0, w: int = 270, h: int = 480) -> np.ndarray:
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip().split(",")
    W, H = int(probe[0]), int(probe[1])
    if W > H:
        w, h = h, w
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(float)


def density(f: np.ndarray, thr: float = 40.0) -> float:
    gy, gx = np.gradient(f)
    return float((np.hypot(gx, gy) > thr).mean())


def video_metrics(video: Path) -> dict:
    fr = frames(video)
    d = np.array([density(f) for f in fr])
    thumbs = [f[::8, ::8] for f in fr]
    var = [float(np.abs(a - b).mean()) for a, b in zip(thumbs, thumbs[1:])]
    return {"frames": len(fr), "density_mean": round(float(d.mean()) * 100, 2), "density_median": round(float(np.median(d)) * 100, 2),
            "empty_frames_pct": round(float((d < 0.02).mean()) * 100, 1), "frame_change_mean": round(float(np.mean(var)), 2)}


def storyboard_metrics(sb: dict) -> dict:
    scenes = sb["scenes"]
    blocks = [b for s in scenes for b in s["blocks"]]
    types = [b["type"] for b in blocks]
    return {"scenes": len(scenes), "blocks": len(blocks), "distinct_block_types": len(set(types)),
            "blocks_per_scene": round(len(blocks) / len(scenes), 2),
            "demo_blocks": sorted({t for t in types if t in DEMO_BLOCKS}),
            "v2_blocks": sorted({t for t in types if t in {"kinetic-text", "counter", "price-compare", "terminal", "dashboard",
                                                           "device", "image", "progress", "scroll-demo", "chart", "install-flow",
                                                           "feature-compare", "logo-sting", "outro", "server-stack", "plan-card"}}),
            "single_block_scenes": sum(1 for s in scenes if len(s["blocks"]) == 1),
            "backdrops": sorted({s.get("backdrop", "glow") for s in scenes})}


if __name__ == "__main__":
    argv = sys.argv[1:]
    label = None
    if "--label" in argv:
        i = argv.index("--label")
        label = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    args = argv
    label = label or Path(args[0]).parent.parent.name
    out = {"label": label, "video": video_metrics(Path(args[0]))}
    if len(args) > 1:
        out["storyboard"] = storyboard_metrics(json.loads(Path(args[1]).read_text()))
    print(json.dumps(out))
