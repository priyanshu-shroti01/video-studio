"""On-device OCR (Apple Vision via a tiny Swift tool) + tolerant text matching.

The tool is compiled from tools/ocr/ocr.swift on first use (swiftc, Xcode Command Line Tools) and cached
in .pipeline/bin/ keyed by the source hash. Nothing leaves the machine; no model download."""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..errors import PipelineError
from ..paths import ROOT, STATE_DIR, sha256_file

SRC = ROOT / "tools/ocr/ocr.swift"
BIN_DIR = STATE_DIR / "bin"


@dataclass
class TextBox:
    text: str
    conf: float
    x: float
    y: float
    w: float
    h: float


def ocr_bin() -> Path:
    tag = sha256_file(SRC)[:12]
    exe = BIN_DIR / f"ocr-{tag}"
    if exe.exists():
        return exe
    if not shutil.which("swiftc"):
        raise PipelineError("swiftc not found (install Xcode Command Line Tools) — OCR QA unavailable")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = exe.with_suffix(".tmp")
    r = subprocess.run(["swiftc", "-O", str(SRC), "-o", str(tmp)], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise PipelineError("could not compile the OCR tool", detail=r.stderr[-1500:])
    tmp.replace(exe)
    return exe


def ocr(images: list[Path], _retry: bool = True) -> dict[str, dict]:
    """-> {path: {"width", "height", "items": [TextBox]}}"""
    if not images:
        return {}
    r = subprocess.run([str(ocr_bin()), *map(str, images)], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise PipelineError("OCR failed", detail=r.stderr[-1000:])
    out = {}
    for line in r.stdout.splitlines():
        d = json.loads(line)
        out[d["file"]] = {"width": d.get("width"), "height": d.get("height"), "error": d.get("error"),
                          "items": [TextBox(**i) for i in d.get("items", [])]}
    failed = [Path(k) for k, v in out.items() if v["error"]]
    if failed and _retry:          # Vision can fail transiently (model load under memory pressure): retry once
        time.sleep(2.0)
        out.update(ocr(failed, _retry=False))
    return out


HOMOGLYPHS = str.maketrans("оаесрхуміОАЕСРХМТВНК", "oaecpxymiOAECPXMTBHK")   # Cyrillic look-alikes OCR returns


def norm(s: str) -> str:
    # Vision reads the rupee sign as ₴ (hryvnia) on these fonts: treat both as the same currency token
    # Vision reads the rupee sign as "₴" or "R" on these fonts: map all to one currency token
    s = unicodedata.normalize("NFKC", s).translate(HOMOGLYPHS).replace("₹", "¤").replace("₴", "¤").replace("’", "'")
    s = re.sub(r"(?<![A-Za-z])R(?=\s?\d)", "¤", s)
    return re.sub(r"[^a-z0-9¤]+", "", s.lower())


def best_match(expected: str, boxes: list[TextBox], region: tuple[float, float, float, float] | None = None,
               pad: float = 40) -> tuple[float, TextBox | None]:
    """Similarity (0..1) of the expected string with the best OCR line (or concatenation of lines in region)."""
    e = norm(expected)
    if not e:
        return 1.0, None
    cands = boxes
    if region:
        x, y, w, h = region
        cands = [b for b in boxes if b.x + b.w >= x - pad and b.x <= x + w + pad and b.y + b.h >= y - pad and b.y <= y + h + pad]
    best, hit = 0.0, None
    for b in cands:
        t = norm(b.text)
        if e in t:
            return 1.0, b
        sm = difflib.SequenceMatcher(None, e, t)
        # longest matching block relative to expected length tolerates icon glyphs read as letters
        m = max((blk.size for blk in sm.get_matching_blocks()), default=0) / len(e)
        r = max(sm.ratio(), m)
        if r > best:
            best, hit = r, b
    if region and len(cands) > 1:                                  # multi-line text in one box
        joined = norm(" ".join(b.text for b in sorted(cands, key=lambda b: (round(b.y / 20), b.x))))
        if e in joined:
            return 1.0, cands[0]
    return best, hit


def _numbers(text: str) -> list[str]:
    """Numbers as displayed. A number right after a currency glyph is taken verbatim; a bare number whose
    first digit is '2' may be a misread rupee sign (Vision reads ₹ as 2/·/₴/R in some fonts) — both readings
    are returned so the caller can require the exact expected value."""
    t = unicodedata.normalize("NFKC", text).translate(HOMOGLYPHS).replace("₹", "¤").replace("₴", "¤")
    t = re.sub(r"(?<![A-Za-z])R(?=\s?\d)", "¤", t)
    out = []
    for m in re.finditer(r"(¤\s?)?(\d[\d,]*(?:\.\d+)?)", t):
        num = m.group(2).replace(",", "")
        out.append(("glyph", num) if m.group(1) else ("bare", num))
    return out


def price_match(expected: str, boxes: list[TextBox], region, pad: float = 40) -> tuple[bool, str]:
    """Strict on the digits: every number in `expected` must be read in the region exactly."""
    want = [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", expected)]
    if not want:
        s, _ = best_match(expected, boxes, region, pad)
        return s >= 0.9, f"text match {s:.2f}"
    x, y, w, h = region
    cands = [b for b in boxes if b.x + b.w >= x - pad and b.x <= x + w + pad and b.y + b.h >= y - pad and b.y <= y + h + pad]
    seen = set()
    for b in cands:
        for kind, num in _numbers(b.text):
            seen.add(num)
            if kind == "bare" and num.startswith("2") and any(len(num) == len(wn) + 1 for wn in want):
                seen.add(num[1:])                     # leading '2' = misread ₹ (only exactly one extra digit)
    ok = all(wn in seen for wn in want)
    return ok, f"wanted {want}, read {sorted(seen)} in {[b.text for b in cands][:4]}"
