"""Hinglish narration: Latin-script display words -> Devanagari spoken words.

Captions show what Indian short-form creators write ("Aaj dekhte hain ki product video kaise banta hai").
Kokoro's Hindi voices only sound right when espeak's Hindi phonemizer reads Devanagari, so with
`voice.lang: "hinglish"` every display word gets a Devanagari spoken form ("आज देखते हैं की प्रोडक्ट वीडियो कैसे
बनता है") and the spoken-word timings map back onto the Latin display words (pronunciation.Prepared.groups).

Sources, highest priority first (`speak()`):
  1. per-project / brand overrides (voice.pronunciation): a Devanagari value is used as is, a Latin value is read
     as an English respelling;
  2. the word list hinglish.json: common Hindi words in their usual Latin spellings, and English words Hinglish
     scripts use, written the way Indians say them;
  3. the shared dictionary (pronunciation.json, English respellings -> Devanagari) and number rules: amounts are
     spoken as Hindi numbers ("₹49" -> "उनचास रुपये", "₹0" -> "ज़ीरो रुपये", "4.5" -> "चार पॉइंट पाँच");
  4. a guess for everything else: words that look like romanised Hindi go through Latin -> Devanagari spelling
     rules; the rest is treated as English: espeak's own English pronunciation (IPA) is rewritten in Devanagari
     with Indian-English conventions (t/d -> ट/ड, "o" in "shop" -> ॉ, rhotic r kept).

English loanwords are written in Devanagari rather than left in Latin script: mixed scripts make espeak switch
to its English voice mid-sentence (with "(en)"/"(hi)" markers) and produce British/American phonemes the Hindi
voices were not trained on, while Devanagari gives retroflex, Indian-English phonemes."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

LEX_PATH = Path(__file__).with_name("hinglish.json")
LANG = "hinglish"
PHONEMIZER_LANG = "hi"
DEVA = "ऀ-ॣ०-ॿ"           # Devanagari letters, signs and digits (the dandas are punctuation)
_DEVA_RE = re.compile(f"[{DEVA}]")
_HALANT, _ANUSVARA, _CHANDRABINDU = "्", "ं", "ँ"

SOURCES = {
    "override": "project/brand override",
    "hindi": "Hinglish word list",
    "english": "English word list",
    "dictionary": "shared dictionary",
    "number": "number rule (Hindi numbers)",
    "letters": "spelled as letters",
    "domain": "domain rule",
    "devanagari": "already Devanagari",
    "hindi-rules": "guess: Hindi spelling rules",
    "english-rules": "guess: English pronunciation",
}


def is_hinglish(lang: str | None) -> bool:
    return (lang or "").lower() == LANG


def has_devanagari(s: str) -> bool:
    return bool(_DEVA_RE.search(s))


@lru_cache(maxsize=1)
def lexicon() -> dict:
    return json.loads(LEX_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------- numbers
def say_int(n: int) -> list[str]:
    """Hindi cardinal in Indian grouping (हज़ार, लाख, करोड़); 0 is "ज़ीरो" (what people say; "शून्य" is formal)."""
    L = lexicon()
    nums, sc = L["numbers"], L["scale"]
    if n < 0:
        return [sc["minus"], *say_int(-n)]
    if n < 100:
        return [nums[n]]
    if n == 100:
        return [sc["hundred"]]                            # "सौ रुपये", not "एक सौ रुपये"
    out: list[str] = []
    for size, name in ((10**7, "crore"), (10**5, "lakh"), (1000, "thousand")):
        if n >= size:
            q, n = divmod(n, size)
            out += [*say_int(q), sc[name]]
    if n >= 100:
        q, n = divmod(n, 100)
        out += [nums[q], sc["hundred"]]
    if n:
        out.append(nums[n])
    return out


def say_number(s: str) -> list[str]:
    s = s.replace(",", "")
    if "." in s:
        whole, frac = s.split(".", 1)
        return [*say_int(int(whole or 0)), lexicon()["scale"]["point"], *(lexicon()["numbers"][int(d)] for d in frac)]
    return say_int(int(s))


def _amount_plural(forms: list[str], amount: str) -> str:
    return forms[0] if amount.replace(",", "") in ("1", "1.0", "1.00") else forms[1]


# --------------------------------------------------------------------------------------------- English -> Devanagari
_IPA_V = ["aɪ", "aʊ", "eɪ", "oʊ", "əʊ", "ɔɪ", "ɪə", "eə", "ʊə", "iː", "uː", "ɑː", "ɔː", "ɜː",
          "i", "ɪ", "e", "ɛ", "æ", "a", "ɑ", "ɒ", "ɔ", "o", "ʊ", "u", "ʌ", "ə", "ɐ", "ᵻ", "ɚ", "ɝ", "ɜ", "ɨ"]
_IPA_C = {"tʃ": "च", "ʧ": "च", "dʒ": "ज", "ʤ": "ज", "p": "प", "b": "ब", "t": "ट", "d": "ड", "k": "क", "ɡ": "ग", "g": "ग",
          "f": "फ़", "v": "व", "w": "व", "θ": "थ", "ð": "द", "s": "स", "z": "ज़", "ʃ": "श", "ʒ": "ज़", "h": "ह", "m": "म",
          "n": "न", "ŋ": "ङ", "l": "ल", "ɹ": "र", "r": "र", "j": "य", "ɾ": "ट", "ʔ": "ट", "x": "ख़", "ç": "ह"}
# vowel -> (independent letter, matra); schwa-like vowels are the consonant's inherent vowel (matra "")
_V = {"i": ("ई", "ी"), "iː": ("ई", "ी"), "ɪ": ("इ", "ि"), "ᵻ": ("इ", "ि"), "ɨ": ("इ", "ि"),
      "e": ("ए", "े"), "ɛ": ("ए", "े"), "eɪ": ("ए", "े"), "æ": ("ऐ", "ै"), "a": ("ऐ", "ै"),
      "ɑ": ("आ", "ा"), "ɑː": ("आ", "ा"), "ɒ": ("ऑ", "ॉ"), "ɔ": ("ऑ", "ॉ"), "ɔː": ("ऑ", "ॉ"),
      "o": ("ओ", "ो"), "oʊ": ("ओ", "ो"), "əʊ": ("ओ", "ो"), "ʊ": ("उ", "ु"), "u": ("ऊ", "ू"), "uː": ("ऊ", "ू"),
      "ʌ": ("अ", ""), "ə": ("अ", ""), "ɐ": ("अ", ""), "aɪ": ("आइ", "ाइ"), "aʊ": ("आउ", "ाउ"), "ɔɪ": ("ऑय", "ॉय"),
      "ɪə": ("इअ", "िअ"), "eə": ("एअ", "ेअ"), "ʊə": ("उअ", "ुअ")}
_RHOTIC = {"ɚ": "ə", "ɝ": "ə", "ɜː": "ə", "ɜ": "ə"}       # r-coloured vowel -> vowel + र
_FRONT = {"i", "iː", "ɪ", "ᵻ", "ɨ", "eɪ"}
_OPEN_NEXT = {"ə", "ʌ", "ɐ", "ɑ", "ɑː", "a", "æ"}


def _parse_ipa(ipa: str) -> list[tuple[str, str]]:
    """IPA word -> [("V"|"C", phoneme)]; stress, length on consonants and syllabic marks dropped."""
    s = re.sub("[ˈˌ̩͡.]", "", ipa)
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(s):
        for ph in _IPA_V:
            if s.startswith(ph, i):
                out.append(("V", ph)); i += len(ph); break
        else:
            two = s[i:i + 2]
            if two in _IPA_C:
                out.append(("C", two)); i += 2
            elif s[i] in _IPA_C:
                out.append(("C", s[i])); i += 1
            else:
                i += 1                                  # ː after a consonant, unknown symbols
    return out


def _render(segs: list[tuple[str, str, str]]) -> str:
    """[("C", letter, "") | ("V", independent, matra) | ("N", sign, "")] -> Devanagari string."""
    out, prev = "", None
    for kind, a, b in segs:
        if kind == "C":
            if prev == "C":
                out += _HALANT
            out += a
        elif kind == "V":
            out += b if prev == "C" else a
        else:                                           # nasal sign on the preceding vowel
            out += a
            kind = "V"
        prev = kind
    return out


def ipa_to_devanagari(us: str, gb: str | None = None) -> str:
    """espeak en-us IPA (optionally with the en-gb IPA of the same word) -> Indian-English Devanagari."""
    ph = _parse_ipa(us)
    if gb:                                              # "shop", "product", "launch": American ɑ -> British ɒ/ɔ
        g = _parse_ipa(gb)
        uv = [k for k, (t, _) in enumerate(ph) if t == "V"]
        gv = [p for t, p in g if t == "V"]
        if len(uv) == len(gv):
            for k, gp in zip(uv, gv):
                if ph[k][1] in ("ɑː", "ɑ") and gp in ("ɒ", "ɔː", "ɔ"):
                    ph[k] = ("V", "ɒ")
    # r-coloured vowels -> vowel + ɹ; collapse doubled consonants
    seq: list[tuple[str, str]] = []
    for t, p in ph:
        items = [("V", _RHOTIC[p]), ("C", "ɹ")] if t == "V" and p in _RHOTIC else [(t, p)]
        for it in items:
            if it[0] == "C" and seq and seq[-1] == it:
                continue
            seq.append(it)
    # syllabic n/l/m after a stop ("button" bʌʔn, "rhythm") get their schwa back
    if len(seq) >= 2 and seq[-1][0] == "C" and seq[-1][1] in "nlm" and seq[-2][0] == "C" \
            and seq[-2][1] not in ("n", "m", "ŋ", "l", "ɹ", "r", "s"):
        seq.insert(len(seq) - 1, ("V", "ə"))
    # vowel meeting vowel: glides ("premium" -> प्रीमियम, "science" -> सायन्स, "power" -> पावर)
    glided: list[tuple[str, str]] = []
    for t, p in seq:
        if t == "V" and glided and glided[-1][0] == "V":
            q = glided[-1][1]
            if q in _FRONT and p in _OPEN_NEXT:
                glided.append(("C", "j"))
            elif q in ("aɪ", "aʊ"):
                glided[-1] = ("V", "ɑ")
                glided.append(("C", "j" if q == "aɪ" else "w"))
        glided.append((t, p))
    seq = glided
    n_vowels = sum(t == "V" for t, _ in seq)
    segs: list[tuple[str, str, str]] = []
    for k, (t, p) in enumerate(seq):
        nxt = seq[k + 1] if k + 1 < len(seq) else None
        prev = seq[k - 1] if k else None
        if t == "V":
            ind, mat = _V.get(p, ("अ", ""))
            if p == "i" and nxt and nxt[1] == "j":
                ind, mat = "इ", "ि"                       # "premium" -> प्रीमियम, "India" -> इंडिया
            if p == "ɔː" and nxt == ("C", "ɹ") and k + 2 == len(seq):
                ind, mat = "ओ", "ो"                       # "store" -> स्टोर, "more" -> मोर
            if p == "ə" and nxt is None and n_vowels > 1 and prev and prev[0] == "C":
                ind, mat = "आ", "ा"                       # "data" -> डेटा, "India" -> इंडिया
            segs.append(("V", ind, mat))
        elif p == "ŋ" and prev and prev[0] == "V":
            segs.append(("N", _ANUSVARA, ""))
            if nxt is None:
                segs.append(("C", "ग", ""))              # "-ing" is said with its g: होस्टिंग
        elif p == "z" and nxt is None and prev and prev[0] == "C":
            segs.append(("C", "स", ""))                  # plural after a consonant: "options" -> ऑप्शंस
        elif p in ("n", "m") and prev and prev[0] == "V" and nxt and nxt[0] == "C" \
                and nxt[1] not in ("j", "w", "ɹ", "l", "h") and (p == "n" or nxt[1] in ("p", "b")) \
                and prev[1] not in ("ɒ", "ɔ", "ɔː", "o", "oʊ", "əʊ"):
            segs.append(("N", _ANUSVARA, ""))           # "content" -> कंटेंट, "simple" -> सिंपल
        else:
            segs.append(("C", _IPA_C[p], ""))
    return _render(segs)


@lru_cache(maxsize=1)
def _espeak():
    """Two cached espeak backends (en-us, en-gb). The library path is set the same way Kokoro sets it."""
    from kokoro_onnx.tokenizer import Tokenizer, _espeak_lock
    from phonemizer.backend import EspeakBackend
    Tokenizer()
    with _espeak_lock:
        return (_espeak_lock, EspeakBackend("en-us", preserve_punctuation=False, with_stress=True),
                EspeakBackend("en-gb", preserve_punctuation=False, with_stress=True))


def english_ipa(word: str) -> tuple[str, str]:
    lock, us, gb = _espeak()
    with lock:
        return us.phonemize([word], strip=True)[0], gb.phonemize([word], strip=True)[0]


@lru_cache(maxsize=8192)
def english_word(word: str) -> str:
    """One English word (or respelling such as "Shro-tee") -> Devanagari, the way it is said in India."""
    L = lexicon()
    w = word.strip("'’").lower()
    if w in L["english"]:
        return L["english"][w]
    if "-" in w:
        return "".join(english_word(p) for p in w.split("-") if p)
    if len(w) == 1 and w in L["letters"]:
        return L["letters"][w]
    if not re.fullmatch(r"[a-z'’]+", w):
        return w
    try:
        us, gb = english_ipa(w)
    except Exception:  # noqa: BLE001 - no espeak available: the Hindi spelling rules are the best we have
        return hindi_word(w)
    return ipa_to_devanagari(us, gb) or hindi_word(w)


def letters(word: str) -> list[str]:
    L = lexicon()["letters"]
    return [L[c] for c in word.lower() if c in L]


# --------------------------------------------------------------------------------------------- romanised Hindi
_H_CONS = [("chh", "छ"), ("cch", "च्छ"), ("ksh", "क्ष"), ("kh", "ख"), ("gh", "घ"), ("ch", "च"), ("jh", "झ"), ("th", "थ"),
           ("dh", "ध"), ("ph", "फ"), ("bh", "भ"), ("sh", "श"), ("k", "क"), ("g", "ग"), ("j", "ज"), ("t", "त"),
           ("d", "द"), ("n", "न"), ("p", "प"), ("b", "ब"), ("m", "म"), ("y", "य"), ("r", "र"), ("l", "ल"), ("v", "व"),
           ("w", "व"), ("s", "स"), ("h", "ह"), ("f", "फ़"), ("z", "ज़"), ("q", "क़"), ("x", "क्स"), ("c", "क")]
_H_VOW = [("aa", "आ", "ा"), ("ai", "ऐ", "ै"), ("au", "औ", "ौ"), ("ee", "ई", "ी"), ("ii", "ई", "ी"), ("oo", "ऊ", "ू"),
          ("uu", "ऊ", "ू"), ("ei", "ए", "े"), ("a", "अ", ""), ("i", "इ", "ि"), ("u", "उ", "ु"), ("e", "ए", "े"),
          ("o", "ओ", "ो")]
_NASAL_END = re.compile(r"(ai|ei|e|o|oo|ao|uo)n$")


def hindi_word(word: str) -> str:
    """Romanised Hindi ("dekhte", "kamaai") -> Devanagari by spelling rules (a best effort; the word list wins)."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return word
    nasal = False
    if _NASAL_END.search(w) and len(w) > 2:
        w, nasal = w[:-1], True                         # "hain" -> हैं, "karen" -> करें, "logon" -> लोगों
    elif re.search(r"iyan$", w):
        w, nasal = w[:-1] + "a", True                   # "khushiyan" -> ख़ुशियाँ
    w = re.sub(r"aiye", "aaiye", w)
    w = re.sub(r"(?<=[aeiou])ye(?=$|ga$|gi$)", "e", w)  # "liye" -> लिए, "bataiye" -> बताइए, "naye" -> नए
    segs: list[tuple[str, str, str]] = []
    i = 0
    while i < len(w):
        for lat, ind, mat in _H_VOW:
            if w.startswith(lat, i):
                last = i + len(lat) == len(w)
                if last and segs and segs[-1][0] == "C":
                    if lat == "a":
                        ind, mat = "आ", "ा"           # final -a is long: "sasta" -> सस्ता
                    elif lat == "i":
                        ind, mat = "ई", "ी"
                    elif lat == "u":
                        ind, mat = "ऊ", "ू"
                segs.append(("V", ind, mat)); i += len(lat); break
        else:
            for lat, dev in _H_CONS:
                if w.startswith(lat, i):
                    segs.append(("C", dev, "")); i += len(lat); break
            else:
                i += 1
    if nasal:
        segs.append(("N", _CHANDRABINDU if segs and segs[-1][2] in ("", "ा", "ू", "ु") else _ANUSVARA, ""))
    return _render(segs)


_HINDI_HINTS = [(re.compile(p), s) for p, s in (
    (r"aa|ii|uu", 2), (r"(?:^|[^sct])h?(kh|bh|dh|jh)", 2), (r"chh", 2), (r"^gh|[aeiou]gh[aeiou]", 1),
    (r"(ega|egi|enge|oge|iye|iyega|aiye|wala|wali|wale|aao|ayein|aayi|aaye)$", 2),
    (r"(na|ne|ta|te|ti|tha|thi|ya|yi|ye|kar|ao|on|ein|ain)$", 1), (r"^(kya|kyu|kai|kah|jah|wah|yah)", 1),
    (r"[^aeiou]i$", 1), (r"[^aeiou]o$", 1), (r"ksh|kk|cch|yy|jj", 2), (r"aha|ahi|aho", 1))]
_ENGLISH_HINTS = [(re.compile(p), s) for p, s in (
    (r"(tion|sion|ment|ness|ship|ing|ings|ed|ers?|est|ly|able|ible|ful|less|ous|ive|ize|ise|ware|ity|ics|logy|ure)$", 2),
    (r"c(?!h)|q|x|ck|wh|wr|tch|dge|ght", 2), (r"[aeiou][^aeiouy]e$", 1), (r"[^aeiou]y$", 1), (r"(aw|ew|ow)$|w[^aeiouh]", 2),
    (r"(ll|ss|ff|pp|zz)", 1), (r"^(un|re|pre|over|out)[a-z]{3,}", 1))]


def looks_hindi(word: str) -> bool:
    """Heuristic for a word that is in neither word list: romanised-Hindi spelling patterns against English ones.
    Ties go to English (content words outside the Hindi word list are mostly English in Hinglish scripts)."""
    w = word.lower()
    h = sum(s for r, s in _HINDI_HINTS if r.search(w))
    e = sum(s for r, s in _ENGLISH_HINTS if r.search(w))
    return h > e


# --------------------------------------------------------------------------------------------- one display token
def to_devanagari_words(spoken: str) -> list[str]:
    """An override or dictionary value -> Devanagari words (Devanagari kept; Latin read as English respelling)."""
    out: list[str] = []
    for w in spoken.split():
        if has_devanagari(w):
            out.append(w)
        elif re.fullmatch(r"\d[\d,]*(?:\.\d+)?", w):
            out += say_number(w)
        elif len(w) == 1 and w.isalpha():
            out += letters(w)
        else:
            core = re.sub(r"[^\w'’-]", "", w)
            if core:
                out.append(english_word(core))
    return out


# "ki" is की ("aapki website ki speed") except after a verb, where it is the conjunction कि ("dekhte hain ki ...")
_KI_THAT = {"hai", "hain", "tha", "thi", "hoga", "hogi", "lagta", "lagti", "lagega", "pata", "socho", "sochiye", "dekho",
            "dekhiye", "chahte", "chahta", "chahti", "kaha", "bataya", "batao", "samjho", "yaad", "maloom", "ummeed"}


def speak(core: str, d, prev: str = "") -> tuple[list[str], str]:
    """Spoken Devanagari words for one display token (punctuation already split off) and where they came from
    (a key of SOURCES). `d` is the pronunciation.Dictionary (overrides + shared entries); `prev` is the previous
    display token (context for "ki")."""
    from . import pronunciation as P
    if not core:
        return [], ""
    if has_devanagari(core):
        return [core], "devanagari"
    L = lexicon()
    e = d.lookup_entry(core)
    if e is not None and e.src == "override":
        return to_devanagari_words(e.spoken), "override"
    key = core.lower().replace("’", "'")
    if key == "ki" and re.sub(r"[^a-z]", "", prev.lower()) in _KI_THAT and not re.search(r"[.,!?;:]$", prev):
        return ["कि"], "hindi"
    if key in L["hindi"]:
        return L["hindi"][key].split(), "hindi"
    if key in L["english"]:
        return L["english"][key].split(), "english"
    if e is not None:
        return to_devanagari_words(e.spoken), "dictionary"
    m = re.fullmatch(r"(.+?)(/[A-Za-z]+)", core)
    if m and m.group(2).lower() in L["suffixes"] and re.search(r"\d", m.group(1)):
        head, _ = speak(m.group(1), d)
        return [*head, *L["suffixes"][m.group(2).lower()].split()], "number"
    for sym in sorted(L["currency"], key=len, reverse=True):
        m = re.fullmatch(re.escape(sym) + r"\s?(\d[\d,]*(?:\.\d+)?)", core)
        if m:
            return [*say_number(m.group(1)), _amount_plural(L["currency"][sym], m.group(1))], "number"
    m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)\s?([A-Za-z]{2})", core)
    if m and m.group(2).upper() in L["units"]:
        return [*say_number(m.group(1)), L["units"][m.group(2).upper()]], "number"
    if core.upper() in L["units"] and core.isupper():
        return [L["units"][core.upper()]], "letters"
    m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)%", core)
    if m:
        return [*say_number(m.group(1)), L["percent"]], "number"
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", core):
        return say_number(core), "number"
    m = re.fullmatch(r"(?:https?://)?((?:[A-Za-z0-9-]+\.)+([A-Za-z]{2,10}))/?", core)
    if m and m.group(2).lower() in d.tlds:
        return to_devanagari_words(" ".join(P.speak_core(core, d))), "domain"
    if re.search(r"\d", core) and re.search(r"[A-Za-z]", core):        # "5G", "4K", "24x7"
        out: list[str] = []
        for part in re.findall(r"\d[\d,]*(?:\.\d+)?|[A-Za-z]+", core):
            out += say_number(part) if part[0].isdigit() else (letters(part) if len(part) <= 3 else [english_word(part)])
        return out, "number"
    if "-" in core.strip("-"):
        out, srcs = [], set()
        for part in (p for p in core.split("-") if p):
            w, s = speak(part, d)
            out += w; srcs.add(s)
        return out, (srcs.pop() if len(srcs) == 1 else "english-rules")
    word = re.sub(r"[^A-Za-z'’]", "", core)
    if not word:
        return [core], "devanagari"
    if word.isupper() and len(word) > 1 and (len(word) <= 3 or not re.search(r"[AEIOU]", word)):
        return letters(word), "letters"
    if looks_hindi(word):
        return [hindi_word(word)], "hindi-rules"
    return [english_word(word)], "english-rules"


def fingerprint_data() -> dict:
    return {"hinglish": lexicon(), "rules": 1}
