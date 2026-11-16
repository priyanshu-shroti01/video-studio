"""Narration language for the creative engine (brief field `language`: "english" (default) | "hinglish").

English is the default and nothing English changes: the same copy bank, cue words, number rules and speaking rate.
With "hinglish" the engine writes Latin-script Hinglish (Hindi grammar, English nouns and tech words kept in
English: "Brief do, aur video lo"), and these language-specific parts switch over:

  copy          the Hinglish copy bank (pipeline/creative/hinglish_copy.py); a template without a Hinglish line is
                not available to a Hinglish concept (never an English line in a Hinglish film)
  cue words     CUE_ALIASES: where a template animates on an English word that Hinglish says in Hindi ("Meet" ->
                "Milo", "person" -> "insaan"), the Hindi word triggers the same beat
  numbers       Hindi number words (ek, do, teen ... sau, hazaar, lakh, crore; pipeline/spoken_numbers.py) count
                like digits in the sync, claim and copy checks; fact numbers are written as DIGITS in Hinglish copy
                (the voice speaks digits as Hindi numbers, captions show the digits)
  rate          WPS["hinglish"]: measured on the Microsoft Madhur voice (95 words in 49.1 s of voice, pauses included)
  LLM           the copy assistant's prompt asks for Latin-script Hinglish in this style; BANNED adds Hinglish
                clichés and superlatives to the English list (which still applies)."""
from __future__ import annotations

import re

from ..intelligence.claims import normalize_numbers as _en_normalize

ENGLISH, HINGLISH = "english", "hinglish"
LANGS = (ENGLISH, HINGLISH)

# Estimator speaking rate (words/s) for estimated_timing's per-token model (which adds punctuation pauses on top).
# English: local Kokoro am_michael +5% (anchors.WPS). Hinglish: fitted on a real Microsoft hi-IN-MadhurNeural render
# (95 words, 49.1 s of voice; 2.03 reproduces it, 2.0 keeps a small margin). Kokoro's Hindi voices are not yet measured
# on Hinglish (reading English, hm_omega ran ~2.5 words/s), so a Kokoro Hinglish film may come out a little shorter.
WPS = {ENGLISH: 2.33, HINGLISH: 2.0}

# English cue word (normalised) -> the Hinglish words that say the same thing. Only used for Hinglish narration.
CUE_ALIASES: dict[str, list[str]] = {
    "meet": ["Milo", "milo"], "this": ["Yeh", "yeh", "Ye"], "approves": ["approve", "approval"], "approve": ["approval"],
    "approval": ["approve"], "person": ["insaan", "koi"], "people": ["log", "insaan"], "humans": ["insaan", "log"],
    "decide": ["faisla", "decide"], "exact": ["sahi", "exact"], "anything": ["kuch"], "ships": ["ship", "publish"],
    "real": ["asli"], "all": ["sab", "Sab"], "before": ["pehle", "Pehle"], "watch": ["dekho", "dekh"],
    "pick": ["chuno", "Chuno"], "choose": ["chuno", "chunna", "chunne"], "promote": ["promote", "likho"], "who": ["kiske", "kaun"],
    "ideas": ["ideas", "idea"], "concepts": ["concept", "ideas"], "drafts": ["banata", "banaata"], "scenes": ["scene"],
    "checks": ["check"], "checked": ["check"], "voice": ["awaaz", "voice"], "audio": ["awaaz"], "renders": ["render"],
    "rendering": ["render"], "keys": ["key"], "again": ["phir", "dobara"], "still": ["phir", "bhi"], "next": ["agle", "agla"],
    "renews": ["renew", "renewal"], "renew": ["renewal"], "same": ["wahi", "same"], "bigger": ["bade", "bada", "Bade"],
    "room": ["jagah"], "grow": ["grow", "badho"], "free": ["free", "muft"], "instant": ["turant", "instant"],
    "instantly": ["turant"], "live": ["live"], "loading": ["load"], "waiting": ["intezaar"], "slow": ["slow", "dheere"],
    "searches": ["search", "dhoondhta", "dhoondhe"], "looks": ["dekhta", "dhoondhe"], "type": ["type", "likho"],
    "launch": ["launch"], "claim": ["claim", "lo"], "everything": ["sab", "Sab"], "nothing": ["kuch", "Kuch"],
    "money": ["paisa", "paise"], "guarantee": ["wapas"], "seven": ["saat", "7"], "six": ["chhe", "6"], "yearly": ["saal"],
    "year": ["saal"], "monthly": ["mahine"], "upgrade": ["upgrade"], "popular": ["popular"], "own": ["apne", "apna", "apni"],
    "itself": ["khud"], "film": ["film"], "software": ["software"], "stages": ["stage"], "completed": ["poora", "complete"],
    "frames": ["frame"], "word": ["shabd", "word"], "package": ["package"], "confirmed": ["confirm"], "separate": ["alag"],
    "posted": ["post"], "studio": ["studio"], "storyboard": ["storyboard"], "mac": ["Mac"], "sync": ["sync"],
    "verified": ["verify", "verified"], "layout": ["layout"], "captions": ["caption", "captions"],
    "subscription": ["subscription"], "proposes": ["propose", "sujhata"], "code": ["code"], "chain": ["chain"],
    "step": ["step"], "files": ["files", "file"], "hard": ["mushkil"], "way": ["tarika", "tarike"], "errors": ["error"],
    "weekend": ["weekend"], "visitors": ["visitor"], "left": ["chala", "gaya"], "extra": ["extra", "alag"],
    "increases": ["badh", "badhta", "badhti"], "price": ["price", "daam"], "everyone": ["sab"],
}

# Hinglish clichés, superlatives and pressure phrases (on top of the English BANNED list, which still applies:
# "best", "number one", "guaranteed", "100%", "unlimited"... are caught in Hinglish lines too)
BANNED = [
    "sabse best", "sabse accha", "sabse achha", "sabse sasta", "sabse saste", "sabse tez", "sabse fast", "number 1",
    "no. 1", "nambar one", "guarantee", "guaranteed", "pakka", "100 percent", "sau percent", "kabhi down nahi",
    "hamesha ke liye", "zindagi bhar", "lifetime", "jaldi karo", "jaldi kijiye", "offer khatam", "aaj hi khareedo",
    "jhakaas", "zabardast", "kamaal ka", "kamaal", "dhamakedaar", "bawaal", "mast", "ekdum mast", "mind-blowing",
    "mind blowing", "life badal", "zindagi badal", "game changer", "next level", "duniya ka", "bhaari discount",
    "free free", "bilkul free", "koi tension nahi", "tension free", "tension-free", "jadoo", "jaadu", "magic",
]

STYLE = (
    "LANGUAGE: Hinglish, written in Latin script (never Devanagari), the way Indian short-form creators write: Hindi "
    "grammar, everyday Hindi words, and English for product and tech nouns (product video, website, brief, storyboard, "
    "render, frame, preview, plan, price, domain). Short, punchy sentences; casual second person ('aap', imperatives "
    "like 'dekho', 'likho', 'chuno'). Avoid Urdu-heavy or textbook Hindi ('upyog', 'prastut', 'uplabdh'). Example "
    "lines: \"Brief do, aur video lo.\" \"Render se pehle har frame dekho.\" \"Na subscription, na API key.\" "
    "Numbers: write them as DIGITS exactly as given in ALLOWED NUMBERS (the voice says them in Hindi); never spell a "
    "number in Hindi words ('teen', 'paanch') unless it is an allowed number. Keep every CUE WORD as written (an "
    "English cue word stays English).")


def lang_of(brief: dict | None) -> str:
    """The brief's narration language; anything unknown is English."""
    v = str((brief or {}).get("language") or ENGLISH).lower()
    return v if v in LANGS else ENGLISH


def wps(lang: str | None) -> float:
    return WPS.get(lang or ENGLISH, WPS[ENGLISH])


def wps_of(sb: dict | None) -> float:
    """Speaking rate for a storyboard (its top-level `language`; English when absent)."""
    return wps((sb or {}).get("language"))


def aliases(lang: str | None) -> dict[str, list[str]]:
    return CUE_ALIASES if lang == HINGLISH else {}


def banned(lang: str | None) -> list[str]:
    return list(BANNED) if lang == HINGLISH else []


def normalize_numbers(text: str, lang: str | None = None) -> str:
    """Spelled numbers -> digits: English always (as before), Hindi number words too for Hinglish."""
    return _en_normalize(text, lang)


# ---- placeholder values -------------------------------------------------------------------------------------
_EN_NUM = re.compile(r"\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ](?:one|two|three|four|five|six|seven|"
                     r"eight|nine))?\b|\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                     r"fifteen|sixteen|seventeen|eighteen|nineteen)\b", re.I)


def localize_values(vals: dict, lang: str | None) -> dict:
    """Copy placeholder values for a language. English: unchanged. Hinglish:
      * `{role}_spoken` (a fact's value.spoken, e.g. "thirty-one") becomes digits ("31"): Hinglish copy writes fact
        numbers as digits and the voice reads them as Hindi numbers; "zero"/"one" stay words ("zero" before a currency word);
      * `{period_per}` = "per month" / "per year" (Hinglish ads say the period in English, and the claim checker
        reads it as the price's period)."""
    if lang != HINGLISH:
        return vals
    out = dict(vals)
    for k, v in vals.items():
        if k.endswith("_spoken") and isinstance(v, str):
            out[k] = _EN_NUM.sub(lambda m: _en_normalize(m.group(0).lower().replace(" ", "-")), v)
    if "period_word" in vals:
        out["period_per"] = "per month" if vals["period_word"] == "a month" else "per year"
    return out


def word_budget(words: tuple[int, int], lang: str | None) -> tuple[int, int]:
    """A template's narration word budget in a language. Budgets are really time budgets written in English words;
    a slower language gets proportionally fewer words (Hinglish at 2.0 vs 2.33 words/s: 14–32 -> 12–27)."""
    if not lang or lang == ENGLISH:
        return words
    r = wps(lang) / WPS[ENGLISH]
    lo = max(3, round(words[0] * r))
    return lo, max(lo, round(words[1] * r))
