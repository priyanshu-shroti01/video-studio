"""Narration ↔ visual sync (a semantic check; frame-accurate A/V is verified separately).

A video can be frame-accurate and still *feel* out of sync: the voice lists "one-click install, SSL, cache"
while the screen stays frozen, or a price card shows ₹39 seconds before the voice says it. Two rules,
evaluated on the resolved timeline (estimated timings in the preview gate, real voice timings in QA):

  * static narration — no visual event (entrance, item reveal, count, keystroke, click, state change)
    for more than STATIC_FAIL s while words are being spoken                            FAIL (> WARN: WARN)
  * early number     — a (non-catalog) number appears on screen more than EARLY s before it is first spoken in that scene  FAIL
"""
from __future__ import annotations

import re

from .contract import TIME_KEYS

STATIC_WARN = 2.5
STATIC_FAIL = 3.0
EARLY = 0.3
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
CATALOG = {"plans"}        # a grid of several plans is context, not one spoken claim
NUM_FIELDS = {"text", "label", "value", "price", "amount", "note", "sub", "detail", "name", "doneText", "title"}


def _times(o) -> list[float]:
    out: list[float] = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in TIME_KEYS or k == "keyTimes":
                if isinstance(v, (int, float)):
                    out.append(float(v))
                elif isinstance(v, list):
                    out += [float(x) for x in v if isinstance(x, (int, float))]
            else:
                out += _times(v)
    elif isinstance(o, list):
        for v in o:
            out += _times(v)
    return out


def _numbers_shown(o, at: float | None, out: list):
    """(number, first display time) for every number in on-screen text, using the nearest enclosing `at`."""
    if isinstance(o, dict):
        if o.get("type") in CATALOG:
            return out
        at = float(o["at"]) if isinstance(o.get("at"), (int, float)) else at
        if o.get("kind") == "number" and isinstance(o.get("to"), (int, float)) and at is not None:
            # a composition number counts up like a counter: it is shown when the count lands (countEnd)
            t = float(o["countEnd"]) if isinstance(o.get("countEnd"), (int, float)) else at
            n = o["to"]
            out.append((str(int(n)) if float(n).is_integer() else str(n), t))
        for k, v in o.items():
            if k in NUM_FIELDS and isinstance(v, (str, int, float)) and at is not None:
                # a count-up builds toward the number; it is "shown" when the count lands
                t = float(o["countEnd"]) if k in ("amount", "value") and isinstance(o.get("countEnd"), (int, float)) else at
                for n in NUM.findall(str(v)):
                    out.append((n.replace(",", "").removesuffix(".0"), t))
            elif isinstance(v, (dict, list)):
                _numbers_shown(v, at, out)
    elif isinstance(o, list):
        for v in o:
            _numbers_shown(v, at, out)
    return out


def evaluate(scenes: list[dict], words: list[dict], duration: float) -> dict:
    """scenes: resolved timeline scenes (absolute seconds); words: [{text,start,end}]."""
    events = sorted({round(t, 3) for s in scenes for t in _times(s["blocks"])} | {round(s["start"], 3) for s in scenes})
    pts = events + [duration]
    static = []
    for a, b in zip(pts, pts[1:]):
        spoken = [w for w in words if a <= w["start"] < b]
        if not spoken:
            continue
        # measure only the stretch where the voice is actually talking with nothing new on screen
        span = min(b, spoken[-1]["end"]) - max(a, spoken[0]["start"])
        if span > STATIC_WARN:
            static.append({"from": round(a, 2), "to": round(b, 2), "seconds": round(span, 1),
                           "level": "FAIL" if span > STATIC_FAIL else "WARN",
                           "said": " ".join(w["text"] for w in spoken)[:120]})
    early = []
    for s in scenes:
        sw = [w for w in words if s["start"] - 1e-3 <= w["start"] <= s["end"] + 1e-3]
        seen = {}
        for b in s["blocks"]:
            for n, t in _numbers_shown(b, None, []):
                seen[n] = min(t, seen.get(n, t))
        for n, t in seen.items():
            spoken = [w["start"] for w in sw if n in NUM.findall(w["text"].replace(",", ""))]
            if spoken and t < spoken[0] - EARLY:
                early.append({"scene": s["id"], "number": n, "shown": round(t, 2), "spoken": round(spoken[0], 2),
                              "lead_s": round(spoken[0] - t, 2)})
    worst = max((x["seconds"] for x in static), default=0.0)
    speech = sum(w["end"] - w["start"] for w in words) or 1.0
    status = "FAIL" if early or any(x["level"] == "FAIL" for x in static) else ("WARN" if static else "PASS")
    return {"status": status, "events": len(events), "longest_static_s": worst,
            "static_share_pct": round(100 * sum(x["seconds"] for x in static) / speech, 1),
            "static": static, "early_numbers": early}


def summary(r: dict) -> str:
    parts = []
    if r["static"]:
        parts.append("frozen while speaking: " + "; ".join(f"{x['from']}-{x['to']}s {x['seconds']}s \"{x['said'][:50]}\""
                                                           for x in r["static"][:4]))
    if r["early_numbers"]:
        parts.append("numbers shown before spoken: " + "; ".join(f"{x['scene']} {x['number']} {x['lead_s']}s early"
                                                                 for x in r["early_numbers"][:4]))
    return " | ".join(parts) or f"a visual event at least every {STATIC_WARN}s of narration; numbers appear as spoken"


def av_offset(voice: "Path", video: "Path", win_s: float = 4.0, max_lag_s: float = 0.3) -> dict:
    """Measured lag of the narration inside the final video vs the voiceover it was built from (4 s windows,
    100 Hz loudness envelopes, ±300 ms search). Positive = the voice in the video is late."""
    import subprocess

    import numpy as np

    def env(p):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        x = np.abs(np.frombuffer(raw, np.float32))
        n = len(x) // 80
        return x[:n * 80].reshape(n, 80).mean(1)
    a, b = env(voice), env(video)
    W, L = int(win_s * 100), int(max_lag_s * 100)
    lags = []
    for s0 in range(L, len(a) - W - L, W):
        seg = a[s0:s0 + W]
        if seg.std() < 1e-4:
            continue
        best = max(((float(np.corrcoef(seg, b[s0 + k:s0 + k + W])[0, 1]), k) for k in range(-L, L + 1)
                    if s0 + k + W <= len(b)), default=None)
        if best and best[0] > 0.6:
            lags.append({"t": round(s0 / 100, 1), "lag_ms": best[1] * 10, "corr": round(best[0], 2)})
    ms = [x["lag_ms"] for x in lags]
    return {"windows": len(lags), "max_abs_lag_ms": max((abs(m) for m in ms), default=None),
            "drift_ms": (ms[-1] - ms[0]) if ms else None, "lags": lags}
