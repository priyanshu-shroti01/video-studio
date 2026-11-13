"""Composition, fact and sync rules for creative storyboards. Each rule returns pass/fail with a detail, so the
director can reject a template sequence and the report can show exactly why.

Field requirements for the v2b blocks / scene backdrop are mirrored here (spec in src/engine/types.ts) so the
creative engine does not depend on pipeline.storyboard being extended."""
from __future__ import annotations

import re

from ..contract import BLOCK_TYPES, ICONS, TIME_KEYS, TONES
from ..storyboard import EXPR, REQUIRED as SB_REQUIRED, Resolver, SceneTiming, resolve_block, validate_storyboard, word_matches
from ..timeline import estimated_timing
from ..timing import Word, norm, tokenize
from .copybank import word_count

WPS, SCENE_GAP, PAD = 2.33, 0.2, 0.5   # WPS measured on the local voice (see anchors.WPS)
DURATION = (30.0, 35.0)
SCENES = (5, 7)
MIN_TYPES, MIN_NEW, MIN_BLOCKS_AVG = 6, 3, 1.8
MAX_SILENT_GAP, MAX_NUMBER_LEAD = 2.5, 0.3
DESIGN_GAP = 2.4      # on ESTIMATED timings, now calibrated to the real voice (anchors.WPS); margin under the 2.5 s QA limit
BACKDROPS = {"glow", "spotlight", "grid", "split", "light", "deep"}
NEW_BLOCKS = {"kinetic-text", "counter", "price-compare", "terminal", "dashboard", "device", "image", "progress", "scroll-demo",
              "chart", "feature-compare", "logo-sting", "outro", "plan-card", "install-flow", "server-stack", "footage",
              "composition"}
V2B = {"plan-card", "install-flow", "server-stack"}
TEXT_ONLY = {"headline", "text", "pill"}
HERO = {"browser", "bars", "compare-rows", "plans", "domain-input", "hook-tag", "flat-line", "price", "logo", "cta", "counter",
        "price-compare", "terminal", "dashboard", "device", "image", "progress", "scroll-demo", "chart", "feature-compare",
        "logo-sting", "outro", "plan-card", "install-flow", "server-stack", "kinetic-text", "checklist", "footage", "composition"}
DEMO = {"install-flow", "domain-input", "dashboard", "scroll-demo", "device", "footage"}
PRICING = {"plan-card", "price-compare", "plans", "price", "counter", "flat-line"}
NON_LABEL_KEYS = {"type", "icon", "tone", "variant", "kind", "size", "align", "frame", "fit", "reveal", "grouping", "prompt", "id",
                  "currency", "period", "suffix", "prefix", "emphasis", "typeAt", "appIcon", "asset",
                  # composition element styling / wiring / provenance (never drawn as text)
                  "role", "shape", "motion", "fill", "stroke", "color", "fromId", "toId", "design"} | TIME_KEYS
# v1 required fields (pipeline.intelligence.storyboard_gen.REQUIRED) + contract v2/v2b
REQUIRED = {"headline": ["size", "words"], "text": ["text", "size"], "pill": ["text", "tone"], "price": ["amount"],
            "checklist": ["items"], "bars": ["title", "bars"], "compare-rows": ["rows"], "plans": ["plans"],
            "domain-input": ["title", "domain", "typeAt", "availableText", "button"], "browser": ["url", "loadUntil"],
            "hook-tag": ["label", "text"], "flat-line": ["title", "points", "drawEnd"], "cta": ["text", "url", "urlAt"], "logo": [],
            **SB_REQUIRED,
            "plan-card": ["name", "price", "features"], "install-flow": ["app", "steps", "doneAt", "doneText"], "server-stack": ["nodes"]}


def estimate_seconds(sb: dict) -> float:
    """Estimated VIDEO length: the preview's timing model (calibrated on the local voice: punctuation pauses,
    scene gaps, holdAfter) plus the 0.7 s end tail the renderer adds."""
    from ..timeline import estimated_timing
    return round(estimated_timing(sb, wps=WPS, gap=SCENE_GAP)["duration"] + 0.7, 1)


def hero_of(scene: dict) -> str | None:
    """The scene's hero block: first non-text block (kinetic-text only if nothing else)."""
    types = [b["type"] for b in scene["blocks"]]
    for t in types:
        if t in HERO and t != "kinetic-text" and t not in ("checklist",):
            return t
    for t in types:
        if t in HERO:
            return t
    return None


# ---- field mirror ------------------------------------------------------------------------------------
def _is_time(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) or (isinstance(v, str) and bool(EXPR.match(v)))


def validate_fields(sb: dict) -> list[str]:
    errs = []
    for si, sc in enumerate(sb.get("scenes", [])):
        p = f"scenes[{si}]({sc.get('id')})"
        if "backdrop" in sc and sc["backdrop"] not in BACKDROPS:
            errs.append(f"{p}: backdrop {sc['backdrop']!r} not in {sorted(BACKDROPS)}")
        for bi, b in enumerate(sc.get("blocks", [])):
            bp, ty = f"{p}.blocks[{bi}]", b.get("type")
            if ty not in BLOCK_TYPES | V2B:
                errs.append(f"{bp}: unknown block type {ty!r}"); continue
            for k in REQUIRED.get(ty, []):
                if k not in b:
                    errs.append(f"{bp}: {ty} needs '{k}'")
            if ty == "plan-card":
                if not isinstance(b.get("price"), (int, float)) or isinstance(b.get("price"), bool):
                    errs.append(f"{bp}: plan-card price must be a number")
                if not isinstance(b.get("name"), str):
                    errs.append(f"{bp}: plan-card name must be a string")
                if not b.get("features") or any(not isinstance(f, dict) or "text" not in f or not _is_time(f.get("at")) for f in b["features"]):
                    errs.append(f"{bp}: plan-card features need [{{text, at}}]")
                if b.get("variant") not in (None, "light", "dark"):
                    errs.append(f"{bp}: plan-card variant must be light or dark")
            if ty == "install-flow":
                if not b.get("steps") or any("label" not in s or not _is_time(s.get("at")) for s in b["steps"]):
                    errs.append(f"{bp}: install-flow steps need [{{label, at}}]")
                if "doneAt" in b and not _is_time(b["doneAt"]):
                    errs.append(f"{bp}: install-flow doneAt must be a time")
            if ty == "server-stack":
                n = b.get("nodes") or []
                if not 2 <= len(n) <= 4 or any("label" not in x or not _is_time(x.get("at")) for x in n):
                    errs.append(f"{bp}: server-stack needs 2–4 nodes [{{label, at}}]")
                st = b.get("status")
                if st is not None and ("text" not in st or not _is_time(st.get("at")) or st.get("tone", "success") not in TONES):
                    errs.append(f"{bp}: server-stack status needs {{text, at, tone?}}")
            if ty == "domain-input" and "button" in b:
                miss = [k for k in ("idle", "busy", "done", "clickAt", "doneAt") if k not in b["button"]]
                if miss:
                    errs.append(f"{bp}: domain-input button missing {miss}")
            if ty == "checklist" and any("text" not in it or "at" not in it for it in b.get("items", [])):
                errs.append(f"{bp}: checklist items need text + at")
            for icon in _find(b, "icon"):
                if icon not in ICONS:
                    errs.append(f"{bp}: unknown icon {icon!r}")
    return errs


def _find(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key and isinstance(v, str):
                yield v
            else:
                yield from _find(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _find(v, key)


def _times(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if (k in TIME_KEYS or k == "typeAt") and isinstance(v, (int, float, str)):
                yield f"{path}.{k}", v
            elif isinstance(v, (dict, list)):
                yield from _times(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _times(v, f"{path}[{i}]")


def _strings(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in NON_LABEL_KEYS:
                continue
            if isinstance(v, str):
                yield f"{path}.{k}", v
            elif isinstance(v, (dict, list)):
                yield from _strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str):
                yield f"{path}[{i}]", v
            else:
                yield from _strings(v, f"{path}[{i}]")


# ---- sync (estimated timings, the same estimate the preview stills use) -----------------------------------
def _resolved(sb: dict) -> list[tuple[dict, SceneTiming, list[dict]]]:
    tm = estimated_timing(sb)
    words = [Word(w["text"], w["start"], w["end"]) for w in tm["words"]]
    spans = tm["scene_spans"]
    starts = [0.0] + [max(spans[k - 1][1] + 0.05, spans[k][0] - 0.15) for k in range(1, len(spans))]
    ends = starts[1:] + [tm["duration"] + 0.7]
    out = []
    for k, sc in enumerate(sb["scenes"]):
        sw = [w for w in words if spans[k][0] - 1e-3 <= w.start <= spans[k][1] + 1e-3]
        st = SceneTiming(sc["id"], round(starts[k], 3), round(ends[k], 3), spans[k][0], spans[k][1], sw)
        R = Resolver(st, sc.get("cues", {}))
        out.append((sc, st, [resolve_block(b, R, i, 30) for i, b in enumerate(sc["blocks"])]))
    return out


INTERVAL_ENDS = ("countEnd", "scrollEnd", "growEnd", "drawEnd", "typeEnd")


def _events(o, out_pts: list, out_iv: list):
    if isinstance(o, dict):
        if isinstance(o.get("at"), (int, float)):
            for e in INTERVAL_ENDS:
                if isinstance(o.get(e), (int, float)):
                    out_iv.append((o["at"], o[e]))
        if o.get("type") == "counter" and isinstance(o.get("at"), (int, float)) and "countEnd" not in o:
            out_iv.append((o["at"], o["at"] + 0.8))
        for k, v in o.items():
            if k in TIME_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                out_pts.append(float(v))
            elif k == "keyTimes" and isinstance(v, list):
                out_pts += [float(x) for x in v]
            elif isinstance(v, (dict, list)):
                _events(v, out_pts, out_iv)
    elif isinstance(o, list):
        for v in o:
            _events(v, out_pts, out_iv)


RE_DISPLAY_NUM = re.compile(r"(?<![A-Za-z\d.])\d[\d,]*(?:\.\d+)?")


def _shown_numbers(o, t_at, out: list, path=""):
    """(number, appear time, path) for every number drawn by a resolved block element."""
    if isinstance(o, dict):
        t = o["at"] if isinstance(o.get("at"), (int, float)) else t_at
        for k, v in o.items():
            if k in NON_LABEL_KEYS and k not in ("prefix", "suffix"):
                continue
            if k in ("price", "to") and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append((float(v), t, f"{path}.{k}"))
            elif isinstance(v, str):
                for m in RE_DISPLAY_NUM.finditer(v):
                    out.append((float(m.group(0).replace(",", "")), t, f"{path}.{k}"))
            elif isinstance(v, (dict, list)):
                _shown_numbers(v, t, out, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str):
                for m in RE_DISPLAY_NUM.finditer(v):
                    out.append((float(m.group(0).replace(",", "")), t_at, f"{path}[{i}]"))
            else:
                _shown_numbers(v, t_at, out, f"{path}[{i}]")


def _spoken_time(words: list[Word], n: float) -> float | None:
    s = str(int(n)) if float(n).is_integer() else str(n)
    for w in words:
        if word_matches(w.text, s) or norm(w.text.replace(",", "")) == norm(s):
            return w.start
    return None


def _first_visible(b: dict) -> float | None:
    """When a block first draws something. A checklist draws nothing until its first item lands."""
    if not isinstance(b.get("at"), (int, float)):
        return None
    if b.get("type") == "checklist":
        its = [i["at"] for i in b.get("items", []) if isinstance(i.get("at"), (int, float))]
        return max(b["at"], min(its)) if its else b["at"]
    return b["at"]


MAX_EMPTY_OPEN = 0.6     # s: beyond this a scene that shows only its backdrop is reported (WARN)
FAIL_EMPTY_OPEN = 2.0    # s: beyond this it is rejected (QA's black-frame check is the backstop for dark backdrops)


def sync_report(sb: dict) -> dict:
    """Per scene: largest narration stretch without a visual event, and numbers drawn > 0.3 s before spoken."""
    scenes, gaps_bad, early, empty_open = [], [], [], []
    for sc, st, blocks in _resolved(sb):
        pts, iv = [], []
        for b in blocks:
            _events(b, pts, iv)
        s0, s1 = st.speech_start, st.speech_end
        cover = sorted([(p, p) for p in pts] + iv)
        cur, worst, worst_at = s0, 0.0, s0
        for a, b in cover:
            if a > cur:
                g = min(a, s1) - cur
                if g > worst:
                    worst, worst_at = g, cur
            cur = max(cur, b)
            if cur >= s1:
                break
        if cur < s1 and s1 - cur > worst:
            worst, worst_at = s1 - cur, cur
        nums = []
        for b in blocks:
            _shown_numbers(b, b.get("at", st.start), nums, f"{b['type']}")
        bad_nums = []
        for n, t, path in nums:
            if n < 2:
                continue
            ts = _spoken_time(st.words, n)
            if ts is not None and t < ts - MAX_NUMBER_LEAD:
                bad_nums.append({"number": n, "shown_at": round(t, 2), "spoken_at": round(ts, 2), "lead_s": round(ts - t, 2), "where": path})
        ats = [t for t in (_first_visible(b) for b in blocks) if t is not None]
        opens = round(max(0.0, min(ats) - st.start), 2) if ats else round(st.end - st.start, 2)
        rec = {"scene": sc["id"], "speech": [round(s0, 2), round(s1, 2)], "events": len(pts), "max_gap_s": round(worst, 2),
               "max_gap_from": round(worst_at, 2), "early_numbers": bad_nums, "opens_empty_s": opens}
        if opens > MAX_EMPTY_OPEN:
            empty_open.append(rec)
        scenes.append(rec)
        if worst > DESIGN_GAP:
            gaps_bad.append(rec)
        early += [{"scene": sc["id"], **x} for x in bad_nums]
    return {"scenes": scenes, "gap_violations": [f"{r['scene']}: {r['max_gap_s']} s without a visual event from {r['max_gap_from']} s"
                                                 for r in gaps_bad],
            "number_violations": [f"{e['scene']}: {e['number']:g} drawn {e['lead_s']} s before it is spoken ({e['where']})" for e in early],
            "open_violations": [f"{r['scene']}: nothing on screen for the first {r['opens_empty_s']} s" for r in empty_open]}


# ---- the rules ---------------------------------------------------------------------------------------
def _rule(rid: str, desc: str, ok: bool, detail="") -> dict:
    return {"id": rid, "rule": desc, "status": "PASS" if ok else "FAIL", "detail": detail}


def layout_overflows(sb: dict, brand_id: str, fmt: str = "short") -> list[dict] | None:
    """Text overflow from the engine's own layout manifest (scripts/engine-layout.mjs, ~0.3 s, no browser).
    None when the manifest tool is unavailable (node / esbuild missing)."""
    try:
        from ..config import deep_merge, load_preset, load_theme
        from ..layout_fit import _overflows
        cfg = deep_merge(load_preset("shorts" if fmt == "short" else "landscape"),
                         {"name": "layout-check", "preset": "shorts" if fmt == "short" else "landscape", "formats": [fmt],
                          "brand": brand_id, "storyboard": sb, "audio": {"music": None}})
        cfg["theme"] = load_theme(brand_id)
        return _overflows(cfg)
    except Exception:  # noqa: BLE001 - an unavailable tool is reported as SKIP, never as a pass
        return None


SHORTS_MAX = 175.0     # vertical films stay YouTube Shorts (< 3 min) even with a flexible duration


def windows(brief: dict | None) -> tuple[tuple[float, float], tuple[int, int]]:
    """(duration window s, scene-count window) for a brief. A 33 s brief keeps the classic 30–35 s / 5–7 scenes.
    `duration_flexible: true` lets the story set the length (from half the target up to the Shorts limit)."""
    d = float((brief or {}).get("duration_seconds") or 33)
    if (brief or {}).get("duration_flexible"):
        return (max(15.0, round(d * 0.5, 1)), SHORTS_MAX), (5, 16)   # long walkthroughs: up to 16 scenes
    if d <= 40:                                    # Shorts: the classic window, unchanged
        return DURATION, SCENES
    return (round(d * 0.91, 1), round(d * 1.06, 1)), (5, max(SCENES[1], round(d / 9)))


def check_rules(sb: dict, *, pf=None, claims: dict | None = None, labels: dict | None = None, sync: dict | None = None,
                layout: list | None | bool = False, brief: dict | None = None) -> list[dict]:
    sc = sb["scenes"]
    (d_lo, d_hi), (s_lo, s_hi) = windows(brief) if brief is not None else (DURATION, SCENES)
    R = []
    errs, _w = validate_storyboard(sb)
    ferrs = validate_fields(sb)
    R.append(_rule("valid", "passes validate_storyboard + v2b field mirror", not errs and not ferrs, "; ".join((errs + ferrs)[:6])))
    R.append(_rule("scenes", f"{s_lo}–{s_hi} scenes", s_lo <= len(sc) <= s_hi, f"{len(sc)} scenes"))
    est = estimate_seconds(sb)
    R.append(_rule("duration", f"estimated {d_lo:g}–{d_hi:g} s at {WPS} words/s", d_lo <= est <= d_hi, f"{est} s"))
    nohero = [s["id"] for s in sc if not any(b["type"] in HERO for b in s["blocks"])]
    R.append(_rule("hero-every-scene", "every scene has a hero visual (never only headline/text/pill)", not nohero,
                   f"no hero: {nohero}" if nohero else ""))
    textled = [s["id"] for s in sc if hero_of(s) == "kinetic-text"]
    R.append(_rule("text-led", "at most one kinetic-type-led scene", len(textled) <= 1, f"{textled}"))
    avg = sum(len(s["blocks"]) for s in sc) / max(1, len(sc))
    R.append(_rule("density", f"≥ {MIN_BLOCKS_AVG} blocks per scene on average", avg >= MIN_BLOCKS_AVG, f"{avg:.2f}"))
    types = {b["type"] for s in sc for b in s["blocks"]}
    R.append(_rule("variety", f"≥ {MIN_TYPES} distinct block types", len(types) >= MIN_TYPES, f"{len(types)}: {sorted(types)}"))
    new = types & NEW_BLOCKS
    R.append(_rule("new-blocks", f"≥ {MIN_NEW} contract-v2/v2b block types", len(new) >= MIN_NEW, f"{sorted(new)}"))
    heroes = [hero_of(s) for s in sc]
    rep = [f"{sc[i]['id']}→{sc[i + 1]['id']} ({heroes[i]})" for i in range(len(sc) - 1) if heroes[i] == heroes[i + 1]]
    R.append(_rule("no-repeat-hero", "no two consecutive scenes with the same hero block", not rep, "; ".join(rep)))
    bds = [s.get("backdrop") for s in sc]
    repb = [f"{sc[i]['id']}→{sc[i + 1]['id']} ({bds[i]})" for i in range(len(sc) - 1) if bds[i] == bds[i + 1]]
    R.append(_rule("no-repeat-backdrop", "every scene has a backdrop; no two consecutive scenes share one",
                   not repb and all(bds), "; ".join(repb) or ("missing backdrop" if not all(bds) else "")))
    demo = [s["id"] for s in sc if s["purpose"] in ("journey", "point", "example") and any(b["type"] in DEMO for b in s["blocks"])]
    R.append(_rule("product-demo", "a real product demonstration (install-flow / domain-input / dashboard / scroll-demo / device / "
                                   "footage; a loading browser does not count)", bool(demo), f"{demo}"))
    pricing = [s["id"] for s in sc if any(b["type"] in ("plan-card", "price", "plans", "price-compare")
                                          or (b["type"] in PRICING and re.search(r"[₹$€£]\s?\d|'prefix': '[₹$€£]'", str(b)))
                                          for b in s["blocks"])]
    price_bad = []
    if claims:
        price_bad = [c["text"] for c in claims["claims"] if c["kind"] == "price" and c["status"] != "VERIFIED"]
    if pf is not None and getattr(pf, "featured", None) is None:      # unpriced product (pack.priced = False)
        R.append(_rule("pricing", "no price shown for an unpriced product, and any price on screen is verified",
                       not pricing and not price_bad, f"unexpected pricing scenes {pricing}" if pricing else "not applicable"))
    else:
        R.append(_rule("pricing", "an explicit pricing scene whose prices are all verified", bool(pricing) and not price_bad,
                       f"pricing scenes {pricing}" + (f"; unverified {price_bad}" if price_bad else "")))
    if claims is not None:
        nr = [f"{c['text']!r} ({c['scope']})" for c in claims["needs_review"]]
        R.append(_rule("claims", "every claim in narration and on screen is verified against the fact base", not nr, "; ".join(nr[:6])))
    if labels is not None:
        narr = {s["id"]: norm(s["narration"]) for s in sc}
        bad = []
        for s in sc:
            for j, b in enumerate(s["blocks"]):
                for path, text in _strings(b):
                    if text in labels:
                        continue
                    if b["type"] in ("kinetic-text", "headline") and path == ".words" and norm(text) in narr[s["id"]]:
                        continue
                    bad.append(f"{s['id']}.{b['type']}{path}={text!r}")
        R.append(_rule("labels-bound", "every on-screen label comes from a template constant, a verified fact, the brief CTA "
                                       "or is spoken in the scene", not bad, "; ".join(bad[:6])))
    if pf is not None and pf.mismatch:
        amt = float(pf.mismatch["brief_amount"])
        hits = []
        for s in sc:
            nums = re.findall(r"\d[\d,]*(?:\.\d+)?", s["narration"] + " " + str(s["blocks"]))
            if any(float(x.replace(",", "")) == amt for x in nums):
                hits.append(s["id"])
        R.append(_rule("brief-price-not-rendered", f"the unverified brief price ({pf.mismatch['brief_price']}) is not rendered",
                       not hits, f"{hits}"))
    if pf is not None:
        ren = [s["id"] for s in sc if re.search(r"renew|hike|increase", (s["narration"] + str(s["blocks"])).lower())]
        R.append(_rule("renewal-backed", "renewal statements only with an explicit renewal fact", not ren or pf.allow.get("renewal", False), f"{ren}"))
    last = sc[-1]
    cta_ok = last["purpose"] == "cta" and any(b["type"] in ("outro", "cta") and (pf is None or b.get("url") in (pf.domain, getattr(pf, "display_url", "") or pf.domain))
                                              for b in last["blocks"])
    R.append(_rule("cta-last", "last scene is the CTA with the brand URL", cta_ok))
    unanchored = []
    for s in sc:
        for j, b in enumerate(s["blocks"]):
            if "at" not in b:
                unanchored.append(f"{s['id']}.{b['type']}: no at")
            for path, v in _times(b):
                if not (isinstance(v, str) and v.startswith("@word:")):
                    unanchored.append(f"{s['id']}.{b['type']}{path}={v!r}")
    R.append(_rule("beats-on-words", "every visual beat is anchored to a spoken word (never the scene start)", not unanchored,
                   "; ".join(unanchored[:6])))
    if layout is not False:
        if layout is None:
            R.append({"id": "layout-fit", "rule": "no text overflow in the engine layout manifest", "status": "SKIP",
                      "detail": "layout manifest tool unavailable (node/esbuild)"})
        else:
            R.append(_rule("layout-fit", "no text overflow in the engine layout manifest", not layout,
                           "; ".join(f"{o['scene']}.{o['type']} {o['text'][:28]!r} {o['estWidth']}>{o['maxWidth']}px" for o in layout[:4])))
    if not errs:
        sy = sync or sync_report(sb)
        R.append(_rule("sync-gaps", f"≤ {DESIGN_GAP} s (estimated; QA limit {MAX_SILENT_GAP} s) of narration without a visual event", not sy["gap_violations"],
                       "; ".join(sy["gap_violations"][:4])))
        ov = sy.get("open_violations") or []
        worst_open = max((r["opens_empty_s"] for r in sy["scenes"]), default=0.0)
        rule = _rule("scene-opens", f"every scene shows content within {MAX_EMPTY_OPEN} s of its start "
                                    f"(rejected beyond {FAIL_EMPTY_OPEN} s)", worst_open <= FAIL_EMPTY_OPEN, "; ".join(ov[:4]))
        if rule["status"] == "PASS" and ov:
            rule["status"] = "WARN"
        R.append(rule)
        R.append(_rule("sync-numbers", f"no number drawn > {MAX_NUMBER_LEAD} s before it is spoken", not sy["number_violations"],
                       "; ".join(sy["number_violations"][:4])))
    return R


def failed(rules: list[dict]) -> list[dict]:
    return [r for r in rules if r["status"] == "FAIL"]


def tokens_of(text: str) -> list[str]:
    return tokenize(text)
