"""Pre-flight checks before heavy work (render, QA): is this Mac able to do it *right now*?

Checks free memory + swap (vm_stat / sysctl vm.swapusage), free disk under output/, that ffmpeg/ffprobe are
installed and that the Apple Vision OCR tool answers (one tiny generated image; a success is cached for 10
minutes in .pipeline/cache/). Hard problems raise PreflightError (code PREFLIGHT) with a plain `hint`; soft
ones are logged as warnings. Typical cost: well under a second (OCR probe ~0.3 s, then cached).

Skip with VIDEO_PREFLIGHT=0 (tests / CI). The system readers below are module-level functions so tests can
monkeypatch them."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .errors import PreflightError
from .paths import CACHE_DIR, OUTPUT_DIR

# thresholds
HARD_MIN_DISK_GB = 2.0
SOFT_MIN_DISK_GB = 5.0
HARD_SWAP_PCT, HARD_MIN_AVAIL_MB = 90.0, 1024.0     # both must hold: swap nearly full AND little memory left
SOFT_SWAP_PCT, SOFT_MIN_AVAIL_MB = 75.0, 1536.0     # either one: warn
OCR_CACHE_S = 600
OCR_TIMEOUT_S = 20
OCR_FILE = "preflight-ocr.json"
OCR_IMAGE = "preflight-ocr.png"

_log = logging.getLogger("pipeline.preflight")
_mem_ocr_cache: dict = {}


@dataclass
class Problem:
    check: str
    hint: str
    action: str | None = None


@dataclass
class Report:
    stage: str
    skipped: bool = False
    hard: list[Problem] = field(default_factory=list)
    soft: list[Problem] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.hard


# ---- system readers (monkeypatched in tests) ----------------------------------------------------------
def enabled() -> bool:
    return os.environ.get("VIDEO_PREFLIGHT", "1").strip().lower() not in ("0", "false", "no", "off")


def read_memory() -> dict | None:
    """{"available_mb", "swap_used_mb", "swap_total_mb"}; None where vm_stat isn't available (not macOS)."""
    if sys.platform != "darwin" or not shutil.which("vm_stat"):
        return None
    from .system import _run, mem_snapshot
    snap = mem_snapshot()
    sw = _run(["sysctl", "-n", "vm.swapusage"])
    total = re.search(r"total = ([\d.]+)M", sw)
    return {"available_mb": snap.available_mb, "swap_used_mb": snap.swap_used_mb,
            "swap_total_mb": float(total.group(1)) if total else 0.0}


def read_disk_free_gb(path: Path) -> float:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free / 2**30


def which(name: str) -> str | None:
    return shutil.which(name)


def ocr_tool() -> Path | None:
    """The compiled Vision OCR tool if it exists (never compiles here: that can take a minute)."""
    from .paths import sha256_file
    from .visual_qa import ocr as O
    exe = O.BIN_DIR / f"ocr-{sha256_file(O.SRC)[:12]}"
    return exe if exe.exists() else None


def run_ocr(exe: Path, image: Path) -> tuple[bool, str, list[str]]:
    """-> (tool worked, error text, recognised strings)."""
    try:
        r = subprocess.run([str(exe), str(image)], capture_output=True, text=True, timeout=OCR_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"no answer within {OCR_TIMEOUT_S}s", []
    except OSError as e:
        return False, str(e), []
    if r.returncode != 0:
        return False, (r.stderr or f"exit {r.returncode}").strip()[-300:], []
    texts, err = [], ""
    for line in r.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        err = err or (d.get("error") or "")
        texts += [i.get("text", "") for i in d.get("items", [])]
    return (not err), err, texts


# ---- the probe image: "OCR" in a 5x7 pixel font, pure Python (no Pillow, no ffmpeg drawtext) -----------
_GLYPHS = {"O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
           "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
           "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"]}


def probe_png(text: str = "OCR", scale: int = 10, pad: int = 2) -> bytes:
    cols, rows = len(text) * 6 - 1 + 2 * pad, 7 + 2 * pad
    grid = [[0] * cols for _ in range(rows)]
    for i, ch in enumerate(text):
        for y, row in enumerate(_GLYPHS[ch]):
            for x, c in enumerate(row):
                if c == "1":
                    grid[pad + y][pad + i * 6 + x] = 1
    w, h = cols * scale, rows * scale
    raw = b"".join(b"\x00" + bytes(0 if grid[y // scale][x // scale] else 255 for x in range(w)) for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _ocr_check(rep: Report, now: float) -> None:
    exe = ocr_tool()
    if exe is None:
        if not which("swiftc"):
            rep.hard.append(Problem("ocr", "Checking the text on screen needs Apple's Command Line Tools. Install "
                                           "them with `xcode-select --install`, then try again."))
        else:
            rep.soft.append(Problem("ocr", "the OCR tool is not built yet; QA compiles it on first use (about a minute)"))
        return
    cache_f = CACHE_DIR / OCR_FILE
    cached = _mem_ocr_cache.get(exe.name)
    if cached is None:
        try:
            d = json.loads(cache_f.read_text())
            cached = d["at"] if d.get("tool") == exe.name and d.get("ok") else None
        except (OSError, ValueError, KeyError):
            cached = None
    if cached is not None and now - cached < OCR_CACHE_S:
        rep.facts["ocr"] = "ok (cached)"
        return
    img = CACHE_DIR / OCR_IMAGE
    if not img.exists():
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(probe_png())
    ok, err, texts = run_ocr(exe, img)
    if not ok:
        rep.facts["ocr"] = f"failed: {err}"
        rep.hard.append(Problem("ocr", "Your Mac's text recognition (OCR) isn't responding, usually because memory "
                                       "is very tight. Close other apps or restart the Mac, then try again.", "retry"))
        return
    rep.facts["ocr"] = "ok"
    if not any(re.sub(r"[^A-Z0-9]", "", t.upper()) for t in texts):
        rep.soft.append(Problem("ocr", "the OCR tool ran but read no text from its test image"))
    _mem_ocr_cache[exe.name] = now
    try:
        cache_f.parent.mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps({"tool": exe.name, "ok": True, "at": now}))
    except OSError:
        pass


# ---- the check ------------------------------------------------------------------------------------------
def check(stage: str, *, out_dir: Path = OUTPUT_DIR, need_ocr: bool = True,
          min_disk_gb: float = HARD_MIN_DISK_GB) -> Report:
    """Run every check and return the report (never raises for a problem; see preflight())."""
    t0 = time.monotonic()
    rep = Report(stage)
    if not enabled():
        rep.skipped = True
        return rep
    # disk
    try:
        free = read_disk_free_gb(out_dir)
        rep.facts["disk_free_gb"] = round(free, 1)
        if free < min_disk_gb:
            rep.hard.append(Problem("disk", f"Only {free:.1f} GB of disk space is free and at least {min_disk_gb:.0f} GB "
                                            "is needed. Free up space (empty the Trash, or archive old videos), then "
                                            "try again.", "free-disk"))
        elif free < SOFT_MIN_DISK_GB:
            rep.soft.append(Problem("disk", f"only {free:.1f} GB disk free under {out_dir}"))
    except OSError as e:
        rep.soft.append(Problem("disk", f"could not read free disk space: {e}"))
    # memory + swap
    mem = read_memory()
    if mem is not None:
        avail, used, total = mem["available_mb"], mem["swap_used_mb"], mem["swap_total_mb"]
        pct = 100.0 * used / total if total > 0 else 0.0
        rep.facts.update(available_mb=round(avail), swap_used_mb=round(used), swap_pct=round(pct, 1))
        if pct >= HARD_SWAP_PCT and avail < HARD_MIN_AVAIL_MB:
            rep.hard.append(Problem("memory", f"Your Mac is almost out of memory ({avail / 1024:.1f} GB free, backup "
                                              f"memory {pct:.0f}% full). Close other apps or restart the Mac, then try "
                                              "again.", "close-apps"))
        elif pct >= SOFT_SWAP_PCT or avail < SOFT_MIN_AVAIL_MB:
            rep.soft.append(Problem("memory", f"memory is tight: {avail:.0f} MB available, swap {pct:.0f}% used "
                                              f"({used:.0f} MB); close apps if the {stage} is slow"))
    # ffmpeg
    missing = [n for n in ("ffmpeg", "ffprobe") if not which(n)]
    if missing:
        rep.hard.append(Problem("ffmpeg", f"{' and '.join(missing)} isn't installed, and the studio needs it to make "
                                          "videos. Install it with `brew install ffmpeg`, then try again."))
    # OCR (Apple Vision, macOS only)
    if need_ocr and sys.platform == "darwin":
        _ocr_check(rep, time.time())
    rep.seconds = round(time.monotonic() - t0, 3)
    return rep


def preflight(stage: str, *, out_dir: Path = OUTPUT_DIR, need_ocr: bool = True, min_disk_gb: float = HARD_MIN_DISK_GB,
              log: Callable | None = None) -> Report:
    """check() + act on it: log soft problems as warnings, raise PreflightError for hard ones."""
    rep = check(stage, out_dir=out_dir, need_ocr=need_ocr, min_disk_gb=min_disk_gb)
    if rep.skipped:
        return rep

    def say(msg: str, level: str) -> None:
        if log is not None:
            log(msg, level)
        else:
            getattr(_log, "warning" if level == "warn" else level)(msg)
    for p in rep.soft:
        say(f"preflight ({stage}): {p.check}: {p.hint}", "warn")
    if rep.hard:
        first = rep.hard[0]
        raise PreflightError(
            f"pre-flight check failed before {stage}: {', '.join(p.check for p in rep.hard)}",
            detail="\n".join(f"{k}: {v}" for k, v in rep.facts.items()) or None,
            hint=" ".join(p.hint for p in rep.hard), action=first.action)
    if rep.seconds > 1.0:
        say(f"preflight ({stage}) took {rep.seconds:.1f}s", "info")
    return rep


__all__ = ["Problem", "Report", "check", "preflight", "enabled", "probe_png"]
