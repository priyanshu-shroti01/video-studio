#!/usr/bin/env python3
"""Fair creative comparison of productions rendered from the same brief.

  uv run python scripts/compare_creative.py <label>=<production-id> [...] --out docs/reports/CREATIVE_COMPARISON.md

Every number comes from the productions' own artifacts (storyboard, preview gate, QA, branding, render
reports, rendered video). Nothing is scored by taste here; the human verdict is recorded separately."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from creative_metrics import storyboard_metrics, video_metrics  # noqa: E402

from pipeline.contract import TIME_KEYS  # noqa: E402
from pipeline.jobs import Registry  # noqa: E402
from pipeline.productions import Productions  # noqa: E402

CLICHES = re.compile(r"game.?changer|seamless|next.?level|unleash|supercharge|revolutioni[sz]e|no tech skills|"
                     r"look no further|take .* to the next|cutting.?edge|world.?class", re.I)


def animated(block) -> bool:
    s = json.dumps(block)
    return any(f'"{k}"' in s for k in TIME_KEYS - {"at"}) or block["type"] in (
        "kinetic-text", "counter", "plan-card", "install-flow", "server-stack", "price-compare", "bars", "plans")


def row(label: str, pid: str) -> dict:
    reg = Registry()
    p = Productions(reg).get(pid)
    pd = Path(p["dir"])
    sb = json.loads((pd / "storyboard.json").read_text())
    out = {"label": label, "production": pid, "state": p["state"]}
    out.update({f"sb_{k}": v for k, v in storyboard_metrics(sb).items()})
    gate = json.loads((pd / "preview/gate.json").read_text()) if (pd / "preview/gate.json").exists() else None
    out["gate"] = gate["status"] if gate else "n/a"
    out["gate_fail"] = [c["id"] for c in gate["checks"] if c["status"] == "FAIL"] if gate else []
    blocks = [b for s in sb["scenes"] for b in s["blocks"]]
    out["animated_blocks"] = sum(animated(b) for b in blocks)
    out["camera_moves"] = sum(1 for s in sb["scenes"] if s.get("camera") not in (None, "none"))
    out["transitions"] = sorted({s.get("transition", "fade") for s in sb["scenes"]})
    narr = " ".join(s["narration"] for s in sb["scenes"])
    words = narr.split()
    sents = [x for x in re.split(r"[.!?]+", narr) if x.strip()]
    out["words"] = len(words)
    out["avg_sentence_words"] = round(len(words) / max(1, len(sents)), 1)
    out["cliches"] = CLICHES.findall(narr)
    if p["job_id"]:
        job = reg.get(p["job_id"])
        jo = Path(job["output_dir"])
        video = jo / "video/final-short.mp4"
        if video.exists():
            out.update({f"v_{k}": v for k, v in video_metrics(video).items()})
        qa = json.loads((jo / "reports/qa-report.json").read_text())
        out["qa"] = qa["status"]
        out["qa_counts"] = qa["formats"][0]["counts"]
        br = jo / "reports/branding-report.json"
        out["branding"] = json.loads(br.read_text())["status"] if br.exists() else "n/a"
        rr = json.loads((jo / "reports/render-report.json").read_text())["formats"][0]
        out["render_fps"] = rr.get("fps_rendered")
        out["render_s"] = rr["seconds"]
        cr = jo / "reports/claims-report.json"
        if cr.exists():
            claims = json.loads(cr.read_text()).get("claims", [])
            out["claims_unverified"] = sum(c.get("status") != "VERIFIED" for c in claims)
    return out


def main():
    args = [a for a in sys.argv[1:] if "=" in a]
    dst = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
    rows = [row(*a.split("=", 1)) for a in args]
    keys = ["production", "state", "gate", "gate_fail", "qa", "qa_counts", "branding", "sb_scenes", "sb_blocks",
            "sb_blocks_per_scene", "sb_single_block_scenes", "sb_distinct_block_types", "sb_v2_blocks", "sb_demo_blocks",
            "sb_backdrops", "animated_blocks", "camera_moves", "transitions", "v_density_mean", "v_empty_frames_pct",
            "v_frame_change_mean", "words", "avg_sentence_words", "cliches", "claims_unverified", "render_fps", "render_s",
            "v_frames"]
    lines = ["| Metric | " + " | ".join(r["label"] for r in rows) + " |", "|---|" + "---|" * len(rows)]
    for k in keys:
        lines.append(f"| `{k}` | " + " | ".join(str(r.get(k, "—")).replace("|", "/") for r in rows) + " |")
    md = "\n".join(lines)
    print(md)
    if dst:
        dst.write_text(md + "\n")
    json.dump(rows, open(Path("output") / "creative-comparison.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
