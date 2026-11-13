"""Component generator: new scene graphics (`composition` blocks) per production, searched and scored.

The fixed template library recombines the same 31 block types, so a brand's videos start to look alike. For suitable
scenes (demo / proof roles whose hero carries structure: steps, a stack, a feature set, a count with satellites, a
comparison) the composer:

1. extracts the scene's **content** from its template hero (`content_of`): the verified labels the template bound to
   facts or copy, their icons and the `@word:` anchors that time them. Nothing else may appear: no label is invented,
   no number is added, every beat keeps the spoken word it was anchored on;
2. builds **candidates** by searching structures (ladder, orbit, grid, network, stacked cards, split compare, funnel,
   layers, hero number, path) × variants × seeded arrangement parameters × motion schemes (cascade, pop, draw, focus),
   each laid out for both canvases (tall: Shorts / narrow columns, wide: 16:9);
3. **scores** them with the existing machinery and its own balance metrics:
   - rejected: invalid block, a label that is not a bound fact / copy string (rules' invented-label test), a number
     drawn > 0.3 s before it is spoken or > 2.4 s of narration without a visual event (rules.sync_report), text
     overflow in either format (the engine's own layout manifest, scripts/engine-layout.mjs), overlapping text;
   - scored: legibility (smallest font in the manifest), sync (largest gap), balance (coverage, centre of mass, span,
     element count, in both layouts), freshness (pipeline/creative/freshness.py) and a small bonus for a structure the
     local LLM proposed or a design a person approved into the brand library;
4. replaces the template hero only when the best candidate scores at least as well as the template itself, and keeps
   the replacement only while the whole concept still passes every creative rule.

The LLM (optional; provider "none" works) may only name which structures fit the scene idea, from the list. It never
places, sizes or labels anything. Deterministic: the same brief, facts, history and seed give the same result."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..storyboard import validate_storyboard
from ..timing import norm
from .anchors import _fmt

SUITABLE_ROLES = ("demo", "proof")
TALL_W, WIDE_W = 940.0, 1500.0          # design widths of the two canvases (Short column, 16:9 natural width)
CANVAS = {"alone": {"tall": 0.9, "wide": 1.7}, "with_support": {"tall": 1.0, "wide": 1.9}}
MOTIONS = ("cascade", "pop", "draw", "focus")
PARAM_SAMPLES = 2                        # seeded arrangement-parameter sets per structure × variant
CANVAS_SCALES = (1.0, 1.3)               # canvas aspect options (×): a flatter canvas leaves room for a tall support block
WEIGHTS = {"legibility": 0.2, "sync": 0.25, "balance": 0.35, "freshness": 0.2}
TEMPLATE_BALANCE = 0.7                   # hand-designed templates are presumed balanced
BONUS = {"llm_first": 0.04, "llm": 0.02, "library": 0.04}
# Smallest rendered size (output px, final hero scale) of a label / value / body text in a generated component. Below it a
# candidate is rejected: 34 px on a 1080-wide Short reads at phone size, 28 px on a 1920-wide 16:9 frame (viewed larger).
MIN_LABEL_PX = {"short": 34.0, "landscape": 28.0}
LEGIBLE_ROLES = ("label", "body")         # manifest roles judged for legibility (titles are large; template UI chrome is not)
TEXT_PAD_PX = 4.0                        # padding around manifest text boxes for the path-crossing test (output px)
PATH_SAMPLES = 48


def fmt_off(expr, off: float):
    """`expr` shifted by `off` seconds (keeps word anchors: "@word:x+0.2")."""
    if not isinstance(expr, str):
        return round(float(expr) + off, 3)
    import re
    m = re.match(r"^(.*?)([+-]\d+(?:\.\d+)?)?$", expr)
    return _fmt(m.group(1), float(m.group(2) or 0) + off)


# ---- content model ---------------------------------------------------------------------------------------
@dataclass
class Item:
    text: str
    at: object                 # time expression (usually "@word:...")
    icon: str | None = None


@dataclass
class Content:
    kind: str                  # sequence | set | stack | count | compare
    items: list[Item]
    title: Item | None = None
    status: Item | None = None
    number: dict | None = None             # counter semantics: to, from, prefix, suffix, decimals, grouping, at, countEnd
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)  # compare: {"label": Item, "values": [bool | str]}
    highlight: int | None = None
    hero: int = 0              # index of the template hero block in the scene
    hero_type: str = ""
    open_at: object = None     # when the template hero itself appeared: the composition's frame opens then too
    absorbs: list[int] = field(default_factory=list)   # support blocks folded into the composition

    def texts(self) -> list[str]:
        out = [i.text for i in self.items] + [x.text for x in (self.title, self.status) if x]
        out += self.columns + [r["label"].text for r in self.rows] + [v for r in self.rows for v in r["values"] if isinstance(v, str)]
        return out

    def key(self) -> str:
        return hashlib.sha256(json.dumps([self.kind, self.texts(), str(self.number and self.number.get("to"))]).encode()).hexdigest()[:12]


def _items(xs, text_key: str, cap: int = 6) -> list[Item]:
    return [Item(x[text_key], x["at"], x.get("icon")) for x in xs if isinstance(x, dict) and isinstance(x.get(text_key), str) and "at" in x][:cap]


def content_of(scene: dict) -> Content | None:
    """The structured content of a scene's template hero, or None when the hero carries no structure."""
    from .rules import hero_of
    blocks = scene.get("blocks", [])
    h = hero_of(scene)
    types = [b["type"] for b in blocks]
    if h not in ("install-flow", "progress", "server-stack", "checklist", "counter", "feature-compare"):
        return None
    i = types.index(h)
    b = blocks[i]
    c: Content | None = None
    if h == "install-flow":
        items = _items(b.get("steps", []), "label")
        c = Content("sequence", items, title=Item(b.get("title") or b["app"], b.get("at", items[0].at if items else 0)) if items else None,
                    status=Item(b["doneText"], b["doneAt"]) if b.get("doneText") and "doneAt" in b else None)
    elif h == "progress":
        items = _items(b.get("steps", []), "label")
        c = Content("sequence", items, title=Item(b["title"], b.get("at", items[0].at)) if b.get("title") and items else None)
    elif h == "server-stack":
        items = _items(b.get("nodes", []), "label")
        st = b.get("status")
        c = Content("stack", items, title=Item(b["title"], b.get("at", items[0].at if items else 0)) if b.get("title") and items else None,
                    status=Item(st["text"], st["at"]) if isinstance(st, dict) and st.get("text") and "at" in st else None)
    elif h == "checklist":
        c = Content("set", _items(b.get("items", []), "text"))
    elif h == "counter":
        sup = next((k for k, x in enumerate(blocks) if x["type"] == "checklist"), None)
        items = _items(blocks[sup].get("items", []), "text") if sup is not None else []
        num = {k: b[k] for k in ("to", "from", "prefix", "suffix", "decimals", "grouping", "at", "countEnd") if k in b}
        if "countEnd" not in num and "at" in num:
            num["countEnd"] = fmt_off(num["at"], 0.8)
        c = Content("count", items, title=Item(b["label"], b.get("at")) if b.get("label") and "at" in b else None, number=num,
                    absorbs=[sup] if sup is not None else [])
    elif h == "feature-compare":
        rows = [{"label": Item(r["label"], r["at"]), "values": list(r.get("values", []))} for r in b.get("rows", [])
                if isinstance(r, dict) and isinstance(r.get("label"), str) and "at" in r][:5]
        c = Content("compare", [r["label"] for r in rows], columns=[x for x in b.get("columns", []) if isinstance(x, str)], rows=rows,
                    title=Item(b["title"], b.get("at", rows[0]["label"].at)) if b.get("title") and rows else None, highlight=b.get("highlight"))
    if c is None or len(c.items) < 2:
        return None
    c.hero, c.hero_type = i, h
    c.open_at = b.get("at", c.items[0].at)
    return c


def frame_at(c: Content):
    """Time of the frame (title, hub, rail, ring, columns): when the template hero appeared, so the scene opens as early."""
    return c.open_at if c.open_at is not None else (c.title.at if c.title else c.items[0].at)


# ---- canvas helpers --------------------------------------------------------------------------------------
class G:
    """One canvas in design px (width W, height H). `box` normalises to [x, y, w, h] fractions, clipped inside."""

    def __init__(self, layout: str, aspect: float):
        self.layout = layout
        self.W = TALL_W if layout == "tall" else WIDE_W
        self.H = round(self.W / aspect, 3)
        self.wide = layout == "wide"

    def box(self, x, y, w, h) -> list[float]:
        x, y = max(0.0, x), max(0.0, y)
        w, h = max(1.0, min(w, self.W - x)), max(1.0, min(h, self.H - y))
        return [round(x / self.W, 4), round(y / self.H, 4), round(w / self.W, 4), round(h / self.H, 4)]


def _clamp(v, a, b):
    return max(a, min(b, v))


TITLE_H, GAP, LABEL_H, STATUS_H = 84.0, 28.0, 108.0, 92.0


def el_text(eid, text, role, box, at, align="center", color=None, item=None):
    e = {"id": eid, "kind": "text", "text": text, "role": role, "align": align, "box": box, "at": at}
    if color:
        e["color"] = color
    if item is not None:
        e["_item"] = item
    return e


def el_shape(eid, shape, box, at, item=None, **kw):
    e = {"id": eid, "kind": "shape", "shape": shape, "box": box, "at": at, **kw}
    if item is not None:
        e["_item"] = item
    return e


def el_icon(eid, icon, box, at, color="brandText", item=None):
    e = {"id": eid, "kind": "icon", "icon": icon, "box": box, "at": at, "color": color}
    if item is not None:
        e["_item"] = item
    return e


def el_conn(eid, a, b, at, curve=0.0, stroke="brand", strokeW=4, item=None):
    e = {"id": eid, "kind": "connector", "fromId": a, "toId": b, "box": [0, 0, 0, 0], "at": at, "stroke": stroke, "strokeW": strokeW}
    if curve:
        e["curve"] = round(curve, 3)
    if item is not None:
        e["_item"] = item
    return e


def el_number(eid, num: dict, box, color="text"):
    e = {"id": eid, "kind": "number", "box": box, "color": color, **{k: v for k, v in num.items()}}
    return e


def _head(c: Content, g: G, out: list) -> float:
    if not c.title:
        return 0.0
    out.append(el_text("title", c.title.text, "title", g.box(0, 0, g.W, TITLE_H), frame_at(c)))
    return TITLE_H + GAP


def _foot(c: Content, g: G, out: list, width_frac: float = 1.0) -> float:
    if not c.status:
        return g.H
    w = g.W * width_frac
    x = (g.W - w) / 2
    y = g.H - STATUS_H
    out.append(el_shape("status-card", "roundrect", g.box(x, y, w, STATUS_H), c.status.at, fill="surface", stroke="success", strokeW=3))
    out.append(el_icon("status-icon", "check", g.box(x + 24, y + 22, 48, 48), c.status.at, color="success"))
    out.append(el_text("status", c.status.text, "label", g.box(x + 88, y + 8, w - 112, STATUS_H - 16), c.status.at, align="left"))
    return y - GAP


def _node(out, g, i, it: Item, cx, cy, d, fill="raised", stroke="brand"):
    out.append(el_shape(f"n{i}", "circle", g.box(cx - d / 2, cy - d / 2, d, d), fmt_off(it.at, -0.05), item=i, fill=fill, stroke=stroke, strokeW=4))
    if it.icon:
        s = d * 0.5
        out.append(el_icon(f"i{i}", it.icon, g.box(cx - s / 2, cy - s / 2, s, s), it.at, item=i))
    else:
        s = d * 0.3
        out.append(el_shape(f"d{i}", "circle", g.box(cx - s / 2, cy - s / 2, s, s), it.at, item=i, fill="brand"))


# ---- structures (each: content, variant, canvas, params -> elements for that canvas) ------------------------
def s_ladder(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    y0 = _head(c, g, out)
    y1 = _foot(c, g, out)
    n = len(c.items)
    if not g.wide:
        slot = (y1 - y0) / n
        d = _clamp(slot * p["node"], 56, 96)
        rx = d / 2 + 6
        cys = [y0 + slot * (i + 0.5) for i in range(n)]
        if v == "rail":
            out.append(el_shape("rail", "line", g.box(rx - 3, cys[0], 6, cys[-1] - cys[0]), frame_at(c), stroke="brand", strokeW=6))
        for i, it in enumerate(c.items):
            _node(out, g, i, it, rx, cys[i], d)
            lh = min(slot * 0.92, LABEL_H)
            x = rx + d / 2 + 30
            out.append(el_text(f"l{i}", it.text, "label", g.box(x, cys[i] - lh / 2, g.W - x, lh), fmt_off(it.at, 0.05), align="left", item=i))
    else:
        slot = g.W / n
        d = _clamp(min(slot * 0.36, (y1 - y0) * 0.32), 56, 104)
        ry = y0 + (y1 - y0) * p["rail"]
        cxs = [slot * (i + 0.5) for i in range(n)]
        if v == "rail":
            out.append(el_shape("rail", "line", g.box(cxs[0], ry - 3, cxs[-1] - cxs[0], 6), frame_at(c), stroke="brand", strokeW=6))
        for i, it in enumerate(c.items):
            _node(out, g, i, it, cxs[i], ry, d)
            y = ry + d / 2 + 22
            out.append(el_text(f"l{i}", it.text, "label", g.box(cxs[i] - slot * 0.47, y, slot * 0.94, min(LABEL_H, y1 - y)), fmt_off(it.at, 0.05), item=i))
    if v == "links":
        for i in range(1, n):
            out.append(el_conn(f"k{i}", f"n{i - 1}", f"n{i}", fmt_off(c.items[i].at, -0.25), curve=p["bend"] * (1 if i % 2 else -1), item=i))
    return out


def s_orbit(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    n = len(c.items)
    top = 0.0
    hub_text = c.title if not c.number else None
    if c.number and c.title:
        top = _head(c, g, out)
    bottom = _foot(c, g, out, 0.7)
    cx, cy = g.W / 2, (top + bottom) / 2
    span = min(g.W, bottom - top)
    R = span * (0.33 if not g.wide else 0.36)
    hd = span * (0.34 if not g.wide else 0.4)
    hub_at = frame_at(c)
    out.append(el_shape("hub", "circle", g.box(cx - hd / 2, cy - hd / 2, hd, hd), hub_at, fill="surface", stroke="brand", strokeW=6))
    if c.number:
        out.append(el_number("num", c.number, g.box(cx - hd * 0.42, cy - hd * 0.2, hd * 0.84, hd * 0.4)))
    elif hub_text:
        out.append(el_text("title", hub_text.text, "title", g.box(cx - hd * 0.38, cy - hd * 0.3, hd * 0.76, hd * 0.6), hub_at))
    else:
        s = hd * 0.42
        out.append(el_icon("hub-icon", c.items[0].icon or "star", g.box(cx - s / 2, cy - s / 2, s, s), hub_at))
    if v == "ring":
        out.append(el_shape("ring", "ring", g.box(cx - R, cy - R, 2 * R, 2 * R), hub_at, stroke="border", strokeW=4))
    d = 76.0 if not g.wide else 84.0
    start = p["start"] + (180.0 / n if n % 2 == 0 and not g.wide else 0.0)
    for i, it in enumerate(c.items):
        th = math.radians(start + i * 360.0 / n)
        nx, ny = cx + R * math.sin(th), cy - R * math.cos(th)
        _node(out, g, i, it, nx, ny, d)
        if v == "spokes":
            out.append(el_conn(f"k{i}", "hub", f"n{i}", fmt_off(it.at, -0.2), item=i))
        s = math.sin(th)
        if g.wide and abs(s) > 0.3:
            w = min(400.0, (g.W - 2 * R - hd) / 2)
            x = nx + d / 2 + 16 if s > 0 else nx - d / 2 - 16 - w
            out.append(el_text(f"l{i}", it.text, "label", g.box(x, ny - LABEL_H / 2, w, LABEL_H), fmt_off(it.at, 0.05),
                               align="left" if s > 0 else "right", item=i))
        else:
            w = min(320.0, g.W * 0.36)
            above = math.cos(th) > 0.35
            y = ny - d / 2 - 6 - 96 if above else ny + d / 2 + 6
            out.append(el_text(f"l{i}", it.text, "label", g.box(_clamp(nx - w / 2, 0, g.W - w), y, w, 96), fmt_off(it.at, 0.05), item=i))
    return out


def s_grid(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    y0 = _head(c, g, out)
    y1 = _foot(c, g, out)
    n = len(c.items)
    if g.wide:
        cols = n if n <= 4 else 3
    else:
        cols = 1 if (n == 2 and v == "rows") else 2
    rows = math.ceil(n / cols)
    cw = (g.W - (cols - 1) * GAP) / cols
    ch = min((y1 - y0 - (rows - 1) * GAP) / rows, (300.0 if v == "tiles" else 180.0) * p["card"])
    gy = y0 + ((y1 - y0) - (rows * ch + (rows - 1) * GAP)) / 2
    for i, it in enumerate(c.items):
        r, k = divmod(i, cols)
        in_row = min(cols, n - r * cols)
        x = (g.W - (in_row * cw + (in_row - 1) * GAP)) / 2 + k * (cw + GAP)
        y = gy + r * (ch + GAP)
        out.append(el_shape(f"n{i}", "roundrect", g.box(x, y, cw, ch), fmt_off(it.at, -0.05), item=i, fill="card", stroke="border", strokeW=2))
        if v == "tiles":
            s = min(72.0, ch * 0.3)
            if it.icon:
                out.append(el_icon(f"i{i}", it.icon, g.box(x + cw / 2 - s / 2, y + ch * 0.12, s, s), it.at, item=i))
            ty = y + ch * 0.12 + (s + 12 if it.icon else 0)
            out.append(el_text(f"l{i}", it.text, "label", g.box(x + 18, ty, cw - 36, y + ch - ty - 14), fmt_off(it.at, 0.05), item=i))
        else:
            s = min(64.0, ch * 0.45)
            if it.icon:
                out.append(el_icon(f"i{i}", it.icon, g.box(x + 24, y + ch / 2 - s / 2, s, s), it.at, item=i))
            tx = x + 24 + (s + 20 if it.icon else 0)
            out.append(el_text(f"l{i}", it.text, "label", g.box(tx, y + 10, x + cw - tx - 20, ch - 20), fmt_off(it.at, 0.05), align="left", item=i))
    return out


def s_network(c: Content, v: str, g: G, p: dict, rng: random.Random) -> list[dict]:
    out: list[dict] = []
    y0 = 0.0
    y1 = _foot(c, g, out, 0.7)
    n = len(c.items)
    cx, cy = g.W / 2, (y0 + y1) / 2
    hd = (0.22 * g.W) if not g.wide else 0.3 * (y1 - y0)
    hub_at = frame_at(c)
    out.append(el_shape("hub", "circle", g.box(cx - hd / 2, cy - hd / 2, hd, hd), hub_at, fill="surface", stroke="brand", strokeW=6))
    if c.title:
        out.append(el_text("title", c.title.text, "title", g.box(cx - hd * 0.38, cy - hd * 0.3, hd * 0.76, hd * 0.6), hub_at))
    else:
        s = hd * 0.42
        out.append(el_icon("hub-icon", c.items[0].icon or "star", g.box(cx - s / 2, cy - s / 2, s, s), hub_at))
    cw = (0.36 if not g.wide else 0.28) * g.W
    ch = 96.0
    rows = math.ceil(n / 2)
    slot = (y1 - y0) / rows
    for i, it in enumerate(c.items):
        side, r = i % 2, i // 2
        jitter = rng.uniform(-1, 1) * p["jitter"] * max(0.0, slot - ch) / 2
        x = 0.0 if side == 0 else g.W - cw
        y = _clamp(y0 + slot * (r + 0.5) - ch / 2 + jitter, y0, y1 - ch)
        out.append(el_shape(f"n{i}", "roundrect", g.box(x, y, cw, ch), fmt_off(it.at, -0.05), item=i, fill="raised", stroke="brand", strokeW=3))
        ix = 0.0
        if it.icon:
            out.append(el_icon(f"i{i}", it.icon, g.box(x + 18, y + ch / 2 - 22, 44, 44), it.at, item=i))
            ix = 56.0
        out.append(el_text(f"l{i}", it.text, "label", g.box(x + 18 + ix, y + 8, cw - 36 - ix, ch - 16), fmt_off(it.at, 0.05),
                           align="left" if it.icon else "center", item=i))
        out.append(el_conn(f"k{i}", "hub", f"n{i}", fmt_off(it.at, -0.2), curve=p["bend"] * (1 if side else -1), item=i))
    if v == "mesh":
        for i in range(2, n):
            out.append(el_conn(f"m{i}", f"n{i - 2}", f"n{i}", fmt_off(c.items[i].at, -0.1), stroke="border", strokeW=3, item=i))
    return out


def s_stacked(c: Content, v: str, g: G, p: dict, rng: random.Random) -> list[dict]:
    out: list[dict] = []
    y0 = _head(c, g, out)
    y1 = _foot(c, g, out)
    n = len(c.items)
    if not g.wide:
        cw = g.W * (0.8 if v == "cascade" else 0.9)
        dy = (y1 - y0) / n
        ch = min(dy * p["overlap"], 190.0)
        dy = (y1 - y0 - ch) / max(1, n - 1)
        dx = (g.W - cw) / max(1, n - 1) if v == "cascade" else 0.0
        for i, it in enumerate(c.items):
            x = dx * i if v == "cascade" else (g.W - cw) / 2 + rng.uniform(-1, 1) * 18
            y = y0 + dy * i
            out.append(el_shape(f"n{i}", "roundrect", g.box(x, y, cw, ch), fmt_off(it.at, -0.05), item=i, fill="raised", stroke="border", strokeW=2))
            strip = min(dy, ch) - 12
            ix = 0.0
            if it.icon:
                s = min(52.0, strip * 0.7)
                out.append(el_icon(f"i{i}", it.icon, g.box(x + 24, y + 6 + strip / 2 - s / 2, s, s), it.at, item=i))
                ix = s + 18
            out.append(el_text(f"l{i}", it.text, "label", g.box(x + 24 + ix, y + 6, cw - 48 - ix, strip), fmt_off(it.at, 0.05), align="left", item=i))
    else:
        ch = (y1 - y0) * (0.86 if v == "cascade" else 0.7)
        dx = g.W / n
        cw = min(dx * p["overlap"], g.W * 0.4)
        dx = (g.W - cw) / max(1, n - 1)
        dy = ((y1 - y0) - ch) / max(1, n - 1) if v == "cascade" else 0.0
        for i, it in enumerate(c.items):
            x = dx * i
            y = y0 + (dy * i if v == "cascade" else ((y1 - y0) - ch) / 2 + rng.uniform(-1, 1) * 14)
            out.append(el_shape(f"n{i}", "roundrect", g.box(x, y, cw, ch), fmt_off(it.at, -0.05), item=i, fill="raised", stroke="border", strokeW=2))
            strip = min(dx, cw) - 24
            if it.icon:
                out.append(el_icon(f"i{i}", it.icon, g.box(x + 22, y + 24, 56, 56), it.at, item=i))
            out.append(el_text(f"l{i}", it.text, "label", g.box(x + 22, y + 96, strip, min(LABEL_H * 1.4, ch - 110)), fmt_off(it.at, 0.05),
                               align="left", item=i))
    return out


def s_compare(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    y0 = _head(c, g, out)
    m = max(1, len(c.columns))
    lw = g.W * (0.4 if not g.wide else 0.46)
    colw = (g.W - lw) / m
    head_h = 72.0
    out_at = frame_at(c)
    for k, col in enumerate(c.columns):
        x = lw + k * colw
        hl = c.highlight == k
        out.append(el_shape(f"col{k}", "roundrect", g.box(x + 8, y0, colw - 16, g.H - y0), out_at, fill="raised" if hl else "card",
                            stroke="brand" if hl else "border", strokeW=4 if hl else 2))
        out.append(el_text(f"h{k}", col, "label", g.box(x + 16, y0 + 8, colw - 32, head_h - 8), out_at))
    rh = (g.H - y0 - head_h - 16) / max(1, len(c.rows))
    for i, r in enumerate(c.rows):
        y = y0 + head_h + 8 + i * rh
        it = r["label"]
        if v == "lines" and i:
            out.append(el_shape(f"sep{i}", "line", g.box(0, y - 2, g.W, 4), it.at, stroke="border", strokeW=2))
        out.append(el_text(f"l{i}", it.text, "label", g.box(0, y + 6, lw - 20, rh - 12), fmt_off(it.at, 0.05), align="left", item=i))
        for k, val in enumerate(r["values"][:m]):
            x = lw + k * colw
            if val is True:
                s = min(56.0, rh * 0.5)
                out.append(el_icon(f"v{i}-{k}", "check", g.box(x + colw / 2 - s / 2, y + rh / 2 - s / 2, s, s), fmt_off(it.at, 0.1),
                                   color="success", item=i))
            elif val is False:
                out.append(el_shape(f"v{i}-{k}", "line", g.box(x + colw / 2 - 22, y + rh / 2 - 3, 44, 6), fmt_off(it.at, 0.1),
                                    stroke="muted", strokeW=5, item=i))
            elif isinstance(val, str):
                out.append(el_text(f"v{i}-{k}", val, "value", g.box(x + 16, y + 6, colw - 32, rh - 12), fmt_off(it.at, 0.1), item=i))
    return out


def s_funnel(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    y0 = _head(c, g, out)
    y1 = _foot(c, g, out)
    n = len(c.items)
    shrink = p["shrink"]
    fr = [1 - shrink * i / max(1, n - 1) for i in range(n)]
    if v == "widening":
        fr = fr[::-1]
    if not g.wide:
        bh = (y1 - y0 - (n - 1) * 14) / n
        for i, it in enumerate(c.items):
            w = g.W * fr[i]
            x, y = (g.W - w) / 2, y0 + i * (bh + 14)
            out.append(el_shape(f"n{i}", "roundrect", g.box(x, y, w, bh), fmt_off(it.at, -0.05), item=i, fill="raised", stroke="brand", strokeW=3))
            out.append(el_text(f"l{i}", it.text, "label", g.box(x + 24, y + 6, w - 48, bh - 12), fmt_off(it.at, 0.05), item=i))
    else:
        bw = (g.W - (n - 1) * 18) / n
        for i, it in enumerate(c.items):
            h = (y1 - y0) * fr[i]
            x, y = i * (bw + 18), y0 + ((y1 - y0) - h) / 2
            out.append(el_shape(f"n{i}", "roundrect", g.box(x, y, bw, h), fmt_off(it.at, -0.05), item=i, fill="raised", stroke="brand", strokeW=3))
            out.append(el_text(f"l{i}", it.text, "label", g.box(x + 16, y + h / 2 - LABEL_H / 2, bw - 32, LABEL_H), fmt_off(it.at, 0.05), item=i))
    return out


def s_layers(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    y0 = _head(c, g, out)
    y1 = _foot(c, g, out)
    n = len(c.items)
    vertical_bars = (v == "bars")
    if vertical_bars:                      # horizontal layers stacked top to bottom
        w = g.W * (1.0 if not g.wide else p["width"])
        x = (g.W - w) / 2
        bh = min((y1 - y0 - (n - 1) * 16) / n, 150.0)
        gy = y0 + ((y1 - y0) - (n * bh + (n - 1) * 16)) / 2
        for i, it in enumerate(c.items):
            y = gy + i * (bh + 16)
            out.append(el_shape(f"n{i}", "roundrect", g.box(x, y, w, bh), fmt_off(it.at, -0.05), item=i, fill="card", stroke="border", strokeW=2))
            out.append(el_shape(f"a{i}", "rect", g.box(x, y + 10, 8, bh - 20), it.at, item=i, fill="brand"))
            ix = 0.0
            if it.icon:
                s = min(60.0, bh * 0.5)
                out.append(el_icon(f"i{i}", it.icon, g.box(x + 34, y + bh / 2 - s / 2, s, s), it.at, item=i))
                ix = s + 22
            out.append(el_text(f"l{i}", it.text, "label", g.box(x + 34 + ix, y + 8, w - 60 - ix, bh - 16), fmt_off(it.at, 0.05), align="left", item=i))
    else:                                  # pillars side by side
        pw = (g.W - (n - 1) * 20) / n
        for i, it in enumerate(c.items):
            x = i * (pw + 20)
            out.append(el_shape(f"n{i}", "roundrect", g.box(x, y0, pw, y1 - y0), fmt_off(it.at, -0.05), item=i, fill="card", stroke="border", strokeW=2))
            out.append(el_shape(f"a{i}", "rect", g.box(x + 14, y0, pw - 28, 8), it.at, item=i, fill="brand"))
            if it.icon:
                s = min(72.0, pw * 0.4)
                out.append(el_icon(f"i{i}", it.icon, g.box(x + pw / 2 - s / 2, y0 + 40, s, s), it.at, item=i))
            out.append(el_text(f"l{i}", it.text, "label", g.box(x + 12, y1 - LABEL_H * 1.5 - 16, pw - 24, LABEL_H * 1.5), fmt_off(it.at, 0.05), item=i))
    return out


def s_hero_number(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    n = len(c.items)
    y0 = _head(c, g, out)
    num = c.number
    if not g.wide:
        d = min(g.W * p["ring"], (g.H - y0) * 0.55)
        rx, ry = (g.W - d) / 2, y0
        list_x, list_y, list_w, list_h = 0.0, y0 + d + GAP, g.W, g.H - (y0 + d + GAP)
    else:
        d = min((g.H - y0) * 0.92, g.W * 0.42)
        rx, ry = g.W * 0.04, y0 + ((g.H - y0) - d) / 2
        list_x, list_y, list_w, list_h = rx + d + 70, y0, g.W - (rx + d + 70), g.H - y0
    at = frame_at(c)
    if v == "arc":
        out.append(el_shape("track", "ring", g.box(rx, ry, d, d), at, stroke="border", strokeW=10))
        out.append(el_shape("arc", "arc", g.box(rx, ry, d, d), at, stroke="brand", strokeW=14, sweep=300, start=210))
    else:
        out.append(el_shape("hub", "circle", g.box(rx, ry, d, d), at, fill="surface", stroke="brand", strokeW=8))
    out.append(el_number("num", num, g.box(rx + d * 0.12, ry + d * 0.3, d * 0.76, d * 0.4)))
    rh = min(list_h / n, 120.0)
    gy = list_y + (list_h - rh * n) / 2
    for i, it in enumerate(c.items):
        y = gy + i * rh
        out.append(el_shape(f"n{i}", "roundrect", g.box(list_x, y + 6, list_w, rh - 12), fmt_off(it.at, -0.05), item=i, fill="card", stroke="border", strokeW=2))
        out.append(el_icon(f"i{i}", it.icon or "check", g.box(list_x + 22, y + rh / 2 - 22, 44, 44), it.at, color="success", item=i))
        out.append(el_text(f"l{i}", it.text, "label", g.box(list_x + 84, y + 12, list_w - 104, rh - 24), fmt_off(it.at, 0.05), align="left", item=i))
    return out


def s_path(c: Content, v: str, g: G, p: dict) -> list[dict]:
    out: list[dict] = []
    y0 = _head(c, g, out)
    y1 = _foot(c, g, out)
    n = len(c.items)
    d = 84.0
    for i, it in enumerate(c.items):
        if not g.wide:
            cy = y0 + (y1 - y0) * (i + 0.5) / n
            left = (i % 2 == 0) if v == "snake" else True
            cx = (g.W * 0.12 + d / 2 if left else g.W * 0.88 - d / 2) if v == "snake" else g.W * (0.08 + 0.3 * i / max(1, n - 1)) + d / 2
            _node(out, g, i, it, cx, cy, d)
            lh = min((y1 - y0) / n * 0.9, LABEL_H)
            if v == "snake" and not left:
                w = cx - d / 2 - 24
                out.append(el_text(f"l{i}", it.text, "label", g.box(0, cy - lh / 2, w, lh), fmt_off(it.at, 0.05), align="right", item=i))
            else:
                x = cx + d / 2 + 24
                out.append(el_text(f"l{i}", it.text, "label", g.box(x, cy - lh / 2, g.W - x, lh), fmt_off(it.at, 0.05), align="left", item=i))
        else:
            cx = g.W * (i + 0.5) / n
            up = (i % 2 == 0) if v == "snake" else False
            mid = (y0 + y1) / 2
            cy = (mid - (y1 - y0) * p["swing"] if up else mid + (y1 - y0) * p["swing"]) if v == "snake" else y1 - (y1 - y0) * (0.25 + 0.5 * i / max(1, n - 1))
            _node(out, g, i, it, cx, cy, d)
            w = g.W / n * 0.96
            y = cy - d / 2 - 12 - LABEL_H if (v == "snake" and not up) or v == "steps" else cy + d / 2 + 12
            out.append(el_text(f"l{i}", it.text, "label", g.box(cx - w / 2, y, w, LABEL_H), fmt_off(it.at, 0.05), item=i))
        if i:
            out.append(el_conn(f"k{i}", f"n{i - 1}", f"n{i}", fmt_off(it.at, -0.25), curve=p["bend"] * (1 if i % 2 else -1), item=i))
    return out


@dataclass(frozen=True)
class Structure:
    id: str
    fits: tuple[str, ...]
    variants: tuple[str, ...]
    items: tuple[int, int]
    build: Callable
    params: Callable[[random.Random], dict]
    describe: str
    seeded: bool = False         # build takes the rng (jitter)


def _u(rng, a, b):
    return round(rng.uniform(a, b), 3)


STRUCTURES: dict[str, Structure] = {s.id: s for s in [
    Structure("ladder", ("sequence", "stack", "set"), ("rail", "links"), (2, 6), s_ladder,
              lambda r: {"node": _u(r, 0.5, 0.7), "rail": _u(r, 0.25, 0.4), "bend": _u(r, 0.15, 0.4)},
              "a timeline: nodes on a rail, each label beside its node"),
    Structure("orbit", ("set", "stack", "count"), ("ring", "spokes"), (3, 6), s_orbit,
              lambda r: {"start": float(r.choice([0, 30, 45, 60]))}, "a hub with the items orbiting it"),
    Structure("grid", ("set", "stack", "sequence"), ("tiles", "rows"), (2, 6), s_grid,
              lambda r: {"card": _u(r, 0.8, 1.0)}, "cards in a grid"),
    Structure("network", ("set", "stack"), ("star", "mesh"), (3, 6), s_network,
              lambda r: {"jitter": _u(r, 0.2, 0.8), "bend": _u(r, 0.0, 0.3)}, "a graph: a hub linked to labelled nodes", True),
    Structure("stacked", ("set", "stack", "sequence"), ("cascade", "deck"), (2, 5), s_stacked,
              lambda r: {"overlap": _u(r, 1.2, 1.45)}, "overlapping stacked cards", True),
    Structure("compare", ("compare",), ("cards", "lines"), (2, 5), s_compare, lambda r: {}, "side-by-side comparison columns"),
    Structure("funnel", ("sequence",), ("narrowing", "widening"), (3, 6), s_funnel,
              lambda r: {"shrink": _u(r, 0.3, 0.5)}, "a funnel of bands, one per step"),
    Structure("layers", ("stack", "set"), ("bars", "pillars"), (2, 5), s_layers,
              lambda r: {"width": _u(r, 0.6, 0.8)}, "layers of a stack"),
    Structure("hero-number", ("count",), ("arc", "chips"), (2, 5), s_hero_number,
              lambda r: {"ring": _u(r, 0.5, 0.62)}, "one big counted number with its satellites"),
    Structure("path", ("sequence",), ("snake", "steps"), (2, 6), s_path,
              lambda r: {"swing": _u(r, 0.14, 0.22), "bend": _u(r, 0.2, 0.5)}, "a journey path through the steps"),
]}


# ---- motion schemes --------------------------------------------------------------------------------------
_DRAWN = {"ring", "arc", "line"}


def apply_motion(els: list[dict], scheme: str) -> list[dict]:
    out = []
    for e in els:
        e = dict(e)
        k, sh = e["kind"], e.get("shape")
        if scheme == "cascade":
            e["motion"] = "draw-on" if k == "connector" or sh in _DRAWN else "pop" if k == "icon" else "scale-in" if k == "shape" else "fade-up"
        elif scheme == "pop":
            e["motion"] = "draw-on" if k == "connector" or sh in _DRAWN else "pop" if k in ("shape", "icon") else "fade"
        elif scheme == "draw":
            e["motion"] = "draw-on" if k == "connector" or sh in _DRAWN else "fade" if k in ("shape", "text") else "scale-in" if k == "icon" else "fade-up"
            if k == "connector":
                e["at"] = fmt_off(e["at"], -0.1)
        elif scheme == "focus":
            e["motion"] = "draw-on" if k == "connector" or sh in _DRAWN else "scale-in" if k == "shape" else "pop" if k == "icon" else "fade-up"
            if k == "shape" and "_item" in e and e["id"].startswith("n"):
                e["pulseAt"] = fmt_off(e["at"], 0.35)
        out.append(e)
    return _containers_move_with_contents(out)


def _inside(inner: list, outer: list, eps: float = 1e-6) -> bool:
    return (inner[0] >= outer[0] - eps and inner[1] >= outer[1] - eps and inner[0] + inner[2] <= outer[0] + outer[2] + eps
            and inner[1] + inner[3] <= outer[1] + outer[3] + eps)


def _containers_move_with_contents(els: list[dict]) -> list[dict]:
    """A card that holds text or an icon must enter the way its contents do. If the card scales while its label stays
    put, the label sits outside the card for the whole entrance (and still does at the cut when the card enters on
    the scene's last word). Containers therefore fade (or fade up with fade-up text); their contents keep their motion."""
    for c in els:
        if c["kind"] != "shape" or c.get("shape") in _DRAWN or not c.get("box"):
            continue
        inside = [e for e in els if e is not c and e["kind"] in ("text", "icon", "number") and e.get("box")
                  and _inside(e["box"], c["box"]) and (not c.get("wide") or not e.get("wide") or _inside(e["wide"], c["wide"]))]
        if inside:
            c["motion"] = "fade-up" if any(e.get("motion") == "fade-up" for e in inside if e["kind"] != "icon") else "fade"
            for e in inside:
                if e["kind"] == "text" and e.get("motion") == "fade-up" and c["motion"] == "fade":
                    e["motion"] = "fade"
    return els


def _merge(tall: list[dict], wide: list[dict]) -> list[dict]:
    if [(e["id"], e["kind"]) for e in tall] != [(e["id"], e["kind"]) for e in wide]:
        raise ValueError("structure produced different elements for the two canvases")
    out = []
    for a, b in zip(tall, wide):
        e = {k: v for k, v in a.items() if not k.startswith("_")}
        if b["box"] != a["box"]:
            e["wide"] = b["box"]
        out.append((e, a.get("_item")))
    # order: shapes and connectors under icons, numbers and text
    rank = {"connector": 0, "shape": 1, "media": 2, "logo": 2, "icon": 3, "number": 4, "text": 5}
    out.sort(key=lambda x: rank[x[0]["kind"]])
    return [e for e, _ in out]


def build_block(c: Content, structure: str, variant: str, params: dict, motion: str, canvas: dict, seed: int,
                source: str = "generated") -> dict:
    S = STRUCTURES[structure]
    lays = {}
    for layout in ("tall", "wide"):
        g = G(layout, canvas[layout])
        rng = random.Random(seed)
        els = S.build(c, variant, g, params, rng) if S.seeded else S.build(c, variant, g, params)
        lays[layout] = apply_motion(els, motion)
    els = _merge(lays["tall"], lays["wide"])
    sig = f"{structure}/{variant}/{motion}"
    return {"type": "composition", "at": frame_at(c), "canvas": dict(canvas), "elements": els,
            "design": {"structure": structure, "variant": variant, "motion": motion, "signature": sig, "source": source}}


# ---- scoring ---------------------------------------------------------------------------------------------
def _rect(e: dict, layout: str) -> tuple[float, float, float, float]:
    b = e.get("wide") if layout == "wide" and e.get("wide") else e["box"]
    return tuple(float(x) for x in b)


def _inter(a, b) -> float:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def balance(block: dict) -> tuple[float, list[str], dict]:
    """(balance score 0..1, rejection reasons, metrics) over both layouts, from the normalised element boxes."""
    reasons: list[str] = []
    per = {}
    for layout in ("tall", "wide"):
        els = block["elements"]
        texts = [_rect(e, layout) for e in els if e["kind"] in ("text", "number")]
        icons = [_rect(e, layout) for e in els if e["kind"] == "icon"]
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                if _inter(texts[i], texts[j]) > 0.15 * min(texts[i][2] * texts[i][3], texts[j][2] * texts[j][3]):
                    reasons.append(f"text boxes overlap ({layout})")
            for ic in icons:
                if _inter(texts[i], ic) > 0.25 * ic[2] * ic[3]:
                    reasons.append(f"an icon covers text ({layout})")
        N = 40
        grid = [[0] * N for _ in range(N)]
        xs, ys = [], []
        for e in els:
            if e["kind"] == "connector" or e.get("shape") == "line":
                continue
            x, y, w, h = _rect(e, layout)
            xs += [x, x + w]
            ys += [y, y + h]
            if e.get("shape") in ("ring", "arc"):
                continue
            for gx in range(int(x * N), min(N, int(math.ceil((x + w) * N)))):
                for gy in range(int(y * N), min(N, int(math.ceil((y + h) * N)))):
                    grid[gy][gx] = 1
        cells = [(gx, gy) for gy in range(N) for gx in range(N) if grid[gy][gx]]
        cov = len(cells) / (N * N)
        if cells:
            mx = sum(c[0] + 0.5 for c in cells) / len(cells) / N
            my = sum(c[1] + 0.5 for c in cells) / len(cells) / N
        else:
            mx = my = 0.0
        dist = math.hypot(mx - 0.5, my - 0.5)
        span = min(max(xs) - min(xs), max(ys) - min(ys)) if xs else 0.0
        n_el = len(els)
        s_cen = 1 - min(1.0, dist / 0.3)
        s_span = _clamp((span - 0.5) / 0.4, 0.0, 1.0)
        s_cnt = 1.0 if 6 <= n_el <= 40 else 0.6
        # arrangement only: how much of the hero box is actually drawn is measured on the manifest (ink_coverage)
        per[layout] = {"box_coverage": round(cov, 3), "centre_offset": round(dist, 3), "span": round(span, 3), "elements": n_el,
                       "score": round((0.2 * s_cen + 0.15 * s_span + 0.15 * s_cnt) / 0.5, 3)}
    score = round(sum(v["score"] for v in per.values()) / len(per), 3)
    return score, sorted(set(reasons)), per


def allowed_labels(labels: dict, narration: str) -> Callable[[str], bool]:
    narr = norm(narration)
    return lambda s: s in labels or (bool(norm(s)) and norm(s) in narr)


def _preset(fmt: str) -> str:
    return "shorts" if fmt == "short" else "landscape"


def layout_metrics(scenes: list[dict], brand_id: str, formats=("short", "landscape")) -> dict | None:
    """Per scene id and format: overflowing texts and the smallest output font of each block, from the engine's own
    layout manifest (one manifest run per format for all scenes). None when node / esbuild is unavailable."""
    try:
        from ..config import deep_merge, load_preset, load_theme
        from ..timeline import build_timeline, estimated_timing
        from ..visual_qa.checks import layout_manifest
        sb = {"version": 1, "scenes": scenes}
        out: dict = {}
        for fmt in formats:
            cfg = deep_merge(load_preset(_preset(fmt)), {"name": "composer-check", "preset": _preset(fmt), "formats": [fmt],
                                                         "brand": brand_id, "storyboard": sb, "audio": {"music": None}})
            cfg["theme"] = load_theme(brand_id)
            tl = build_timeline(cfg, estimated_timing(sb))
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(tl.props[fmt], f)
                pf = Path(f.name)
            try:
                m = layout_manifest(pf)
            finally:
                pf.unlink(missing_ok=True)
            for sc in m["scenes"]:
                rec = out.setdefault(sc["id"], {})
                rec[fmt] = {"blocks": [{"type": b["type"], "bbox": b["bbox"],
                                        "overflow": [t["text"] for t in b.get("texts", []) if t.get("overflow")],
                                        "min_font": min((t["fontSize"] for t in b.get("texts", [])), default=None),
                                        "texts": [{"text": t["text"], "role": t["role"], "fontSize": t["fontSize"], "bbox": t["bbox"]}
                                                  for t in b.get("texts", [])]}
                                       for b in sc["blocks"]]}
        return out
    except Exception:  # noqa: BLE001 - an unavailable tool means "cannot verify", never a pass
        return None


def label_px(mblock: dict) -> float | None:
    """Smallest rendered label / value / body text of a manifest block (output px); None when it has none."""
    fs = [t["fontSize"] for t in mblock.get("texts", []) if t["role"] in LEGIBLE_ROLES]
    return min(fs) if fs else None


def item_px(mblock: dict, items: list[str]) -> float | None:
    """Smallest rendered size of the texts that show the content items (a wrapped item is several lines). The same
    strings exist in the template hero and in every candidate, so both are judged on the same text, never on a
    template's decorative chrome (window titles, status pills)."""
    fs = [t["fontSize"] for t in mblock.get("texts", []) if len(t["text"]) >= 3 and any(t["text"] in it for it in items)]
    return min(fs) if fs else label_px(mblock)


def _legibility(per_fmt: dict, items: list[str]) -> float:
    """Same scale for a generated component and a template hero: the smallest item text per format against that
    format's minimum (0.5 × minimum -> 0, 1.4 × minimum -> 1); the worse format counts."""
    out = []
    for fmt, mb in per_fmt.items():
        px = item_px(mb, items)
        if px is None:
            continue
        lo = MIN_LABEL_PX.get(fmt, 30.0)
        out.append(_clamp((px - 0.5 * lo) / (0.9 * lo), 0.0, 1.0))
    return round(min(out), 3) if out else 1.0


# ---- drawn geometry in output px (mirror of src/engine/geometry-composition.ts) ------------------------------------
_ROUND = ("circle", "ring", "arc")


def _layout_of(block: dict, bbox: dict) -> tuple[str, float]:
    """Which canvas the engine used for this block box (tall / wide), from the box's aspect."""
    cv = block.get("canvas") or {}
    at, aw = float(cv.get("tall", 1.0)), float(cv.get("wide", 1.9))
    a = bbox["w"] / max(1e-6, bbox["h"])
    return ("tall", at) if abs(a - at) <= abs(a - aw) else ("wide", aw)


def _px_rects(block: dict, bbox: dict, layout: str) -> list[tuple[float, float, float, float]]:
    out = []
    for e in block["elements"]:
        x, y, w, h = _rect(e, layout)
        r = (bbox["x"] + x * bbox["w"], bbox["y"] + y * bbox["h"], w * bbox["w"], h * bbox["h"])
        if e["kind"] == "icon" or (e["kind"] == "shape" and e.get("shape") in _ROUND):
            s = min(r[2], r[3])
            r = (r[0] + (r[2] - s) / 2, r[1] + (r[3] - s) / 2, s, s)
        out.append(r)
    return out


def _edge(r, round_: bool, dx: float, dy: float, gap: float) -> tuple[float, float]:
    cx, cy = r[0] + r[2] / 2, r[1] + r[3] / 2
    ln = math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    if round_:
        d = min(r[2], r[3]) / 2
    else:
        tx = r[2] / 2 / abs(ux) if abs(ux) > 1e-9 else math.inf
        ty = r[3] / 2 / abs(uy) if abs(uy) > 1e-9 else math.inf
        d = min(tx, ty)
    return cx + ux * (d + gap), cy + uy * (d + gap)


def drawn_paths(block: dict, bbox: dict) -> list[tuple[int, set[int], list[tuple[float, float]]]]:
    """(element index, endpoint element indices, sampled points in output px) of every connector, line, ring and arc as
    the engine draws it in this box (quadratic curves and arcs included)."""
    layout, _ = _layout_of(block, bbox)
    els = block["elements"]
    rects = _px_rects(block, bbox, layout)
    ids = {e["id"]: i for i, e in enumerate(els) if e.get("id")}
    k = bbox["w"] / (TALL_W if layout == "tall" else WIDE_W)        # design px -> output px
    out = []
    N = PATH_SAMPLES
    for i, e in enumerate(els):
        if e["kind"] == "connector":
            a, b = ids.get(e.get("fromId")), ids.get(e.get("toId"))
            if a is None or b is None or a == b:
                continue
            ra, rb = rects[a], rects[b]
            rnd = lambda j: els[j]["kind"] == "shape" and els[j].get("shape") in _ROUND  # noqa: E731
            dx = rb[0] + rb[2] / 2 - (ra[0] + ra[2] / 2)
            dy = rb[1] + rb[3] / 2 - (ra[1] + ra[3] / 2)
            x1, y1 = _edge(ra, rnd(a), dx, dy, 8 * k)
            x2, y2 = _edge(rb, rnd(b), -dx, -dy, 8 * k)
            bend = _clamp(float(e.get("curve", 0.0)), -1.0, 1.0)
            L = math.hypot(x2 - x1, y2 - y1)
            nx, ny = ((-(y2 - y1) / L, (x2 - x1) / L) if L else (0.0, 0.0))
            cx, cy = (x1 + x2) / 2 + nx * bend * L * 0.5, (y1 + y2) / 2 + ny * bend * L * 0.5
            pts = [((1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t * t * x2, (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t * t * y2)
                   for t in (j / N for j in range(N + 1))]
            out.append((i, {a, b}, pts))
        elif e["kind"] == "shape" and e.get("shape") == "line":
            x, y, w, h = rects[i]
            pts = [(x + w * j / N, y + h / 2) for j in range(N + 1)] if w >= h else [(x + w / 2, y + h * j / N) for j in range(N + 1)]
            out.append((i, set(), pts))
        elif e["kind"] == "shape" and e.get("shape") in ("ring", "arc"):
            x, y, w, _h = rects[i]
            r = max(0.0, w / 2 - float(e.get("strokeW", 4)) * k / 2)
            start = float(e.get("start", 0.0))
            sweep = 360.0 if e["shape"] == "ring" else _clamp(float(e.get("sweep", 360.0)), 0.0, 360.0)
            pts = [(x + w / 2 + r * math.sin(math.radians(start + sweep * j / N)), y + w / 2 - r * math.cos(math.radians(start + sweep * j / N)))
                   for j in range(N + 1)]
            out.append((i, set(), pts))
    return out


def path_crossings(block: dict, mblock: dict) -> list[str]:
    """Texts that a drawn connector / line / ring / arc runs through (padded manifest text boxes). Texts inside the
    path's own endpoint elements (a label in the card a connector reaches) are not crossings."""
    bbox = mblock["bbox"]
    layout, _ = _layout_of(block, bbox)
    rects = _px_rects(block, bbox, layout)
    hits = []
    for i, ends, pts in drawn_paths(block, bbox):
        own = [rects[j] for j in ends]
        for t in mblock.get("texts", []):
            b = t["bbox"]
            cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
            if any(r[0] <= cx <= r[0] + r[2] and r[1] <= cy <= r[1] + r[3] for r in own):
                continue
            x0, y0 = b["x"] - TEXT_PAD_PX, b["y"] - TEXT_PAD_PX
            x1, y1 = b["x"] + b["w"] + TEXT_PAD_PX, b["y"] + b["h"] + TEXT_PAD_PX
            if any(x0 <= px <= x1 and y0 <= py <= y1 for px, py in pts):
                hits.append(f"{block['elements'][i]['kind']} {block['elements'][i].get('id', i)} crosses {t['text']!r}")
    return hits


def ink_coverage(block: dict, mblock: dict, n: int = 60) -> float:
    """Share of the hero box that is drawn: manifest text extents, icons, filled shapes (circles as circles); rings and arcs
    count 35 % of the area they enclose. Lines and connectors are not coverage."""
    bbox = mblock["bbox"]
    layout, _ = _layout_of(block, bbox)
    rects = _px_rects(block, bbox, layout)
    grid = [[0.0] * n for _ in range(n)]
    cw, ch = bbox["w"] / n, bbox["h"] / n

    def mark(r, wgt, circle=False):
        gx0, gx1 = int(max(0, (r[0] - bbox["x"]) / cw)), int(min(n, math.ceil((r[0] + r[2] - bbox["x"]) / cw)))
        gy0, gy1 = int(max(0, (r[1] - bbox["y"]) / ch)), int(min(n, math.ceil((r[1] + r[3] - bbox["y"]) / ch)))
        cx, cy, rad = r[0] + r[2] / 2, r[1] + r[3] / 2, min(r[2], r[3]) / 2
        for gy in range(gy0, gy1):
            for gx in range(gx0, gx1):
                if circle:
                    px, py = bbox["x"] + (gx + 0.5) * cw, bbox["y"] + (gy + 0.5) * ch
                    if math.hypot(px - cx, py - cy) > rad:
                        continue
                grid[gy][gx] = max(grid[gy][gx], wgt)

    for e, r in zip(block["elements"], rects):
        if e["kind"] in ("icon", "logo", "media"):
            mark(r, 1.0)
        elif e["kind"] == "shape" and e.get("shape") in ("rect", "roundrect"):
            mark(r, 1.0)
        elif e["kind"] == "shape" and e.get("shape") == "circle":
            mark(r, 1.0, circle=True)
        elif e["kind"] == "shape" and e.get("shape") in ("ring", "arc"):
            mark(r, 0.35, circle=True)
    for t in mblock.get("texts", []):
        b = t["bbox"]
        mark((b["x"], b["y"], b["w"], b["h"]), 1.0)
    return round(sum(map(sum, grid)) / (n * n), 3)


def fill_score(cov: float) -> float:
    """0 at ≤ 12 % of the hero box drawn, 1 from 38 %, easing off above 75 % (crowded)."""
    if cov > 0.75:
        return round(max(0.6, 1 - (cov - 0.75) / 0.5), 3)
    return round(_clamp((cov - 0.12) / 0.26, 0.0, 1.0), 3)


def _sync_of(scene: dict) -> tuple[dict, list[str]]:
    from .rules import DESIGN_GAP, sync_report
    sy = sync_report({"scenes": [scene]})
    rec = sy["scenes"][0]
    reasons = []
    if sy["number_violations"]:
        reasons.append("number drawn before it is spoken: " + "; ".join(sy["number_violations"][:2]))
    if sy["gap_violations"]:
        reasons.append("narration without a visual event: " + "; ".join(sy["gap_violations"][:2]))
    score = round(1 - 0.5 * min(1.0, rec["max_gap_s"] / DESIGN_GAP), 3)
    return {"score": score, "max_gap_s": rec["max_gap_s"]}, reasons


def replace_hero(scene: dict, c: Content, block: dict) -> dict:
    out = copy.deepcopy(scene)
    out["blocks"] = [copy.deepcopy(block) if k == c.hero else b for k, b in enumerate(out["blocks"]) if k == c.hero or k not in c.absorbs]
    if out.get("layout") == "split":                  # a split made for the template's blocks no longer applies
        for k in ("layout", "splitAt", "splitRatio"):
            out.pop(k, None)
    return out


@dataclass
class Candidate:
    structure: str
    variant: str
    params: dict
    motion: str
    source: str = "generated"
    canvas: dict | None = None
    block: dict | None = None
    scene: dict | None = None
    rejected: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    total: float = 0.0

    @property
    def signature(self) -> str:
        return f"{self.structure}/{self.variant}/{self.motion}"

    def design(self) -> dict:
        return {"structure": self.structure, "variant": self.variant, "motion": self.motion, "signature": self.signature, "source": self.source}

    def summary(self) -> dict:
        return {"design": self.design(), "params": self.params, "canvas": self.canvas, "scores": self.scores,
                "total": round(self.total, 4), "rejected": self.rejected}


def _total(s: dict, bonus: float = 0.0) -> float:
    return round(sum(WEIGHTS[k] * s[k] for k in WEIGHTS) + bonus, 4)


_GEOM_KEYS = ("kind", "box", "wide", "text", "role", "shape", "fromId", "toId", "curve", "sweep", "start", "strokeW", "icon",
              "to", "from", "prefix", "suffix", "decimals", "grouping", "variant", "asset", "id")


def _geometry_key(block: dict) -> str:
    """Candidates that draw the same boxes (they differ only in motion / timing) share one layout measurement."""
    return json.dumps([block.get("canvas"), [{k: e.get(k) for k in _GEOM_KEYS} for e in block.get("elements", [])]], sort_keys=True)


def score_candidates(scene: dict, cands: list[Candidate], content: Content, *, labels: dict, brand_id: str,
                     fresh=None, used_structures: set | frozenset = frozenset(), template_id: str | None = None,
                     llm_pick: list[str] | None = None) -> dict:
    """Scores every candidate (fills .scores / .rejected / .total) and the template baseline. -> {"template": {...},
    "layout": "ok" | "unavailable"}"""
    ok_label = allowed_labels(labels, scene["narration"])
    for k, cd in enumerate(cands):
        cd.scene = replace_hero(scene, content, cd.block)
        cd.scene["id"] = f"k{k}"
        errs, _ = validate_storyboard({"scenes": [cd.scene]})
        if errs:
            cd.rejected.append("invalid: " + "; ".join(errs[:2]))
        bad = [e["text"] for e in cd.block["elements"] if e["kind"] == "text" and not ok_label(e["text"])]
        if bad:
            cd.rejected.append(f"invented label(s) {bad[:3]} (not a bound fact / copy string and not spoken)")
        if not errs:
            sy, why = _sync_of(cd.scene)
            cd.scores["sync"] = sy["score"]
            cd.scores["max_gap_s"] = sy["max_gap_s"]
            cd.rejected += why
        b, why, per = balance(cd.block)
        cd.scores["balance"] = b
        cd.scores["balance_detail"] = per
        cd.rejected += why
        pen = fresh.design_penalty(cd.signature, cd.structure) if fresh is not None else 0.0
        if cd.structure in used_structures:
            pen = min(1.0, pen + 0.5)
        cd.scores["freshness"] = round(1 - pen, 3)
    ref = copy.deepcopy(scene)
    ref["id"] = "ref"
    # layout: one manifest per format for the template scene + one scene per distinct layout (motion does not move boxes)
    groups: dict[str, list[Candidate]] = {}
    for cd in cands:
        if not cd.rejected:
            groups.setdefault(_geometry_key(cd.block), []).append(cd)
    lay_scenes = [ref] + [g[0].scene for g in groups.values()]
    lm = layout_metrics(lay_scenes, brand_id)
    tmpl_sync, _ = _sync_of(scene)
    tmpl = {"template": template_id, "hero": content.hero_type, "balance": TEMPLATE_BALANCE, "sync": tmpl_sync["score"],
            "max_gap_s": tmpl_sync["max_gap_s"],
            "freshness": round(1 - (fresh.template_penalty(template_id, content.hero_type) if fresh is not None and template_id else 0.0), 3)}
    if lm is None:
        for cd in cands:
            cd.rejected.append("layout manifest unavailable (node / esbuild): overflow cannot be verified")
        tmpl["legibility"] = 1.0
        tmpl["total"] = _total(tmpl)
        return {"template": tmpl, "layout": "unavailable"}
    items = [i.text for i in content.items]
    tmpl["legibility"] = _legibility({f: m["blocks"][content.hero] for f, m in lm.get("ref", {}).items() if content.hero < len(m["blocks"])}, items)
    tmpl["overflow"] = sorted({t for m in lm.get("ref", {}).values() for b in m["blocks"] for t in b["overflow"]})
    tmpl["total"] = _total(tmpl)
    for g in groups.values():
        sid = g[0].scene["id"]
        per_fmt = lm.get(sid, {})
        comp_idx = next(i for i, b in enumerate(g[0].scene["blocks"]) if b["type"] == "composition")
        over = sorted({t for m in per_fmt.values() for t in (m["blocks"][comp_idx]["overflow"] if comp_idx < len(m["blocks"]) else [])})
        other = sorted({t for m in per_fmt.values() for i, b in enumerate(m["blocks"]) if i != comp_idx for t in b["overflow"]})
        mblocks = {f: m["blocks"][comp_idx] for f, m in per_fmt.items() if comp_idx < len(m["blocks"])}
        leg = _legibility(mblocks, items)
        small = [f"{f} {label_px(mb):.0f} px < {MIN_LABEL_PX.get(f, 30):g}" for f, mb in mblocks.items()
                 if label_px(mb) is not None and label_px(mb) < MIN_LABEL_PX.get(f, 30.0)]
        cross = sorted({f"{h} ({f})" for f, mb in mblocks.items() for h in path_crossings(g[0].block, mb)})
        covs = {f: ink_coverage(g[0].block, mb) for f, mb in mblocks.items()}
        fill = round(sum(fill_score(c) for c in covs.values()) / max(1, len(covs)), 3)
        for cd in g:
            cd.scores["legibility"] = leg
            cd.scores["label_px"] = {f: label_px(mb) for f, mb in mblocks.items()}
            cd.scores["ink_coverage"] = covs
            cd.scores["arrangement"] = cd.scores["balance"]
            cd.scores["balance"] = round(0.5 * fill + 0.5 * cd.scores["arrangement"], 3)
            if small:
                cd.rejected.append(f"labels too small: {'; '.join(small)}")
            if cross:
                cd.rejected.append(f"a connector / line crosses text: {cross[:3]}")
            if over:
                cd.rejected.append(f"text overflow in the layout manifest: {over[:3]}")
            if other:
                cd.rejected.append(f"the scene's other blocks overflow next to it: {other[:2]}")
    for cd in cands:
        if "legibility" not in cd.scores:
            cd.scores["legibility"] = 0.0
        if "sync" not in cd.scores:
            cd.scores["sync"] = 0.0
        bonus = BONUS["library"] if cd.source.startswith("library:") else 0.0
        if llm_pick and cd.structure in llm_pick:
            bonus += BONUS["llm_first"] if cd.structure == llm_pick[0] else BONUS["llm"]
        cd.scores["bonus"] = round(bonus, 3)
        cd.total = _total(cd.scores, bonus)
    return {"template": tmpl, "layout": "ok"}


# ---- search ----------------------------------------------------------------------------------------------
def seed_for(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def canvas_for(scene: dict, c: Content) -> dict:
    support = len(scene["blocks"]) - len(c.absorbs) - 1
    return dict(CANVAS["with_support" if support > 0 else "alone"])


def candidates_for(c: Content, scene: dict, seed: int, library: list[dict] | tuple = ()) -> list[Candidate]:
    """The search space for one scene: structures × variants × seeded parameter sets × motion schemes (+ approved
    library designs that fit the content)."""
    rng = random.Random(seed)
    base = canvas_for(scene, c)
    canvases = [{k: round(min(3.0, v * f), 3) for k, v in base.items()} for f in CANVAS_SCALES]
    out: list[Candidate] = []
    for S in STRUCTURES.values():
        if c.kind not in S.fits or not S.items[0] <= len(c.items) <= S.items[1]:
            continue
        if S.id in ("orbit", "hero-number") and c.kind == "count" and not c.number:
            continue
        for v in S.variants:
            seen = []
            for _ in range(PARAM_SAMPLES):
                p = S.params(rng)
                if p in seen:
                    continue
                seen.append(p)
                for cv in canvases:
                    for m in MOTIONS:
                        out.append(Candidate(S.id, v, p, m, canvas=cv))
    for entry in library:
        d = entry.get("design", {})
        S = STRUCTURES.get(d.get("structure"))
        if not S or c.kind not in entry.get("fits", S.fits) or not S.items[0] <= len(c.items) <= S.items[1]:
            continue
        if d.get("variant") not in S.variants or d.get("motion") not in MOTIONS:
            continue
        own = entry.get("canvas") if isinstance(entry.get("canvas"), dict) and {"tall", "wide"} <= set(entry["canvas"]) else None
        for cv in ([own] if own else canvases):               # an approved design keeps the canvas it was approved with
            out.append(Candidate(S.id, d["variant"], dict(entry.get("params") or S.params(random.Random(seed))), d["motion"],
                                 source=f"library:{entry.get('name')}", canvas=dict(cv)))
    for cd in out:
        try:
            cd.block = build_block(c, cd.structure, cd.variant, cd.params, cd.motion, cd.canvas, seed, cd.source)
        except (ValueError, KeyError, ZeroDivisionError) as e:
            cd.rejected.append(f"structure failed to build: {e}")
            cd.block = {"type": "composition", "elements": [{"kind": "shape", "shape": "rect", "box": [0, 0, 1, 1]}]}
    return out


def llm_structures(provider, scene: dict, c: Content, options: list[str], log: list | None = None) -> list[str]:
    """Ask the local LLM which structures fit the scene idea (names only, from `options`). [] when unavailable."""
    if provider is None or not options:
        return []
    try:
        ok, why = provider.available()
        if not ok:
            (log or []).append({"event": "llm_unavailable", "task": "component_structure", "reason": why})
            return []
        schema = {"type": "object", "additionalProperties": False, "required": ["structures"],
                  "properties": {"structures": {"type": "array", "maxItems": 3, "items": {"type": "string", "enum": options}}}}
        desc = "\n".join(f"- {o}: {STRUCTURES[o].describe}" for o in options)
        msg = (f"A {scene.get('purpose')} scene of a product video. Narration: \"{scene['narration']}\". It shows {len(c.items)} "
               f"{c.kind} items: {', '.join(i.text for i in c.items)}.\nWhich of these graphic structures express this idea best? "
               f"Pick up to three, best first.\n{desc}\nJSON: {{\"structures\": [names]}}")
        r = provider.generate_json(system="You are a motion designer. You only choose a structure name from the list; you never "
                                          "write labels, numbers or layout. Return JSON only.",
                                   messages=[{"role": "user", "content": msg}], schema=schema, task="component_structure",
                                   context={"options": options}, temperature=0.2, seed=7, max_tokens=80)
        picks = [x for x in (r.data or {}).get("structures", []) if x in options] if isinstance(r.data, dict) else []
        (log if log is not None else []).append({"event": "component_structure", "picks": picks, "schema_errors": r.schema_errors[:3]})
        return list(dict.fromkeys(picks))[:3]
    except Exception as e:  # noqa: BLE001 - the model is optional; any failure means "no proposal"
        (log if log is not None else []).append({"event": "llm_error", "task": "component_structure", "error": str(e)[:200]})
        return []


@dataclass
class SearchResult:
    content: Content
    candidates: list[Candidate]
    template: dict
    layout: str
    llm: list[str]
    seed: int

    @property
    def ranked(self) -> list[Candidate]:
        ok = [c for c in self.candidates if not c.rejected]
        return sorted(ok, key=lambda c: (-c.total, c.signature, c.source, json.dumps([c.params, c.canvas], sort_keys=True)))

    @property
    def best(self) -> Candidate | None:
        r = self.ranked
        return r[0] if r else None

    def alternates(self, n: int = 3) -> list[Candidate]:
        out, seen = [], {self.best.structure} if self.best else set()
        for c in self.ranked[1:]:
            if c.structure not in seen:
                out.append(c)
                seen.add(c.structure)
            if len(out) >= n:
                break
        return out

    def rejected_counts(self) -> dict:
        out: dict[str, int] = {}
        for c in self.candidates:
            for r in c.rejected:
                k = r.split(":")[0].split(" (")[0]
                out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))


def search(scene: dict, c: Content, *, labels: dict, brand_id: str, seed: int, fresh=None, used_structures=frozenset(),
           template_id: str | None = None, library=(), provider=None, log: list | None = None) -> SearchResult:
    cands = candidates_for(c, scene, seed, library)
    options = sorted({cd.structure for cd in cands})
    picks = llm_structures(provider, scene, c, options, log)
    info = score_candidates(scene, cands, c, labels=labels, brand_id=brand_id, fresh=fresh, used_structures=used_structures,
                            template_id=template_id, llm_pick=picks)
    return SearchResult(c, cands, info["template"], info["layout"], picks, seed)


def apply_recipe(scene: dict, recipe: dict) -> dict:
    """Rebuild a chosen design on the scene's CURRENT content (the copy may have changed since the search) and put it
    in place of the template hero. Deterministic; returns the scene unchanged if its hero no longer has structure."""
    c = content_of(scene)
    if c is None:
        return scene
    blk = build_block(c, recipe["structure"], recipe["variant"], recipe["params"], recipe["motion"], recipe["canvas"], recipe["seed"],
                      recipe.get("source", "generated"))
    blk["design"]["component"] = recipe["id"]
    return replace_hero(scene, c, blk)


def component_id(*parts) -> str:
    return "cmp-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]


# ---- concept-level integration -------------------------------------------------------------------------
def _concept_rules(concept: dict, st, copies: dict) -> tuple[list[dict], dict]:
    from .claims_v2 import verify
    from .director import compose
    from .rules import check_rules, layout_overflows
    sb, ctx, _ = compose(concept, st, copies)
    claims = verify(sb, st.fb, st.tb)
    rules = check_rules(sb, pf=st.pf, claims=claims, labels=ctx.labels, brief=st.brief,
                        layout=layout_overflows(sb, st.brand.id, st.brief.get("format", "short")))
    return rules, sb


def generate_components(concept: dict, st, copies: dict, log: list | None = None) -> list[dict]:
    """Search a generated component for every suitable scene of a planned concept; replace the template hero where the
    best candidate scores at least as well as the template, keep only replacements under which the whole concept still
    passes every rule. Mutates concept (scene_plan[*].component, components, freshness, rules, ...). -> final rules."""
    from .director import compose
    from .rules import failed
    log = log if log is not None else getattr(st, "component_log", None)
    sb, ctx, _ = compose(concept, st, copies)
    fresh = getattr(st, "fresh", None)
    library = getattr(st, "library", ()) or ()
    used: set[str] = set()
    records: list[dict] = []
    cache = getattr(st, "component_cache", None)
    for k, sp in enumerate(concept["scene_plan"]):
        if sp["role"] not in SUITABLE_ROLES:
            continue
        sc = sb["scenes"][k]
        c = content_of(sc)
        if c is None:
            continue
        seed = seed_for(st.brand.id, st.pf.family, sp["template"], c.key(), len(fresh.productions) if fresh else 0)
        ck = (sp["template"], c.key(), tuple(sorted(used)), sc["narration"])
        res = cache.get(ck) if cache is not None else None
        if res is None:
            res = search(sc, c, labels=ctx.labels, brand_id=st.brand.id, seed=seed, fresh=fresh, used_structures=frozenset(used),
                         template_id=sp["template"], library=library, provider=getattr(st, "provider", None), log=log)
            if cache is not None:
                cache[ck] = res
        best = res.best
        prev_generated = k > 0 and any(r["selected"] and r["scene"] == concept["scene_plan"][k - 1]["scene"] for r in records)
        rec = {"concept": concept["id"], "blueprint": concept["blueprint"], "scene": sp["scene"], "role": sp["role"],
               "template": sp["template"], "replaces": c.hero_type, "content": {"kind": c.kind, "items": len(c.items)},
               "searched": len(res.candidates), "rejected": res.rejected_counts(), "template_score": res.template,
               "layout_check": res.layout, "llm_structures": res.llm, "seed": seed, "selected": False}
        if best is None:
            rec["reason"] = "no candidate passed the rules"
            records.append(rec)
            continue
        recipe = {"structure": best.structure, "variant": best.variant, "params": best.params, "motion": best.motion,
                  "canvas": best.block["canvas"], "seed": seed, "source": best.source}
        recipe["id"] = component_id(st.brand.id, concept["blueprint"], sp["template"], c.key(), recipe)
        rec.update({"id": recipe["id"], "design": best.design(), "params": best.params, "canvas": best.block["canvas"],
                    "scores": {**best.scores, "total": best.total}, "block": best.block,
                    "alternates": [a.summary() for a in res.alternates()], "recipe": recipe})
        if prev_generated:                      # two generated graphics in a row would repeat the hero type
            rec["reason"] = "template kept: the previous scene is already a generated graphic (no-repeat-hero)"
        elif best.total >= res.template["total"]:
            sp["component"] = recipe
            rec["selected"] = True
            rec["reason"] = f"scores {best.total:.3f} ≥ template {res.template['total']:.3f}"
            used.add(best.structure)
        else:
            rec["reason"] = f"template kept: {res.template['total']:.3f} > best generated {best.total:.3f}"
        records.append(rec)
    rules, final = _concept_rules(concept, st, copies)
    chosen = [r for r in records if r["selected"]]
    def drop(r, why):
        next(x for x in concept["scene_plan"] if x["scene"] == r["scene"]).pop("component", None)
        r["selected"], r["reason"] = False, "reverted: the concept failed " + why

    while failed(rules) and chosen:              # never trade a passing concept for a new graphic
        why = ", ".join(x["id"] for x in failed(rules))
        for r in reversed(chosen):               # first try undoing one replacement at a time (newest first)
            sp = next(x for x in concept["scene_plan"] if x["scene"] == r["scene"])
            keep = sp.pop("component")
            trial, trial_sb = _concept_rules(concept, st, copies)
            if not failed(trial):
                chosen.remove(r)
                drop(r, why)
                rules, final = trial, trial_sb
                break
            sp["component"] = keep
        else:
            drop(chosen.pop(), why)
            rules, final = _concept_rules(concept, st, copies)
    concept["components"] = records
    concept["rules"] = rules
    concept["block_types"] = sorted({b["type"] for s in final["scenes"] for b in s["blocks"]})
    gen = [r["scene"] for r in records if r["selected"]]
    concept["visual_approach"]["generated"] = gen
    concept["visual_approach"]["hero_blocks"] = ["composition" if sp["scene"] in gen else h
                                                 for sp, h in zip(concept["scene_plan"], concept["visual_approach"]["hero_blocks"])]
    if fresh is not None:
        concept["freshness"] = fresh.concept_report(concept)
    return rules
