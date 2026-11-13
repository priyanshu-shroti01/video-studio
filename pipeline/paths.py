"""Workspace-confined paths, hashing and atomic writes.

Every path that comes from configuration goes through `safe_path`, which resolves symlinks and
refuses anything outside the approved roots (path traversal / absolute-path injection)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .errors import PathError, ResourceError

ROOT = Path(os.environ.get("VIDEO_PIPELINE_ROOT", Path(__file__).resolve().parent.parent)).resolve()
STATE_DIR = ROOT / ".pipeline"          # registry.db, bundles, caches, tmp
OUTPUT_DIR = ROOT / "output"            # one directory per job, never overwritten
TMP_DIR = STATE_DIR / "tmp"
CACHE_DIR = STATE_DIR / "cache"

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def approved_roots() -> list[Path]:
    return [ROOT]


def safe_path(p: str | os.PathLike, *, must_exist: bool = False, roots: list[Path] | None = None) -> Path:
    """Resolve `p` (relative to ROOT) and require it to stay inside an approved root."""
    if p is None or str(p).strip() == "":
        raise PathError("empty path")
    if "\x00" in str(p):
        raise PathError("NUL byte in path")
    raw = Path(p)
    full = (raw if raw.is_absolute() else ROOT / raw).resolve()
    roots = roots or approved_roots()
    if not any(full == r or r in full.parents for r in roots):
        raise PathError(f"path escapes the workspace: {p}", detail=str(full))
    if must_exist and not full.exists():
        raise PathError(f"missing file: {p}", detail=str(full))
    return full


def safe_name(name: str) -> str:
    if not SAFE_NAME.match(name or ""):
        raise PathError(f"unsafe name {name!r}: use letters, digits, '.', '_' or '-' (max 100)")
    return name


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def ensure_dirs() -> None:
    for d in (STATE_DIR, OUTPUT_DIR, TMP_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)


def tmp_path_near(dst: Path, suffix: str = "") -> Path:
    """A temp file in the destination's directory, so the final os.replace is atomic (same filesystem)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=suffix or dst.suffix, dir=dst.parent)
    os.close(fd)
    return Path(name)


def atomic_write_bytes(dst: Path, data: bytes) -> None:
    tmp = tmp_path_near(dst)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(dst: Path, text: str) -> None:
    atomic_write_bytes(dst, text.encode("utf-8"))


def atomic_write_json(dst: Path, obj) -> None:
    atomic_write_text(dst, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def publish_file(src: Path, dst: Path, *, overwrite: bool = False) -> None:
    """Move a finished temp file into place atomically; refuse to clobber unless asked."""
    if dst.exists() and not overwrite:
        raise PathError(f"refusing to overwrite existing output: {rel(dst)}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def free_gb(path: Path = ROOT) -> float:
    return shutil.disk_usage(path).free / 1e9


def require_free_space(min_gb: float, path: Path = ROOT) -> float:
    free = free_gb(path)
    if free < min_gb:
        raise ResourceError(f"only {free:.1f} GB free on disk; this job needs at least {min_gb:.1f} GB",
                            detail="free space with `video-pipeline clean --dry-run` or lower the job's formats")
    return free
