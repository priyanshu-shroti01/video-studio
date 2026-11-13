"""Cue mapping: narration words -> time expressions ("@word:theme", "@word:WordPress#2+0.4").

Python owns time. A template says which narration words should trigger which element; `Anchors` finds the
first matching spoken word *after the previous cue* (so elements always appear in narration order), and when a
cue word is not spoken it chains a small offset from the previous cue instead of inventing a word. Every
expression it returns references a word that is in the scene's narration, so it passes validate_storyboard and
resolves against the real TTS timings."""
from __future__ import annotations

import re

from ..storyboard import word_matches
from ..timing import norm, tokenize

WPS = 2.33          # measured: local Kokoro am_michael at +5% speaks 2.37 words/s (3 renders, 2026-11-13); 2.33 absorbs pauses


def _est_times(tokens: list[str], wps: float = WPS) -> list[float]:
    """Same per-token estimate as pipeline.timeline.estimated_timing (relative to the first word)."""
    t, out = 0.0, []
    for tok in tokens:
        out.append(round(t, 3))
        d = max(0.18, len(tok) / (wps * 5.2))
        t += d + (0.25 if tok[-1:] in ".!?" else 0.08 if tok[-1:] in ",;:—" else 0.02)
    return out


def _fmt(base: str, off: float) -> str:
    off = round(off, 2)
    return base if abs(off) < 1e-9 else f"{base}{'+' if off > 0 else '-'}{abs(off):g}"


class Anchors:
    def __init__(self, narration: str):
        self.narration = narration
        self.tokens = tokenize(narration)
        self.times = _est_times(self.tokens)
        self.speech_end = self.times[-1] + 0.3 if self.times else 0.5
        self.last: tuple[str, float, float] | None = None      # (base expr, offset, est time)
        self.used: list[dict] = []

    # -- lookups ---------------------------------------------------------------------------
    def index_of(self, word: str, start: int = 0) -> int | None:
        for i in range(start, len(self.tokens)):
            if word_matches(self.tokens[i], word):
                return i
        return None

    def has(self, word: str) -> bool:
        return self.index_of(word) is not None

    def _base(self, word: str, i: int) -> str:
        w = re.sub(r"[^\w',.]", "", word).rstrip(".,")
        nth = sum(1 for t in self.tokens[:i + 1] if word_matches(t, w))
        return f"@word:{w}" + (f"#{nth}" if nth > 1 else "")

    # -- the API ---------------------------------------------------------------------------
    def at(self, cands, off: float = 0.0, *, gap: float = 0.45, name: str = "", advance: bool = True,
           priority: bool = False, free: bool = False) -> str:
        """Expression for the first spoken candidate word after the previous cue (+off); otherwise the previous
        cue + gap (or scene-relative when nothing was cued yet)."""
        cands = [cands] if isinstance(cands, str) else list(cands or [])
        if free:     # an independent element: first spoken candidate anywhere, does not move the cue cursor
            advance = False
        last_t = self.last[2] if self.last and not free else -1.0
        best = None
        for c in cands:
            if not norm(c) and not re.search(r"\d", c):
                continue
            j = 0
            while True:
                i = self.index_of(c, j)
                if i is None:
                    break
                if self.times[i] + off >= last_t + 0.12:
                    if best is None or i < best[0]:
                        best = (i, c)
                    break
                j = i + 1
            if priority and best:      # candidate order wins over narration order
                break
        if best:
            i, c = best
            base, o, t = self._base(c, i), off, self.times[i] + off
            hit = c
        elif self.last:
            base, o0, t0 = self.last
            o, t, hit = o0 + gap, t0 + gap, None
        else:   # nothing cued yet: the first spoken word (never the scene start)
            base, o, t, hit = self.word_expr(0), off, (self.times[0] if self.times else 0.0) + off, None
        expr = _fmt(base, o)
        self.used.append({"element": name, "cues": cands, "word": hit, "expr": expr})
        if advance:
            self.last = (base, o, t)
        return expr

    def after(self, off: float, name: str = "") -> str:
        """Previous cue + off (does not need a word)."""
        if not self.last:
            return self.first_word(off, name=name)
        base, o, t = self.last
        self.last = (base, o + off, t + off)
        expr = _fmt(base, o + off)
        self.used.append({"element": name, "cues": [], "word": None, "expr": expr})
        return expr

    def word_expr(self, i: int) -> str:
        """'@word:X[#n]' for token i (cleaned of punctuation)."""
        i = i if i >= 0 else len(self.tokens) + i
        m = re.search(r"\w[\w',.]*\w|\w", self.tokens[i])
        w = m.group(0).rstrip(".,") if m else self.tokens[i]
        return self._base(w, i)

    def last_word(self, off: float = 0.2, name: str = "") -> str:
        """The final spoken word + off (for end-of-scene beats such as scroll ends)."""
        expr = _fmt(self.word_expr(-1), off)
        self.used.append({"element": name, "cues": [], "word": "<last>", "expr": expr})
        return expr

    def first_word(self, off: float = 0.0, name: str = "") -> str:
        expr = _fmt(self.word_expr(0), off)
        if self.last is None:
            self.last = (self.word_expr(0), off, (self.times[0] if self.times else 0.0) + off)
        self.used.append({"element": name, "cues": [], "word": "<first>", "expr": expr})
        return expr

    def missing(self, words: list[str]) -> list[str]:
        return [w for w in words if not self.has(w)]
