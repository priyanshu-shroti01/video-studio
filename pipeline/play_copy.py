"""Studio play copies: the same H.264 picture with the audio as Opus, for in-app playback.

Some embedded browsers (VS Code's built-in browser, other Electron webviews) ship without the licensed AAC decoder,
so a final MP4 plays there with picture but no sound. Opus decodes everywhere. The copy keeps the video stream
byte for byte (`-c:v copy`) and only re-encodes the audio. It lives in output/_play/, outside every job folder, so
the approved package, its hashes and the files people download are untouched.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
from pathlib import Path

from .paths import ROOT

PLAY_DIR = ROOT / "output" / "_play"
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _key(src: Path) -> str:
    st = src.stat()
    return hashlib.sha256(f"{src.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:20]


def play_copy(src: Path, *, play_dir: Path | None = None, timeout: int = 300) -> Path | None:
    """The Opus-audio play copy of `src` (made once, then cached by the source's path, size and mtime).
    Returns None when it can't be made; callers then play the original."""
    src = Path(src)
    if not src.is_file() or not shutil.which("ffmpeg"):
        return None
    d = Path(play_dir) if play_dir else PLAY_DIR
    key = _key(src)
    dst = d / f"{key}.mp4"
    if dst.exists():
        return dst
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if dst.exists():
            return dst
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{key}.part.mp4"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
                            "-c:v", "copy", "-c:a", "libopus", "-b:a", "128k", "-movflags", "+faststart", str(tmp)],
                           capture_output=True, timeout=timeout)
        if r.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(dst)
    return dst
