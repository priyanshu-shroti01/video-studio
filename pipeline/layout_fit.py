"""Pre-render layout fitting. The engine's layout is deterministic (scripts/engine-layout.mjs), so text
overflow can be found BEFORE any TTS or rendering, from estimated timings. Conservative repairs only:

  1. step a block's `size` down (xl -> l -> m) — e.g. a single long word in an xl headline;
  2. shorten a "·"-separated list (drop the trailing item) — e.g. a CTA feature line;
  3. anything else is reported as unresolved (never silently deleted).

Every change is recorded so the reviewer sees exactly what was adjusted."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from .timeline import build_timeline, estimated_timing
from .visual_qa.checks import layout_manifest

SIZES = ["xl", "l", "m", "s"]


def _overflows(cfg: dict) -> list[dict]:
    tl = build_timeline(cfg, estimated_timing(cfg["storyboard"]))
    out = []
    for fmt, props in tl.props.items():
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(props, f)
            pf = Path(f.name)
        try:
            m = layout_manifest(pf)
        finally:
            pf.unlink(missing_ok=True)
        for sc in m["scenes"]:
            for b in sc["blocks"]:
                for t in b.get("texts", []):
                    if t.get("overflow"):
                        out.append({"format": fmt, "scene": sc["id"], "index": b["index"], "type": b["type"],
                                    "text": t["text"], "estWidth": round(t["estWidth"]), "maxWidth": round(t["maxWidth"])})
    return out


def _find_string_field(block: dict, text: str):
    for k, v in block.items():
        if isinstance(v, str) and v.strip() == text.strip():
            return k
    return None


def fit_storyboard(cfg: dict, max_rounds: int = 8) -> tuple[dict, list[dict], list[dict]]:
    """-> (storyboard, fixes, unresolved). `cfg` is a resolved project config (load_project)."""
    cfg = copy.deepcopy(cfg)
    sb = cfg["storyboard"]
    fixes: list[dict] = []
    issues: list[dict] = []
    for _ in range(max_rounds):
        issues = _overflows(cfg)
        if not issues:
            break
        changed = False
        for it in issues:
            scene = next(s for s in sb["scenes"] if s["id"] == it["scene"])
            block = scene["blocks"][it["index"]]
            field = _find_string_field(block, it["text"])
            if field and " · " in block[field]:
                before = block[field]
                block[field] = " · ".join(before.split(" · ")[:-1])
                fixes.append({**it, "fix": f"shortened {field}", "from": before, "to": block[field]})
                changed = True
            elif block.get("size") in SIZES[:-1]:
                before = block["size"]
                block["size"] = SIZES[SIZES.index(before) + 1]
                fixes.append({**it, "fix": f"size {before} -> {block['size']}"})
                changed = True
        if not changed:
            break
    if fixes:
        issues = _overflows(cfg)          # report the state AFTER the last repair, never a stale list
    return sb, fixes, issues
