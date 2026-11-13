"""Pure timeline construction: (resolved config, voice timing) -> RenderProps per format, caption pages,
SFX cues and the resolved storyboard. No file I/O, so the runner (real TTS timings) and the storyboard
preview (estimated timings) build *identical* props from the same code."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import captions as C
from .contract import CONTRACT_VERSION, FORMATS
from .errors import PipelineError
from .storyboard import Resolver, SceneTiming, auto_sfx, resolve_block
from .timing import Word, tokenize

FPS = 30


@dataclass
class Timeline:
    duration: float
    frames: int
    fps: int
    words: list[Word]
    pages: list
    resolved: list[dict]
    sfx: list[dict]
    brand_bar: dict | None
    props: dict[str, dict]
    ass: dict[str, str]
    srt: str
    storyboard_out: dict
    max_cps: float
    warnings: list[str] = field(default_factory=list)


def caption_cfg(cfg: dict, fmt: str) -> dict:
    cc = dict(cfg["captions"])
    if fmt == "landscape" and "landscape" in cfg.get("captionsByFormat", {}):
        cc.update(cfg["captionsByFormat"]["landscape"])
    return cc


def watermark_props(cfg: dict) -> dict | None:
    """Brand profile watermark (overridable per project via `branding.watermark`)."""
    wm = {**cfg.get("brandProfile", {}).get("watermark", {}), **cfg.get("branding", {}).get("watermark", {})}
    if wm.get("policy", "none") == "none":
        return None
    out = {"policy": wm["policy"], "opacity": float(wm.get("opacity", 0.85)),
           "position": wm.get("position", "top-right"), "widthFrac": float(wm.get("widthFrac", 0.07)),
           "marginFrac": float(wm.get("marginFrac", 0.04)), "variant": wm.get("variant", "mark")}
    if wm.get("asset"):
        out["asset"] = wm["asset"]
    return out


def build_timeline(cfg: dict, tm: dict) -> Timeline:
    warnings: list[str] = []
    words = [Word(w["text"], w["start"], w["end"], w.get("interpolated", False)) for w in tm["words"]]
    tail = cfg["audio"].get("tail", 0.7)
    frames = round(round(tm["duration"] + tail, 3) * FPS)
    duration = frames / FPS
    spans = tm["scene_spans"]
    scenes_sb = cfg["storyboard"]["scenes"]
    starts = [0.0] + [max(spans[k - 1][1] + 0.05, spans[k][0] - 0.15) for k in range(1, len(spans))]
    ends = starts[1:] + [duration]
    resolved, sfx = [], []
    for k, sc in enumerate(scenes_sb):
        sw = [w for w in words if spans[k][0] - 1e-3 <= w.start <= spans[k][1] + 1e-3]
        st = SceneTiming(sc["id"], round(starts[k], 3), round(ends[k], 3), spans[k][0], spans[k][1], sw)
        Rz = Resolver(st, sc.get("cues", {}))
        blocks = [resolve_block(b, Rz, i, FPS) for i, b in enumerate(sc["blocks"])]
        for b in blocks:
            for key in ("at", "exitAt"):
                if key in b and not (st.start - 0.2 <= b[key] <= st.end + 0.01):
                    warnings.append(f"scene {sc['id']}: block {b['type']} {key}={b[key]} outside scene [{st.start}, {st.end}]")
        scene = {"id": sc["id"], "purpose": sc["purpose"], "start": st.start, "end": st.end,
                 "transition": sc.get("transition", "fade"), "layout": sc.get("layout", "stack"),
                 **({"splitAt": sc["splitAt"]} if "splitAt" in sc else {}),
                 **({"splitRatio": sc["splitRatio"]} if "splitRatio" in sc else {}),
                 "mood": sc.get("mood", "neutral"), "blocks": blocks}
        for opt in ("camera", "motion", "backdrop"):           # contract v2 scene options
            if opt in sc:
                scene[opt] = sc[opt]
        resolved.append(scene)
        if cfg["audio"].get("autoSfx", True) and sc.get("autoSfx", True):
            sfx += auto_sfx(k, st, blocks, cfg["theme"].get("sfx", {}))
        for ev in sc.get("sfx", []):
            sfx.append({"t": Rz.time(ev["at"]), "sound": ev["sound"], "gain": ev.get("gain", cfg["audio"].get("sfxDb", -12)),
                        "kind": "explicit"})
    sfx = sorted((e for e in sfx if 0 <= e["t"] < duration - 0.05), key=lambda e: e["t"])
    max_sfx = cfg["audio"].get("maxSfxPerSecond", 2.5)          # prevent excessive SFX
    if sfx and len(sfx) / duration > max_sfx:
        warnings.append(f"{len(sfx)} sfx cues in {duration:.1f}s exceeds {max_sfx}/s; thinning ticks/keys")
        keep, last = [], -9.0
        for e in sfx:
            if e.get("kind") in ("tick", "keys") and e["t"] - last < 0.12:
                continue
            keep.append(e); last = e["t"]
        sfx = keep
    bb = [s for s, sc in zip(resolved, scenes_sb) if sc.get("brandBar")]
    brand_bar = {"from": bb[0]["start"], "to": bb[-1]["end"]} if bb else None
    cc = cfg["captions"]
    pages = C.build_pages(words, max_words=cc.get("maxWords", 4), max_chars=cc.get("maxChars", 28),
                          hold=cc.get("hold", 0.6), audio_end=tm["duration"])
    crep = C.validate_pages(pages, words, tm["duration"], max_cps=cc.get("maxCps", 25))
    if crep.errors:
        raise PipelineError("caption timing invalid", detail="\n".join(crep.errors))
    warnings += [f"captions: {w}" for w in crep.warnings]
    theme_render = {k: v for k, v in cfg["theme"].items() if k not in ("sfx", "source", "$comment")}
    wm = watermark_props(cfg)
    props, ass = {}, {}
    for fmt in cfg["formats"]:
        ccf = caption_cfg(cfg, fmt)
        w_, h_ = FORMATS[fmt]
        ass[fmt] = C.to_ass(pages, words, width=w_, height=h_, font=cfg["theme"]["fonts"]["sans"]["family"],
                            font_size=ccf.get("fontSize", 66), bottom_frac=ccf.get("bottomFrac", 0.27),
                            highlight=cfg["theme"]["caption"]["highlight"], karaoke=ccf.get("style", "word") == "word")
        p = {"contractVersion": CONTRACT_VERSION, "format": fmt, "fps": FPS, "durationInFrames": frames,
             "theme": theme_render,
             "captions": {"enabled": ccf.get("enabled", True), "style": ccf.get("style", "word"),
                          "maxWords": ccf.get("maxWords", 4), "fontSize": ccf.get("fontSize", 66),
                          "bottomFrac": ccf.get("bottomFrac", 0.27), "maxWidthFrac": ccf.get("maxWidthFrac", 0.8),
                          "pages": [{"start": pg.start, "end": pg.end, "wordIdx": pg.word_idx} for pg in pages]},
             "words": [w.as_dict() for w in words], "scenes": resolved, "brandBar": brand_bar}
        if CONTRACT_VERSION >= 2:
            p["watermark"] = wm
            if cfg.get("motion"):
                p["motion"] = cfg["motion"]
        props[fmt] = p
    sb_out = {"duration": duration, "frames": frames, "fps": FPS, "scenes": [
        {**{k: s[k] for k in ("id", "purpose", "start", "end", "transition")},
         "narration": scenes_sb[i]["narration"], "speech": spans[i],
         "captions": [pg.text(words) for pg in pages if spans[i][0] - 1e-3 <= pg.start <= spans[i][1] + 1e-3],
         "sfx": [e for e in sfx if s["start"] <= e["t"] < s["end"]], "blocks": s["blocks"]}
        for i, s in enumerate(resolved)]}
    return Timeline(duration, frames, FPS, words, pages, resolved, sfx, brand_bar, props, ass, C.to_srt(pages, words),
                    sb_out, crep.max_cps, warnings)


def estimated_timing(storyboard: dict, wps: float = 2.33, gap: float = 0.2) -> dict:   # wps measured on the local voice
    """Timing estimate for previews before any TTS: words at `wps`, pauses after punctuation.
    Only for storyboard previews — production timing always comes from the real voice."""
    words, spans, t = [], [], 0.0
    for sc in storyboard["scenes"]:
        s0 = t
        for tok in tokenize(sc["narration"]):
            d = max(0.18, len(tok) / (wps * 5.2))
            words.append({"text": tok, "start": round(t, 3), "end": round(t + d, 3)})
            t += d + (0.25 if tok[-1:] in ".!?" else 0.08 if tok[-1:] in ",;:—" else 0.02)
        spans.append((s0, words[-1]["end"]))
        t = words[-1]["end"] + gap + float(sc.get("holdAfter", 0.0))
    return {"duration": round(words[-1]["end"] + 0.25, 3), "words": words, "scene_spans": spans}
