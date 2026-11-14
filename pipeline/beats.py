"""Beat / onset detection for the music bed, and beat snapping of effect transitions and punch-zooms.

Detection (numpy + ffmpeg only, deterministic):
  * decode to mono 22.05 kHz float (ffmpeg), STFT (Hann 1024 / hop 512), log-compressed spectral flux = onset envelope;
  * tempo from the envelope's autocorrelation (60–200 BPM, mild prior around 120 BPM);
  * beats by dynamic programming (Ellis 2007: onset strength + a penalty for deviating from the beat period);
  * onsets by peak picking on the envelope.
Results are cached per track content: `.pipeline/cache/beats/<sha256>.json`.

Snapping (`snap_timeline`): when a storyboard opts in (`beatSync: true`, set by the director for new concepts) and a
music track is configured, a scene boundary whose scene enters with an EFFECT transition, and every punch-zoom, may move
to the nearest beat within ±SNAP_WINDOW s, but only if the word-anchor rules still hold:
  * a boundary never cuts the previous scene before its last word has been spoken (+0.05 s), never shows the new scene
    after its first word, never cuts a block / effect of the previous scene, and keeps every scene ≥ MIN_SCENE s;
  * a punch-zoom stays on its anchor word (never before the start of a spoken number);
  * the narration-sync check (sync_check.evaluate) must not get worse: no new static stretch > 2.5 s, no early number.
Every decision (snapped / kept, with the reason) is recorded."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from .paths import CACHE_DIR, ROOT, sha256_file

VERSION = 1
SR = 22050
N_FFT = 1024
HOP = 512
SNAP_WINDOW = 0.12
MIN_SCENE = 0.8
BPM_RANGE = (60.0, 200.0)
SNAP_TRANSITIONS = {"whip-pan", "zoom-through", "push", "iris", "light-leak", "glitch"}
SNAP_EFFECTS = {"punch-zoom"}


# ---------------------------------------------------------------------------------------------- detection
def decode(path: Path, sr: int = SR) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {path}: {p.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype="<f4").astype(np.float64)


def onset_envelope(x: np.ndarray, sr: int = SR) -> tuple[np.ndarray, float]:
    """Spectral-flux onset strength per hop (normalised to max 1) and the envelope frame rate (Hz)."""
    if len(x) < N_FFT:
        x = np.pad(x, (0, N_FFT - len(x)))
    n = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(N_FFT)[None, :]
    mag = np.abs(np.fft.rfft(frames, axis=1))
    logm = np.log1p(1000.0 * mag)
    flux = np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    # remove the slowly varying part (sustained loudness), keep the attacks
    k = 16
    local = np.convolve(flux, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
    env = np.maximum(0.0, flux - local)
    m = env.max()
    return (env / m if m > 0 else env), sr / HOP


def estimate_tempo(env: np.ndarray, fr: float) -> float:
    """BPM from the autocorrelation of the onset envelope (log-normal prior centred on 120 BPM)."""
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    # a beat period rarely falls on a whole number of hops: its peak is split over two lags, so score a 3-lag window
    ac = np.convolve(ac, np.ones(3), mode="same")
    lags = np.arange(len(ac))
    lo = max(1, int(fr * 60.0 / BPM_RANGE[1]))
    hi = min(len(ac) - 2, int(fr * 60.0 / BPM_RANGE[0]))
    if hi <= lo:
        return 120.0
    bpm = 60.0 * fr / np.maximum(lags[lo:hi + 1], 1)
    prior = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
    score = ac[lo:hi + 1] * prior
    i = int(np.argmax(score)) + lo
    # parabolic refinement of the peak lag
    if lo < i < hi:
        a, b, c = ac[i - 1], ac[i], ac[i + 1]
        den = a - 2 * b + c
        off = 0.5 * (a - c) / den if den != 0 else 0.0
    else:
        off = 0.0
    return float(60.0 * fr / (i + max(-0.5, min(0.5, off))))


def track_beats(env: np.ndarray, fr: float, bpm: float, tightness: float = 100.0) -> np.ndarray:
    """Dynamic-programming beat tracker: frame indices of the beats."""
    period = fr * 60.0 / bpm
    n = len(env)
    score = env.copy()
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    for t in range(n):
        a, b = t - hi, t - lo
        if b < 0:
            continue
        a = max(0, a)
        prev = np.arange(a, b + 1)
        pen = -tightness * np.log((t - prev) / period) ** 2
        cand = score[a:b + 1] + pen
        j = int(np.argmax(cand))
        if cand[j] > 0:
            score[t] = env[t] + cand[j]
            back[t] = prev[j]
    # start from the best-scoring frame in the last period, then follow the back pointers
    tail = max(0, n - int(round(period)))
    t = tail + int(np.argmax(score[tail:])) if n else 0
    beats = []
    while t >= 0 and n:
        beats.append(t)
        t = back[t]
    return np.array(sorted(beats), dtype=int)


def pick_onsets(env: np.ndarray, fr: float, delta: float = 0.08, wait_s: float = 0.08) -> np.ndarray:
    """Local maxima of the envelope above a moving threshold (seconds)."""
    w = 3
    thr = np.convolve(env, np.ones(15) / 15, mode="same") + delta
    out, last = [], -1e9
    for i in range(w, len(env) - w):
        if env[i] >= thr[i] and env[i] == env[i - w:i + w + 1].max() and (i - last) / fr >= wait_s:
            out.append(i)
            last = i
    return np.array(out, dtype=float) / fr


def detect(x: np.ndarray, sr: int = SR) -> dict:
    """Beats + onsets of a mono signal. Pure (no I/O); deterministic."""
    env, fr = onset_envelope(x, sr)
    bpm = estimate_tempo(env, fr)
    bt = track_beats(env, fr, bpm)
    # frame i analyses samples [i·HOP, i·HOP + N_FFT): an attack gives its strongest flux when it reaches the centre of
    # the (Hann) window, so a frame's time is that centre
    c = N_FFT / 2 / sr
    beats = [round(float(b) / fr + c, 4) for b in bt]
    return {"version": VERSION, "bpm": round(bpm, 2), "beats": beats,
            "onsets": [round(float(o) + c, 4) for o in pick_onsets(env, fr)], "duration": round(len(x) / sr, 3)}


def cache_path(sha: str) -> Path:
    return CACHE_DIR / "beats" / f"{sha}.json"


def beats_for(track: str | Path) -> dict:
    """Detected beats of a music file (cached per sha256 of its bytes)."""
    p = Path(track)
    p = p if p.is_absolute() else ROOT / p
    sha = sha256_file(p)
    cp = cache_path(sha)
    if cp.exists():
        try:
            d = json.loads(cp.read_text())
            if d.get("version") == VERSION:
                return d
        except (OSError, ValueError):
            pass
    d = {**detect(decode(p)), "sha256": sha, "file": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)}
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    tmp.replace(cp)
    return d


def timeline_beats(info: dict, duration: float) -> list[float]:
    """Beat times on the video timeline: the mix plays the track from 0 and loops it (pipeline/audio.py mix)."""
    beats, period = info.get("beats") or [], float(info.get("duration") or 0)
    if not beats or period <= 0:
        return []
    out, k = [], 0
    while k * period < duration:
        out += [round(b + k * period, 4) for b in beats if b + k * period < duration]
        k += 1
    return out


# ---------------------------------------------------------------------------------------------- snapping
def _nearest(beats: list[float], t: float, window: float) -> float | None:
    if not beats:
        return None
    a = np.asarray(beats)
    i = int(np.argmin(np.abs(a - t)))
    return float(a[i]) if abs(a[i] - t) <= window + 1e-9 else None


def _times(o) -> list[float]:
    from .sync_check import _times as st
    return st(o)


def _sync(scenes: list[dict], words: list[dict], duration: float) -> dict:
    from .sync_check import evaluate
    return evaluate(scenes, words, duration)


def _not_worse(before: dict, after: dict) -> str | None:
    from .sync_check import STATIC_WARN
    if len(after["early_numbers"]) > len(before["early_numbers"]):
        return "a number would appear before it is spoken"
    worst_b = max([x["seconds"] for x in before["static"]], default=0.0)
    worst_a = max([x["seconds"] for x in after["static"]], default=0.0)
    if worst_a > max(STATIC_WARN, worst_b) + 1e-9 or len(after["static"]) > len(before["static"]):
        return "it would leave > 2.5 s of narration without a visual event"
    return None


def snap_timeline(resolved: list[dict], words: list[dict], beats: list[float], duration: float, fps: int,
                  anchors: dict[tuple[int, int], dict] | None = None, sfx: list[dict] | None = None,
                  window: float = SNAP_WINDOW) -> dict:
    """Snap effect-transition boundaries and punch-zooms of `resolved` (modified in place) to `beats`.

    words: [{text, start, end}] (absolute). anchors: (scene index, effect index) -> {"start", "end", "text", "numeric"}
    of the effect's anchor word. sfx: the cue list; a boundary's transition whoosh moves with it. -> report."""
    snapped, kept = [], []
    q = lambda x: round(round(x * fps) / fps, 3)  # noqa: E731  (land on a frame)
    base = _sync(resolved, words, duration)
    spans = []
    for s in resolved:
        sw = [w for w in words if s["start"] - 1e-3 <= w["start"] <= s["end"] + 1e-3]
        spans.append((sw[0]["start"], sw[-1]["end"]) if sw else (s["start"], s["end"]))
    for k in range(1, len(resolved)):
        s, prev = resolved[k], resolved[k - 1]
        if s.get("transition") not in SNAP_TRANSITIONS:
            continue
        B = s["start"]
        b = _nearest(beats, B, window)
        rec = {"kind": "transition", "scene": s["id"], "transition": s["transition"], "from": B}
        if b is None:
            kept.append({**rec, "reason": f"no beat within ±{int(window * 1000)} ms"})
            continue
        nb = q(b)
        reason = None
        prev_last = max([w["end"] for w in words if prev["start"] - 1e-3 <= w["start"] < B], default=prev["start"])
        nxt_first = min([w["start"] for w in words if B - 0.2 <= w["start"] <= s["end"]], default=s["end"])
        if nb < prev_last + 0.05:
            reason = "the previous scene's last word would be cut"
        elif nb > max(nxt_first, B):
            reason = "the new scene would appear after its first word"
        elif nb - prev["start"] < MIN_SCENE or s["end"] - nb < MIN_SCENE:
            reason = "a scene would get too short"
        elif any(t > nb - 0.3 for t in _times(prev["blocks"]) + _times(prev.get("effects", []))):
            reason = "a block or effect of the previous scene would be cut"
        if reason is None and abs(nb - B) > 1e-6:
            old = (prev["end"], s["start"])
            prev["end"], s["start"] = nb, nb
            r = _not_worse(base, _sync(resolved, words, duration))
            if r:
                prev["end"], s["start"] = old
                reason = r
        if reason:
            kept.append({**rec, "reason": reason})
            continue
        if sfx is not None:
            for e in sfx:
                if e.get("kind") == "transition" and abs(e["t"] - (B + 0.1)) < 1e-3:
                    e["t"] = round(nb + 0.1, 3)
        snapped.append({**rec, "to": nb, "beat": round(b, 3), "delta_ms": round((nb - B) * 1000)})
        base = _sync(resolved, words, duration)
    for si, s in enumerate(resolved):
        for ei, e in enumerate(s.get("effects", [])):
            if e.get("type") not in SNAP_EFFECTS:
                continue
            at = e["at"]
            rec = {"kind": e["type"], "scene": s["id"], "effect": ei, "from": at}
            b = _nearest(beats, at, window)
            if b is None:
                kept.append({**rec, "reason": f"no beat within ±{int(window * 1000)} ms"})
                continue
            nb = q(b)
            a = (anchors or {}).get((si, ei))
            reason = None
            if a is None:
                reason = "not anchored to a spoken word"
            elif nb < a["start"] - (0.0 if a.get("numeric") else 0.06) or nb > a["end"]:
                reason = f"the beat is off the anchor word {a['text']!r}"
            elif nb < s["start"] + 0.1 or nb > s["end"] - 0.7:
                reason = "too close to the scene's cut"
            if reason is None and abs(nb - at) > 1e-6:
                e["at"] = nb
                r = _not_worse(base, _sync(resolved, words, duration))
                if r:
                    e["at"] = at
                    reason = r
            if reason:
                kept.append({**rec, "reason": reason})
                continue
            snapped.append({**rec, "to": nb, "beat": round(b, 3), "delta_ms": round((nb - at) * 1000)})
            base = _sync(resolved, words, duration)
    return {"window_ms": int(window * 1000), "snapped": snapped, "kept": kept}
