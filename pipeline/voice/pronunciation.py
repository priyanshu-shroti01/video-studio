"""Display text -> spoken text, with a token map so timings can come back to the display text.

Captions show the script exactly ("shrotihost.in", "₹49", "NVMe"); the engine is given a spoken form
("Shro-tee Host dot in", "forty nine rupees", "N V M e"). `prepare()` returns both and the grouping
between them; `timing.map_to_display()` turns spoken-word timings into display-token timings.

Sources, highest priority first: per-project overrides (voice.pronunciation), the shared dictionary
(pronunciation.json), then rules (currency, units, percentages, numbers, domain names)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..paths import sha256_json
from ..timing import tokenize

DICT_PATH = Path(__file__).with_name("pronunciation.json")
_LEAD = re.compile(r"^[^\w₹$]+")
_TRAIL = re.compile(r"[^\w%]+$")
_SPOKEN_PUNCT = {"—": ",", "–": ",", "…": "...", ";": ",", ":": ","}
_KEEP_PUNCT = set(".,?!")

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def say_int(n: int) -> str:
    """Cardinal number in words, space separated (no hyphens: one engine word per spoken word)."""
    if n < 0:
        return "minus " + say_int(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + say_int(n % 100))
    for size, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= size:
            rest = n % size
            return say_int(n // size) + " " + name + ("" if rest == 0 else " " + say_int(rest))
    return str(n)


def say_number(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        whole, frac = s.split(".", 1)
        return say_int(int(whole or 0)) + " point " + " ".join(_ONES[int(d)] for d in frac)
    n = int(s)
    if 1900 <= n <= 2099 and len(s) == 4 and n % 100 and not 2000 <= n < 2010:  # years: "twenty twenty six"
        return say_int(n // 100) + " " + (say_int(n % 100) if n % 100 >= 10 else "oh " + say_int(n % 100))
    return say_int(n)


@dataclass
class Entry:
    display: str
    spoken: str
    case: bool = False

    @property
    def n(self) -> int:
        return len(self.display.split())

    def matches(self, core: str) -> bool:
        return core == self.display if self.case else core.lower() == self.display.lower()


@dataclass
class Dictionary:
    entries: list[Entry]
    units: dict[str, list[str]]
    currency: dict[str, list[str]]
    tlds: set[str]
    fingerprint: str = ""

    def lookup(self, core: str) -> str | None:
        for e in self.entries:
            if e.n == 1 and e.matches(core):
                return e.spoken
        return None


@lru_cache(maxsize=1)
def _base() -> dict:
    return json.loads(DICT_PATH.read_text())


def load(overrides: dict[str, str] | None = None) -> Dictionary:
    raw = _base()
    entries = [Entry(d, s, True) for d, s in (overrides or {}).items()]  # project overrides win, exact case first
    entries += [Entry(d, s, False) for d, s in (overrides or {}).items()]
    entries += [Entry(e["display"], e["spoken"], bool(e.get("case"))) for e in raw["entries"]]
    fp = sha256_json({"dict": raw, "overrides": overrides or {}})
    return Dictionary(entries, raw.get("units", {}), raw.get("currency", {}), set(raw.get("tlds", [])), fp)


@dataclass
class Prepared:
    display: str
    display_tokens: list[str]
    spoken_tokens: list[str]
    groups: list[tuple[list[str], int]] = field(default_factory=list)   # (display tokens, n spoken words)

    @property
    def spoken(self) -> str:
        return " ".join(self.spoken_tokens)

    @property
    def changed(self) -> bool:
        return self.spoken_tokens != self.display_tokens


def _split(tok: str) -> tuple[str, str, str]:
    lead = (_LEAD.match(tok) or [""])[0]
    rest = tok[len(lead):]
    trail = (_TRAIL.search(rest) or [""])[0] if rest else ""
    core = rest[: len(rest) - len(trail)] if trail else rest
    return lead, core, trail


def _plural(forms: list[str], amount: str) -> str:
    return forms[0] if amount.replace(",", "") in ("1", "1.0", "1.00") else forms[1]


def speak_core(core: str, d: Dictionary) -> list[str]:
    """Spoken words for one display token (without its surrounding punctuation)."""
    if not core:
        return []
    hit = d.lookup(core)
    if hit is not None:
        return hit.split()
    # suffixes like "/mo": "₹49/mo", "49/mo"
    m = re.fullmatch(r"(.+?)(/[A-Za-z]+)", core)
    if m and d.lookup(m.group(2)) is not None and re.search(r"\d", m.group(1)):
        return speak_core(m.group(1), d) + d.lookup(m.group(2)).split()
    for sym in sorted(d.currency, key=len, reverse=True):
        m = re.fullmatch(re.escape(sym) + r"\s?(\d[\d,]*(?:\.\d+)?)", core)
        if m:
            return say_number(m.group(1)).split() + [_plural(d.currency[sym], m.group(1))]
    m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)\s?([A-Za-z]{2})", core)
    if m and m.group(2).upper() in d.units:
        return say_number(m.group(1)).split() + [_plural(d.units[m.group(2).upper()], m.group(1))]
    m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)%", core)
    if m:
        return say_number(m.group(1)).split() + ["percent"]
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", core):
        return say_number(core).split()
    m = re.fullmatch(r"(?:https?://)?((?:[A-Za-z0-9-]+\.)+([A-Za-z]{2,10}))/?", core)
    if m and m.group(2).lower() in d.tlds:
        words: list[str] = []
        for k, label in enumerate(m.group(1).split(".")):
            if k:
                words.append("dot")
            if label.lower() == "www":
                words += ["W", "W", "W"]
            else:
                words += (d.lookup(label) or label).split()
        return words
    return [core]


def _spoken_trail(trail: str) -> str:
    out = ""
    for ch in trail:
        ch = _SPOKEN_PUNCT.get(ch, ch)
        if ch in _KEEP_PUNCT or ch == "...":
            out = ch if not out else out
    return out


def prepare(text: str, overrides: dict[str, str] | None = None, d: Dictionary | None = None) -> Prepared:
    d = d or load(overrides)
    toks = tokenize(text)
    p = Prepared(text, toks, [], [])
    multi = sorted((e for e in d.entries if e.n > 1), key=lambda e: -e.n)
    i = 0
    while i < len(toks):
        hit = None
        for e in multi:
            cand = toks[i:i + e.n]
            if len(cand) < e.n:
                continue
            parts = [_split(t) for t in cand]
            if any(tr for _, _, tr in parts[:-1]) or any(ld for ld, _, _ in parts[1:]):
                continue  # punctuation inside the phrase: not the same phrase
            if e.matches(" ".join(c for _, c, _ in parts)):
                hit = (cand, e.spoken.split(), parts[-1][2])
                break
        if hit is None:
            _, core, trail = _split(toks[i])
            words = speak_core(core, d)
            prev = _split(toks[i - 1])[1] if i else ""
            if core.upper() in d.units and d.lookup(core) is None and re.fullmatch(r"[\d.,]+", prev):
                words = [_plural(d.units[core.upper()], prev)]  # "1 GB" -> "one gigabyte"
            hit = ([toks[i]], words or [toks[i]], trail)
        cand, words, trail = hit
        words = list(words)
        words[-1] += _spoken_trail(trail)
        p.groups.append((cand, len(words)))
        p.spoken_tokens += words
        i += len(cand)
    if tokenize(p.spoken) != p.spoken_tokens:  # every spoken word must be one engine/caption token
        raise ValueError(f"pronunciation produced unsplittable spoken text: {p.spoken!r}")
    return p
