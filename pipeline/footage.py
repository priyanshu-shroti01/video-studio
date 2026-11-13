"""Footage blocks (real video clips: screen recordings, product footage) on the Python side.

The engine draws a `footage` block from its public/-relative `asset`; Python owns the facts about the file:

* the asset must stay inside public/, be an .mp4 / .webm and decode with a video stream (ffprobe);
* `aspect` (display width / height: sample aspect ratio and rotation applied) and `duration` (seconds of the video
  stream, so the engine can hold the last frame) are filled from ffprobe when the storyboard leaves them out;
* `startFrom` must lie inside the clip.

Brand isolation (pipeline/brands.py referenced_assets / asset_allowed: the key `asset`) and licensing
(pipeline/assets.py, registered in the job's asset manifest by the runner) cover the file like any image."""
from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

from .errors import PipelineError
from .paths import ROOT, safe_path

VIDEO_EXTS = (".mp4", ".webm")


def footage_blocks(storyboard: dict):
    """Every footage block of a storyboard (live dicts, so callers can fill fields in place)."""
    for sc in storyboard.get("scenes", []):
        for b in sc.get("blocks", []):
            if isinstance(b, dict) and b.get("type") == "footage":
                yield sc, b


def public_file(asset: str) -> Path:
    """public/-relative asset -> absolute path inside public/ (raises PathError when it escapes public/)."""
    a = str(asset).replace("\\", "/").lstrip("/").removeprefix("public/")
    return safe_path(Path("public") / a, roots=[(ROOT / "public").resolve()])


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _ratio(s) -> float | None:
    if not s or s in ("0:1", "N/A"):
        return None
    a, _, b = str(s).replace("/", ":").partition(":")
    x, y = _num(a), _num(b or 1)
    return x / y if x and y else None


@lru_cache(maxsize=256)
def _probe_cached(path: str, mtime: float, size: int) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,sample_aspect_ratio,duration,nb_frames,r_frame_rate:"
                        "stream_tags=rotate:stream_side_data=rotation:format=duration,format_name",
                        "-of", "json", path], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise PipelineError(f"cannot read video {path}", detail=r.stderr[-400:])
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams") or []
    if not streams or not streams[0].get("width") or not streams[0].get("height"):
        raise PipelineError(f"not a video (no video stream): {path}")
    st = streams[0]
    w, h = int(st["width"]), int(st["height"])
    w_disp = w * (_ratio(st.get("sample_aspect_ratio")) or 1.0)
    rot = _num((st.get("tags") or {}).get("rotate"))
    for sd in st.get("side_data_list") or []:
        if "rotation" in sd:
            rot = _num(sd["rotation"])
    if rot is not None and round(abs(rot)) % 180 == 90:
        w_disp, h = h, w_disp
    duration = _num(st.get("duration")) or _num((data.get("format") or {}).get("duration"))
    if not duration:
        duration = _last_frame_end(path)
    return {"codec": st.get("codec_name"), "width": w, "height": int(st["height"]), "aspect": round(w_disp / h, 6),
            "duration": round(duration, 6) if duration else None, "fps": _ratio(st.get("r_frame_rate")),
            "format": (data.get("format") or {}).get("format_name", "")}


def _last_frame_end(path: str) -> float | None:
    """Duration of a video whose container does not store one (e.g. a MediaRecorder WebM): last packet pts + duration."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,duration_time",
                        "-of", "csv=p=0", path], capture_output=True, text=True, timeout=120)
    end = None
    for line in r.stdout.splitlines():
        pts, _, dur = line.partition(",")
        p = _num(pts)
        if p is not None:
            e = p + (_num(dur) or 0.0)
            end = e if end is None else max(end, e)
    return end


def probe_video(path: Path) -> dict:
    """{codec, width, height, aspect (display w/h), duration (s, video stream), fps, format}; cached per file version."""
    p = Path(path)
    st = p.stat()
    return dict(_probe_cached(str(p), st.st_mtime, st.st_size))


def prepare_footage(storyboard: dict) -> list[str]:
    """Validate every footage asset and fill missing `aspect` / `duration` in place. Returns error strings."""
    errs: list[str] = []
    for sc, b in footage_blocks(storyboard):
        where = f"$storyboard.scenes({sc.get('id')}).footage"
        asset = b.get("asset")
        if not isinstance(asset, str) or not asset.strip():
            continue  # reported by validate_storyboard
        try:
            f = public_file(asset)
        except PipelineError as e:
            errs.append(f"{where}: asset {asset!r} must be a file inside public/ ({e})")
            continue
        if f.suffix.lower() not in VIDEO_EXTS:
            errs.append(f"{where}: asset {asset!r} must be a video ({', '.join(VIDEO_EXTS)})")
            continue
        if not f.is_file():
            errs.append(f"{where}: missing video public/{asset}")
            continue
        try:
            info = probe_video(f)
        except PipelineError as e:
            errs.append(f"{where}: {e} {getattr(e, 'detail', '') or ''}".rstrip())
            continue
        b.setdefault("aspect", info["aspect"])
        if info["duration"]:
            b.setdefault("duration", info["duration"])
        dur = _num(b.get("duration"))
        start = _num(b.get("startFrom", 0)) or 0.0
        if dur and start >= dur:
            errs.append(f"{where}: startFrom {start} s is past the end of {asset} ({dur:.2f} s)")
    return errs
