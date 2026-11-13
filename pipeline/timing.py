"""Word-timing alignment and validation.

The provider's word boundaries are NOT the script: Edge TTS drops punctuation, can merge words
("Building a"), split tokens ("shrotihost" "." "in"), or spell numbers. We align boundaries back
onto the script tokens so captions show the exact script text, in spoken order, with real timings.
Tokens without a direct boundary are interpolated *inside* a measured span (never estimated from
sentence word counts) and flagged `interpolated`; too many interpolations is an error."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .errors import TimingError
from .tts import Boundary

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
        "seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + "hundred" + ("" if n % 100 == 0 else number_words(n % 100))
    if n < 1_000_000:
        return number_words(n // 1000) + "thousand" + ("" if n % 1000 == 0 else number_words(n % 1000))
    return str(n)


def norm(s: str) -> str:
    """Compare form: lowercase letters/digits only; apostrophes dropped (contractions: don't -> dont)."""
    s = unicodedata.normalize("NFKC", s).lower().replace("’", "'")
    return re.sub(r"[^a-z0-9]", "", s)


def forms(s: str) -> set[str]:
    n = norm(s)
    out = {n}
    digits = re.sub(r"[,_]", "", s)
    m = re.fullmatch(r"\D*?(\d{1,6})\D*", digits)
    if m:
        out.add(number_words(int(m.group(1))))
    return out


def tokenize(text: str) -> list[str]:
    """Script tokens = whitespace-separated, punctuation kept attached; em-dash joins are split so
    'month—with' becomes 'month—' + 'with' (Edge TTS speaks them as two words)."""
    text = re.sub(r"([—–])(?=\S)", r"\1 ", " ".join(text.split()))
    return [t for t in text.split(" ") if norm(t) or re.search(r"\d", t)]


@dataclass
class Word:
    text: str
    start: float
    end: float
    interpolated: bool = False

    def as_dict(self):
        d = {"text": self.text, "start": round(self.start, 3), "end": round(self.end, 3)}
        if self.interpolated:
            d["interpolated"] = True
        return d


def _eq(a: str, b: str) -> bool:
    return bool(forms(a) & forms(b))


def align(script: str, bounds: list[Boundary], duration: float, max_interp_frac: float = 0.2) -> list[Word]:
    return align_with_stats(script, bounds, duration, max_interp_frac)[0]


def align_with_stats(script: str, bounds: list[Boundary], duration: float,
                     max_interp_frac: float = 0.2) -> tuple[list[Word], dict]:
    """`align`, plus what it had to do: tokens with no boundary (`missing`), provider boundaries it
    skipped to resync (`skipped`: repeated/extra/reordered words), merges and splits."""
    toks = tokenize(script)
    if not toks:
        raise TimingError("script has no words")
    B = [b for b in bounds if norm(b.text)]
    if not B:
        raise TimingError("provider returned no word timestamps", transient=True)
    out: list[Word] = []
    missing = 0  # tokens with no provider boundary at all (subdividing a merged boundary doesn't count)
    skipped = merged = split = 0
    i = j = 0
    while i < len(toks) and j < len(B):
        if _eq(toks[i], B[j].text):
            out.append(Word(toks[i], B[j].start, B[j].end)); i += 1; j += 1; continue
        # provider split one script token into several boundaries ("shrotihost" "." "in", "forty" "nine" for 49)
        acc, hit, want = "", None, forms(toks[i])
        for k in range(j, min(j + 5, len(B))):
            acc += norm(B[k].text)
            if acc in want:
                hit = k; break
            if not any(f.startswith(acc) for f in want):
                break
        if hit is not None:
            out.append(Word(toks[i], B[j].start, B[hit].end)); i += 1; j = hit + 1; split += 1; continue
        # provider merged several script tokens into one boundary -> split its span by characters
        acc, hit, want = "", None, forms(B[j].text)
        for k in range(i, min(i + 5, len(toks))):
            acc += norm(toks[k])
            if acc in want:
                hit = k; break
            if not any(f.startswith(acc) for f in want):
                break
        if hit is not None:
            group = toks[i:hit + 1]
            total = sum(max(1, len(norm(t))) for t in group)
            t0, span = B[j].start, B[j].end - B[j].start
            for t in group:
                d = span * max(1, len(norm(t))) / total
                out.append(Word(t, t0, t0 + d, interpolated=len(group) > 1)); t0 += d
            i = hit + 1; j += 1; merged += 1; continue
        # resync: smallest skip on either side that re-establishes a match
        best = None
        for a in range(0, 4):
            for b in range(0, 4):
                if (a or b) and i + a < len(toks) and j + b < len(B) and _eq(toks[i + a], B[j + b].text):
                    if best is None or a + b < sum(best):
                        best = (a, b)
        if best is None:
            raise TimingError(f"cannot align script word {toks[i]!r} with provider word {B[j].text!r}",
                              detail=f"script context: {' '.join(toks[max(0, i - 3):i + 4])}")
        a, b = best
        lo = out[-1].end if out else 0.0
        hi = B[j + b].start
        missing += a
        skipped += b
        for k in range(a):  # unmatched script tokens: interpolate inside the measured gap
            s = lo + (hi - lo) * k / max(1, a)
            out.append(Word(toks[i + k], s, lo + (hi - lo) * (k + 1) / max(1, a), interpolated=True))
        i += a; j += b
    if i < len(toks):  # trailing tokens the provider never reported
        lo = out[-1].end if out else 0.0
        rest = toks[i:]
        missing += len(rest)
        hi = max(lo + 0.05 * len(rest), min(duration, lo + 0.4 * len(rest)))
        for k, t in enumerate(rest):
            out.append(Word(t, lo + (hi - lo) * k / len(rest), lo + (hi - lo) * (k + 1) / len(rest), True))
    skipped += len(B) - j  # provider words after the last script token (extra/repeated speech)
    if missing > max(1, max_interp_frac * len(out)):
        raise TimingError(f"{missing}/{len(out)} words had no provider timestamp (limit {max_interp_frac:.0%})")
    return out, {"tokens": len(toks), "boundaries": len(B), "missing": missing, "skipped": skipped,
                 "merged": merged, "split": split}


@dataclass
class TimingReport:
    ok: bool
    errors: list[str]
    warnings: list[str]
    fixed_overlaps: int
    interpolated: int

    def as_dict(self):
        return self.__dict__


def script_mismatches(script: str, words: list[Word], limit: int = 5) -> list[str]:
    """Missing, extra/repeated and reordered words: the caption words must be exactly the script
    tokens, in script order (text compared verbatim, punctuation included)."""
    want, got = tokenize(script), [w.text for w in words]
    if want == got:
        return []
    n, m = len(want), len(got)
    # LCS over the two token sequences -> the edits that turn the script into the words
    L = [[0] * (m + 1) for _ in range(n + 1)]
    for a in range(n - 1, -1, -1):
        for b in range(m - 1, -1, -1):
            L[a][b] = L[a + 1][b + 1] + 1 if want[a] == got[b] else max(L[a + 1][b], L[a][b + 1])
    a = b = 0
    missing, extra = [], []
    while a < n or b < m:
        if a < n and b < m and want[a] == got[b]:
            a += 1; b += 1
        elif b < m and (a == n or L[a][b + 1] >= L[a + 1][b]):
            extra.append((b, got[b])); b += 1
        else:
            missing.append((a, want[a])); a += 1
    out = []
    moved = {t for _, t in missing} & {t for _, t in extra}
    for k, t in missing:
        if t in moved:
            continue
        out.append(f"script word {k} {t!r} missing from timings")
    for k, t in extra:
        if t in moved:
            continue
        kind = "repeated" if t in want else "not in script"
        out.append(f"timing word {k} {t!r} {kind}")
    for t in sorted(moved):
        out.append(f"word {t!r} out of script order")
    return out[:limit] + ([f"... {len(out) - limit} more"] if len(out) > limit else [])


def validate_words(words: list[Word], duration: float, *, fix: bool = True, max_word_s: float = 3.0,
                   script: str | None = None, min_word_s: float = 0.02) -> TimingReport:
    errors, warnings, fixed = [], [], 0
    if not words:
        return TimingReport(False, ["no words"], [], 0, 0)
    if script is not None:
        errors += script_mismatches(script, words)
    for k, w in enumerate(words):
        if w.start < -1e-3 or w.end > duration + 0.05:
            errors.append(f"word {k} {w.text!r} [{w.start:.3f},{w.end:.3f}] outside audio 0..{duration:.3f}s")
        if w.end < w.start:
            errors.append(f"word {k} {w.text!r} ends before it starts")
        elif w.end - w.start > max_word_s:
            warnings.append(f"word {k} {w.text!r} lasts {w.end - w.start:.2f}s (>{max_word_s}s)")
        elif w.end - w.start < min_word_s:
            warnings.append(f"word {k} {w.text!r} lasts only {w.end - w.start:.3f}s")
        if k:
            p = words[k - 1]
            if w.start < p.start - 1e-3:
                errors.append(f"word {k} {w.text!r} starts before word {k - 1} (order broken)")
            elif w.start < p.end - 0.01:
                if fix:
                    p.end = w.start; fixed += 1
                else:
                    errors.append(f"words {k - 1}/{k} overlap by {p.end - w.start:.3f}s")
    interp = sum(w.interpolated for w in words)
    if interp:
        warnings.append(f"{interp} word(s) interpolated inside measured spans")
    return TimingReport(not errors, errors, warnings, fixed, interp)


def pause_cuts(words: list[Word], max_pause: float) -> list[tuple[float, float]]:
    """(cut_start, cut_len) for every gap between words longer than max_pause (keep 60% after the word)."""
    cuts = []
    for a, b in zip(words, words[1:]):
        gap = b.start - a.end
        if max_pause and gap > max_pause:
            cuts.append((a.end + max_pause * 0.6, gap - max_pause))
    return cuts


def shift_for_cuts(words: list[Word], cuts: list[tuple[float, float]]) -> None:
    for w in words:
        sh = sum(cl for cs, cl in cuts if cs < w.start)
        w.start -= sh
        w.end -= sh


def map_to_display(groups: list[tuple[list[str], int]], spoken: list[Word]) -> list[Word]:
    """Spoken-word timings -> display-token timings.

    `groups` is [(display_tokens, n_spoken_words)] in order (pronunciation.Prepared.groups): e.g.
    (["shrotihost.in."], 4) for "Shroti Host dot in.". A display token covers exactly the span of its
    spoken words. When several display tokens share spoken words (a multi-word dictionary entry), they
    map 1:1 if the counts match, otherwise the span is split by display length (flagged interpolated)."""
    if sum(n for _, n in groups) != len(spoken):
        raise TimingError(f"pronunciation map expects {sum(n for _, n in groups)} spoken words, "
                          f"timings have {len(spoken)}")
    out: list[Word] = []
    k = 0
    for disp, n in groups:
        part = spoken[k:k + n]
        k += n
        if not part:
            raise TimingError(f"display tokens {disp} have no spoken words")
        if len(disp) == n:
            out += [Word(d, w.start, w.end, w.interpolated) for d, w in zip(disp, part)]
        elif len(disp) == 1:
            out.append(Word(disp[0], part[0].start, part[-1].end, any(w.interpolated for w in part)))
        else:
            t0, span = part[0].start, part[-1].end - part[0].start
            total = sum(max(1, len(norm(d))) for d in disp)
            for d in disp:
                dur = span * max(1, len(norm(d))) / total
                out.append(Word(d, t0, t0 + dur, True)); t0 += dur
    return out
