"""Platform routing from the ACTUAL video file (ffprobe), not from the format name.

  9:16, <= 180 s            -> YouTube Shorts + Instagram Reels
  9:16, >  180 s            -> YouTube (long-form: Shorts max out at 3 min) + Instagram Reels if within the
                               Reels API limits (3 s - 15 min, <= 300 MB), otherwise flagged
  16:9                      -> YouTube standard video with chapters. NEVER Instagram (suggest the 9:16 render)
  anything else             -> YouTube only; Instagram refused (this pipeline only routes 9:16 to Reels)

Limits verified 2026-11-13 (see docs/SOCIAL_PUBLISHING.md for the URLs):
  YouTube Shorts: square or vertical, up to 3 minutes (support.google.com/youtube/answer/15424877)
  Instagram Reels API: MP4/MOV, H.264/HEVC, AAC <= 48 kHz, 23-60 fps, max 1920 columns, 3 s - 15 min,
  <= 300 MB (developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..errors import PipelineError

SHORTS_MAX_S = 180.0
IG_REELS_MIN_S, IG_REELS_MAX_S = 3.0, 900.0
IG_MAX_BYTES = 300 * 1024 * 1024
IG_MAX_COLUMNS = 1920
IG_FPS = (23.0, 60.0)
VERTICAL_9_16 = 9 / 16
LANDSCAPE_16_9 = 16 / 9
TOL = 0.03


class ProbeError(PipelineError):
    code, exit_code = "VIDEO_PROBE_FAILED", 2


def probe(video: Path) -> dict:
    """Width/height (rotation-corrected), duration, fps, codecs and size of a video file."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                            str(video)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise ProbeError(f"ffprobe failed: {e}") from e
    if r.returncode != 0:
        raise ProbeError(f"ffprobe could not read {Path(video).name}", detail=r.stderr[-500:])
    d = json.loads(r.stdout or "{}")
    vs = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    if not vs:
        raise ProbeError(f"{Path(video).name} has no video stream")
    aus = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    w, h = int(vs["width"]), int(vs["height"])
    rot = 0
    for sd in vs.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = int((vs.get("tags") or {}).get("rotate", rot))
    if abs(rot) % 180 == 90:
        w, h = h, w
    num, _, den = (vs.get("avg_frame_rate") or vs.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    dur = float(d.get("format", {}).get("duration") or vs.get("duration") or 0)
    return {"width": w, "height": h, "aspect": round(w / h, 4), "duration_s": round(dur, 3), "fps": round(fps, 3),
            "video_codec": vs.get("codec_name"), "audio_codec": aus.get("codec_name") if aus else None,
            "audio_sample_rate": int(aus["sample_rate"]) if aus and aus.get("sample_rate") else None,
            "size_bytes": Path(video).stat().st_size, "orientation": orientation(w, h)}


def orientation(w: int, h: int) -> str:
    a = w / h
    if abs(a - VERTICAL_9_16) <= TOL:
        return "vertical-9:16"
    if abs(a - LANDSCAPE_16_9) <= TOL * 2:
        return "landscape-16:9"
    if abs(a - 1) <= TOL:
        return "square"
    return "vertical-other" if a < 1 else "landscape-other"


def instagram_problems(info: dict) -> list[str]:
    """Reasons a probed file cannot go to Instagram Reels through the API (empty = eligible)."""
    p = []
    if info["orientation"] != "vertical-9:16":
        p.append(f"aspect {info['width']}x{info['height']} is not 9:16: only vertical 9:16 video is routed to Instagram Reels")
    if info["duration_s"] < IG_REELS_MIN_S:
        p.append(f"{info['duration_s']:.1f} s is shorter than the Reels minimum of {IG_REELS_MIN_S:.0f} s")
    if info["duration_s"] > IG_REELS_MAX_S:
        p.append(f"{info['duration_s']:.0f} s exceeds the Reels API maximum of {IG_REELS_MAX_S / 60:.0f} min")
    if info["size_bytes"] > IG_MAX_BYTES:
        p.append(f"file is {info['size_bytes'] / 1e6:.0f} MB; the Reels API maximum is 300 MB")
    if info["width"] > IG_MAX_COLUMNS:
        p.append(f"width {info['width']} exceeds the Reels maximum of {IG_MAX_COLUMNS} columns")
    if info.get("fps") and not IG_FPS[0] <= info["fps"] <= IG_FPS[1] + 0.01:
        p.append(f"{info['fps']} fps is outside the Reels range 23-60 fps")
    if info.get("video_codec") and info["video_codec"] not in ("h264", "hevc"):
        p.append(f"video codec {info['video_codec']} is not H.264/HEVC")
    if info.get("audio_sample_rate") and info["audio_sample_rate"] > 48000:
        p.append(f"audio sample rate {info['audio_sample_rate']} Hz exceeds 48 kHz")
    return p


def plan(info: dict, fmt: str | None = None) -> dict:
    """Structured routing plan with a reason for every destination and every refusal."""
    dests, rejected, suggestions = [], [], []
    o, dur = info["orientation"], info["duration_s"]
    vertical = o in ("vertical-9:16", "vertical-other", "square")
    if vertical and dur <= SHORTS_MAX_S:
        dests.append({"platform": "youtube", "kind": "short",
                      "reason": f"{o}, {dur:.1f} s <= {SHORTS_MAX_S:.0f} s: YouTube classifies it as a Short"})
    elif vertical:
        dests.append({"platform": "youtube", "kind": "video",
                      "reason": f"{o}, {dur:.0f} s > {SHORTS_MAX_S:.0f} s: too long for Shorts, uploads as a regular video"})
    else:
        dests.append({"platform": "youtube", "kind": "video", "chapters": True,
                      "reason": f"{o}: standard YouTube video; chapters are added when there are >= 3 chapters of >= 10 s"})
    ig = instagram_problems(info)
    if not ig:
        dests.append({"platform": "instagram", "kind": "reel",
                      "reason": f"9:16, {dur:.1f} s, {info['size_bytes'] / 1e6:.1f} MB: within the Reels API limits"})
    else:
        rejected.append({"platform": "instagram", "reasons": ig})
        if o.startswith("landscape"):
            suggestions.append("Landscape video never goes to Instagram. Render the 9:16 'short' format of this "
                               "production for Reels.")
    if vertical and dur > SHORTS_MAX_S:
        suggestions.append("Over 3 minutes: it will not appear in the Shorts feed. Cut a <= 180 s version for Shorts.")
    return {"format": fmt, "video": info, "destinations": dests, "rejected": rejected, "suggestions": suggestions}


def plan_file(video: Path, fmt: str | None = None) -> dict:
    return plan(probe(video), fmt)
