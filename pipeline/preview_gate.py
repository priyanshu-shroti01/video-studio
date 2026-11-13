"""Storyboard preview quality gate + human preview review (before any expensive render).

Automated checks on the low-cost preview (one still per scene) and the storyboard:
  * empty scene      — content density of the still below 2.5% (mostly backdrop)              FAIL
  * repetition       — two consecutive scene stills look alike                              FAIL
  * hero visual      — a scene with only headline/text/pill (hooks may lead with a headline)   FAIL
  * invented labels  — on-screen "Label: ₹N" patterns, or numbers not found in verified facts FAIL
  * text overflow    — from the engine's layout manifest                                    FAIL
  * narration sync   — voice runs >3 s over a frozen screen, or a number shows before it is spoken  FAIL (pipeline/sync_check.py)
  * variety          — fewer than 5 distinct block types in the video                       WARN
  * backdrop rhythm  — the same backdrop in more than 3 consecutive scenes                  WARN

Then a named person must approve the preview for the exact storyboard hash before rendering. An
explicit override is possible but audited, and leaves a blocking review flag for final approval."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .paths import ROOT, atomic_write_json, atomic_write_text, sha256_file, sha256_json

EMPTY_DENSITY = 0.025
SIMILAR = 6.0                       # mean abs grey diff (0-255) of 64x114 thumbnails
LABEL_NUMBER = re.compile(r"^[A-Za-z][\w ]{1,24}:\s*(₹|rs\.?|inr)?\s*\d", re.I)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
TEXT_FIELDS = ("text", "label", "note", "sub", "title", "name", "price", "value", "detail", "billing", "doneText",
               "availableText", "badge", "tagline", "cta", "status")


def _gray(png: Path, w: int = 64) -> np.ndarray:
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(png)], capture_output=True, text=True).stdout.strip().split(",")
    W, H = int(info[0]), int(info[1])
    h = int(round(w * H / W))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", f"scale={w * 4}:{h * 4}", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h * 4, w * 4).astype(float)


def density(img: np.ndarray, thr: float = 40.0) -> float:
    gy, gx = np.gradient(img)
    return float((np.hypot(gx, gy) > thr).mean())


def _strings(block: dict):
    def rec(o, key=None):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from rec(v, k)
        elif isinstance(o, list):
            for v in o:
                yield from rec(v, key)
        elif isinstance(o, str) and key in TEXT_FIELDS:
            yield key, o
    yield from rec(block)
    if block.get("type") == "footage" and isinstance(block.get("caption"), str):
        yield "caption", block["caption"]        # (image captions keep their v0.4 behaviour)


def _num_str(v) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def verified_numbers(brand: str) -> set[str]:
    f = ROOT / "knowledge" / brand / "facts.json"
    nums: set[str] = set()
    if f.exists():
        for fact in json.loads(f.read_text()).get("facts", []):
            for n in NUMBER.findall(json.dumps(fact, ensure_ascii=False)):
                nums.add(n.replace(",", ""))
    return nums


def saved_storyboard_hash(prod_dir: Path) -> str:
    """Digest of the storyboard and project files AS SAVED. The gate and preview approval must use this same digest.
    Never hash the loaded storyboard: loading fills in derived values (footage aspect/duration from ffprobe), so a
    loaded copy never matches the file and every footage production would look "changed after the preview"."""
    prod_dir = Path(prod_dir)
    return sha256_json({"sb": json.loads((prod_dir / "storyboard.json").read_text()),
                        "project": sha256_file(prod_dir / "project.json")})


def evaluate(prod_dir: Path, cfg: dict) -> dict:
    from .layout_fit import _overflows
    from .storyboard import HERO_BLOCKS
    sb = cfg["storyboard"]
    prev = json.loads((prod_dir / "preview/preview.json").read_text())
    stills = {s["scene"]: ROOT / s["png"] for s in prev["stills"]}
    checks, metrics = [], {"scenes": []}

    def add(cid, status, detail):
        checks.append({"id": cid, "status": status, "detail": detail})

    grays, empty, alike = {}, [], []
    for s in sb["scenes"]:
        g = _gray(stills[s["id"]])
        grays[s["id"]] = g
        d = density(g)
        metrics["scenes"].append({"scene": s["id"], "density_pct": round(d * 100, 2),
                                  "blocks": [b["type"] for b in s["blocks"]], "backdrop": s.get("backdrop", "glow")})
        if d < EMPTY_DENSITY:
            empty.append(f"{s['id']} ({d:.1%})")
    ids = [s["id"] for s in sb["scenes"]]
    for a, b in zip(ids, ids[1:]):
        diff = float(np.abs(grays[a][::4, ::4] - grays[b][::4, ::4]).mean())
        if diff < SIMILAR:
            alike.append(f"{a}≈{b} ({diff:.1f})")
    add("preview.empty_scenes", "FAIL" if empty else "PASS", f"mostly-empty scenes: {empty}" if empty else "every scene has content")
    add("preview.repetition", "FAIL" if alike else "PASS", f"consecutive scenes look alike: {alike}" if alike else "consecutive scenes differ")
    no_hero = [s["id"] for s in sb["scenes"] if not any(b["type"] in HERO_BLOCKS for b in s["blocks"])
               and not (s["purpose"] == "hook" and any(b["type"] in ("headline", "kinetic-text") for b in s["blocks"]))]
    add("storyboard.hero_visual", "FAIL" if no_hero else "PASS",
        f"scenes without a hero visual: {no_hero}" if no_hero else "every scene has a hero visual")
    facts_nums = verified_numbers(cfg["brand"])
    labels, unverified = [], []
    for s in sb["scenes"]:
        for b in s["blocks"]:
            for key, txt in _strings(b):
                if LABEL_NUMBER.search(txt.strip()):
                    labels.append(f"{s['id']}/{b['type']}.{key}: {txt!r}")
                for n in NUMBER.findall(txt):
                    if n.replace(",", "") not in facts_nums:
                        unverified.append(f"{s['id']}/{b['type']}.{key}: {n} in {txt!r}")
            if b["type"] == "price" and str(b.get("amount")) not in facts_nums:
                unverified.append(f"{s['id']}/price.amount: {b.get('amount')}")
            if b["type"] == "plan-card" and str(b.get("price")) not in facts_nums:
                unverified.append(f"{s['id']}/plan-card.price: {b.get('price')}")
            if b["type"] == "composition":             # generated graphics: every counted number must be a fact value
                for e in b.get("elements", []):
                    v = e.get("to") if e.get("kind") == "number" else None
                    if isinstance(v, (int, float)) and _num_str(v) not in facts_nums:
                        unverified.append(f"{s['id']}/composition.number: {v}")
    add("storyboard.invented_labels", "FAIL" if labels else "PASS",
        f"label-with-number text (invented UI): {labels}" if labels else "no invented 'Label: number' UI text")
    add("storyboard.numbers_verified", "FAIL" if unverified else "PASS",
        f"numbers on screen not in verified facts: {unverified[:6]}" if unverified else "every on-screen number is in the verified facts")
    try:
        ov = _overflows(cfg)
        add("layout.overflow", "FAIL" if ov else "PASS",
            "; ".join(f"{o['scene']}/{o['type']} {o['text'][:30]!r}" for o in ov) if ov else "every text fits")
    except Exception as e:  # noqa: BLE001
        add("layout.overflow", "FAIL", f"layout check failed: {e}")
    from . import sync_check
    from .timeline import build_timeline, estimated_timing
    tm = estimated_timing(sb)
    tl = build_timeline({**cfg, "formats": [prev["format"]]}, tm)
    sync = sync_check.evaluate(tl.resolved, tm["words"], tl.duration)
    metrics["sync"] = {k: sync[k] for k in ("longest_static_s", "static_share_pct", "static", "early_numbers")}
    add("storyboard.narration_sync", sync["status"], sync_check.summary(sync))
    types = {b["type"] for s in sb["scenes"] for b in s["blocks"]}
    add("storyboard.variety", "PASS" if len(types) >= 5 else "WARN", f"{len(types)} distinct block types: {sorted(types)}")
    bd = [s.get("backdrop", "glow") for s in sb["scenes"]]
    run = max((len(list(g)) for _, g in __import__("itertools").groupby(bd)), default=0)
    add("storyboard.backdrop_rhythm", "PASS" if run <= 3 else "WARN", f"longest run of the same backdrop: {run} scenes ({bd})")
    status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else ("WARN" if any(c["status"] == "WARN" for c in checks) else "PASS")
    storyboard_hash = saved_storyboard_hash(prod_dir)
    rep = {"status": status, "storyboard_hash": storyboard_hash, "checks": checks, "metrics": metrics,
           "contact_sheet": prev["contact_sheet"]}
    atomic_write_json(prod_dir / "preview/gate.json", rep)
    md = [f"# Storyboard preview gate: **{status}**", "", f"Contact sheet: `{prev['contact_sheet']}` (estimated timings)", "",
          "| Check | Status | Detail |", "|---|---|---|"]
    md += [f"| `{c['id']}` | {c['status']} | {c['detail'].replace('|', '/')[:220]} |" for c in checks]
    md += ["", "A person must review the contact sheet and approve the preview before the full render:",
           "`uv run video-pipeline production approve-preview --id <P> --reviewer \"Name\"`"]
    atomic_write_text(prod_dir / "preview/GATE.md", "\n".join(md) + "\n")
    return rep
