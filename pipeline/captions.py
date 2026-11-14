"""Caption pages (shared by the burned-in Remotion captions, SRT and ASS) + validation."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .timing import Word

SENTENCE_END = re.compile(r"[.!?…]$")
CLAUSE_END = re.compile(r"[,;:—–]$")

# Caption looks drawn by the engine (src/engine/captions.ts). "word" / "phrase" are the original values and render the
# classic look (boxed page, karaoke colour on the current word / no highlight), so every existing project is unchanged.
CLASSIC_STYLES = ("word", "phrase", "classic")
KINETIC_STYLES = ("pop", "highlight", "karaoke")         # short word-synced pages (1–3 / up to 4 words)
STYLES = (*CLASSIC_STYLES, *KINETIC_STYLES, "minimal")
# NEW productions only (pipeline.intelligence.api / pipeline.api.default_project): brief -> brand -> this
FORMAT_DEFAULT_STYLE = {"short": "pop", "landscape": "minimal"}
# reading speed for word-synced pages is measured over a window of consecutive pages at least this long: a 1–3
# word page shows exactly the words being spoken, so its own chars/s is the local speech rate of a fraction of a
# second (noisy), while a ~1.5 s window is what the eye actually reads.
KINETIC_READING_WINDOW = 1.5
_FUNCTION_WORDS = {"a", "an", "the", "of", "to", "in", "on", "at", "for", "with", "and", "or", "but", "by", "from",
                   "its", "your", "our", "my", "their", "is", "are", "as", "into", "than"}
_JOINERS = {"of", "to", "in", "on", "at", "for", "with", "by", "from", "into", "than", "and", "or", "but", "that",
            "which", "before", "after", "so", "because"}


@dataclass
class Page:
    start: float
    end: float
    word_idx: list[int]

    def text(self, words: list[Word]) -> str:
        return " ".join(words[i].text for i in self.word_idx)


def build_pages(words: list[Word], *, max_words: int = 4, max_chars: int = 28, min_dur: float = 0.5,
                hold: float = 0.6, audio_end: float | None = None) -> list[Page]:
    """Group words into on-screen pages: break on sentence ends, clauses, max words / chars.
    A page shows from its first word until the next page starts (bounded by `hold` after its last word),
    and never past the end of the voiceover."""
    pages, cur = [], []
    for i, w in enumerate(words):
        chars = sum(len(words[k].text) + 1 for k in cur) + len(w.text)
        if cur and (len(cur) >= max_words or chars > max_chars):
            pages.append(cur); cur = []
        cur.append(i)
        if SENTENCE_END.search(w.text) or (CLAUSE_END.search(w.text) and len(cur) >= 2):
            pages.append(cur); cur = []
    if cur:
        pages.append(cur)
    out = []
    end_limit = audio_end if audio_end is not None else words[-1].end + hold
    for k, idx in enumerate(pages):
        start = words[idx[0]].start
        natural = words[idx[-1]].end + hold
        nxt = words[pages[k + 1][0]].start if k + 1 < len(pages) else end_limit
        end = min(max(natural, start + min_dur), nxt, end_limit)
        out.append(Page(round(start, 3), round(max(end, start + 0.05), 3), idx))
    return out


def is_kinetic(style: str | None) -> bool:
    return style in KINETIC_STYLES


def reading_window(style: str | None) -> float:
    """Window (s) the reading-speed check uses for this caption style (0 = per page, the classic check)."""
    return KINETIC_READING_WINDOW if is_kinetic(style) else 0.0


def _bare(s: str) -> str:
    return re.sub(r"[^\w₹$€%]+", "", s.lower())


def protected_spans(words: list[Word], names: list[str] = ()) -> list[tuple[int, int]]:
    """[start, end) word ranges a page must never split: the given names (brand / product, matched on bare tokens,
    e.g. "Video Studio" or "Shroti Host") and runs of 2–3 Capitalised words that do not start a sentence."""
    bare = [_bare(w.text) for w in words]
    spans: list[tuple[int, int]] = []
    for name in names:
        toks = [_bare(t) for t in name.split() if _bare(t)]
        if len(toks) < 2:
            continue
        for i in range(len(words) - len(toks) + 1):
            if bare[i:i + len(toks)] == toks and not any(SENTENCE_END.search(words[k].text) or CLAUSE_END.search(words[k].text)
                                                          for k in range(i, i + len(toks) - 1)):
                spans.append((i, i + len(toks)))
    i = 0
    while i < len(words):
        starts_sentence = i == 0 or bool(SENTENCE_END.search(words[i - 1].text))
        j = i
        while j < len(words) and words[j].text[:1].isupper() and (j == i or not (SENTENCE_END.search(words[j - 1].text)
                                                                                 or CLAUSE_END.search(words[j - 1].text))):
            j += 1
        if starts_sentence and j - i >= 3:
            i += 1                                     # "Meet Video Studio": the sentence-initial word is not part of it
            continue
        if not starts_sentence and 2 <= j - i <= 3:
            spans.append((i, j))
        i = max(j, i + 1)
    spans.sort()
    out: list[tuple[int, int]] = []
    for a, b in spans:                                  # merge overlaps
        if out and a < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def build_kinetic_pages(words: list[Word], *, max_words: int = 3, max_chars: int = 18, min_dur: float = 0.3,
                        hold: float = 0.6, audio_end: float | None = None, names: list[str] = ()) -> list[Page]:
    """Short word-synced pages for the kinetic looks (pop / highlight / karaoke): at most `max_words` words, a page
    ends at every sentence or clause end, a page never ends on a dangling function word ("the", "of", "your"), and a
    protected name ("Video Studio") is never split (it may exceed `max_words` on its own page)."""
    unit_of = {}
    for a, b in protected_spans(words, names):
        for k in range(a, b):
            unit_of[k] = (a, b)
    units, i = [], 0
    while i < len(words):
        a, b = unit_of.get(i, (i, i + 1))
        units.append(list(range(a, b)))
        i = b
    pages, cur = [], []

    def chars(idx):
        return sum(len(words[k].text) for k in idx) + max(0, len(idx) - 1)

    for k_u, u in enumerate(units):
        joiner = len(u) == 1 and _bare(words[u[0]].text) in _JOINERS
        if cur and len(cur) >= 2 and joiner and len(cur) + 1 <= max_words and max_words >= 3:
            pages.append(cur)                           # phrase break before "of / that / and …" ("a film | that was made")
            cur = []
        if cur and (len(cur) + len(u) > max_words or chars(cur + u) > max_chars):
            carry = []
            ends = SENTENCE_END.search(words[u[-1]].text) or CLAUSE_END.search(words[u[-1]].text)
            if ends and len(u) == 1 and len(cur) >= 3 and cur[-1] not in unit_of:
                carry = [cur.pop()]                     # no one-word orphan: "and its | own time." not "and its own | time."
            if len(cur) >= 2 and cur[-1] not in unit_of and _bare(words[cur[-1]].text) in _FUNCTION_WORDS \
                    and len(carry) + len(u) + 1 <= max_words:
                carry = [cur.pop(), *carry]             # "the" moves to the next page with its noun
            pages.append(cur)
            cur = carry
        cur = cur + u
        last = words[cur[-1]].text
        if SENTENCE_END.search(last) or CLAUSE_END.search(last):
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    return _timed(pages, words, min_dur=min_dur, hold=hold, audio_end=audio_end)


def _timed(pages: list[list[int]], words: list[Word], *, min_dur: float, hold: float, audio_end: float | None) -> list[Page]:
    out = []
    end_limit = audio_end if audio_end is not None else words[-1].end + hold
    for k, idx in enumerate(pages):
        start = words[idx[0]].start
        natural = words[idx[-1]].end + hold
        nxt = words[pages[k + 1][0]].start if k + 1 < len(pages) else end_limit
        end = min(max(natural, start + min_dur), nxt, end_limit)
        out.append(Page(round(start, 3), round(max(end, start + 0.05), 3), idx))
    return out


def pages_for(cc: dict, words: list[Word], audio_end: float, names: list[str] = ()) -> list[Page]:
    """Caption pages for a resolved caption config (`cfg["captions"]`): the classic grouping for classic / minimal
    (identical to before), short word-synced pages for the kinetic styles."""
    style = cc.get("style", "word")
    if is_kinetic(style):
        cap = 4 if style == "karaoke" else 3
        return build_kinetic_pages(words, max_words=min(cc.get("maxWords", cap), cap),
                                   max_chars=min(cc.get("maxChars", 28), 24 if style == "karaoke" else 18),
                                   hold=cc.get("hold", 0.6), audio_end=audio_end, names=names)
    return build_pages(words, max_words=cc.get("maxWords", 4), max_chars=cc.get("maxChars", 28),
                       hold=cc.get("hold", 0.6), audio_end=audio_end)


def caption_names(cfg: dict) -> list[str]:
    """Names a caption page must never split: the brand's display name (theme + brand profile)."""
    names = [cfg.get("theme", {}).get("name"), cfg.get("brandProfile", {}).get("name")]
    return sorted({n for n in names if isinstance(n, str) and n.strip()})


def validate_opts(style: str | None) -> dict:
    """validate_pages options per style. Word-synced pages: reading speed over a window (see KINETIC_READING_WINDOW);
    a page may be shorter than the classic 0.25 s flicker limit down to 0.2 s (6 frames), because the eye follows the
    highlighted word through a stream of pages instead of reading each page from scratch."""
    return {"window": reading_window(style), "min_page_s": 0.2} if is_kinetic(style) else {}


def style_props(ccf: dict) -> dict:
    """Optional RenderProps caption fields (contract-additive: written only when the project sets them, so the
    props of a classic project stay byte-identical)."""
    return {k: ccf[k] for k in ("uppercase", "emphasis") if k in ccf}


def default_style(fmt: str, brand_profile: dict | None = None, brief: dict | None = None) -> str:
    """Caption style for a NEW production: the brief's `captions.style` -> the brand's `creative.captions.style`
    (a style name, or {"short": …, "landscape": …}) -> the format default (short: pop, landscape: minimal)."""
    for src in ((brief or {}).get("captions", {}).get("style"),
                (brand_profile or {}).get("creative", {}).get("captions", {}).get("style")):
        if isinstance(src, dict):
            src = src.get(fmt)
        if isinstance(src, str) and src in STYLES:
            return src
    return FORMAT_DEFAULT_STYLE.get(fmt, "word")


def apply_default_style(project: dict, brand_profile: dict | None = None, brief: dict | None = None) -> dict:
    """Write the resolved caption style into a NEW project dict (explicit project values win). Existing project files
    are never touched, so a project without `captions.style` keeps the preset's classic look."""
    fmts = project.get("formats") or ["short"]
    caps = project.setdefault("captions", {})
    caps.setdefault("style", default_style(fmts[0], brand_profile, brief))
    if fmts[0] == "short":                  # the landscape variant of a Short (captionsByFormat) gets its own default
        land = project.setdefault("captionsByFormat", {}).setdefault("landscape", {})
        b_style = (brief or {}).get("captions", {}).get("style")      # a brief's single style is for the Short
        land.setdefault("style", default_style("landscape", brand_profile,
                                               brief if isinstance(b_style, dict) else None))
    return project


def window_cps(spans: list[tuple[float, float, str]], window: float) -> list[tuple[int, float]]:
    """(index of the first page, chars/s) per reading window: consecutive pages merged until they span ≥ `window` s
    (window 0 = every page on its own, the classic per-page check)."""
    out = []
    for k in range(len(spans)):
        j, text = k, spans[k][2]
        while spans[j][1] - spans[k][0] < window and j + 1 < len(spans) and spans[j + 1][0] - spans[j][1] < 0.3:
            j += 1
            text += " " + spans[j][2]
        out.append((k, len(text) / max(spans[j][1] - spans[k][0], 1e-3)))
    return out


def _srt_ts(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000); m, ms = divmod(ms, 60_000); sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def to_srt(pages: list[Page], words: list[Word]) -> str:
    out = []
    for n, p in enumerate(pages, 1):
        out += [str(n), f"{_srt_ts(p.start)} --> {_srt_ts(p.end)}", p.text(words), ""]
    return "\n".join(out)


def _ass_ts(s: float) -> str:
    cs = int(round(s * 100))
    h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); sec, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{sec:02}.{cs:02}"


def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")[:6]
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def to_ass(pages: list[Page], words: list[Word], *, width: int, height: int, font: str, font_size: int,
           bottom_frac: float, highlight: str, text_color: str = "#FFFFFF", karaoke: bool = True) -> str:
    """ASS with per-word karaoke (\\k) timing; MarginV places the box like the burned-in captions."""
    margin_v = int(height * bottom_frac)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{font_size},{_ass_color(highlight)},{_ass_color(text_color)},&H00000000,&H8C000000,-1,0,0,0,100,100,0,0,3,2,0,2,{int(width * 0.1)},{int(width * 0.1)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for p in pages:
        if karaoke:
            parts, t = [], p.start
            for i in p.word_idx:
                w = words[i]
                lead = max(0, int(round((w.start - t) * 100)))
                if lead:
                    parts.append(f"{{\\k{lead}}}")
                parts.append(f"{{\\k{max(1, int(round((w.end - w.start) * 100)))}}}{_ass_escape(w.text)} ")
                t = w.end
            text = "".join(parts).rstrip()
        else:
            text = _ass_escape(p.text(words))
        lines.append(f"Dialogue: 0,{_ass_ts(p.start)},{_ass_ts(p.end)},Caption,,0,0,0,,{text}")
    return head + "\n".join(lines) + "\n"


def _ass_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


@dataclass
class CaptionReport:
    errors: list[str]
    warnings: list[str]
    max_cps: float
    max_wps: float


def validate_pages(pages: list[Page], words: list[Word], audio_duration: float, *, max_cps: float = 25.0,
                   min_page_s: float = 0.25, window: float = 0.0) -> CaptionReport:
    errors, warnings, cps_max, wps_max = [], [], 0.0, 0.0
    if not pages:
        return CaptionReport(["no caption pages"], [], 0, 0)
    covered = sorted(i for p in pages for i in p.word_idx)
    if covered != list(range(len(words))):
        errors.append("caption pages do not cover every word exactly once, in order")
    for k, p in enumerate(pages):
        if p.end > audio_duration + 0.05:
            errors.append(f"page {k + 1} ends at {p.end:.2f}s after the voiceover ({audio_duration:.2f}s)")
        if p.start < 0 or p.end <= p.start:
            errors.append(f"page {k + 1} has invalid span {p.start:.2f}-{p.end:.2f}")
        if k and p.start < pages[k - 1].end - 1e-3:
            errors.append(f"pages {k}/{k + 1} overlap")
        dur = p.end - p.start
        if dur < min_page_s:
            warnings.append(f"page {k + 1} visible only {dur:.2f}s")
        if window <= 0:
            cps = len(p.text(words)) / max(dur, 1e-3)
            wps = len(p.word_idx) / max(dur, 1e-3)
            cps_max, wps_max = max(cps_max, cps), max(wps_max, wps)
            if cps > max_cps:
                warnings.append(f"page {k + 1} reads at {cps:.0f} chars/s (> {max_cps:.0f})")
    if window > 0:                                    # word-synced pages: chars/s over reading windows
        spans = [(p.start, p.end, p.text(words)) for p in pages]
        for (k, cps) in window_cps(spans, window):
            cps_max = max(cps_max, cps)
            if cps > max_cps:
                warnings.append(f"pages from {k + 1} read at {cps:.0f} chars/s over ≥{window:.1f}s (> {max_cps:.0f})")
        wps_max = max(len(p.word_idx) / max(p.end - p.start, 1e-3) for p in pages)
    return CaptionReport(errors, warnings, round(cps_max, 1), round(wps_max, 2))


_SRT_BLOCK = re.compile(r"(\d+)\n(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})\n(.+?)(?:\n\n|\n?$)", re.S)


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    def sec(t):
        h, m, rest = t.split(":"); s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    blocks = _SRT_BLOCK.findall(text.strip() + "\n\n")
    if not blocks and text.strip():
        raise ValueError("not a valid SRT file")
    return [(sec(a), sec(b), body.strip()) for _, a, b, body in blocks]
