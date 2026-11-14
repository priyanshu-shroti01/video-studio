"""Frame-accurate in-browser preview (Studio Preview & QA): the exact RenderProps the renderer would use for a
production's current storyboard, for the Remotion <Player> to play with the real engine.

Same code path as the preview stills and gate (pipeline/preview.py):
    load_project(project.json) -> build_timeline(cfg, estimated_timing(storyboard)) -> props[fmt]
so what the user scrubs is what the full render draws, except for the timing: until the voice is recorded,
word times are ESTIMATED (pipeline.timeline.estimated_timing). The final render re-times everything to the real
narration, so scene bounds and anchored cues move by a few frames. (Phase 2: generate the local voice first and
build these props from its real timings, so the preview is exact.)

The props are returned unchanged (byte-identical to what the renderer writes to props-<fmt>.json for the same
timing). Assets are not rewritten inside the props: the engine resolves every asset with remotion's staticFile(),
which prefixes `window.remotion_staticBase`. The Studio sets that to `staticBase` ("/files/public"), the existing
/files/ route that serves public/ through pipeline.api.safe_output_file. `assets` lists every public/ file the
props reference with its Studio URL, so the UI can report missing files before playing.

Read-only: no file is written, nothing is rendered, no state changes."""
from __future__ import annotations

import urllib.parse
from pathlib import Path

from .config import load_project, theme_asset_paths
from .contract import FORMATS
from .errors import NotFound, PipelineError
from .paths import ROOT, rel, sha256_json
from .timeline import build_timeline, estimated_timing

STATIC_BASE = "/files/public"
TIMING = "estimated"
TIMING_NOTE = ("Estimated timing: no voice has been recorded yet, so word and scene times are estimates. "
               "The final render re-times everything to the real narration.")


def public_url(path: str) -> str:
    """Studio URL of a public/ file, as remotion's staticFile() builds it with staticBase=/files/public
    (per-segment encodeURIComponent)."""
    return f"{STATIC_BASE}/" + "/".join(urllib.parse.quote(part, safe="!*'()") for part in path.lstrip("/").split("/"))


def _asset_paths(props: dict) -> list[str]:
    """Every public/ path the engine may load via staticFile(): theme logos + fonts, and any `asset` in blocks
    (image, device, footage, composition media, app icons) and the watermark."""
    out = set(theme_asset_paths(props["theme"]))

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "asset" and isinstance(v, str) and v:
                    out.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(props["scenes"])
    walk(props.get("watermark") or {})
    return sorted(out)


def _scene_frames(props: dict) -> list[dict]:
    fps, n = props["fps"], props["durationInFrames"]
    out = []
    for s in props["scenes"]:
        a = max(0, min(n - 1, round(s["start"] * fps)))
        b = max(a, min(n - 1, round(s["end"] * fps) - 1))
        out.append({"id": s["id"], "purpose": s["purpose"], "start": s["start"], "end": s["end"],
                    "startFrame": a, "endFrame": b})
    return out


def props_for_project(project: str | Path, fmt: str | None = None) -> dict:
    """Player props for a project file (workspace-relative path). See player_props."""
    cfg, warnings = load_project(project)
    fmt = fmt or cfg["formats"][0]
    if fmt not in FORMATS:
        raise PipelineError(f"unknown format {fmt!r} (expected one of {', '.join(FORMATS)})")
    project_formats = list(cfg["formats"])
    cfg = {**cfg, "formats": [fmt]}                       # as the preview stills do: any format can be previewed
    tl = build_timeline(cfg, estimated_timing(cfg["storyboard"]))
    props = tl.props[fmt]
    width, height = FORMATS[fmt]
    assets = [{"path": a, "url": public_url(a), "exists": (ROOT / "public" / a).is_file()} for a in _asset_paths(props)]
    return {
        "format": fmt,
        "formats": list(FORMATS),
        "projectFormats": project_formats,
        "inProject": fmt in project_formats,
        "timing": TIMING,
        "timingNote": TIMING_NOTE,
        "fps": props["fps"],
        "durationInFrames": props["durationInFrames"],
        "width": width,
        "height": height,
        "staticBase": STATIC_BASE,
        "props": props,
        "propsHash": sha256_json(props),
        "scenes": _scene_frames(props),
        "assets": assets,
        "missingAssets": [a["path"] for a in assets if not a["exists"]],
        "warnings": list(warnings) + list(tl.warnings),
    }


def player_props(production_id: str, fmt: str | None = None) -> dict:
    """-> the Studio player payload for a production's current storyboard (format default: its first format).

    Response shape (GET /api/productions/<id>/player-props?format=short|landscape):
      productionId, storyboardHash, format, formats, projectFormats, inProject, timing ("estimated"), timingNote,
      fps, durationInFrames, width, height, staticBase, props (RenderProps), propsHash,
      scenes [{id, purpose, start, end, startFrame, endFrame}], assets [{path, url, exists}], missingAssets, warnings"""
    from .api import _reg
    from .preview_gate import saved_storyboard_hash
    from .productions import Productions
    p = Productions(_reg()).get(production_id)
    d = Path(p["dir"])
    if not (d / "storyboard.json").is_file() or not (d / "project.json").is_file():
        raise NotFound(f"production {production_id} has no storyboard yet: select a concept or save a storyboard first")
    out = props_for_project(rel(d / "project.json"), fmt)
    return {"productionId": production_id, "storyboardHash": saved_storyboard_hash(d), **out}
