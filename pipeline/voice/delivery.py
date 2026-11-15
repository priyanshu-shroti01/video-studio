"""Per-scene delivery: how the narrator says a scene, not just what.

A hook is said with urgency, a problem seriously, a reveal with excitement, proof upbeat and a call to action
calmly. Each delivery is a small change of speaking rate (all engines) and pitch (Microsoft voices; local engines
ignore pitch) on top of the production's voice. A scene sets it with `"delivery": "urgent"`; without one it
follows the scene's `purpose`.
"""
from __future__ import annotations

import re

# name -> (rate change in %, pitch change in Hz)
DELIVERIES: dict[str, tuple[int, int]] = {
    "neutral": (0, 0),
    "urgent": (8, 3),
    "serious": (-4, -4),
    "excited": (6, 6),
    "upbeat": (4, 4),
    "calm": (-5, -2),
}
BY_PURPOSE = {"hook": "urgent", "problem": "serious", "turn": "excited", "resolution": "upbeat", "cta": "calm",
              "conclusion": "calm"}
PITCH_PROVIDERS = {"edge"}          # engines that honour a pitch change


def scene_delivery(scene: dict) -> str:
    d = scene.get("delivery")
    if d in DELIVERIES:
        return d
    return BY_PURPOSE.get(scene.get("purpose", ""), "neutral")


def _shift(value: str | None, delta: int, unit: str) -> str:
    m = re.fullmatch(rf"([+-]?\d+){re.escape(unit)}", (value or f"+0{unit}").strip())
    base = int(m.group(1)) if m else 0
    return f"{base + delta:+d}{unit}"


def scene_voice(v: dict, scene: dict) -> dict:
    """The production's voice section with this scene's delivery applied (rate always; pitch where supported)."""
    rate_d, pitch_d = DELIVERIES[scene_delivery(scene)]
    if not rate_d and not pitch_d:
        return v
    out = {**v, "rate": _shift(v.get("rate"), rate_d, "%")}
    if v.get("provider") in PITCH_PROVIDERS and pitch_d:
        out["pitch"] = _shift(v.get("pitch"), pitch_d, "Hz")
    return out
