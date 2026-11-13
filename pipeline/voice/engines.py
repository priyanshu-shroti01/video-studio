"""Local TTS engines behind tts.TTSProvider: Kokoro-82M (ONNX, CPU) and Piper (ONNX, CPU).

Both run fully offline. Both report per-phoneme durations, which `native.words_from_phonemes` turns
into word boundaries; if that fails for a text, the engine falls back to local Whisper word timestamps
(asr.py) and says so in `last_info["timing_method"]`.

Models load lazily on first use and stay resident for the following scenes; call `unload()` (or
tts.unload_all()) when the stage is done. The `timeout` argument is not enforceable inside an
onnxruntime call and is ignored (local inference cannot hang on the network)."""
from __future__ import annotations

import gc
import json
import os
import re
import threading
import time
import wave
from pathlib import Path

from ..errors import TTSError
from ..timing import tokenize
from . import registry
from .native import PUNCT, Ph, refine_with_energy, words_from_phonemes

KOKORO_SR = 24000
# Measured on 15 voices x 9 scenes (docs/LOCAL_TTS.md): audio leads the predicted durations by ~2 frames
# (word onsets 35-80 ms late, median ~50 ms). hexgrad's own pipeline subtracts 3 frames at the start.
KOKORO_LAG_FRAMES = 2
KOKORO_TIMING_REV = "t2"   # bump when word-timing extraction changes (part of the cache key)
_THREADS = 4  # M1 Pro: 8 P-cores; leave headroom for a concurrent render
# Models are released after this many idle seconds even if nobody calls unload() (memory is tight and
# the runner keeps this process alive through the render). 0 disables.
IDLE_UNLOAD_S = float(os.environ.get("VIDEO_PIPELINE_TTS_IDLE_UNLOAD_S", "20"))


class _IdleUnload:
    """Serialises synthesis and unloads the model (and Whisper) after IDLE_UNLOAD_S without use."""
    _lock: threading.Lock
    _timer: threading.Timer | None = None

    def _guard_init(self):
        self._lock, self._timer = threading.Lock(), None

    def synthesize(self, *a, **k):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            try:
                return self._synthesize(*a, **k)
            finally:
                if IDLE_UNLOAD_S > 0:
                    self._timer = threading.Timer(IDLE_UNLOAD_S, self._idle)
                    self._timer.daemon = True
                    self._timer.start()

    def _idle(self):
        if self._lock.acquire(blocking=False):
            try:
                self.unload()
                from . import asr
                asr.unload()
            finally:
                self._lock.release()


def speed_from_rate(rate: str) -> float:
    m = re.fullmatch(r"([+-]\d{1,2})%", rate or "+0%")
    if not m:
        raise TTSError(f"invalid rate {rate!r} (expected e.g. '+5%')")
    return 1.0 + int(m.group(1)) / 100.0


def write_wav(path: Path, audio, sr: int) -> None:
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _ort_session(model: Path, threads: int = _THREADS):
    import onnxruntime as rt
    so = rt.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.log_severity_level = 3
    if os.environ.get("VIDEO_PIPELINE_ORT_ARENA", "1") == "0":
        so.enable_cpu_mem_arena = False
    return rt.InferenceSession(str(model), sess_options=so, providers=["CPUExecutionProvider"])


def _fallback_whisper(tokens_text: str, audio_path: Path, info: dict):
    from . import asr
    info["timing_method"] = "whisper"
    return asr.shared().word_boundaries(audio_path, prompt=tokens_text)


class KokoroProvider(_IdleUnload):
    """Kokoro-82M v1.0, onnx-community "timestamped" export (outputs `waveform` + `durations`)."""
    name = "kokoro"
    online = False
    uses_pronunciation = True
    ext = ".wav"
    MODEL = ["kokoro-model", "kokoro-vocab"]

    def __init__(self):
        registry.require(self.MODEL, "kokoro", verify=False)  # cheap presence check; sha verified on load
        import kokoro_onnx  # noqa: F401  (dependency check)
        from importlib.metadata import version
        self.version = (f"kokoro-onnx{version('kokoro-onnx')}/{registry.entry('kokoro-model')['sha256'][:12]}"
                        f"/{KOKORO_TIMING_REV}")
        self.sess = self.tok = None
        self.styles: dict[str, object] = {}
        self.last_info: dict = {}
        self.load_s = 0.0
        self._guard_init()

    def load(self):
        if self.sess is not None:
            return
        registry.require(self.MODEL, "kokoro")
        t0 = time.perf_counter()
        from kokoro_onnx.tokenizer import Tokenizer
        vocab = json.loads(registry.path("kokoro-vocab").read_text())["model"]["vocab"]
        vocab.pop("$", None)  # pad id 0 is added explicitly
        self.tok = Tokenizer(vocab=vocab)
        self.sess = _ort_session(registry.path("kokoro-model"))
        self.load_s = time.perf_counter() - t0

    def unload(self):
        self.sess = self.tok = None
        self.styles.clear()
        gc.collect()

    def style(self, voice: str):
        import numpy as np
        if voice not in self.styles:
            ids = registry.voice_files("kokoro", voice)
            registry.require(ids, "kokoro")
            self.styles[voice] = np.fromfile(registry.path(ids[0]), dtype=np.float32).reshape(-1, 1, 256)
        return self.styles[voice]

    @staticmethod
    def lang_for(voice: str, override: str | None = None) -> str:
        if override:
            return override
        return "en-gb" if voice.startswith("b") else "en-us"  # a*: American; h*: Hindi voices read English as en-us

    def _run(self, phonemes: str, style, speed: float):
        import numpy as np
        ids = self.tok.tokenize(phonemes, limit=510)
        known = self.tok.known(phonemes)
        assert len(ids) == len(known)
        out = self.sess.run(None, {"input_ids": np.array([[0, *ids, 0]], dtype=np.int64),
                                   "style": np.asarray(style[min(len(ids), len(style)) - 1], dtype=np.float32),
                                   "speed": np.array([speed], dtype=np.float32)})
        audio = np.asarray(out[0]).ravel()
        dur = np.asarray(out[1]).ravel()
        edges = np.concatenate([[0.0], np.cumsum(dur)])
        edges = edges * (len(audio) / edges[-1])  # frames -> samples (exactly 600/frame at speed 1)
        lag = KOKORO_LAG_FRAMES * 600 / speed
        edges = np.clip(edges - lag, 0, len(audio))
        phs = [Ph(ch, edges[i + 1] / KOKORO_SR, edges[i + 2] / KOKORO_SR) for i, ch in enumerate(known)]
        return audio, phs

    def phonemize(self, text: str, lang: str) -> str:
        return self.tok.phonemize(text, lang)

    def _synthesize(self, text, voice, rate, pitch, out, timeout, options=None):
        import numpy as np
        self.load()
        opts = options or {}
        lang = self.lang_for(voice, opts.get("lang"))
        style, speed = self.style(voice), speed_from_rate(rate)
        t0 = time.perf_counter()
        phon = " ".join(self.phonemize(text, lang).split())
        # one pass keeps prosody; split at sentence ends only if the 510-phoneme context is exceeded
        chunks, cur = [], ""
        for sent in re.split(r"(?<=[.!?])\s+", phon):
            if cur and len(cur) + 1 + len(sent) > 500:
                chunks.append(cur); cur = sent
            else:
                cur = f"{cur} {sent}".strip()
        chunks.append(cur)
        parts, phs, offset = [], [], 0.0
        for k, ch in enumerate(chunks):
            if len(ch) > 510:
                raise TTSError(f"a sentence is too long for Kokoro ({len(ch)} phonemes > 510); split it")
            a, p = self._run(ch, style, speed)
            if k:
                gap = np.zeros(int(0.25 * KOKORO_SR), dtype=np.float32)
                parts.append(gap); offset += len(gap) / KOKORO_SR
                phs.append(Ph(" ", offset - 0.25, offset))
            phs += [Ph(x.p, x.start + offset, x.end + offset) for x in p]
            parts.append(a); offset += len(a) / KOKORO_SR
        audio = np.concatenate(parts)
        synth_s = time.perf_counter() - t0
        write_wav(Path(out), audio, KOKORO_SR)
        info = {"engine": "kokoro", "lang": lang, "speed": speed, "phonemes": phon, "synth_s": round(synth_s, 3),
                "audio_s": round(len(audio) / KOKORO_SR, 3), "pitch_ignored": pitch not in ("+0Hz", "-0Hz", None)}
        toks = tokenize(text)
        try:
            bounds, info["timing_method"] = words_from_phonemes(toks, phs)
        except ValueError:
            try:
                iso = [self.phonemize(re.sub(r"[^\w'’-]", "", t) or t, lang) for t in toks]
                bounds, info["timing_method"] = words_from_phonemes(toks, phs, iso)
            except ValueError:
                bounds = _fallback_whisper(text, Path(out), info)
        if info["timing_method"].startswith("native"):
            bounds, info["energy_snapped_edges"] = refine_with_energy(bounds, audio, KOKORO_SR)
        self.last_info = info
        return bounds


class PiperProvider(_IdleUnload):
    """Piper (piper-tts 1.8, OHF-Voice/piper1-gpl) with voices patched to output phoneme durations."""
    name = "piper"
    online = False
    uses_pronunciation = True
    ext = ".wav"
    SENTENCE_GAP = 0.25

    def __init__(self):
        import piper  # noqa: F401
        from importlib.metadata import version
        self.version = f"piper-tts{version('piper-tts')}"
        self.voices: dict[str, object] = {}
        self.last_info: dict = {}
        self.load_s = 0.0
        self._guard_init()

    def load(self, voice: str):
        if voice in self.voices:
            return self.voices[voice]
        ids = registry.voice_files("piper", voice)
        registry.require(ids, "piper")
        self.unload()  # one Piper voice resident at a time
        t0 = time.perf_counter()
        from piper import PiperVoice
        from piper.config import PiperConfig
        model, cfg = (registry.path(i) for i in ids[:2])
        pv = PiperVoice(config=PiperConfig.from_dict(json.loads(cfg.read_text())), session=_ort_session(model))
        self.voices[voice] = pv
        self.load_s = time.perf_counter() - t0
        return pv

    def unload(self):
        self.voices.clear()
        gc.collect()

    def _synthesize(self, text, voice, rate, pitch, out, timeout, options=None):
        import numpy as np
        from piper.config import SynthesisConfig
        pv = self.load(voice)
        speed = speed_from_rate(rate)
        base = pv.config.length_scale or 1.0
        syn = SynthesisConfig(length_scale=base / speed)
        t0 = time.perf_counter()
        parts, phs, offset, sr, ok, phon = [], [], 0.0, pv.config.sample_rate, True, []
        for k, chunk in enumerate(pv.synthesize(text, syn, include_alignments=True)):
            if k:
                gap = np.zeros(int(self.SENTENCE_GAP * sr), dtype=np.float32)
                parts.append(gap); phs.append(Ph(" ", offset, offset + self.SENTENCE_GAP)); offset += self.SENTENCE_GAP
            a = chunk.audio_float_array.ravel()
            phon.append("".join(chunk.phonemes))
            if chunk.phoneme_alignments:
                t = offset
                for al in chunk.phoneme_alignments:
                    d = al.num_samples / sr
                    if al.phoneme not in ("^", "$", "_"):
                        phs.append(Ph(al.phoneme, t, t + d))
                    t += d
            else:
                ok = False
            parts.append(a); offset += len(a) / sr
        if not parts:
            raise TTSError("piper produced no audio")
        audio = np.concatenate(parts)
        synth_s = time.perf_counter() - t0
        write_wav(Path(out), audio, sr)
        info = {"engine": "piper", "speed": speed, "phonemes": " | ".join(phon), "synth_s": round(synth_s, 3),
                "audio_s": round(len(audio) / sr, 3), "pitch_ignored": pitch not in ("+0Hz", "-0Hz", None)}
        toks = tokenize(text)
        bounds = None
        if ok:
            try:
                bounds, info["timing_method"] = words_from_phonemes(toks, phs)
            except ValueError:
                try:
                    iso = ["".join(p for s in pv.phonemize(re.sub(r"[^\w'’-]", "", t) or t) for p in s
                                   if p not in PUNCT) for t in toks]
                    bounds, info["timing_method"] = words_from_phonemes(toks, phs, iso)
                except ValueError:
                    bounds = None
        if bounds is None:
            bounds = _fallback_whisper(text, Path(out), info)
        self.last_info = info
        return bounds


# ---------------------------------------------------------------------------------------------
# Out-of-process execution (default): the model lives in a worker process that exits when idle or on
# unload(), so its memory really goes back to the OS (measured: freeing an onnxruntime session inside a
# long-lived process leaves RSS at ~620 MB on macOS). It also makes the `timeout` enforceable.
# ---------------------------------------------------------------------------------------------
class WorkerProvider:
    online = False
    uses_pronunciation = True
    ext = ".wav"

    def __init__(self, name: str):
        self.name = name
        if name == "kokoro":
            registry.require(KokoroProvider.MODEL, "kokoro", verify=False)
            from importlib.metadata import version
            self.version = (f"kokoro-onnx{version('kokoro-onnx')}/{registry.entry('kokoro-model')['sha256'][:12]}"
                            f"/{KOKORO_TIMING_REV}")
        elif name == "piper":
            from importlib.metadata import version
            self.version = f"piper-tts{version('piper-tts')}"
        else:
            raise TTSError(f"no local engine {name!r}")
        self.proc = None
        self.last_info: dict = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _start(self):
        import subprocess
        import sys
        from ..paths import ROOT
        env = {**os.environ, "VIDEO_PIPELINE_TTS_INPROCESS": "1", "VIDEO_PIPELINE_TTS_IDLE_UNLOAD_S": "0",
               "HF_HUB_OFFLINE": "1"}
        self.proc = subprocess.Popen([sys.executable, "-m", "pipeline.voice.worker"], cwd=ROOT, env=env, text=True,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1)

    def _kill(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.stdin.close()
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()

    def unload(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._kill()

    def _idle(self):
        if self._lock.acquire(blocking=False):
            try:
                self._kill()
            finally:
                self._lock.release()

    def synthesize(self, text, voice, rate, pitch, out, timeout, options=None):
        import select
        from ..tts import Boundary
        # presence of the voice's files is checked here, in this process, so the error is immediate
        registry.require(registry.voice_files(self.name, voice), self.name, verify=False)
        with self._lock:
            if self._timer:
                self._timer.cancel()
            try:
                if self.proc is None or self.proc.poll() is not None:
                    self._start()
                req = {"provider": self.name, "text": text, "voice": voice, "rate": rate, "pitch": pitch,
                       "out": str(out), "options": options or {}}
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
                ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
                line = self.proc.stdout.readline() if ready else ""
                if not line:
                    self._kill()
                    raise TTSError(f"local {self.name} worker gave no result within {timeout:.0f}s", transient=True)
                res = json.loads(line)
                if not res["ok"]:
                    if res.get("code") == registry.ModelMissing.code:
                        raise registry.ModelMissing(res["error"], detail=res.get("detail"))
                    raise TTSError(res["error"], detail=res.get("detail"), transient=bool(res.get("transient")))
                self.last_info = res["info"]
                return [Boundary(**b) for b in res["bounds"]]
            except (BrokenPipeError, OSError, json.JSONDecodeError) as e:
                self._kill()
                raise TTSError(f"local {self.name} worker failed: {e}", transient=True) from e
            finally:
                if IDLE_UNLOAD_S > 0 and self.proc is not None:
                    self._timer = threading.Timer(IDLE_UNLOAD_S, self._idle)
                    self._timer.daemon = True
                    self._timer.start()


def make(name: str):
    """Provider factory used by tts.PROVIDERS: out-of-process unless VIDEO_PIPELINE_TTS_INPROCESS=1."""
    if os.environ.get("VIDEO_PIPELINE_TTS_INPROCESS") == "1":
        return {"kokoro": KokoroProvider, "piper": PiperProvider}[name]()
    return WorkerProvider(name)
