"""Local speech recognition (faster-whisper, Whisper base.en int8 on CPU) for two jobs:

1. timing fallback: word timestamps for an engine that could not report its own durations;
2. evaluation: ASR round-trip intelligibility (WER vs the spoken script) and brand-term recognition.

Whisper word timestamps come from cross-attention alignment, not true forced alignment: expect tens of
milliseconds of error (measured in docs/LOCAL_TTS.md). Runs offline: the model is loaded from
models/voice/whisper/base.en and Hugging Face network access is disabled for this process."""
from __future__ import annotations

import gc
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from ..errors import TTSError
from ..tts import Boundary
from . import registry

FILES = ["whisper-model", "whisper-config", "whisper-tokenizer", "whisper-vocab"]
_shared = None


def decode16k(path: Path) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True, timeout=120)
    if p.returncode != 0:
        raise TTSError(f"cannot decode {path.name} for ASR", detail=p.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


class Whisper:
    def __init__(self, threads: int = 4):
        self.model, self.threads, self.load_s = None, threads, 0.0

    def load(self):
        if self.model is None:
            registry.require(FILES, "whisper")
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            t0 = time.perf_counter()
            from faster_whisper import WhisperModel
            self.model = WhisperModel(str(registry.path("whisper-model").parent), device="cpu", compute_type="int8",
                                      cpu_threads=self.threads, local_files_only=True)
            self.load_s = time.perf_counter() - t0
        return self.model

    def unload(self):
        self.model = None
        gc.collect()

    def transcribe(self, path: Path, prompt: str | None = None) -> tuple[str, list[Boundary]]:
        m = self.load()
        segs, _ = m.transcribe(decode16k(path), language="en", beam_size=5, word_timestamps=True,
                               vad_filter=False, condition_on_previous_text=False, initial_prompt=prompt)
        words, text = [], []
        for s in segs:
            text.append(s.text)
            for w in s.words or []:
                words.append(Boundary(w.word.strip(), round(w.start, 3), round(w.end, 3)))
        return " ".join(t.strip() for t in text).strip(), words

    def word_boundaries(self, path: Path, prompt: str | None = None) -> list[Boundary]:
        """Word timestamps, split so hyphenated/dotted ASR words ("forty-nine", "shrotihost.in") become
        several boundaries that timing.align can re-join or match."""
        _, words = self.transcribe(path, prompt=prompt)
        out = []
        for b in words:
            parts = [p for p in re.split(r"[-\s]+", b.text) if p]
            if len(parts) <= 1:
                out.append(b); continue
            span = b.end - b.start
            total = sum(len(p) for p in parts)
            t = b.start
            for p in parts:
                d = span * len(p) / total
                out.append(Boundary(p, round(t, 3), round(t + d, 3))); t += d
        return out


def shared() -> Whisper:
    global _shared
    if _shared is None:
        _shared = Whisper()
    return _shared


def unload():
    if _shared is not None:
        _shared.unload()
