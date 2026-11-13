"""Remotion rendering: bundle cache, chunked + resumable renders, VideoToolbox with x264 fallback,
Chromium crash/stall handling, and a memory-aware concurrency controller.

Design goal (from the operator): maximum *sustained* throughput without swapping or Chromium
instability — not maximum worker count. Each chunk is gated on available memory; if a chunk causes
swap growth or page-outs, the next chunk runs with fewer Chromium tabs."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import procs
from .contract import COMPOSITION_ID, FORMATS
from .errors import Cancelled, EncoderError, PipelineError, RenderError, ResourceError
from .paths import ROOT, STATE_DIR, atomic_write_json, sha256_json
from .system import mem_snapshot

BUNDLES = STATE_DIR / "bundles"
BENCH_FILE = STATE_DIR / "benchmark.json"
CHROMIUM_TRANSIENT = re.compile(r"Target closed|Protocol error|Page crashed|Browser (?:has )?(?:closed|disconnected)|"
                                r"crashed|ECONNRESET|socket hang up|Navigation timeout|TimeoutError|"
                                r"timed out|delayRender\(\) .* was called but not cleared", re.I)
ENCODER_FAIL = re.compile(r"videotoolbox|VTCompressionSession|hardware.?accelerat|Error initializing output stream|"
                          r"Could not open encoder", re.I)
PROGRESS = re.compile(r"(\d+)\s*/\s*(\d+)")


def remotion_bin() -> list[str]:
    local = ROOT / "node_modules" / ".bin" / "remotion"
    if not local.exists():
        raise RenderError("Remotion CLI not installed (run `npm ci`)")
    return [str(local)]


def chromium_path() -> Path | None:
    base = ROOT / "node_modules" / ".remotion" / "chrome-headless-shell"
    if not base.exists():
        return None
    for p in base.rglob("chrome-headless-shell"):
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def ensure_chromium() -> Path:
    p = chromium_path()
    if p:
        return p
    procs.run([*remotion_bin(), "browser", "ensure"], cwd=ROOT, timeout=600)
    p = chromium_path()
    if not p:
        raise RenderError("Chromium headless shell is unavailable after `remotion browser ensure`")
    return p


def ffmpeg_has_videotoolbox() -> bool:
    try:
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
        if "h264_videotoolbox" not in enc:
            return False
        p = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=0.2:r=30",
                            "-c:v", "h264_videotoolbox", "-b:v", "8M", "-f", "null", "-"], capture_output=True, timeout=60)
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------------------------
def _tree_fingerprint(paths: list[Path]) -> str:
    items = []
    for base in paths:
        if base.is_file():
            items.append((str(base.relative_to(ROOT)), base.stat().st_size, int(base.stat().st_mtime)))
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and ".DS_Store" not in p.name:
                st = p.stat()
                items.append((str(p.relative_to(ROOT)), st.st_size, int(st.st_mtime)))
    return sha256_json(items)


def ensure_bundle(log: Callable[[str], None] = print) -> Path:
    """Bundle once per (src, public, lockfile, config) fingerprint; reused by every chunk and job."""
    fp = _tree_fingerprint([ROOT / "src", ROOT / "public", ROOT / "package-lock.json", ROOT / "remotion.config.ts"])[:16]
    dst = BUNDLES / fp
    if (dst / "index.html").exists():
        return dst
    BUNDLES.mkdir(parents=True, exist_ok=True)
    tmp = BUNDLES / f".tmp-{fp}-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    log(f"bundling Remotion project -> {dst.name}")
    procs.run([*remotion_bin(), "bundle", "src/index.ts", "--out-dir", str(tmp), "--log=error"], cwd=ROOT, timeout=600)
    if not (tmp / "index.html").exists():
        raise RenderError("Remotion bundle produced no index.html")
    try:
        os.replace(tmp, dst)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)  # another process won the race; theirs is identical
    for old in sorted((p for p in BUNDLES.iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=lambda p: p.stat().st_mtime)[:-3]:
        shutil.rmtree(old, ignore_errors=True)
    return dst


# ---------------------------------------------------------------------------------------------
@dataclass
class RenderSettings:
    encoder: str = "auto"            # auto | videotoolbox | x264
    bitrate: str = "40M"
    image_format: str = "png"
    chunk_frames: int = 300
    concurrency: int = 4
    timeout_per_chunk: float = 900
    stall_timeout: float = 120
    retries: int = 2
    min_available_mb: float = 1500   # floor before starting a chunk (plus ~350 MB per Chromium tab)
    per_tab_mb: float = 350

    @classmethod
    def from_config(cls, r: dict, fmt: str) -> "RenderSettings":
        conc = r.get("concurrency", "auto")
        if conc == "auto":
            conc = recommended_concurrency(fmt)
        return cls(encoder=r.get("encoder", "auto"), bitrate=r.get("bitrate", "40M"),
                   image_format=r.get("imageFormat", "png"), chunk_frames=r.get("chunkFrames", 300),
                   concurrency=int(conc), timeout_per_chunk=r.get("timeoutPerChunk", 900),
                   stall_timeout=r.get("stallTimeout", 120), retries=r.get("retries", 2))


def recommended_concurrency(fmt: str) -> int:
    """From the last `video-pipeline benchmark` on this machine; conservative default otherwise."""
    try:
        data = json.loads(BENCH_FILE.read_text())
        return int(data["recommended"][fmt]["concurrency"])
    except (OSError, KeyError, ValueError, TypeError):
        return 4


@dataclass
class ChunkReport:
    frames: tuple[int, int]
    seconds: float
    encoder: str
    concurrency: int
    peak_rss_mb: float
    swap_delta_mb: float
    pageouts_delta: int
    reused: bool = False
    attempts: int = 1


@dataclass
class RenderReport:
    format: str
    frames: int
    fps: int
    seconds: float = 0.0
    chunks: list[ChunkReport] = field(default_factory=list)
    encoder: str = ""
    output: str = ""

    def as_dict(self):
        d = {k: v for k, v in self.__dict__.items() if k != "chunks"}
        d["chunks"] = [c.__dict__ for c in self.chunks]
        d["fps_rendered"] = round(self.frames / self.seconds, 2) if self.seconds else None
        d["realtime_factor"] = round((self.frames / self.fps) / self.seconds, 3) if self.seconds else None
        d["peak_rss_mb"] = max((c.peak_rss_mb for c in self.chunks), default=0)
        return d


def count_frames(path: Path) -> int:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=120)
    try:
        return int(p.stdout.strip().split(",")[0])
    except ValueError:
        return -1


def wait_for_memory(need_mb: float, should_cancel: Callable[[], bool], log, max_wait: float = 300) -> float:
    t0 = time.time()
    while True:
        m = mem_snapshot()
        if m.available_mb >= need_mb:
            return m.available_mb
        if should_cancel():
            raise Cancelled("cancelled while waiting for memory")
        if time.time() - t0 > max_wait:
            return m.available_mb
        log(f"waiting for memory: {m.available_mb:.0f} MB available, want {need_mb:.0f} MB")
        time.sleep(5)


def render_format(*, props_file: Path, props_hash: str, fmt: str, total_frames: int, fps: int, out: Path,
                  chunks_dir: Path, s: RenderSettings, bundle: Path, should_cancel: Callable[[], bool],
                  log: Callable[[str], None] = print, on_progress: Callable[[float], None] | None = None,
                  runner=procs.run) -> RenderReport:
    """Render `total_frames` of the Storyboard composition as muted H.264 chunks, reuse valid chunks
    from an interrupted run, then losslessly concatenate them into `out`."""
    w, h = FORMATS[fmt]
    chunks_dir.mkdir(parents=True, exist_ok=True)
    rep = RenderReport(fmt, total_frames, fps)
    encoder = "x264" if s.encoder == "x264" else ("videotoolbox" if s.encoder in ("auto", "videotoolbox") else "x264")
    conc = max(1, s.concurrency)
    spans = [(a, min(a + s.chunk_frames, total_frames) - 1) for a in range(0, total_frames, s.chunk_frames)]
    done_frames = 0
    t_start = time.time()
    files = []
    for a, b in spans:
        if should_cancel():
            raise Cancelled("cancelled during render")
        f = chunks_dir / f"{fmt}-{a:06d}-{b:06d}.mp4"
        meta_f = f.with_suffix(".json")
        n = b - a + 1
        if f.exists() and meta_f.exists():
            try:
                meta = json.loads(meta_f.read_text())
            except json.JSONDecodeError:
                meta = {}
            if meta.get("props_hash") == props_hash and meta.get("frames") == n and count_frames(f) == n:
                rep.chunks.append(ChunkReport((a, b), 0.0, meta.get("encoder", "?"), meta.get("concurrency", 0), 0, 0, 0, True))
                files.append(f); done_frames += n
                log(f"[{fmt}] chunk {a}-{b}: reused (validated {n} frames)")
                if on_progress:
                    on_progress(done_frames / total_frames)
                continue
            f.unlink(missing_ok=True); meta_f.unlink(missing_ok=True)
        attempts = 0
        while True:
            attempts += 1
            wait_for_memory(s.min_available_mb + s.per_tab_mb * conc, should_cancel, log)
            m0 = mem_snapshot()
            tmp = chunks_dir / f".{f.stem}.part.mp4"
            tmp.unlink(missing_ok=True)
            args = [*remotion_bin(), "render", str(bundle), COMPOSITION_ID, str(tmp), f"--props={props_file}",
                    f"--frames={a}-{b}", "--muted", "--codec=h264", f"--video-bitrate={s.bitrate}",
                    f"--image-format={s.image_format}", "--color-space=bt709", f"--concurrency={conc}",
                    f"--timeout={int(s.timeout_per_chunk * 1000)}", "--log=info", "--overwrite",
                    "--hardware-acceleration=" + ("required" if encoder == "videotoolbox" else "disable")]
            if s.image_format == "jpeg":
                args.append("--jpeg-quality=92")
            env = {**os.environ, "REMOTION_HW": "required" if encoder == "videotoolbox" else "disable",
                   "REMOTION_BITRATE": s.bitrate, "REMOTION_CONCURRENCY": str(conc)}

            def prog(line, a=a, n=n):
                mm = PROGRESS.search(line)
                if mm and on_progress and int(mm.group(2)) == n:
                    on_progress((done_frames + int(mm.group(1))) / total_frames)
            try:
                r = runner(args, cwd=ROOT, env=env, timeout=s.timeout_per_chunk, stall_timeout=s.stall_timeout,
                           should_cancel=should_cancel, sample_rss=True, on_line=prog)
                got = count_frames(tmp)
                if got != n:
                    raise RenderError(f"chunk {a}-{b}: expected {n} frames, file has {got}", transient=True)
                m1 = mem_snapshot()
                os.replace(tmp, f)
                cr = ChunkReport((a, b), round(r.seconds, 2), encoder, conc, round(r.peak_rss_mb),
                                 round(m1.swap_used_mb - m0.swap_used_mb, 1), m1.pageouts - m0.pageouts, False, attempts)
                atomic_write_json(meta_f, {"props_hash": props_hash, "frames": n, "encoder": encoder,
                                           "concurrency": conc, "seconds": cr.seconds, "w": w, "h": h})
                rep.chunks.append(cr); files.append(f); done_frames += n
                log(f"[{fmt}] chunk {a}-{b}: {n} frames in {cr.seconds:.1f}s ({n / max(cr.seconds, 0.01):.1f} fps) "
                    f"enc={encoder} tabs={conc} rss={cr.peak_rss_mb:.0f}MB swapΔ={cr.swap_delta_mb:+.0f}MB "
                    f"pageoutsΔ={cr.pageouts_delta}")
                if (cr.swap_delta_mb > 64 or cr.pageouts_delta > 2000) and conc > 1:
                    conc = max(1, conc // 2)
                    log(f"[{fmt}] memory pressure detected -> lowering Chromium tabs to {conc} for remaining chunks")
                break
            except Cancelled:
                tmp.unlink(missing_ok=True)
                raise
            except PipelineError as e:
                tmp.unlink(missing_ok=True)
                text = f"{e.message}\n{e.detail or ''}"
                if encoder == "videotoolbox" and ENCODER_FAIL.search(text) and s.encoder == "auto":
                    log(f"[{fmt}] VideoToolbox failed ({e.message}); falling back to software x264")
                    encoder = "x264"
                    continue
                transient = e.transient or bool(CHROMIUM_TRANSIENT.search(text))
                if transient and attempts <= s.retries:
                    if conc > 1:
                        conc = max(1, conc // 2)
                    delay = min(30, 2 ** attempts)
                    log(f"[{fmt}] chunk {a}-{b} failed ({e.message}); retry {attempts}/{s.retries} in {delay}s "
                        f"with {conc} tabs")
                    time.sleep(delay)
                    continue
                if encoder == "videotoolbox" and s.encoder == "videotoolbox":
                    raise EncoderError(f"VideoToolbox encoding failed: {e.message}", detail=e.detail) from e
                raise RenderError(f"render failed on frames {a}-{b}: {e.message}", detail=e.detail,
                                  transient=transient) from e
    # lossless concat of validated chunks
    lst = chunks_dir / f"{fmt}-concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in files))
    tmp_out = out.with_name(f".{out.stem}.part.mp4")
    procs.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
               "-movflags", "+faststart", str(tmp_out)], cwd=chunks_dir, timeout=600)
    got = count_frames(tmp_out)
    if got != total_frames:
        tmp_out.unlink(missing_ok=True)
        raise RenderError(f"concatenated video has {got} frames, expected {total_frames}")
    os.replace(tmp_out, out)
    rep.seconds = round(time.time() - t_start, 2)
    rep.encoder = ",".join(sorted({c.encoder for c in rep.chunks}))
    rep.output = str(out)
    return rep


def acquire_render_slot(registry, jid: str, max_jobs: int, should_cancel, log, poll: float = 3.0) -> int:
    waited = False
    while True:
        slot = registry.acquire_slot(jid, max_jobs)
        if slot is not None:
            return slot
        if should_cancel():
            raise Cancelled("cancelled while queued for a render slot")
        if not waited:
            log(f"all {max_jobs} render slot(s) busy; waiting")
            waited = True
        time.sleep(poll)


def preflight(min_free_gb: float) -> dict:
    from .paths import require_free_space
    free = require_free_space(min_free_gb)
    m = mem_snapshot()
    if m.available_mb < 800:
        raise ResourceError(f"only {m.available_mb:.0f} MB memory available; close apps before rendering")
    return {"free_gb": round(free, 1), "available_mb": round(m.available_mb), "swap_used_mb": m.swap_used_mb}
