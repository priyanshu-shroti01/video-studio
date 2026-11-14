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
# footage.legibility: recorded UI text must be readable at the size the film shows it. Measured on the OCR line box
# (Apple Vision: ascender to descender, about the font's em size) of each readable line inside a footage viewport or
# callout panel, as a fraction of the frame height, because that is what scales with the screen it is watched on.
# * 9:16 is watched full screen on a phone: 1920 px span ~14-15 cm (6.1-6.7" phones, ~844 pt tall). Apple's smallest
#   readable text style is 11-12 pt, i.e. 1.3-1.4 % of the screen height; caption-safe UI text starts at ~1.5 %
#   (28.8 px of 1920, a ~28 px line box). Below that the viewer sees texture, not words -> FAIL (blocking).
# * 16:9 is watched on a laptop / TV, or embedded: 1.1 % (12 px of 1080, ~2 mm on a 13" laptop full screen) is the
#   floor of comfortable reading -> WARN (advisory; desktop viewers can lean in or go full screen).
LEGIBILITY = {"short": (0.015, FAIL, True), "landscape": (0.011, WARN, False)}
LEGIBLE_MIN_CHARS = 3        # a "line" needs >= 3 letters/digits (icons, bullets and single glyphs are not reading)
LEGIBLE_MIN_CONF = 0.5


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


def frame_at(video: Path, t: float, out: Path, size: tuple[int, int] | None = None) -> Path:
    """The frame shown at second `t` (time-based, so any fps works). `size`: downscale to the design size first
    (2x "ultra" renders), so OCR, crops and pixel thresholds all work in the manifest's coordinates."""
    vf = ["-vf", f"scale={size[0]}:{size[1]}:flags=area"] if size else []
    procs.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1", *vf,
               str(out)], timeout=60)
    return out


def video_size(video: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True, timeout=30).stdout.strip()
    w, h = map(int, out.split(",")[:2])
    return w, h


def qa_frame_size(video_wh: tuple[int, int], design_wh: tuple[int, int]) -> tuple[int, int] | None:
    """QA works in design units (the layout manifest's 1080-wide coordinates). A render at an integer scale of the
    design size is downscaled to it before any OCR/pixel check -> returns the target size; None = use as is."""
    vw, vh = video_wh
    dw, dh = design_wh
    if (vw, vh) == (dw, dh):
        return None
    if vw % dw or vh % dh or vw // dw != vh // dh:
        raise ValueError(f"video {vw}x{vh} is not an integer scale of the design size {dw}x{dh}")
    return dw, dh


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


def _footage_rects(sc: dict, t: float) -> list[dict]:
    """Where the recorded UI the viewer is meant to read is drawn at t: the callout panels that are up at t (the clip
    behind a callout is dimmed context), else the footage viewports."""
    views, lenses = [], []
    for b in sc["blocks"]:
        if not (b["visible"]["from"] <= t <= b["visible"]["to"]):
            continue
        for md in b.get("media", []):
            views.append(md["bbox"])
            lenses += [c["bbox"] for c in md.get("callouts", []) if c["from"] <= t < c["to"]]
    return lenses or views


def footage_sample_times(sc: dict) -> list[float]:
    """Settled times to judge a footage scene's legibility: each zoom move's end, each callout once it has popped in,
    and the scene's settled end (as frame_checks). Without zoom data: three evenly spaced times in the visible window."""
    ts: set[float] = set()
    for b in sc["blocks"]:
        for md in b.get("media", []):
            v0, v1 = b["visible"]["from"] + 0.3, b["visible"]["to"] - 0.2
            cand = [t + 0.05 for t in md.get("settle", [])]
            cand += [c["from"] + 0.5 for c in md.get("callouts", []) if c["from"] + 0.5 < c["to"]]
            if not md.get("settle") and not md.get("callouts"):
                cand += [v0 + (v1 - v0) * f for f in (0.2, 0.5, 0.8)]
            cand.append(max(v0, sc["end"] - 0.4))
            ts |= {round(t, 2) for t in cand if v0 <= t <= v1}
    return sorted(ts)


def legibility_stats(items, rects: list[dict], frame_h: float) -> dict | None:
    """Median OCR line height (px and fraction of the frame height) of the readable lines whose centre lies inside
    `rects` (footage viewports / callout panels). None when no readable line is there."""
    hs = sorted(b.h for b in items if b.conf >= LEGIBLE_MIN_CONF and len(re.sub(r"[^0-9A-Za-z]", "", b.text)) >= LEGIBLE_MIN_CHARS
                and _center_in((b.x, b.y, b.w, b.h), rects))
    if not hs:
        return None
    med = float(np.median(hs))
    return {"lines": len(hs), "median_px": round(med, 1), "median_frac": round(med / frame_h, 4)}


def legibility_check(per_scene: dict[str, list[dict | None]], fmt: str, frame_h: float) -> Check:
    """footage.legibility from per-scene sample stats (legibility_stats per settled sample). A scene's value is the
    median of its samples' medians; it fails (9:16, blocking) / warns (16:9) below LEGIBILITY[fmt]."""
    frac, bad_status, blocking = LEGIBILITY.get(fmt, LEGIBILITY["landscape"])
    need = frac * frame_h
    low, parts, empty = [], [], []
    for sid, samples in per_scene.items():
        got = [s for s in samples if s]
        if not got:
            empty.append(sid)
            continue
        med = float(np.median([s["median_px"] for s in got]))
        parts.append(f"{sid} {med:.1f}px ({med / frame_h:.2%}, {len(got)} samples, {sum(s['lines'] for s in got)} lines)")
        if med < need:
            low.append(parts[-1])
    head = f"needs >= {need:.1f}px ({frac:.1%} of {frame_h:.0f})"
    if low:
        return Check("footage.legibility", "visual", bad_status, blocking,
                     f"recorded UI text too small to read in {fmt} ({head}): " + "; ".join(low) +
                     " (re-record with a larger uiScale, use fit 'fill' / callouts, or zoom closer)")
    if empty and not parts:
        return Check("footage.legibility", "visual", WARN, False, f"no readable UI text found inside the footage ({', '.join(empty)})")
    return Check("footage.legibility", "visual", PASS, blocking, f"recorded UI text readable ({head}): " + "; ".join(parts) +
                 (f"; no readable text in {', '.join(empty)}" if empty else ""))


def footage_legibility(m: dict, video: Path, fmt: str, workdir: Path,
                       size: tuple[int, int] | None = None) -> tuple[Check | None, dict]:
    """OCR the footage scenes at their settled sample times and judge the size of the recorded UI text."""
    shots = []
    for i, sc in enumerate(m["scenes"]):
        if not any(b.get("media") for b in sc["blocks"]):
            continue
        for j, t in enumerate(footage_sample_times(sc)):
            shots.append((sc, t, frame_at(video, t, workdir / f"leg-{i:02d}-{j:02d}.png", size)))
    if not shots:
        return None, {}
    texts = ocr([p for _, _, p in shots])
    per: dict[str, list] = {}
    detail: dict = {}
    for sc, t, png in shots:
        st = legibility_stats(texts[str(png)]["items"], _footage_rects(sc, t), m["height"])
        per.setdefault(sc["id"], []).append(st)
        detail.setdefault(sc["id"], []).append({"t": t, **(st or {"lines": 0})})
    return legibility_check(per, fmt, m["height"]), detail


def _center_in(box: tuple, rects: list[dict]) -> bool:
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    return any(r["x"] <= cx <= r["x"] + r["w"] and r["y"] <= cy <= r["y"] + r["h"] for r in rects)


# Shorts / Reels / TikTok draw their UI over the bottom ~20 % (title, description, music) and a right-hand action
# rail; the rail is ~80–160 px wide depending on the app, so the check uses the narrowest common rail (10 % = 108 px of
# 1080: the classic 80 %-wide caption column ends exactly there). The new caption looks keep a 140 px side inset.
SHORTS_UI = {"bottomFrac": 0.2, "railFrac": 0.1}


def caption_ui_check(m: dict) -> Check:
    """The caption box the engine reserves (layout manifest `captionBand`) stays out of the platform UI zones."""
    b, W, H = m["captionBand"], m["width"], m["height"]
    bottom, right, left = b["y"] + b["h"], b["x"] + b["w"], b["x"]
    bad = []
    if bottom > H * (1 - SHORTS_UI["bottomFrac"]) + 0.5:
        bad.append(f"bottom edge at {bottom / H:.0%} of height (UI below {1 - SHORTS_UI['bottomFrac']:.0%})")
    if right > W * (1 - SHORTS_UI["railFrac"]) + 0.5 or left < W * SHORTS_UI["railFrac"] - 0.5:
        bad.append(f"column {left:.0f}–{right:.0f}px reaches the side rail (>{W * (1 - SHORTS_UI['railFrac']):.0f}px)")
    return Check("layout.caption_platform_ui", "visual", WARN if bad else PASS, False,
                 "; ".join(bad) if bad else f"captions inside {left:.0f}–{right:.0f}px, above {bottom / H:.0%} of height")


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
    if m.get("format") == "short":
        cs.append(caption_ui_check(m))
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


def frame_checks(m: dict, video: Path, theme: dict, workdir: Path,
                 size: tuple[int, int] | None = None) -> tuple[list[Check], dict]:
    """OCR + pixel checks on real frames at each block's settled time (`size`: see qa_frame_size)."""
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
            shots.append((sc, t, frame_at(video, t, workdir / f"vqa-{i:02d}-{j}.png", size)))
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
        on = frame_at(video, (a + b_) / 2, workdir / "vqa-wm-on.png", size)
        cov_on = content_coverage(crop(rgb(on), wm["bbox"]), bg)
        gaps = [(x[1], y[0]) for x, y in zip(wm["visibleRanges"], wm["visibleRanges"][1:]) if y[0] - x[1] > 0.8]
        cov_off = None
        if gaps:
            off = frame_at(video, (gaps[0][0] + gaps[0][1]) / 2, workdir / "vqa-wm-off.png", size)
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
    size = qa_frame_size(video_size(video), (m["width"], m["height"]))
    with tempfile.TemporaryDirectory(dir=job_out / "work") as td:
        fc, detail = frame_checks(m, video, theme, Path(td), size)
        leg, detail["footage_legibility"] = footage_legibility(m, video, fmt, Path(td), size)
    cs += fc + ([leg] if leg else [])
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
