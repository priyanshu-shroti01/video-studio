"""Visual & brand QA driven by the engine's layout manifest (scripts/engine-layout.mjs).

The renderer knows exactly where every text, logo and watermark should be, so most layout problems are
checked deterministically from the manifest. The rendered frames are then verified where it matters:
on-device OCR (Apple Vision) confirms prices/URLs/CTAs/titles are actually legible at their boxes, and
pixel analysis confirms logo presence/colour and watermark presence/suppression.

Statuses follow pipeline/qa.py (PASS/WARN/FAIL; FAIL on a critical check blocks the job)."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .. import procs
from ..paths import ROOT, atomic_write_json
from ..qa import FAIL, PASS, WARN, Check
from .ocr import best_match, norm, ocr, price_match

LAYOUT_SCRIPT = ROOT / "scripts/engine-layout.mjs"
CAMERA_TOL = 18          # px: max camera displacement documented in docs/MOTION.md (push-in ≤ 15.9 px on Shorts)
FORBIDDEN_LABELS = re.compile(r"remotion|watermark|lorem|ipsum|sample text|placeholder|template|trial version|"
                              r"made with|preview only|unregistered|todo", re.I)
EXACT_ROLES = {"price", "url"}


def _intended_label_boxes(sc: dict, t: float) -> list[tuple]:
    """Boxes of on-screen copy the storyboard itself placed (from verified facts/copy) that contains a word on the
    forbidden list, e.g. a stack node named "Remotion renderer". Such text is the film's message, not a stray label."""
    out = []
    for b in sc["blocks"]:
        if not (b["visible"]["from"] <= t <= b["visible"]["to"]):
            continue
        for tx in b.get("texts", []):
            if FORBIDDEN_LABELS.search(tx.get("text", "")):
                bb = tx["bbox"]
                pad = CAMERA_TOL + 20
                out.append((bb["x"] - pad, bb["y"] - pad, bb["w"] + 2 * pad, bb["h"] + 2 * pad, tx["text"]))
    return out


def _is_intended(item, boxes: list[tuple]) -> bool:
    """OCR text is intended copy only if it lies inside such a box AND its forbidden word is in that box's text."""
    words = {w.lower() for w in FORBIDDEN_LABELS.findall(item.text)}
    for x, y, w, h, text in boxes:
        if _center_in((item.x, item.y, item.w, item.h), [{"x": x, "y": y, "w": w, "h": h}]) and \
                words <= {m.lower() for m in FORBIDDEN_LABELS.findall(text)}:
            return True
    return False


def layout_manifest(props_file: Path) -> dict:
    r = procs.run(["node", str(LAYOUT_SCRIPT), str(props_file)], cwd=ROOT, timeout=120)
    txt = r.output[r.output.index("{"):]
    return json.loads(txt)


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def frame_at(video: Path, t: float, out: Path) -> Path:
    procs.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1", str(out)],
              timeout=60)
    return out


def rgb(png: Path) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, timeout=60)
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(png)], capture_output=True, text=True, timeout=30).stdout.strip()
    w, h = map(int, info.split(",")[:2])
    return np.frombuffer(p.stdout, np.uint8).reshape(h, w, 3).astype(float)


def crop(img: np.ndarray, b: dict, pad: float = 0) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0 = int(max(0, b["x"] - pad)), int(max(0, b["y"] - pad))
    x1, y1 = int(min(w, b["x"] + b["w"] + pad)), int(min(h, b["y"] + b["h"] + pad))
    return img[y0:y1, x0:x1]


def content_coverage(region: np.ndarray, bg: np.ndarray) -> float:
    """Fraction of pixels clearly different from the local background colour."""
    if region.size == 0:
        return 0.0
    d = np.linalg.norm(region - bg, axis=2)
    return float((d > 45).mean())


def color_presence(region: np.ndarray, color: np.ndarray, tol: float = 60) -> float:
    if region.size == 0:
        return 0.0
    return float((np.linalg.norm(region - color, axis=2) < tol).mean())


def _rect_inside(b: dict, area: dict, tol: float = 2) -> bool:
    return (b["x"] >= area["x"] - tol and b["y"] >= area["y"] - tol and
            b["x"] + b["w"] <= area["x"] + area["w"] + tol and b["y"] + b["h"] <= area["y"] + area["h"] + tol)


def _intersects(a: dict, b: dict) -> bool:
    return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def _overlap_ranges(r1: list, r2: list) -> list:
    out = []
    for a0, a1 in r1:
        for b0, b1 in r2:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi - lo > 0.05:
                out.append((round(lo, 2), round(hi, 2)))
    return out


def _media_rects(sc: dict, t: float | None = None) -> list[dict]:
    """Video viewports (footage blocks) of a manifest scene, optionally only those visible at t."""
    return [md["bbox"] for b in sc["blocks"] for md in b.get("media", [])
            if t is None or b["visible"]["from"] <= t <= b["visible"]["to"]]


def _center_in(box: tuple, rects: list[dict]) -> bool:
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    return any(r["x"] <= cx <= r["x"] + r["w"] and r["y"] <= cy <= r["y"] + r["h"] for r in rects)


def static_checks(m: dict) -> list[Check]:
    cs: list[Check] = []
    overflow, outside, in_caption, aspect_bad = [], [], [], []
    media_bad, media_n = [], 0
    logo_windows = []
    for sc in m["scenes"]:
        for b in sc["blocks"]:
            for t in b.get("texts", []):
                if t.get("overflow"):
                    overflow.append(f"{sc['id']}/{b['type']}: {t['text'][:40]!r} needs {t['estWidth']:.0f}px of {t['maxWidth']:.0f}px")
            if not _rect_inside(b["bbox"], m["safeArea"], tol=CAMERA_TOL):
                outside.append(f"{sc['id']}/{b['type']}")
            if _intersects(b["bbox"], m["captionBand"]):
                in_caption.append(f"{sc['id']}/{b['type']}")
            for lg in b.get("logos", []):
                if lg.get("expectedAspect") and abs(lg["aspect"] - lg["expectedAspect"]) / lg["expectedAspect"] > 0.03:
                    aspect_bad.append(f"{sc['id']}: {lg['variant']} box {lg['aspect']:.3f} vs file {lg['expectedAspect']:.3f}")
                logo_windows.append((b["visible"]["from"], b["visible"]["to"]))
            for md in b.get("media", []):
                media_n += 1
                if md.get("expectedAspect") and abs(md["aspect"] - md["expectedAspect"]) / md["expectedAspect"] > 0.01:
                    media_bad.append(f"{sc['id']}: {md['asset']} box {md['aspect']:.3f} vs clip {md['expectedAspect']:.3f}")
    cs.append(Check("layout.text_overflow", "visual", FAIL if overflow else PASS, True,
                    "; ".join(overflow[:5]) if overflow else "every text fits its box"))
    cs.append(Check("layout.safe_area", "visual", FAIL if outside else PASS, True,
                    f"outside safe area: {outside}" if outside else "all blocks inside the safe area"))
    cs.append(Check("layout.caption_band", "visual", FAIL if in_caption else PASS, True,
                    f"blocks in caption band: {in_caption}" if in_caption else "caption band kept clear"))
    cs.append(Check("brand.logo_aspect", "branding", FAIL if aspect_bad else PASS, True,
                    "; ".join(aspect_bad) if aspect_bad else "every logo drawn at its intrinsic aspect"))
    if media_n:
        cs.append(Check("layout.media_aspect", "visual", FAIL if media_bad else PASS, True,
                        "; ".join(media_bad) if media_bad else f"{media_n} video viewport(s) at the clip's own aspect"))
    wm = m.get("watermark")
    if wm:
        dup = _overlap_ranges(wm["visibleRanges"], logo_windows + ([(m["brandBar"]["from"], m["brandBar"]["to"])]
                                                                   if m.get("brandBar") else []))
        cs.append(Check("brand.no_duplicate_branding", "branding", FAIL if dup else PASS, True,
                        f"watermark visible together with a logo at {dup}" if dup else
                        "watermark hidden whenever a logo/CTA/brand bar is on screen"))
        cs.append(Check("brand.watermark_safe", "branding",
                        PASS if not _intersects(wm["bbox"], m["captionBand"]) else FAIL, True,
                        f"watermark {wm['policy']} at {[round(v) for v in wm['bbox'].values()]}"))
    return cs


def ocr_engine_check(texts: dict[str, dict]) -> Check:
    """An OCR engine error must never read as "no text on screen": every OCR-based check would pass on no evidence."""
    errs = sorted({v["error"] for v in texts.values() if v.get("error")})
    n = sum(1 for v in texts.values() if v.get("error"))
    return Check("ocr.engine", "visual", FAIL if errs else PASS, True,
                 f"OCR failed on {n}/{len(texts)} frames (the OCR checks below have no evidence): {errs[0][:160]}" if errs
                 else f"OCR read all {len(texts)} sampled frames")


def frame_checks(m: dict, video: Path, theme: dict, workdir: Path) -> tuple[list[Check], dict]:
    """OCR + pixel checks on real frames at each block's settled time."""
    cs: list[Check] = []
    detail: dict = {"scenes": []}
    shots = []
    for i, sc in enumerate(m["scenes"]):
        # Sample when everything has settled: just before the scene's exit (counters finished, typing done,
        # CTA landed). Blocks that leave early (exitAt) get their own sample just before they leave.
        times = {round(max(sc["start"] + 0.5, sc["end"] - 0.4), 2)}
        for b in sc["blocks"]:
            if b["visible"]["to"] < sc["end"] - 0.5:
                times.add(round(max(b["visible"]["from"] + 0.3, b["visible"]["to"] - 0.4), 2))
        for j, t in enumerate(sorted(times)):
            shots.append((sc, t, frame_at(video, t, workdir / f"vqa-{i:02d}-{j}.png")))
    texts = ocr([p for _, _, p in shots])
    cs.append(ocr_engine_check(texts))
    brand = _hex(theme["colors"]["brand"])
    bg = _hex(theme["colors"]["bg"])
    wrong_exact, weak_titles, labels, logo_bad, footage_labels = [], [], [], [], []
    for sc, t, png in shots:
        items = texts[str(png)]["items"]
        img = rgb(png)
        sd = {"scene": sc["id"], "t": round(t, 2), "ocr": [b.text for b in items], "texts": []}
        for b in sc["blocks"]:
            if not (b["visible"]["from"] <= t <= b["visible"]["to"]):
                continue
            for tx in b.get("texts", []):
                bb = tx["bbox"]
                score, _ = best_match(tx["text"], items, (bb["x"], bb["y"], bb["w"], bb["h"]), pad=CAMERA_TOL + 20)
                role = tx.get("role", "body")
                sd["texts"].append({"text": tx["text"], "role": role, "score": round(score, 2)})
                if role == "price":
                    ok, why = price_match(tx["text"], items, (bb["x"], bb["y"], bb["w"], bb["h"]), pad=CAMERA_TOL + 20)
                    sd["texts"][-1]["price_check"] = why
                    if not ok:
                        wrong_exact.append(f"{sc['id']}: price {tx['text']!r} not shown ({why})")
                elif role in EXACT_ROLES and norm(tx["text"]) and score < 1.0:
                    wrong_exact.append(f"{sc['id']}: {role} {tx['text']!r} not read exactly (best {score:.2f})")
                elif role == "title" and len(norm(tx["text"])) >= 3 and score < 0.75:
                    weak_titles.append(f"{sc['id']}: {tx['text'][:40]!r} ({score:.2f})")
            for lg in b.get("logos", []):
                region = crop(img, lg["bbox"])
                cov = content_coverage(region, bg)
                col = color_presence(region, brand)
                clipped = not _rect_inside(lg["bbox"], {"x": 0, "y": 0, "w": m["width"], "h": m["height"]})
                ok = cov > 0.04 and col > 0.003 and not clipped
                if not ok:
                    logo_bad.append(f"{sc['id']}: {lg['variant']} coverage {cov:.3f} brand-colour {col:.4f}"
                                    f"{' clipped' if clipped else ''}")
        media = _media_rects(sc, t)
        intended = _intended_label_boxes(sc, t)
        for item in items:
            if FORBIDDEN_LABELS.search(item.text) and not _is_intended(item, intended):
                # text inside a footage viewport is the recorded product UI, not an engine label: advisory only
                (footage_labels if media and _center_in((item.x, item.y, item.w, item.h), media) else labels).append(f"{sc['id']}: {item.text!r}")
        detail["scenes"].append(sd)
    cs.append(Check("ocr.prices_urls_exact", "visual", FAIL if wrong_exact else PASS, True,
                    "; ".join(wrong_exact[:6]) if wrong_exact else "every price and URL read back exactly"))
    cs.append(Check("ocr.titles_legible", "visual", WARN if weak_titles else PASS, False,
                    "; ".join(weak_titles[:6]) if weak_titles else "titles legible"))
    cs.append(Check("ocr.no_template_labels", "branding", FAIL if labels else PASS, True,
                    f"unexpected labels: {labels}" if labels else "no template/preview/watermark labels in frame"))
    if footage_labels:
        cs.append(Check("ocr.footage_labels", "branding", WARN, False,
                        f"template-like words inside recorded footage (check the recording): {footage_labels[:6]}"))
    cs.append(Check("brand.logo_present", "branding", FAIL if logo_bad else PASS, True,
                    "; ".join(logo_bad) if logo_bad else "every expected logo present, in brand colour, unclipped"))
    wm = m.get("watermark")
    if wm and wm["visibleRanges"]:
        a, b_ = wm["visibleRanges"][0]
        on = frame_at(video, (a + b_) / 2, workdir / "vqa-wm-on.png")
        cov_on = content_coverage(crop(rgb(on), wm["bbox"]), bg)
        gaps = [(x[1], y[0]) for x, y in zip(wm["visibleRanges"], wm["visibleRanges"][1:]) if y[0] - x[1] > 0.8]
        cov_off = None
        if gaps:
            off = frame_at(video, (gaps[0][0] + gaps[0][1]) / 2, workdir / "vqa-wm-off.png")
            cov_off = content_coverage(crop(rgb(off), wm["bbox"]), bg)
        ok = cov_on > 0.03 and (cov_off is None or cov_off < cov_on * 0.6 or cov_off < 0.03)
        cs.append(Check("brand.watermark_render", "branding", PASS if ok else FAIL, True,
                        f"watermark coverage visible={cov_on:.3f} suppressed={cov_off if cov_off is None else round(cov_off, 3)}"))
    # palette consistency: saturated pixels should sit near the theme palette
    palette = [_hex(v) for v in (theme["colors"][k] for k in ("brand", "brandHover", "brandText", "success", "danger",
                                                             "warning", "info"))]
    off = []
    for sc, t, png in shots:
        full = rgb(png)
        for r in _media_rects(sc, t):            # recorded footage is not drawn in the brand palette
            x0, y0 = int(max(0, r["x"] - CAMERA_TOL)), int(max(0, r["y"] - CAMERA_TOL))
            full[y0:int(r["y"] + r["h"] + CAMERA_TOL), x0:int(r["x"] + r["w"] + CAMERA_TOL)] = _hex(theme["colors"]["bg"])
        img = full[::4, ::4].reshape(-1, 3)
        mx, mn = img.max(axis=1), img.min(axis=1)
        sat = img[(mx - mn) > 90]
        if len(sat) < 200:
            continue
        d = np.min(np.stack([np.linalg.norm(sat - c, axis=1) for c in palette]), axis=0)
        frac = float((d > 120).mean())
        if frac > 0.35:
            off.append(f"{sc['id']}: {frac:.0%} of saturated pixels off-palette")
    cs.append(Check("brand.palette", "branding", WARN if off else PASS, False,
                    "; ".join(off) if off else "saturated colours match the brand palette"))
    return cs, detail


def run_visual_qa(job_out: Path, fmt: str, props_file: Path, video: Path, theme: dict) -> list[Check]:
    m = layout_manifest(props_file)
    atomic_write_json(job_out / "metadata" / f"layout-{fmt}.json", m)
    cs = static_checks(m)
    with tempfile.TemporaryDirectory(dir=job_out / "work") as td:
        fc, detail = frame_checks(m, video, theme, Path(td))
    cs += fc
    atomic_write_json(job_out / "reports" / f"visual-qa-{fmt}.json",
                      {"format": fmt, "checks": [c.__dict__ for c in cs], "ocr": detail})
    return cs


def write_branding_report(job_out: Path, per_fmt: dict[str, list[Check]]) -> dict:
    rep = {"checks": [{"format": f, **c.__dict__} for f, cs in per_fmt.items() for c in cs
                      if c.category == "branding"]}
    rep["status"] = "FAIL" if any(c["status"] == FAIL for c in rep["checks"]) else (
        "WARN" if any(c["status"] == WARN for c in rep["checks"]) else "PASS")
    atomic_write_json(job_out / "reports" / "branding-report.json", rep)
    return rep
