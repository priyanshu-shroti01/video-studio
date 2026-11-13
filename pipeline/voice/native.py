"""Word boundaries from an engine's own phoneme durations (no ASR, no network).

Kokoro (timestamped ONNX export) and Piper (voice patched to expose `w_ceil`) report how many audio
samples each phoneme occupies. Phonemes are grouped back into the spoken words of the text:

* fast path: espeak produced one phoneme-word per text word -> 1:1;
* otherwise espeak merged or split words (it writes "with the" as one word "wɪððə"), so each text word
  is phonemized on its own and aligned to the sentence phonemes character by character (Needleman-
  Wunsch, stress marks ignored); each text word gets the time span of the phonemes aligned to it.

Punctuation phonemes are pauses and never belong to a word."""
from __future__ import annotations

from dataclasses import dataclass

from ..timing import norm
from ..tts import Boundary

STRESS = set("ˈˌ")
PUNCT = set(".,!?;:—…\"()“”«»¡¿'")


@dataclass
class Ph:
    """One phoneme with its time span (seconds)."""
    p: str
    start: float
    end: float


def _phoneme_words(phs: list[Ph]) -> list[list[Ph]]:
    words, cur = [], []
    for ph in phs:
        if ph.p == " ":
            if cur:
                words.append(cur); cur = []
        elif ph.p in PUNCT:
            if cur:
                words.append(cur); cur = []
        else:
            cur.append(ph)
    if cur:
        words.append(cur)
    return [w for w in words if any(x.p not in STRESS for x in w)]


def _span(chars: list[Ph]) -> tuple[float, float]:
    core = [c for c in chars if c.p not in STRESS] or chars
    return core[0].start, core[-1].end


def words_from_phonemes(tokens: list[str], phs: list[Ph], isolated: list[str] | None = None) -> tuple[list[Boundary], str]:
    """-> (one Boundary per text token, method). `isolated[i]` = phonemes of tokens[i] said alone
    (needed only when the phoneme-word count differs from the token count)."""
    tokens = [t for t in tokens if norm(t)]
    pw = _phoneme_words(phs)
    if len(pw) == len(tokens):
        return [Boundary(t, *(round(float(x), 4) for x in _span(w))) for t, w in zip(tokens, pw)], "native"
    if isolated is None or len(isolated) != len(tokens):
        raise ValueError(f"{len(pw)} phoneme words for {len(tokens)} text words and no per-word phonemes")
    # character alignment: A = isolated phonemes (owner = token index), B = sentence phonemes
    A, owner = [], []
    for k, iso in enumerate(isolated):
        for ch in iso:
            if ch in STRESS or ch in PUNCT or ch == " ":
                continue
            A.append(ch); owner.append(k)
    Bp = [ph for w in pw for ph in w if ph.p not in STRESS]
    n, m = len(A), len(Bp)
    if not n or not m:
        raise ValueError("no phonemes to align")
    # DP with three ops; costs: match 0, substitute 1, gap 1
    INF = 10**9
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    D[0] = list(range(m + 1))
    for a in range(1, n + 1):
        D[a][0] = a
        row, prev, ca = D[a], D[a - 1], A[a - 1]
        for b in range(1, m + 1):
            row[b] = min(prev[b - 1] + (0 if ca == Bp[b - 1].p else 1), prev[b] + 1, row[b - 1] + 1)
    a, b = n, m
    who = [-1] * m
    while a > 0 and b > 0:
        if D[a][b] == D[a - 1][b - 1] + (0 if A[a - 1] == Bp[b - 1].p else 1):
            who[b - 1] = owner[a - 1]; a -= 1; b -= 1
        elif D[a][b] == D[a - 1][b] + 1:
            a -= 1
        else:
            b -= 1
    # unaligned sentence phonemes take the previous owner (or the next one at the very start)
    last = next((w for w in who if w >= 0), 0)
    for k in range(m):
        if who[k] < 0:
            who[k] = last
        last = who[k] = max(who[k], last)  # owners never go backwards in time
    spans: dict[int, list[Ph]] = {}
    for k, ph in enumerate(Bp):
        spans.setdefault(who[k], []).append(ph)
    out = []
    for k, t in enumerate(tokens):
        if k in spans:
            out.append(Boundary(t, round(float(spans[k][0].start), 4), round(float(spans[k][-1].end), 4)))
    # tokens with no phonemes (fully reduced) are simply absent -> timing.align interpolates them
    return out, "native+dp"


def refine_with_energy(bounds: list[Boundary], audio, sr: int, *, thr_db: float = -40.0, frame: float = 0.005,
                       reach: float = 0.15) -> tuple[list[Boundary], int]:
    """Snap word edges that touch a pause (punctuation, utterance start/end) to the audio's energy
    edges. Kokoro's duration predictor gives the phoneme before a pause most of the pause (measured:
    word ends 200-350 ms late, see docs/LOCAL_TTS.md); real silence makes these edges unambiguous.
    Edges only move inward (ends earlier, starts within +-reach); intra-phrase edges are untouched.
    -> (bounds, number of edges moved)."""
    import numpy as np
    f = max(1, int(frame * sr))
    n = len(audio) // f
    if not n or not bounds:
        return bounds, 0
    e = np.sqrt((np.asarray(audio[: n * f], dtype=np.float64).reshape(n, f) ** 2).mean(1)) + 1e-12
    loud = 20 * np.log10(e / e.max()) > thr_db
    out = [Boundary(b.text, b.start, b.end) for b in bounds]
    moved = 0
    for k, b in enumerate(out):
        pause_after = k == len(out) - 1 or b.text[-1:] in ".,?!;:"
        pause_before = k == 0 or out[k - 1].text[-1:] in ".,?!;:"
        if pause_after:
            lo, hi = int((b.start + 0.04) / frame), min(n, int(b.end / frame) + 1)
            idx = np.nonzero(loud[lo:hi])[0]
            if len(idx):
                end = (lo + idx[-1] + 1) * frame
                if end < b.end - 0.01:
                    b.end = round(float(end), 4); moved += 1
        if pause_before:
            floor = out[k - 1].end if k else 0.0
            lo = max(int(floor / frame), int((b.start - reach) / frame), 0)
            hi = min(n, int((b.start + reach) / frame))
            idx = np.nonzero(loud[lo:hi])[0]
            if len(idx):
                start = (lo + idx[0]) * frame
                if abs(start - b.start) > 0.01 and start < b.end - 0.03:
                    b.start = round(float(start), 4); moved += 1
    return out, moved
