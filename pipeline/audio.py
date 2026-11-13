"""Audio engine: voiceover assembly, mixing with side-chain ducking, two-pass EBU R128 mastering,
and measurement (loudness, true peak, clipping, silence, ducking depth). FFmpeg only, arg arrays.

Source files are never modified: every stage writes new files (atomically) into the job directory."""
from __future__ import annotations

import array
import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import procs
from .errors import AssetError, PipelineError
from .paths import ROOT, tmp_path_near
from .timing import Word, pause_cuts, shift_for_cuts

SR = 48000
NORM = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"


def ffprobe_duration(path: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(p.stdout.strip())
    except ValueError as e:
        raise AssetError(f"not readable audio/video: {path}", detail=p.stderr[-400:]) from e


# ---------------------------------------------------------------------------------------------
# Voiceover assembly
# ---------------------------------------------------------------------------------------------
@dataclass
class SceneVoice:
    audio: Path
    words: list[Word]          # scene-relative, aligned to script tokens
    duration: float
    hold: float = 0.0          # extra silence after this scene (storyboard holdAfter)


@dataclass
class Voiceover:
    path: Path
    duration: float
    words: list[Word]                          # absolute
    scene_spans: list[tuple[float, float]]     # speech span per scene (absolute)
    removed_s: float = 0.0


def build_voiceover(scenes: list[SceneVoice], out: Path, *, max_pause: float, pad: float, gap: float,
                    lead: float = 0.0) -> Voiceover:
    """Per scene: shorten long pauses (cut from the middle of the gap), trim to last word + pad, then
    join scenes with `gap` seconds of silence. Word timings are shifted by exactly what was cut."""
    inputs, chains, labels, words_out, spans = [], [], [], [], []
    t, removed = lead, 0.0
    f = 0.012  # splice fades (avoid clicks)
    for si, sc in enumerate(scenes):
        ws = [Word(w.text, w.start, w.end, w.interpolated) for w in sc.words]
        cuts = pause_cuts(ws, max_pause)
        end = min(sc.duration, ws[-1].end + pad)
        keep, cur = [], max(0.0, ws[0].start - 0.08) if si else 0.0  # scenes after the first start tight
        head_trim = cur
        for cs, cl in cuts:
            keep.append((cur, cs)); cur = cs + cl
        keep.append((cur, end))
        shift_for_cuts(ws, cuts)
        inputs += ["-i", str(sc.audio)]
        for k, (a, b) in enumerate(keep):
            lab = f"s{si}_{k}"
            chains.append(f"[{si}:a]atrim={a:.4f}:{b:.4f},asetpts=N/SR/TB,aresample={SR},"
                          f"aformat=sample_fmts=fltp:channel_layouts=mono,afade=t=in:d={f},"
                          f"afade=t=out:st={max(0.0, b - a - f):.4f}:d={f}[{lab}]")
            labels.append(f"[{lab}]")
        seg_len = sum(b - a for a, b in keep)
        removed += (sc.duration - seg_len)
        for w in ws:
            words_out.append(Word(w.text, round(w.start - head_trim + t, 4), round(w.end - head_trim + t, 4), w.interpolated))
        spans.append((t + ws[0].start - head_trim, t + ws[-1].end - head_trim))
        t += seg_len
        g = gap + max(0.0, sc.hold)
        if si < len(scenes) - 1 and g > 0:
            lab = f"g{si}"
            chains.append(f"anullsrc=r={SR}:cl=mono:d={g:.4f},aformat=sample_fmts=fltp[{lab}]")
            labels.append(f"[{lab}]")
            t += g
    if lead > 0:
        chains.insert(0, f"anullsrc=r={SR}:cl=mono:d={lead:.4f},aformat=sample_fmts=fltp[lead]")
        labels.insert(0, "[lead]")
    graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[o]"
    tmp = tmp_path_near(out, ".wav")
    try:
        procs.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[o]",
                   "-c:a", "pcm_s16le", "-ar", str(SR), "-ac", "1", str(tmp)], timeout=300)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    dur = ffprobe_duration(out)
    return Voiceover(out, dur, words_out, spans, round(removed, 3))


# ---------------------------------------------------------------------------------------------
# SFX kit (opus-sound-layer catalog)
# ---------------------------------------------------------------------------------------------
class Kit:
    def __init__(self, root: Path):
        self.root, self.by_id, self.types, self._rot = Path(root), {}, {}, {}
        cat = self.root / "catalog.json"
        if cat.exists():
            c = json.loads(cat.read_text())
            self.by_id = {s["id"]: s for s in c["sounds"]}
            self.types = c["types"]

    def resolve(self, spec: str) -> tuple[Path, float, str]:
        """-> (file, peak_offset_s, id). spec = existing file | kit id | kit type (rotates defaults)."""
        p = Path(spec)
        cand = p if p.is_absolute() else ROOT / p
        if cand.suffix and cand.exists():
            return cand, 0.0, spec
        if spec in self.by_id:
            s = self.by_id[spec]
            f = self.root / s["file"]
            if not f.exists():
                raise AssetError(f"sound '{spec}' is in the catalog but its file is missing: {f}")
            return f, float(s.get("peak_offset_s", 0.0)), spec
        if spec in self.types:
            pool = self.types[spec].get("defaults") or [s["id"] for s in self.by_id.values() if s["type"] == spec]
            if not pool:
                raise AssetError(f"kit has no '{spec}' sounds")
            i = self._rot.get(spec, 0)
            self._rot[spec] = i + 1
            return self.resolve(pool[i % len(pool)])
        raise AssetError(f"unknown sound '{spec}': not a file, kit id or kit type")


# ---------------------------------------------------------------------------------------------
# Mixing + mastering
# ---------------------------------------------------------------------------------------------
@dataclass
class MixSettings:
    music_db: float = -14.0
    voice_db: float = 0.0
    sfx_db: float = -6.0
    duck_threshold: float = 0.03
    duck_ratio: float = 4.0
    duck_attack_ms: float = 20.0
    duck_release_ms: float = 400.0
    music_fade_in: float = 0.8
    music_fade_out: float = 1.5
    lufs: float | None = -14.0
    true_peak: float = -1.5
    lra: float = 11.0
    voice_ref_lufs: float | None = -18.0   # voice is levelled to this before ducking, so the side-chain
                                           # threshold means the same thing for every TTS provider

    @classmethod
    def from_config(cls, a: dict) -> "MixSettings":
        d = a.get("duck", {})
        return cls(music_db=a.get("musicDb", -14), voice_db=a.get("voiceDb", 0), sfx_db=a.get("sfxDb", -6),
                   duck_threshold=d.get("threshold", 0.03), duck_ratio=d.get("ratio", 4),
                   duck_attack_ms=d.get("attackMs", 20), duck_release_ms=d.get("releaseMs", 400),
                   music_fade_in=a.get("musicFadeIn", 0.8), music_fade_out=a.get("musicFadeOut", 1.5),
                   lufs=a.get("lufs", -14), true_peak=a.get("truePeak", -1.5), lra=a.get("lra", 11),
                   voice_ref_lufs=a.get("voiceRefLufs", -18))


@dataclass
class SfxEvent:
    sound: str
    t: float
    gain_db: float
    id: str = ""


@dataclass
class MixResult:
    path: Path
    duration: float
    events: list[dict] = field(default_factory=list)
    stems: dict = field(default_factory=dict)


def loudnorm_two_pass(src: Path, dst: Path, target: float, tp: float, lra: float) -> dict:
    r = procs.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af",
                   f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"], timeout=300)
    m = json.loads(r.output[r.output.rindex("{"):r.output.rindex("}") + 1])
    if float(m["input_i"]) == float("-inf") or m["input_i"] in ("-inf", "inf"):
        raise PipelineError("mix is silent; cannot normalise loudness")
    af = (f"loudnorm=I={target}:TP={tp}:LRA={lra}:linear=true:measured_I={m['input_i']}:"
          f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset={m['target_offset']},aresample={SR}")
    tmp = tmp_path_near(dst, ".wav")
    try:
        procs.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", af, "-c:a", "pcm_s24le", str(tmp)], timeout=300)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()
    return m


def mix(*, out: Path, duration: float, voice: list[tuple[Path, float]], music: Path | None,
        sfx: list[SfxEvent], kit: Kit, s: MixSettings, stems_dir: Path | None = None,
        timeout: float = 600) -> MixResult:
    inputs, chains, events = [], [], []
    n_in = 0

    def add(path: Path, loop: bool = False) -> int:
        nonlocal n_in
        if not Path(path).exists():
            raise AssetError(f"missing audio input: {path}")
        inputs.extend((["-stream_loop", "-1"] if loop else []) + ["-i", str(path)])
        n_in += 1
        return n_in - 1

    vo, levelling = [], []
    for k, (f, start) in enumerate(voice):
        i = add(f)
        g = s.voice_db
        if s.voice_ref_lufs is not None:
            measured = loudness(Path(f))["integrated_lufs"]
            if measured == float("-inf"):
                raise PipelineError(f"voiceover is silent: {f}")
            lift = max(-20.0, min(20.0, s.voice_ref_lufs - measured))
            g += lift
            levelling.append({"file": str(f), "measured_lufs": round(measured, 2), "gain_db": round(lift, 2)})
        chains.append(f"[{i}:a]{NORM},volume={g:.2f}dB,adelay={int(round(start * 1000))}:all=1[v{k}]")
        vo.append(f"[v{k}]")
    fx = []
    for k, ev in enumerate(sfx):
        for j, layer in enumerate(ev.sound.split("+")):
            f, peak, sid = kit.resolve(layer)
            start = max(0.0, ev.t - peak)
            gain = ev.gain_db - 4 * j
            i = add(f)
            chains.append(f"[{i}:a]{NORM},volume={gain}dB,adelay={int(round(start * 1000))}:all=1[s{k}_{j}]")
            fx.append(f"[s{k}_{j}]")
            events.append({"id": ev.id or f"sfx{k}", "sound": sid, "file": str(f), "t": round(ev.t, 3),
                           "placed_s": round(start, 3), "gain_db": gain})
    buses = []
    if vo:
        pre = "".join(vo) + (f"amix=inputs={len(vo)}:normalize=0:duration=longest," if len(vo) > 1 else "")
        chains.append(f"{pre}apad=whole_dur={duration},atrim=0:{duration},asplit=3[vo][vokey][vostem]")
        buses.append("[vo]")
    want_stems = stems_dir is not None
    if music:
        i = add(music, loop=True)
        fo = min(s.music_fade_out, duration / 2)
        chains.append(f"[{i}:a]{NORM},atrim=0:{duration},asetpts=N/SR/TB,volume={s.music_db}dB,"
                      f"afade=t=in:d={s.music_fade_in},afade=t=out:st={duration - fo}:d={fo},asplit=2[mus][musref]")
        if vo:
            chains.append(f"[mus][vokey]sidechaincompress=threshold={s.duck_threshold}:ratio={s.duck_ratio}:"
                          f"attack={s.duck_attack_ms}:release={s.duck_release_ms}:knee=3:link=maximum[musd0]")
        else:
            chains.append("[mus]anull[musd0]")
        chains.append("[musd0]asplit=2[musd][musstem]")
        buses.append("[musd]")
    elif vo:
        chains.append("[vokey]anullsink")
    if fx:
        chains.append("".join(fx) + f"amix=inputs={len(fx)}:normalize=0:duration=longest,apad=whole_dur={duration},"
                      f"atrim=0:{duration},asplit=2[fx][fxstem]")
        buses.append("[fx]")
    if not buses:
        raise PipelineError("nothing to mix")
    master = (f"amix=inputs={len(buses)}:normalize=0:duration=longest," if len(buses) > 1 else "anull,")
    chains.append("".join(buses) + master + f"apad=whole_dur={duration},atrim=0:{duration}[out]")

    pre = tmp_path_near(out, ".premaster.wav")
    maps = ["-map", "[out]", "-c:a", "pcm_f32le", str(pre)]
    stems: dict[str, str] = {}
    unused = []
    if want_stems:
        stems_dir.mkdir(parents=True, exist_ok=True)
        for lab, name, present in (("vostem", "voice", bool(vo)), ("musstem", "music_ducked", bool(music)),
                                   ("musref", "music_reference", bool(music)), ("fxstem", "sfx", bool(fx))):
            if present:
                p = stems_dir / f"{name}.wav"
                maps += ["-map", f"[{lab}]", "-c:a", "pcm_s16le", str(p)]
                stems[name] = str(p)
    else:
        unused = [lab for lab, present in (("vostem", bool(vo)), ("musstem", bool(music)), ("musref", bool(music)),
                                           ("fxstem", bool(fx))) if present]
        for lab in unused:
            chains.append(f"[{lab}]anullsink")
    try:
        procs.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains), *maps], timeout=timeout)
        if s.lufs is not None:
            loudnorm_two_pass(pre, out, s.lufs, s.true_peak, s.lra)
        else:
            procs.run(["ffmpeg", "-v", "error", "-y", "-i", str(pre), "-c:a", "pcm_s24le", str(out)], timeout=120)
    finally:
        if pre.exists():
            pre.unlink()
    return MixResult(out, ffprobe_duration(out), events, {**stems, "voice_levelling": levelling} if levelling else stems)


# ---------------------------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------------------------
def decode_f32(path: Path, channels: int = 1, sr: int = SR, start: float | None = None, dur: float | None = None) -> array.array:
    args = ["ffmpeg", "-v", "error"]
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path)]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    p = subprocess.run(args, capture_output=True, timeout=300)
    if p.returncode != 0:
        raise AssetError(f"cannot decode audio from {path}", detail=p.stderr.decode(errors="replace")[-400:])
    a = array.array("f")
    a.frombytes(p.stdout)
    return a


def rms_db(x, a: int = 0, b: int | None = None) -> float:
    seg = x[a:b]
    if not len(seg):
        return float("-inf")
    m = math.sqrt(sum(v * v for v in seg) / len(seg))
    return 20 * math.log10(m) if m > 0 else float("-inf")


def loudness(path: Path) -> dict:
    r = procs.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                   "loudnorm=print_format=json", "-f", "null", "-"], timeout=300)
    m = json.loads(r.output[r.output.rindex("{"):r.output.rindex("}") + 1])
    f = lambda k: float(m[k]) if m[k] not in ("-inf", "inf") else float("-inf")
    return {"integrated_lufs": f("input_i"), "true_peak_dbtp": f("input_tp"), "lra_lu": f("input_lra")}


def silences(path: Path, noise_db: float = -50, min_s: float = 0.5) -> list[tuple[float, float]]:
    r = procs.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                   f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"], timeout=300)
    out, start = [], None
    for line in r.output.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].split()[0])
        elif "silence_end:" in line and start is not None:
            end = float(line.split("silence_end:")[1].split("|")[0])
            out.append((round(start, 3), round(end, 3)))
            start = None
    if start is not None:
        out.append((round(start, 3), round(ffprobe_duration(path), 3)))
    return out


def analyze(path: Path, *, clip_threshold: float = 0.999) -> dict:
    """Loudness, peaks, clipping and silence for a finished mix (or the audio of an MP4)."""
    x = decode_f32(path, channels=2)
    peak = max((abs(v) for v in x), default=0.0)
    clipped = sum(1 for v in x if v >= clip_threshold or v <= -clip_threshold)
    rep = {"file": str(path), "duration_s": round(ffprobe_duration(path), 3),
           "sample_peak_dbfs": round(20 * math.log10(peak), 2) if peak > 0 else float("-inf"),
           "clipped_samples": clipped, "silences": silences(path)}
    rep.update({k: round(v, 2) for k, v in loudness(path).items()})
    return rep


def ducking_depth(stems: dict, words: list[Word], *, min_window: float = 0.25) -> dict | None:
    """Measured ducking: (ducked music - reference music) RMS during speech, and outside speech."""
    if "music_ducked" not in stems or "music_reference" not in stems:
        return None
    d = decode_f32(Path(stems["music_ducked"]), sr=8000)
    r = decode_f32(Path(stems["music_reference"]), sr=8000)
    sr = 8000
    speech = [(int(w.start * sr), int(w.end * sr)) for w in words if w.end - w.start >= 0.05]
    if not speech:
        return None
    ds = sum(rms_lin(d, a, b) for a, b in speech) / len(speech)
    rs = sum(rms_lin(r, a, b) for a, b in speech) / len(speech)
    under = 20 * math.log10(ds / rs) if ds > 0 and rs > 0 else None
    return {"under_voice_db": round(under, 1) if under is not None else None, "windows": len(speech)}


def rms_lin(x, a: int, b: int) -> float:
    seg = x[a:b]
    return math.sqrt(sum(v * v for v in seg) / len(seg)) if len(seg) else 0.0
