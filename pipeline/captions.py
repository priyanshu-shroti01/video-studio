"""Caption pages (shared by the burned-in Remotion captions, SRT and ASS) + validation."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .timing import Word

SENTENCE_END = re.compile(r"[.!?…]$")
CLAUSE_END = re.compile(r"[,;:—–]$")


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
                   min_page_s: float = 0.25) -> CaptionReport:
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
        cps = len(p.text(words)) / max(dur, 1e-3)
        wps = len(p.word_idx) / max(dur, 1e-3)
        cps_max, wps_max = max(cps_max, cps), max(wps_max, wps)
        if cps > max_cps:
            warnings.append(f"page {k + 1} reads at {cps:.0f} chars/s (> {max_cps:.0f})")
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
