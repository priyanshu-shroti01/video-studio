"""Human-review aids. Automated QA cannot judge pronunciation; this lists exactly what a person should
listen for, with timestamps, using the same pronunciation rules the TTS used."""
from __future__ import annotations

import re

from ..timing import norm
from ..voice.pronunciation import prepare

TECH_TERMS = r"nvme|cpanel|whmcs|vps|wordpress|litespeed|ssl|₹|\.in\b|\.com\b"


def _terms(overrides: dict) -> re.Pattern:
    """Technical terms plus every brand/project respelling (brand names come from brands/<id>/pronunciation.json)."""
    extra = "|".join(re.escape(k) for k in sorted(overrides, key=len, reverse=True))
    return re.compile(TECH_TERMS + (f"|{extra}" if extra else ""), re.I)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def pronunciation_checklist(cfg: dict, timing: dict) -> tuple[str, list[dict]]:
    overrides = cfg.get("voice", {}).get("pronunciation") or {}
    brand_terms = _terms(overrides)
    words = timing["words"]
    items, wi = [], 0
    for sc, span in zip(cfg["storyboard"]["scenes"], timing["scene_spans"]):
        prep = prepare(sc["narration"], overrides)
        sw = [w for w in words if span[0] - 1e-3 <= w["start"] <= span[1] + 1e-3]
        k = 0
        for disp, n_spoken in prep.groups:
            display = " ".join(disp)
            spoken = " ".join(prep.spoken_tokens[k:k + n_spoken])
            k += n_spoken
            changed = norm(display) != norm(spoken)
            if changed or brand_terms.search(display):
                t = next((w["start"] for w in sw if norm(w["text"]) == norm(disp[0])), span[0])
                items.append({"scene": sc["id"], "time": round(t, 2), "display": display, "spoken": spoken,
                              "why": "respelled for the voice" if changed else "brand/technical term"})
    lines = ["# Pronunciation review", "",
             "Automated QA cannot judge pronunciation. Listen at each timestamp in `audio/voiceover.wav` "
             "(or the final video) and tick the box if it sounds right for an Indian audience.", "",
             f"Voice: `{cfg['voice'].get('provider')}` / `{cfg['voice'].get('voice')}`. "
             "Fix a word with a project override: `\"voice\": {\"pronunciation\": {\"Display\": \"spoken respelling\"}}`.",
             "", "| ✓ | Time | Scene | On screen | Spoken as | Why |", "|---|---|---|---|---|---|"]
    for it in items:
        lines.append(f"| [ ] | {_mmss(it['time'])} | {it['scene']} | {it['display']} | {it['spoken']} | {it['why']} |")
    return "\n".join(lines) + "\n", items
