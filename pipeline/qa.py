"""Automated QA for a finished video. An encoder exit code of 0 proves nothing; these checks look at
the actual file: container/streams, full decode, geometry, timing, black/frozen/blank frames, audio
loudness/peaks/clipping/silence/voice presence, and caption files.

Every check -> {id, category, status PASS|WARN|FAIL, critical, detail, metrics}. Any FAIL on a
critical check makes the job fail QA (it is not marked COMPLETED)."""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import audio as A
from . import procs
from .captions import parse_srt
from .contract import FORMATS
from .paths import atomic_write_json, atomic_write_text

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    id: str
    category: str
    status: str
    critical: bool
    detail: str
    metrics: dict = field(default_factory=dict)


@dataclass
class Expect:
    fmt: str
    fps: int
    duration: float                 # seconds of picture
    require_audio: bool = True
    lufs: float | None = -14.0
    lufs_tol: float = 1.0
    max_true_peak: float = -1.0
    speech: list[tuple[float, float]] = field(default_factory=list)   # word spans (absolute)
    scene_starts: list[float] = field(default_factory=list)
    end_fade_s: float = 0.5
    freeze_warn_s: float = 3.0
    planned_sfx: int = 0
    placed_sfx: int = 0
    caption_bottom_frac: float | None = None
    min_caption_bottom_frac: float = 0.0
    branding_present: bool = True


def ffprobe(path: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        return {}
    return json.loads(p.stdout or "{}")


def _fps(r: str) -> float:
    try:
        a, b = r.split("/")
        return float(a) / float(b) if float(b) else 0.0
    except (ValueError, AttributeError):
        return 0.0


def structural(path: Path, ex: Expect) -> tuple[list[Check], dict]:
    cs: list[Check] = []
    if not path.exists():
        return [Check("file.exists", "structure", FAIL, True, f"{path} does not exist")], {}
    size = path.stat().st_size
    cs.append(Check("file.nonempty", "structure", PASS if size > 10_000 else FAIL, True, f"{size / 1e6:.2f} MB",
                    {"bytes": size}))
    info = ffprobe(path)
    if not info:
        cs.append(Check("container.valid", "structure", FAIL, True, "ffprobe cannot read the container"))
        return cs, {}
    fmt = info.get("format", {})
    cs.append(Check("container.valid", "structure", PASS if "mp4" in fmt.get("format_name", "") else FAIL, True,
                    fmt.get("format_name", "?")))
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    cs.append(Check("stream.video", "structure", PASS if v else FAIL, True, "present" if v else "missing"))
    if ex.require_audio:
        cs.append(Check("stream.audio", "structure", PASS if a else FAIL, True, "present" if a else "missing"))
    if v:
        w, h = FORMATS[ex.fmt]
        ok = (v["width"], v["height"]) == (w, h)
        sar = v.get("sample_aspect_ratio", "1:1")
        cs.append(Check("video.resolution", "structure", PASS if ok else FAIL, True,
                        f"{v['width']}x{v['height']} (expected {w}x{h})", {"w": v["width"], "h": v["height"]}))
        cs.append(Check("video.aspect", "structure", PASS if sar in ("1:1", "0:1") and ok else FAIL, True,
                        f"SAR {sar}, DAR {v['width']}:{v['height']}"))
        fps = _fps(v.get("avg_frame_rate", "0/1"))
        cs.append(Check("video.fps", "structure", PASS if abs(fps - ex.fps) < 0.01 else FAIL, True, f"{fps:.3f} fps"))
        codec_ok = v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p"
        cs.append(Check("video.codec", "structure", PASS if codec_ok else FAIL, True,
                        f"{v.get('codec_name')} {v.get('profile')} {v.get('pix_fmt')}"))
        tagged = v.get("color_primaries") == "bt709" and v.get("color_transfer") == "bt709"
        cs.append(Check("video.color_tags", "structure", PASS if tagged else WARN, False,
                        f"primaries={v.get('color_primaries')} transfer={v.get('color_transfer')} "
                        f"matrix={v.get('color_space')}"))
        vd = float(v.get("duration", fmt.get("duration", 0)))
        ok = abs(vd - ex.duration) <= 1.5 / ex.fps
        cs.append(Check("video.duration", "structure", PASS if ok else FAIL, True,
                        f"{vd:.3f}s (expected {ex.duration:.3f}s)", {"seconds": vd}))
    if a:
        ad = float(a.get("duration", 0))
        vd = float(v.get("duration", 0)) if v else 0
        ok = abs(ad - vd) <= 0.12
        cs.append(Check("audio.duration", "audio", PASS if ok else FAIL, True,
                        f"audio {ad:.3f}s vs video {vd:.3f}s", {"audio_s": ad}))
    # full decode: catches truncation and corrupt packets that headers don't reveal
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True,
                       timeout=900)
    errs = [l for l in p.stderr.splitlines() if l.strip()]
    cs.append(Check("decode.full", "structure", PASS if p.returncode == 0 and not errs else FAIL, True,
                    "decoded every frame and sample" if not errs else "; ".join(errs[:3])))
    return cs, info


def _filter_log(path: Path, vf: str) -> str:
    r = procs.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf", vf, "-f", "null", "-"],
                  timeout=900, check=False)
    return r.output


def visual(path: Path, ex: Expect, dur: float) -> list[Check]:
    cs = []
    log = _filter_log(path, "blackdetect=d=0.1:pic_th=0.98:pix_th=0.06")
    blacks = [(float(m.group(1)), float(m.group(2))) for m in
              re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    unexpected = [(s, e) for s, e in blacks if not (e >= dur - 0.05 and s >= dur - ex.end_fade_s - 0.05) and not e <= 0.2]
    cs.append(Check("visual.black_frames", "visual", FAIL if unexpected else PASS, True,
                    f"unexpected black: {unexpected}" if unexpected else
                    ("only the planned end fade" if blacks else "none"), {"black_segments": blacks}))
    log = _filter_log(path, f"freezedetect=n=0.0005:d={ex.freeze_warn_s}")
    freezes = [(float(s), float(e)) for s, e in zip(re.findall(r"freeze_start: ([\d.]+)", log),
                                                    re.findall(r"freeze_end: ([\d.]+)", log))]
    tail_freeze = re.findall(r"freeze_start: ([\d.]+)", log)
    if len(tail_freeze) > len(freezes):
        freezes.append((float(tail_freeze[-1]), dur))
    cs.append(Check("visual.frozen", "visual", WARN if freezes else PASS, False,
                    f"static for ≥{ex.freeze_warn_s}s: {freezes}" if freezes else "no long static stretches",
                    {"freezes": freezes}))
    # blank frames (flat colour): sample each scene's middle and check luma range
    times = sorted({*(ex.scene_starts or []), dur / 2})
    blanks = []
    for t in [min(dur - 0.1, s + 0.8) for s in times]:
        r = procs.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                       "-vf", "signalstats,metadata=print",  # one key= per metadata filter, so print all
                       "-f", "null", "-"], timeout=60, check=False)
        ymax = re.search(r"signalstats\.YMAX=([\d.]+)", r.output)
        ymin = re.search(r"signalstats\.YMIN=([\d.]+)", r.output)
        if ymax and ymin and float(ymax.group(1)) - float(ymin.group(1)) < 24:
            blanks.append(round(t, 2))
    cs.append(Check("visual.blank_scenes", "visual", FAIL if blanks else PASS, True,
                    f"flat frames at {blanks}" if blanks else f"{len(times)} scene samples have content"))
    if ex.caption_bottom_frac is not None:
        ok = ex.caption_bottom_frac >= ex.min_caption_bottom_frac
        cs.append(Check("visual.caption_safe_area", "visual", PASS if ok else WARN, False,
                        f"caption box bottom at {ex.caption_bottom_frac:.0%} of height "
                        f"(platform overlay zone ≤ {ex.min_caption_bottom_frac:.0%})"))
    cs.append(Check("visual.branding", "visual", PASS if ex.branding_present else WARN, False,
                    "logo/CTA present in storyboard" if ex.branding_present else "no branding element"))
    return cs


def audio_checks(path: Path, ex: Expect) -> tuple[list[Check], dict]:
    cs: list[Check] = []
    rep = A.analyze(path)
    I, tp = rep["integrated_lufs"], rep["true_peak_dbtp"]
    if ex.lufs is not None:
        ok = abs(I - ex.lufs) <= ex.lufs_tol
        cs.append(Check("audio.loudness", "audio", PASS if ok else WARN, False,
                        f"{I:.1f} LUFS (target {ex.lufs} ±{ex.lufs_tol})", {"lufs": I, "lra": rep["lra_lu"]}))
    cs.append(Check("audio.true_peak", "audio", PASS if tp <= ex.max_true_peak else FAIL, True,
                    f"{tp:.1f} dBTP (limit {ex.max_true_peak})", {"true_peak": tp}))
    cs.append(Check("audio.clipping", "audio", PASS if rep["clipped_samples"] == 0 else FAIL, True,
                    f"{rep['clipped_samples']} samples at full scale", {"clipped": rep["clipped_samples"]}))
    # unexpected silence: silent stretches overlapping speech
    sil = rep["silences"]
    bad = [s for s in sil if any(a < s[1] and b > s[0] and min(b, s[1]) - max(a, s[0]) > 0.3 for a, b in ex.speech)]
    cs.append(Check("audio.silence", "audio", FAIL if bad else PASS, True,
                    f"silence during narration: {bad}" if bad else f"{len(sil)} silent gap(s), none inside speech",
                    {"silences": sil}))
    if ex.speech:
        x = A.decode_f32(path, sr=8000)
        sr = 8000
        levels = [A.rms_db(x, int(a * sr), int(b * sr)) for a, b in ex.speech if b - a > 0.08]
        quiet = sum(1 for l in levels if l < -45)
        ok = levels and quiet / len(levels) < 0.1
        med = sorted(levels)[len(levels) // 2] if levels else float("-inf")
        cs.append(Check("audio.voice_present", "audio", PASS if ok else FAIL, True,
                        f"median word level {med:.1f} dBFS, {quiet}/{len(levels)} words below -45 dBFS",
                        {"median_word_dbfs": med}))
    if ex.planned_sfx:
        ok = ex.placed_sfx >= ex.planned_sfx
        cs.append(Check("audio.sfx_placed", "audio", PASS if ok else FAIL, False,
                        f"{ex.placed_sfx}/{ex.planned_sfx} sound effects placed"))
    return cs, rep


def caption_checks(srt: Path | None, ass: Path | None, audio_dur: float, words: list[dict], max_cps: float) -> list[Check]:
    cs = []
    if srt is None:
        return [Check("captions.present", "captions", FAIL, True, "no caption file")]
    try:
        cues = parse_srt(srt.read_text(encoding="utf-8"))
        cs.append(Check("captions.srt_valid", "captions", PASS if cues else FAIL, True, f"{len(cues)} cues"))
    except (ValueError, OSError) as e:
        return [Check("captions.srt_valid", "captions", FAIL, True, str(e))]
    over = [i + 1 for i, (a, b, _) in enumerate(cues) if b > audio_dur + 0.05 or a < 0]
    cs.append(Check("captions.within_audio", "captions", FAIL if over else PASS, True,
                    f"cues outside audio: {over}" if over else f"all cues inside 0–{audio_dur:.2f}s"))
    overlap = [i + 1 for i in range(1, len(cues)) if cues[i][0] < cues[i - 1][1] - 1e-3]
    cs.append(Check("captions.no_overlap", "captions", FAIL if overlap else PASS, True,
                    f"overlapping cues: {overlap}" if overlap else "no overlaps"))
    fast = [(i + 1, round(len(t) / max(b - a, 1e-3))) for i, (a, b, t) in enumerate(cues) if len(t) / max(b - a, 1e-3) > max_cps]
    cs.append(Check("captions.reading_speed", "captions", WARN if fast else PASS, False,
                    f"faster than {max_cps:.0f} chars/s: {fast[:5]}" if fast else f"all ≤ {max_cps:.0f} chars/s"))
    text_words = " ".join(t for _, _, t in cues).split()
    cs.append(Check("captions.complete", "captions", PASS if len(text_words) == len(words) else FAIL, True,
                    f"{len(text_words)} caption words vs {len(words)} spoken"))
    if ass is not None:
        t = ass.read_text(encoding="utf-8") if ass.exists() else ""
        ok = "[Script Info]" in t and "[Events]" in t and t.count("Dialogue:") == len(cues)
        cs.append(Check("captions.ass_valid", "captions", PASS if ok else FAIL, False,
                        f"{t.count('Dialogue:')} dialogue lines"))
    return cs


def previews(path: Path, out_dir: Path, scene_starts: list[float], dur: float, w: int, h: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    picks = [("first", 0.05), ("middle", dur / 2), ("final", max(0, dur - 0.6))]
    picks += [(f"scene{k + 1:02d}", min(dur - 0.1, s + 1.0)) for k, s in enumerate(scene_starts)]
    paths = {}
    for name, t in picks:
        p = frames_dir / f"{name}.jpg"
        procs.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-q:v", "3", str(p)],
                  timeout=60)
        paths[name] = str(p)
    n = 12
    cols = 6 if h > w else 4
    rows = math.ceil(n / cols)
    sheet = out_dir / "contact-sheet.jpg"
    step = max(dur / n, 1 / 30)
    procs.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf",
               f"fps=1/{step:.3f},scale={360 if h > w else 480}:-2,tile={cols}x{rows}:padding=8:color=white",
               "-frames:v", "1", "-q:v", "3", str(sheet)], timeout=300)
    return {"contact_sheet": str(sheet), "frames": paths}


def run_qa(video: Path, ex: Expect, *, srt: Path | None, ass: Path | None, words: list[dict],
           reports_dir: Path, previews_dir: Path, max_cps: float = 25.0, title: str = "",
           extra: list[Check] | None = None) -> dict:
    t0 = time.time()
    checks, info = structural(video, ex)
    checks += extra or []
    fatal = any(c.status == FAIL and c.id in ("file.exists", "container.valid", "stream.video") for c in checks)
    audio_rep = {}
    prev = {}
    if not fatal:
        dur = float(info.get("format", {}).get("duration", ex.duration))
        checks += visual(video, ex, dur)
        if any(s["codec_type"] == "audio" for s in info.get("streams", [])):
            ac, audio_rep = audio_checks(video, ex)
            checks += ac
        checks += caption_checks(srt, ass, ex.duration, words, max_cps)
        w, h = FORMATS[ex.fmt]
        prev = previews(video, previews_dir, ex.scene_starts, dur, w, h)
    failed = [c for c in checks if c.status == FAIL and c.critical]
    status = FAIL if failed else (WARN if any(c.status != PASS for c in checks) else PASS)
    report = {"video": str(video), "format": ex.fmt, "status": status, "seconds": round(time.time() - t0, 1),
              "counts": {s: sum(c.status == s for c in checks) for s in (PASS, WARN, FAIL)},
              "checks": [c.__dict__ for c in checks], "audio": audio_rep, "previews": prev}
    atomic_write_json(reports_dir / f"qa-report-{ex.fmt}.json", report)
    return report


def write_markdown(reports: list[dict], dst: Path, title: str) -> None:
    lines = [f"# QA report — {title}", ""]
    for r in reports:
        lines += [f"## {r['format']}: **{r['status']}**  ({r['counts']['PASS']} pass · {r['counts']['WARN']} warn · "
                  f"{r['counts']['FAIL']} fail, {r['seconds']} s)", "", f"`{Path(r['video']).name}`", "",
                  "| Check | Status | Critical | Detail |", "|---|---|---|---|"]
        for c in r["checks"]:
            mark = {"PASS": "PASS", "WARN": "**WARN**", "FAIL": "**FAIL**"}[c["status"]]
            lines.append(f"| `{c['id']}` | {mark} | {'yes' if c['critical'] else 'no'} | {c['detail'].replace('|', '/')} |")
        if r.get("previews"):
            lines += ["", f"Contact sheet: `{Path(r['previews']['contact_sheet']).name}` (previews/)", ""]
    atomic_write_text(dst, "\n".join(lines) + "\n")
