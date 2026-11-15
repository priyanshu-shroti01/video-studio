"""Real local voice for the Studio preview player, before the full render.

generate_preview_voice(pid) synthesises the production's storyboard narration with its configured voice through the
SAME code path as the render's GENERATING_AUDIO stage (pipeline/runner.py):
    per scene  JobRunner._synthesize_scenes -> tts.synthesize_from_config (pronunciation, spoken form, TTS cache)
                                              -> timing.align -> validate_words
    assembled  audio.build_voiceover(maxPause, pad, sceneGap) -> validate_words(fix=False)
inside the scheduler's HeavyWork("tts") (never overlaps a render or the LLM), then unloads the TTS worker.

Per-scene audio is cached by text in .pipeline/cache/tts (tts.synthesize), so the render re-uses what the preview
synthesised and vice versa. The assembled result is cached under
    output/productions/<P>/preview/voice/<key[:16]>/{voiceover.wav, timing.json, meta.json}
where key = the render's GENERATING_AUDIO input hash: sha256(voice config incl. merged brand pronunciations,
voice_fingerprint (pronunciation dictionary + model hashes), narration texts, holdAfter, pipeline version).
Unchanged narration is never re-synthesised; any change produces a new key (older entries are kept, not deleted).

timing.json has the render's metadata/timing.json shape, so build_timeline(cfg, timing) gives the props the render
will build from the same voice."""
from __future__ import annotations

import json
import os
import shutil
import time
import urllib.parse
import uuid
from pathlib import Path

from . import __version__
from . import audio as A
from . import tts
from .errors import NotFound, PipelineError
from .paths import atomic_write_json, rel, sha256_file, sha256_json
from .timing import validate_words

SUBDIR = Path("preview") / "voice"


def voice_key(cfg: dict) -> str:
    """Cache key of a resolved project config's voiceover (identical to the runner's GENERATING_AUDIO input hash)."""
    v = cfg["voice"]
    scenes = cfg["storyboard"]["scenes"]
    from .voice.delivery import scene_delivery
    return sha256_json({"voice": v, "vfp": tts.voice_fingerprint(v), "narr": [s["narration"] for s in scenes],
                        "delivery": [scene_delivery(s) for s in scenes],
                        "hold": [s.get("holdAfter", 0) for s in scenes], "v": __version__})


def voice_dir(prod_dir: Path) -> Path:
    return Path(prod_dir) / SUBDIR


def entry_dir(prod_dir: Path, key: str) -> Path:
    return voice_dir(prod_dir) / key[:16]


def file_url(path: Path) -> str:
    """Studio /files/ URL of a workspace file (pipeline.api.safe_output_file serves output/)."""
    return "/files/" + "/".join(urllib.parse.quote(p, safe="!*'()") for p in rel(path).split("/"))


def find(prod_dir: Path, key: str) -> dict | None:
    """-> {key, dir, audio, timing, meta} for a complete, intact cache entry, else None."""
    e = entry_dir(prod_dir, key)
    wav, tf, mf = e / "voiceover.wav", e / "timing.json", e / "meta.json"
    try:
        meta = json.loads(mf.read_text())
        timing = json.loads(tf.read_text())
    except (OSError, ValueError):
        return None
    if meta.get("key") != key or not wav.is_file() or meta.get("sha256") != sha256_file(wav):
        return None
    return {"key": key, "dir": e, "audio": wav, "timing": timing, "meta": meta}


def _load(production_id: str) -> tuple[dict, Path]:
    from .api import _reg
    from .config import load_project
    from .productions import Productions
    p = Productions(_reg()).get(production_id)
    d = Path(p["dir"])
    if not (d / "storyboard.json").is_file() or not (d / "project.json").is_file():
        raise NotFound(f"production {production_id} has no storyboard yet: select a concept or save a storyboard first")
    cfg, _ = load_project(rel(d / "project.json"))
    return cfg, d


def _write_status(prod_dir: Path, key: str, state: str, **extra) -> None:
    atomic_write_json(voice_dir(prod_dir) / "status.json",
                      {"key": key, "state": state, "updated": round(time.time(), 3), **extra})


def status(production_id: str) -> dict:
    """GET /api/productions/<P>/preview-voice: is a preview voice ready for the CURRENT narration?
    -> {productionId, key, ready, state, progress, durationS, audio: {url, durationS} | None, provider, voice}"""
    cfg, d = _load(production_id)
    key = voice_key(cfg)
    hit = find(d, key)
    try:
        st = json.loads((voice_dir(d) / "status.json").read_text())
    except (OSError, ValueError):
        st = {}
    if st.get("key") != key:
        st = {}
    v = cfg["voice"]
    return {"productionId": production_id, "key": key, "ready": bool(hit),
            "state": "ready" if hit else st.get("state", "none"), "progress": 1.0 if hit else st.get("progress", 0.0),
            "error": None if hit else st.get("error"),
            "audio": {"url": file_url(hit["audio"]), "durationS": hit["timing"]["duration"]} if hit else None,
            "provider": v.get("provider"), "voice": v.get("voice")}


class _Stage:
    """The minimal JobRunner surface _synthesize_scenes uses (log, cancelled, reg.update(progress)), so the preview
    runs the render's per-scene TTS code unchanged without a job."""

    def __init__(self, prod_dir: Path, key: str, n: int, log, should_cancel):
        self.jid, self._log, self._cancel = f"preview-voice:{prod_dir.name}", log, should_cancel
        outer = self

        class _Reg:
            def update(self, _jid, progress=None, **_kw):
                outer.progress = progress
                _write_status(prod_dir, key, "synthesizing", progress=progress, scenes=n)
        self.reg = _Reg()
        self.progress = 0.0

    def log(self, msg, level="info", stage=None, **_data):
        self._log(msg)

    def cancelled(self) -> bool:
        return bool(self._cancel())


def generate_preview_voice(production_id: str, *, log=None, should_cancel=None, force: bool = False) -> dict:
    """Synthesise (or reuse) the preview voiceover for the production's current storyboard.
    -> {productionId, key, cached, durationS, words, scenes, audio: {url, durationS}, timingFile, provider, voice}"""
    from .runner import JobRunner
    from .scheduler import HeavyWork
    log = log or (lambda m: None)
    should_cancel = should_cancel or (lambda: False)
    cfg, d = _load(production_id)
    v = cfg["voice"]
    scenes = cfg["storyboard"]["scenes"]
    key = voice_key(cfg)

    def result(hit: dict, cached: bool) -> dict:
        tm = hit["timing"]
        return {"productionId": production_id, "key": key, "cached": cached, "durationS": tm["duration"],
                "words": len(tm["words"]), "scenes": len(tm["scene_spans"]),
                "audio": {"url": file_url(hit["audio"]), "durationS": tm["duration"]},
                "timingFile": rel(hit["dir"] / "timing.json"), "provider": v.get("provider"), "voice": v.get("voice")}

    if not force and (hit := find(d, key)):
        return result(hit, True)
    if v.get("provider") in tts.ONLINE_PROVIDERS and not v.get("allowOnline"):
        raise tts.online_refusal(v["provider"])
    vd = voice_dir(d)
    vd.mkdir(parents=True, exist_ok=True)
    work = vd / f".tmp-{uuid.uuid4().hex[:8]}"
    work.mkdir()
    t0 = time.time()
    try:
        stage = _Stage(d, key, len(scenes), log, should_cancel)
        heavy = HeavyWork(_reg(), "tts", ref=production_id, should_cancel=stage.cancelled, log=log) \
            if v["provider"] not in ("mock", "edge") else None       # as the runner: local TTS models are memory-heavy
        _write_status(d, key, "waiting" if heavy else "synthesizing", progress=0.0, scenes=len(scenes))
        if heavy:
            g = heavy.__enter__()
            log(f"scheduler: tts granted after {g.waited_s}s ({g.available_mb} MB available)")
        try:
            _write_status(d, key, "synthesizing", progress=0.0, scenes=len(scenes))
            per = JobRunner._synthesize_scenes(stage, scenes, v)
        finally:
            tts.unload_all()                       # free the TTS worker (as the runner does before rendering)
            if heavy:
                heavy.__exit__(None, None, None)
        _write_status(d, key, "assembling", progress=1.0, scenes=len(scenes))
        vo = A.build_voiceover(per, work / "voiceover.wav", max_pause=v.get("maxPause", 0.35),
                               pad=v.get("pad", 0.25), gap=v.get("sceneGap", 0.2))
        rep = validate_words(vo.words, vo.duration, fix=False)
        if not rep.ok:
            raise PipelineError("assembled voiceover timings are invalid", detail="\n".join(rep.errors))
        timing = {"duration": vo.duration, "words": [w.as_dict() for w in vo.words], "scene_spans": vo.scene_spans,
                  "removed_pause_s": vo.removed_s, "report": rep.as_dict(), "voice": v}
        atomic_write_json(work / "timing.json", timing)
        atomic_write_json(work / "meta.json", {
            "key": key, "productionId": production_id, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "seconds": round(time.time() - t0, 2), "provider": v["provider"], "voice": v["voice"],
            "sha256": sha256_file(work / "voiceover.wav"), "duration": vo.duration,
            "scenes": getattr(stage, "_align_log", [])})
        dst = entry_dir(d, key)
        if dst.exists():                           # force, or a corrupt entry: set it aside, never delete it silently
            os.replace(dst, vd / f".old-{dst.name}-{uuid.uuid4().hex[:6]}")
        os.replace(work, dst)
    except BaseException as e:
        msg = e.message if isinstance(e, PipelineError) else f"{type(e).__name__}: {e}"
        _write_status(d, key, "failed", error=msg)
        raise
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
    _write_status(d, key, "ready", progress=1.0, scenes=len(scenes))
    log(f"preview voice {vo.duration:.2f}s ({len(vo.words)} words) in {time.time() - t0:.1f}s")
    return result(find(d, key) or {"key": key, "dir": dst, "audio": dst / "voiceover.wav", "timing": timing}, False)


def _reg():
    from .api import _reg as r
    return r()

