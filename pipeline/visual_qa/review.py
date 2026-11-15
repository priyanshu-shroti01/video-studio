"""Human-review aids. Automated QA cannot judge pronunciation; this lists exactly what a person should
listen for, with timestamps, using the same pronunciation rules the TTS used."""
from __future__ import annotations

import re

from ..timing import norm
from ..voice.hinglish import SOURCES, is_hinglish
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
    lang = cfg.get("voice", {}).get("lang")
    if is_hinglish(lang):
        return _hinglish_checklist(cfg, timing, overrides)
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


def _hinglish_checklist(cfg: dict, timing: dict, overrides: dict) -> tuple[str, list[dict]]:
    """Hinglish: every display word was transliterated, so every word is listed with its Devanagari spoken form and
    where that form came from; guesses (spelling rules / English pronunciation) are listed first."""
    words = timing["words"]
    items = []
    for sc, span in zip(cfg["storyboard"]["scenes"], timing["scene_spans"]):
        prep = prepare(sc["narration"], overrides, lang="hinglish")
        sw = [w for w in words if span[0] - 1e-3 <= w["start"] <= span[1] + 1e-3]
        k = wi = 0
        for (disp, n_spoken), src in zip(prep.groups, prep.sources):
            display = " ".join(disp)
            spoken = " ".join(prep.spoken_tokens[k:k + n_spoken])
            k += n_spoken
            t = span[0]
            for j in range(wi, len(sw)):                       # timings are in script order
                if norm(sw[j]["text"]) == norm(disp[0]):
                    t, wi = sw[j]["start"], j + 1
                    break
            items.append({"scene": sc["id"], "time": round(t, 2), "display": display, "spoken": spoken,
                          "source": src, "guess": src.endswith("-rules"), "why": SOURCES.get(src, src)})
    guesses = [it for it in items if it["guess"]]
    lines = ["# Pronunciation review (Hinglish)", "",
             "Automated QA cannot judge pronunciation. The captions show the Latin-script Hinglish; the voice read the "
             "Devanagari form below with Kokoro's Hindi phonemizer. Listen at each timestamp in `audio/voiceover.wav` "
             "(or the final video) and tick the box if it sounds right. Words marked *guess* were not in the word "
             "list (pipeline/voice/hinglish.json): check those first.", "",
             f"Voice: `{cfg['voice'].get('provider')}` / `{cfg['voice'].get('voice')}`, lang `hinglish`. "
             f"{len(items)} words, {len(guesses)} guessed. Fix a word with a project override: "
             "`\"voice\": {\"pronunciation\": {\"Display\": \"देवनागरी\"}}`.", "",
             "| ✓ | Time | Scene | On screen | Spoken as (Devanagari) | Source |", "|---|---|---|---|---|---|"]
    for it in sorted(items, key=lambda it: (not it["guess"], it["time"])):
        why = f"*guess*: {it['why']}" if it["guess"] else it["why"]
        lines.append(f"| [ ] | {_mmss(it['time'])} | {it['scene']} | {it['display']} | {it['spoken']} | {why} |")
    return "\n".join(lines) + "\n", items
