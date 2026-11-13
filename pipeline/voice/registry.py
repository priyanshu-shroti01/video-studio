"""Local voice model registry: what each model file is, where it came from, its sha256 and licence.

`registry.json` is the source of truth. Files live under models/voice/ (git-ignored). `require()` checks
presence + sha256 (hashed once per process per file state) and raises a clear, non-transient
TTSError naming the fetch command when something is missing or modified.

    uv run python -m pipeline.voice.registry status
    uv run python -m pipeline.voice.registry fetch kokoro|piper|whisper|all
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from functools import lru_cache
from pathlib import Path

from ..errors import TTSError
from ..paths import ROOT

REGISTRY = Path(__file__).with_name("registry.json")
MODELS_DIR = Path(os.environ.get("VIDEO_PIPELINE_VOICE_MODELS") or ROOT / "models" / "voice")
FETCH_HINT = "uv run python -m pipeline.voice.registry fetch {group}"
_verified: dict[tuple[str, int, int], str] = {}


class ModelMissing(TTSError):
    code = "VOICE_MODEL_MISSING"


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(REGISTRY.read_text())


def files(group: str) -> list[dict]:
    return [f for f in load()["files"] if f["group"] == group]


def entry(file_id: str) -> dict:
    for f in load()["files"]:
        if f["id"] == file_id:
            return f
    raise KeyError(file_id)


def path(f: dict | str) -> Path:
    f = entry(f) if isinstance(f, str) else f
    return MODELS_DIR / f["path"]


def voices(provider: str) -> dict[str, dict]:
    return load()["voices"].get(provider, {})


def sha256(p: Path) -> str:
    st = p.stat()
    k = (str(p), st.st_size, st.st_mtime_ns)
    if k not in _verified:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _verified[k] = h.hexdigest()
    return _verified[k]


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def problems(ids: list[str], verify: bool = True) -> list[str]:
    out = []
    for i in ids:
        f = entry(i)
        p = path(f)
        if not p.exists():
            out.append(f"missing {_rel(p)}")
        elif verify and f.get("sha256") and sha256(p) != f["sha256"]:
            out.append(f"sha256 mismatch for {_rel(p)} (corrupt or replaced; re-fetch it)")
    return out


def require(ids: list[str], group: str, verify: bool = True) -> None:
    errs = problems(ids, verify)
    if errs:
        raise ModelMissing(f"local voice model files for '{group}' are not installed or invalid; run: "
                           + FETCH_HINT.format(group=group), detail="\n".join(errs))


def voice_files(provider: str, voice: str) -> list[str]:
    v = voices(provider).get(voice)
    if v is None:
        raise TTSError(f"unknown {provider} voice {voice!r}; installed voices: {sorted(voices(provider))}")
    return list(v["files"])


# ---------------------------------------------------------------------------------------------
# fetching (official sources only, pinned revisions, sha256-verified)
# ---------------------------------------------------------------------------------------------
def _download(url: str, dst: Path, want: str | None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "video-pipeline-voice-fetch"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as fh:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            fh.write(chunk)
    got = hashlib.sha256(tmp.read_bytes()).hexdigest() if want else None
    if want and got != want:
        tmp.unlink()
        raise TTSError(f"sha256 mismatch downloading {url}", detail=f"want {want}\ngot  {got}")
    os.replace(tmp, dst)


def fetch(group: str) -> None:
    for f in load()["files"]:
        if group not in ("all", f["group"]):
            continue
        p = path(f)
        if f.get("derived"):
            continue
        if p.exists() and (not f.get("sha256") or sha256(p) == f["sha256"]):
            print(f"ok       {f['path']}")
            continue
        print(f"fetching {f['url']}")
        _download(f["url"], p, f.get("sha256"))
    for f in load()["files"]:  # derived files: Piper voices patched to expose phoneme durations
        if group in ("all", f["group"]) and f.get("derived") == "piper-alignment" and not path(f).exists():
            src = path(f["from"])
            print(f"patching {src.name} -> {path(f).name} (adds the w_ceil duration output)")
            subprocess.run(["uv", "run", "--with", "onnx==1.23.2", "python", "-m", "piper.patch_voice_with_alignment",
                            str(src), "--output", str(path(f))], check=True, cwd=ROOT)


def status() -> list[tuple[str, str, str]]:
    rows = []
    for f in load()["files"]:
        p = path(f)
        if not p.exists():
            st = "MISSING"
        elif f.get("sha256") and sha256(p) != f["sha256"]:
            st = "SHA-MISMATCH"
        else:
            st = "ok"
        rows.append((f["group"], f["path"], st))
    return rows


if __name__ == "__main__":  # pragma: no cover - CLI
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "fetch":
        fetch(sys.argv[2] if len(sys.argv) > 2 else "all")
    for g, p, st in status():
        print(f"{st:12} {g:8} {p}")
