"""Numbers as they are SPOKEN in narration: digits, English number words and (for Hinglish) Hindi number words.

Hinglish narration (Latin script, brief `language: "hinglish"`) says numbers three ways: digits ("31 blocking
checks", which the Hindi voice reads as a Hindi number), English words ("thirty-one checks") and Hindi words in
their usual Latin spellings ("teen ideas", "paanch sau", "do hazaar"). The sync rules ("no number on screen before
it is spoken"), the claim checker (an invented "paanch minute" is a number claim) and the copy validator use these
helpers so a Hindi number word counts exactly like its digits.

Two Hindi number words are also everyday words: "do" (2, and the imperative "give/do": "Brief do, aur video lo")
and "saath" / "sath" (60, and "with": "awaaz ke saath"). They count as numbers only when a noun-like word follows
directly (no punctuation, not a particle such as "aur", "na", "hai") and, for saath, when it does not follow a
postposition ("ke/ki/ka saath"). Everything English is left exactly as before unless `lang` is "hinglish"."""
from __future__ import annotations

import re

HINGLISH = "hinglish"

# ---- Hindi cardinals (common Latin spellings; the first spelling is the canonical one) ------------------------
_HI = {
    0: "shunya", 1: "ek", 2: "do", 3: "teen", 4: "chaar char", 5: "paanch panch", 6: "chhe chhah chheh chah",
    7: "saat", 8: "aath", 9: "nau", 10: "das", 11: "gyarah gyaarah", 12: "barah baarah", 13: "terah", 14: "chaudah",
    15: "pandrah pandrah", 16: "solah", 17: "satrah satraah", 18: "atharah athaarah", 19: "unnees unnis", 20: "bees bis",
    21: "ikkees ikkis", 22: "baees bais baais", 23: "teis teyis", 24: "chaubees chaubis", 25: "pachchees pachees pachis",
    26: "chhabbees chhabbis", 27: "sattaees sattais", 28: "atthaees atthais", 29: "untees untis", 30: "tees tis",
    31: "iktees iktis ikattis ikatees", 32: "battees battis", 33: "taintees taintis tetees", 34: "chauntees chauntis",
    35: "paintees paintis", 36: "chhattees chhattis", 37: "saintees saintis", 38: "artees adtees adtis", 39: "untaalees untalis",
    40: "chaalees chalis", 41: "iktaalees iktalis", 42: "bayaalees bayalis byalis", 43: "taintaalees taintalis tentalis",
    44: "chavaalees chawalis chavalis", 45: "paintaalees paintalis", 46: "chhiyaalees chhiyalis", 47: "saintaalees saintalis",
    48: "artaalees adtalis artalis", 49: "unchaas unchas", 50: "pachaas pachas", 51: "ikyaavan ikyavan", 52: "baavan bavan",
    53: "tirpan trepan", 54: "chauvan chauwan", 55: "pachpan", 56: "chhappan", 57: "sattaavan sattavan", 58: "atthaavan atthavan",
    59: "unsath", 60: "saath sath", 61: "iksath", 62: "baasath basath", 63: "tirsath", 64: "chaunsath", 65: "painsath",
    66: "chhiyasath", 67: "sarsath", 68: "arsath adsath", 69: "unhattar", 70: "sattar", 71: "ikhattar", 72: "bahattar",
    73: "tihattar", 74: "chauhattar", 75: "pachhattar", 76: "chhihattar", 77: "satattar", 78: "athattar", 79: "unaasi unasi",
    80: "assi assee", 81: "ikyaasi ikyasi", 82: "bayaasi bayasi", 83: "tiraasi tirasi", 84: "chauraasi chaurasi",
    85: "pachaasi pachasi", 86: "chhiyaasi chhiyasi", 87: "sataasi satasi", 88: "athaasi athasi atthasi", 89: "navaasi navasi nawasi",
    90: "nabbe", 91: "ikyaanave ikyanve", 92: "baanave baanve", 93: "tiraanave tiranve", 94: "chauraanave chauranve",
    95: "pachaanave pachanve", 96: "chhiyaanave chhiyanve", 97: "sattaanave sattanve", 98: "atthaanave atthanve",
    99: "ninyaanave ninyanve ninanve",
}
HINDI_UNITS: dict[str, int] = {w: n for n, ws in _HI.items() for w in ws.split()}
HINDI_SCALES = {"sau": 100, "so": 100, "hazaar": 1000, "hazar": 1000, "hajaar": 1000, "hajar": 1000,
                "lakh": 100_000, "laakh": 100_000, "crore": 10_000_000, "karod": 10_000_000, "karor": 10_000_000}
HINDI_FRACTIONS = {"dedh": 1.5, "dhai": 2.5, "dhaai": 2.5}          # "dedh sau" = 150, "dhai hazaar" = 2500

_EN_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
            "seventeen eighteen nineteen").split()
_EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
EN_UNITS: dict[str, int] = {w: i for i, w in enumerate(_EN_ONES)} | {w: 10 * i for i, w in enumerate(_EN_TENS) if i >= 2}
EN_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "million": 1_000_000, "crore": 10_000_000}

# "do" / "saath" are numbers only before a noun-like word (see the module docstring)
AMBIGUOUS = {"do", "saath", "sath", "so"}
PARTICLES = {"aur", "ya", "na", "nahi", "nahin", "hai", "hain", "ho", "to", "toh", "bhi", "hi", "se", "ke", "ki", "ka", "ko",
             "mein", "me", "par", "pe", "jo", "jab", "kyunki", "lekin", "phir", "fir", "yeh", "ye", "woh", "wo", "aap", "aapka",
             "aapki", "aapke", "apna", "apni", "apne", "sab", "kuch", "abhi", "bas", "please", "karo", "karna", "dekho",
             # English words that follow the verb "do" ("Do it now", "do the math"), never a counted noun
             "it", "this", "that", "the", "a", "an", "you", "your", "not", "now", "more", "so", "what", "we", "they"}
_POSTPOSITIONS = {"ke", "ki", "ka", "unke", "iske", "uske", "mere", "tere", "aapke", "sab", "saath"}
_TOKEN = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*|\d[\d,]*(?:\.\d+)?")


def _low(w: str) -> str:
    return re.sub(r"[^a-z\-]", "", w.lower())


def _hi_value(word: str, prev: str | None, nxt: str | None, nxt_glued: bool) -> int | float | None:
    """Value of one Hindi number word in context, or None."""
    w = _low(word)
    if w not in HINDI_UNITS and w not in HINDI_SCALES and w not in HINDI_FRACTIONS:
        return None
    if w in AMBIGUOUS:
        n = _low(nxt or "")
        if not nxt_glued or not n or n in PARTICLES:
            return None
        if w in ("saath", "sath") and _low(prev or "") in _POSTPOSITIONS:
            return None
        if w == "so" and n not in HINDI_SCALES:          # "so" is "sau" only as a scale ("do so" is rare; keep it strict)
            return None
    return HINDI_UNITS.get(w, HINDI_SCALES.get(w, HINDI_FRACTIONS.get(w)))


def _en_value(word: str) -> int | None:
    w = _low(word)
    if w in EN_UNITS or w in EN_SCALES:
        return EN_UNITS.get(w, EN_SCALES.get(w))
    parts = w.split("-")                                  # "thirty-one", "forty-nine"
    if len(parts) == 2 and parts[0] in EN_UNITS and parts[1] in EN_UNITS and EN_UNITS[parts[0]] >= 20 and EN_UNITS[parts[1]] < 10:
        return EN_UNITS[parts[0]] + EN_UNITS[parts[1]]
    return None


def _combine(vals: list[tuple[str, float]]) -> float:
    """[(kind, value)] of one spoken number -> its value. kind: "u" unit, "s" scale, "f" fraction, "d" digits."""
    total, cur = 0.0, 0.0
    for kind, v in vals:
        if kind == "s":
            if v >= 1000:
                total += (cur or 1) * v
                cur = 0.0
            else:
                cur = (cur or 1) * v
        else:
            cur += v
    return total + cur


def spoken_numbers(tokens: list[str], lang: str | None = None) -> list[tuple[int, float]]:
    """(index of the first token, value) for every number spoken in a token list (script tokens or caption words).

    Digits always count; single English number words always count (as before: "six" ~ "6"); runs of number words
    ("five hundred", "paanch sau", "do hazaar paanch sau") and every Hindi number word count only for Hinglish."""
    hi = (lang or "").lower() == HINGLISH
    out: list[tuple[int, float]] = []
    i, n = 0, len(tokens)
    while i < n:
        run: list[tuple[str, float]] = []
        j = i
        while j < n:
            tok = tokens[j]
            core = tok.strip(".,!?;:\"'()“”‘’—–…")
            glued = not re.search(r"[.,!?;:—–…]$", tok)            # nothing between this word and the next
            prev = tokens[j - 1] if j > 0 else None
            nxt = tokens[j + 1] if j + 1 < n else None
            if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", core):
                v, kind = float(core.replace(",", "")), "d"
            elif (ev := _en_value(core)) is not None and (hi or not run):
                v, kind = float(ev), "s" if _low(core) in EN_SCALES else "u"
            elif hi and (hv := _hi_value(core, prev, nxt, glued)) is not None:
                w = _low(core)
                v, kind = float(hv), "s" if w in HINDI_SCALES else "f" if w in HINDI_FRACTIONS else "u"
            else:
                break
            if run and kind in ("u", "d", "f") and run[-1][0] in ("u", "d", "f"):
                break                                             # "ek do teen": three numbers, not one
            if not run and kind == "s" and not hi and v != 100:
                break
            run.append((kind, v))
            j += 1
            if not hi or not glued:
                break                                             # English: one word per number (unchanged); punctuation ends a run
        if run:
            out.append((i, _combine(run)))
            i = j
        else:
            i += 1
    return out


def spoken_index(tokens: list[str], value: float, lang: str | None = None) -> int | None:
    """Index of the first token where `value` is spoken, or None."""
    for i, v in spoken_numbers(tokens, lang):
        if abs(v - float(value)) < 1e-9:
            return i
    return None


def normalize_hindi(text: str) -> str:
    """Hindi number words (and runs of number words) -> digits, for the claim checker and the copy validator
    ("teen ideas" -> "3 ideas", "paanch sau" -> "500"). A lone "ek" / "shunya" stays a word, as "one" does in English
    ("ek Mac" is not a count). English number words are left to the English normaliser."""
    toks = list(_TOKEN.finditer(text))
    words = [m.group(0) for m in toks]
    # glue: whether only spaces separate a word from the next one
    glued = [not re.search(r"[^\s]", text[toks[k].end():toks[k + 1].start()]) if k + 1 < len(toks) else False
             for k in range(len(toks))]
    out, last, k = [], 0, 0
    while k < len(toks):
        run, j = [], k
        while j < len(toks):
            w = _low(words[j])
            nxt = words[j + 1] if j + 1 < len(toks) else None
            hv = _hi_value(words[j], words[j - 1] if j else None, nxt, glued[j])
            if hv is None or w in EN_UNITS or w in EN_SCALES:
                break
            kind = "s" if w in HINDI_SCALES else "f" if w in HINDI_FRACTIONS else "u"
            if run and kind != "s" and run[-1][0] != "s":
                break
            if not run and kind == "s":
                break                                             # a bare "sau"/"lakh" is a word, not a count
            run.append((kind, float(hv)))
            j += 1
            if not glued[j - 1]:
                break
        if run and len(run) == 1 and run[0][1] < 2:
            run = []                                              # "ek", "shunya" alone stay words (like English "one")
            j = k + 1
        if run:
            v = _combine(run)
            out.append(text[last:toks[k].start()])
            out.append(str(int(v)) if float(v).is_integer() else str(v))
            last = toks[j - 1].end()
            k = j
        else:
            k += 1
    out.append(text[last:])
    return "".join(out)
