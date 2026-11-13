"""Voice generation behind a provider interface.

Providers:
  kokoro  Kokoro-82M (Apache-2.0) via onnxruntime on CPU. LOCAL. Native word timings. Default.
  piper   Piper voices (piper-tts) via onnxruntime on CPU. LOCAL. Native word timings.
  edge    LEGACY. Microsoft Edge neural voices via `edge-tts`: an ONLINE service (narration text is sent
          to Microsoft). Refused unless the caller opts in (`allow_online=True` <- voice.allowOnline).
  mock    Deterministic offline provider for tests/CI: tone bursts with exact, known word timings.
Local engines live in pipeline/voice/engines.py; see docs/LOCAL_TTS.md.

Local providers (and mock) speak a *spoken form* of the narration (pipeline/voice/pronunciation.py:
"shrotihost.in" -> "Shro-tee Host dot in", "₹49" -> "forty nine rupees") and the returned boundaries
are mapped back onto the *display* tokens, so captions show the script exactly.

Every result is cached by sha256(provider, voice, rate, pitch, text, provider version [, spoken form,
options]) and the cache entry is re-validated (file hash + full decode) before reuse. Edge cache keys
are unchanged, so existing Edge cache entries remain valid and are never deleted by this module."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from . import procs
from .errors import TTSError
from .paths import CACHE_DIR, atomic_write_json, sha256_file, sha256_json, tmp_path_near

TICKS = 10_000_000  # edge-tts offsets are in 100 ns units
MAX_CHARS = 3000


@dataclass
class Boundary:
    """One provider word boundary (provider text may differ from the script: merges, numbers...)."""
    text: str
    start: float
    end: float


@dataclass
class TTSResult:
    audio: Path                      # mono/stereo audio file as delivered by the provider
    boundaries: list[Boundary]
    duration: float                  # exact decoded duration (seconds)
    meta: dict = field(default_factory=dict)


class TTSProvider(Protocol):
    name: str
    version: str

    def synthesize(self, text: str, voice: str, rate: str, pitch: str, out: Path, timeout: float) -> list[Boundary]: ...


def decode_duration(path: Path, sr: int = 48000) -> float:
    """Sample-exact duration by decoding; raises TTSError if the file is not valid audio."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       capture_output=True, timeout=120)
    if p.returncode != 0 or not p.stdout:
        raise TTSError(f"audio failed to decode: {path.name}", detail=p.stderr.decode(errors="replace")[-500:])
    return len(p.stdout) / 2 / sr


def validate_text(text: str) -> str:
    t = " ".join(text.split())
    if not t:
        raise TTSError("empty narration")
    if len(t) > MAX_CHARS:
        raise TTSError(f"narration too long for one request ({len(t)} > {MAX_CHARS} chars); split the scene")
    if any(ord(ch) < 32 for ch in t):
        raise TTSError("control characters in narration")
    return t


class EdgeProvider:
    name = "edge"
    online = True       # requires explicit opt-in (allow_online=True); never used as a fallback

    def __init__(self):
        try:
            import edge_tts  # noqa: F401
            self.version = edge_tts.__version__
        except ImportError as e:  # pragma: no cover - environment issue
            raise TTSError("edge-tts is not installed (uv sync)") from e

    def synthesize(self, text, voice, rate, pitch, out, timeout):
        import aiohttp
        import edge_tts

        async def go():
            com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary",
                                       connect_timeout=15, receive_timeout=60)
            words: list[Boundary] = []
            with open(out, "wb") as f:
                async for chunk in com.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        s = chunk["offset"] / TICKS
                        words.append(Boundary(chunk["text"], round(s, 3), round(s + chunk["duration"] / TICKS, 3)))
            return words

        try:
            return asyncio.run(asyncio.wait_for(go(), timeout))
        except (asyncio.TimeoutError, TimeoutError) as e:
            raise TTSError(f"edge-tts timed out after {timeout:.0f}s", transient=True) from e
        except (aiohttp.ClientError, edge_tts.exceptions.NoAudioReceived, edge_tts.exceptions.WebSocketError) as e:
            raise TTSError(f"edge-tts network/service error: {type(e).__name__}: {e}", transient=True) from e
        except ValueError as e:  # invalid voice / rate / pitch strings
            raise TTSError(f"edge-tts rejected the request: {e}") from e


class MockProvider:
    """Offline test double. Word durations are deterministic (not a model of real speech)."""
    name = "mock"
    version = "1"

    def __init__(self, fail_times: int = 0, fail_kind: str = "timeout"):
        self.fail_times, self.fail_kind, self.calls = fail_times, fail_kind, 0

    def synthesize(self, text, voice, rate, pitch, out, timeout):
        self.calls += 1
        if self.calls <= self.fail_times:
            if self.fail_kind == "timeout":
                raise TTSError("mock timeout", transient=True)
            raise TTSError("mock permanent failure")
        t, words, parts = 0.08, [], []
        for i, w in enumerate(text.split()):
            d = 0.12 + 0.045 * len(w)
            words.append(Boundary(w.strip(".,!?;:"), round(t, 3), round(t + d, 3)))
            parts.append(f"sine=f={300 + 40 * (i % 5)}:d={d:.3f}")
            gap = 0.30 if w[-1] in ".!?" else 0.06
            parts.append(f"anullsrc=r=24000:cl=mono:d={gap:.3f}")
            t += d + gap
        args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.08"]
        for p in parts:
            args += ["-f", "lavfi", "-i", p]
        n = len(parts) + 1
        args += ["-filter_complex", "".join(f"[{k}:a]aresample=24000,aformat=channel_layouts=mono[a{k}];" for k in range(n))
                 + "".join(f"[a{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1,volume=0.3[o]",
                 "-map", "[o]", "-c:a", "libmp3lame", "-q:a", "4", str(out)]
        procs.run(args, timeout=60)
        return words


class _Lazy:
    """Import local engines only when selected (keeps `import pipeline.tts` light). By default the
    engine runs in a worker process that exits when idle (memory returns to the OS)."""
    def __init__(self, name):
        self.name = name

    def __call__(self):
        from .voice import engines
        return engines.make(self.name)


MockProvider.uses_pronunciation = True
PROVIDERS = {"kokoro": _Lazy("kokoro"), "piper": _Lazy("piper"), "edge": EdgeProvider,
             "mock": MockProvider}
LOCAL_PROVIDERS = ("kokoro", "piper")
ONLINE_PROVIDERS = ("edge",)
_instances: dict[str, TTSProvider] = {}


def online_refusal(provider: str) -> TTSError:
    return TTSError(f"TTS provider {provider!r} is an ONLINE service: the narration text would be sent to Microsoft. "
                    "It is disabled unless the project opts in with voice.allowOnline: true. "
                    f"Use a local provider instead ({', '.join(LOCAL_PROVIDERS)}).")


def get_provider(name: str) -> TTSProvider:
    if name not in PROVIDERS:
        raise TTSError(f"unknown TTS provider {name!r}; available: {sorted(PROVIDERS)}")
    if name not in _instances:
        _instances[name] = PROVIDERS[name]()
    return _instances[name]


def unload_all() -> None:
    """Release local model memory (Kokoro/Piper sessions, Whisper). Safe to call any time."""
    for p in _instances.values():
        if hasattr(p, "unload"):
            p.unload()
    try:
        from .voice import asr
        asr.unload()
    except ImportError:  # pragma: no cover
        pass


def voice_fingerprint(v: dict) -> str:
    """Everything outside the voice config that changes local audio: pronunciation dictionary and
    model hashes. Add to stage cache keys so a dictionary edit re-synthesises."""
    from .voice import pronunciation, registry
    fp = {"pron": pronunciation.load(v.get("pronunciation")).fingerprint}
    if v.get("provider") in LOCAL_PROVIDERS:
        try:
            fp["files"] = {i: registry.entry(i)["sha256"] for i in registry.voice_files(v["provider"], v["voice"])}
        except TTSError:
            fp["files"] = None
        if v["provider"] == "kokoro":
            fp["model"] = registry.entry("kokoro-model")["sha256"]
    return sha256_json(fp)


def synthesize_from_config(text: str, v: dict, **kw) -> "TTSResult":
    """synthesize() with every field of a project `voice` section (what the runner should call)."""
    opts = {k: v[k] for k in ("lang",) if v.get(k)}
    return synthesize(text, provider=v["provider"], voice=v["voice"], rate=v.get("rate", "+0%"),
                      pitch=v.get("pitch", "+0Hz"), timeout=v.get("timeout", 90), attempts=v.get("attempts", 4),
                      allow_online=bool(v.get("allowOnline", False)), pronunciation=v.get("pronunciation"),
                      options=opts or None, **kw)


def synthesize(text: str, *, provider: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz",
               timeout: float = 90, attempts: int = 4, cache_dir: Path = CACHE_DIR / "tts",
               provider_obj: TTSProvider | None = None, on_retry=None, allow_online: bool = False,
               pronunciation: dict | None = None, options: dict | None = None) -> TTSResult:
    text = validate_text(text)
    if provider in ONLINE_PROVIDERS and not allow_online and provider_obj is None:
        raise online_refusal(provider)
    prov = provider_obj or get_provider(provider)
    if getattr(prov, "online", False) and not allow_online:
        raise online_refusal(prov.name)
    prep = None
    if getattr(prov, "uses_pronunciation", False):
        from .voice import pronunciation as P
        try:
            prep = P.prepare(text, pronunciation)
        except ValueError as e:
            raise TTSError(str(e)) from e
    spoken = prep.spoken if prep else text
    key_d = {"p": prov.name, "v": getattr(prov, "version", "?"), "voice": voice, "rate": rate, "pitch": pitch,
             "text": text}
    if prep is not None and (prov.name != "mock" or prep.changed):
        key_d.update({"spoken": spoken, "opts": options or {}})   # edge keys stay exactly as before
    key = sha256_json(key_d)
    entry = cache_dir / key[:2] / key
    audio, meta_f = entry / f"voice{getattr(prov, 'ext', '.mp3')}", entry / "meta.json"
    if meta_f.exists() and audio.exists():
        try:
            meta = json.loads(meta_f.read_text())
            if meta.get("sha256") == sha256_file(audio) and meta.get("text") == text:
                dur = decode_duration(audio)
                if abs(dur - meta["duration"]) < 0.01:
                    return TTSResult(audio, [Boundary(**b) for b in meta["boundaries"]], dur, {**meta, "cache": "hit"})
        except (json.JSONDecodeError, KeyError, TypeError, TTSError):
            pass
        shutil.rmtree(entry, ignore_errors=True)  # corrupt cache entry: rebuild, never trust it

    entry.mkdir(parents=True, exist_ok=True)

    def attempt():
        tmp = tmp_path_near(audio, audio.suffix)
        try:
            if options:
                bounds = prov.synthesize(spoken, voice, rate, pitch, tmp, timeout, options=options)
            else:
                bounds = prov.synthesize(spoken, voice, rate, pitch, tmp, timeout)
            if not tmp.exists() or tmp.stat().st_size < 512:
                raise TTSError("provider returned no audio", transient=True)
            dur = decode_duration(tmp)
            if dur < 0.2:
                raise TTSError(f"provider returned {dur:.2f}s of audio", transient=True)
            os.replace(tmp, audio)
            return bounds, dur
        finally:
            if tmp.exists():
                tmp.unlink()

    bounds, dur = procs.retry(attempt, attempts=attempts, base=1.5, cap=20, on_retry=on_retry)
    extra: dict = {}
    if prep is not None:
        from .timing import align_with_stats, map_to_display
        spoken_words, stats = align_with_stats(spoken, bounds, dur)
        disp = map_to_display(prep.groups, spoken_words)
        extra = {"spoken": spoken, "spoken_boundaries": [b.__dict__ for b in bounds], "align": stats,
                 "interpolated": [k for k, w in enumerate(disp) if w.interpolated],
                 "words": [w.as_dict() for w in disp]}
        bounds = [Boundary(w.text, round(w.start, 4), round(w.end, 4)) for w in disp]
    info = dict(getattr(prov, "last_info", {}) or {})
    if info:
        extra["engine"] = info
    meta = {"provider": prov.name, "provider_version": getattr(prov, "version", "?"), "voice": voice, "rate": rate,
            "pitch": pitch, "text": text, "duration": round(dur, 4), "sha256": sha256_file(audio),
            "boundaries": [b.__dict__ for b in bounds], "options": options or {}, **extra, "cache": "miss"}
    atomic_write_json(meta_f, meta)
    return TTSResult(audio, bounds, dur, meta)
