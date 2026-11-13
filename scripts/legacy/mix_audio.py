#!/usr/bin/env python3
"""Mix voiceover + background music + CC0 sound effects with automatic ducking (FFmpeg only).

Quick form:
  python3 scripts/legacy/mix_audio.py \
      --voice public/voiceover/intro.mp3 \
      --music audio/music/bed.mp3 \
      --sfx whoosh@0.0 --sfx "hit/fs-123-impact-1@2.4:-3" --sfx my/own.wav@5.1 \
      --out public/audio/mix.wav [--video out/silent.mp4 --mux out/final.mp4]

Cue-sheet form (same file format as opus-sound-layer's mix.py, so one cues.json
drives both this quick mixer and the full sound-designer pipeline):
  python3 scripts/legacy/mix_audio.py --cues audio/cues.json --out public/audio/mix.wav

  {"fps": 30, "duration_s": 12.0, "kit": "audio/kit",
   "music": {"file": "audio/music/bed.mp3", "gain_db": -14},
   "voice": [{"file": "public/voiceover/intro.mp3", "start_s": 0.3}],
   "cues":  [{"t": 0.0, "sound": "whoosh"}, {"frame": 72, "sound": "hit+boom", "gain_db": -2}]}

Sound spec (--sfx SPEC@SECONDS[:GAIN_DB], or "sound" in a cue):
  type          rotate through that type's defaults in the kit (whoosh, hit, pop, riser, ...)
  type/id       an exact id picked with `bash scripts/sound-layer.sh browse --type hit`
  path          any audio file
  a+b           layer several (peaks aligned)

How the ducking works: the voice bus is the side-chain key of an FFmpeg
`sidechaincompress` on the music bus. While the narrator speaks the music drops
(~10-14 dB at the defaults); between phrases it recovers over --duck-release ms.
Each effect is placed so its loudest point (catalog peak_offset_s) lands on the cue.
Master: EBU R128 loudnorm to -14 LUFS / -1.5 dBTP (YouTube / Shorts / Reels target).
"""
import argparse, json, os, subprocess, sys

SR = 48000


def ffprobe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def loudnorm_two_pass(src, dst, target, tp=-1.5, lra=11):
    """EBU R128 two-pass: measure, then apply a linear gain (no pumping, accurate on short clips)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", src, "-af",
                        f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, check=True).stderr
    m = json.loads(r[r.rindex("{"):r.rindex("}") + 1])
    af = (f"loudnorm=I={target}:TP={tp}:LRA={lra}:linear=true:measured_I={m['input_i']}:"
          f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset={m['target_offset']},aresample={SR}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", af, "-c:a", "pcm_s24le", dst], check=True)


class Kit:
    def __init__(self, root):
        self.root, self.by_id, self.types, self._rot = root, {}, {}, {}
        cat = os.path.join(root, "catalog.json")
        if os.path.exists(cat):
            c = json.load(open(cat))
            self.by_id = {s["id"]: s for s in c["sounds"]}
            self.types = c["types"]

    def resolve(self, spec):
        """-> (file, peak_offset_s)"""
        if os.path.exists(spec):
            return spec, 0.0
        if spec in self.by_id:
            s = self.by_id[spec]
            return os.path.join(self.root, s["file"]), s.get("peak_offset_s", 0.0)
        if spec in self.types:
            pool = self.types[spec].get("defaults") or [s["id"] for s in self.by_id.values() if s["type"] == spec]
            if not pool:
                sys.exit(f"kit has no '{spec}' sounds (see audio/kit/catalog.json)")
            i = self._rot.get(spec, 0); self._rot[spec] = i + 1
            return self.resolve(pool[i % len(pool)])
        sys.exit(f"unknown sound '{spec}': not a file, kit id or kit type (kit: {self.root})")


def parse_at(s, default_gain):
    """'spec@1.25:-3' -> (spec, 1.25, -3.0)"""
    if "@" not in s:
        sys.exit(f"--sfx/--voice needs @seconds, got '{s}'")
    spec, rest = s.rsplit("@", 1)
    t, _, g = rest.partition(":")
    return spec, float(t), float(g) if g else default_gain


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cues", help="cue sheet JSON (see above)")
    ap.add_argument("--voice", action="append", default=[], help="FILE or FILE@START_S (repeatable)")
    ap.add_argument("--music", help="background music file (looped/trimmed to length)")
    ap.add_argument("--sfx", action="append", default=[], help="SPEC@SECONDS[:GAIN_DB] (repeatable)")
    ap.add_argument("--kit", default="audio/kit")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--duration", type=float, help="output length (default: last sound + --tail)")
    ap.add_argument("--tail", type=float, default=0.8)
    ap.add_argument("--music-db", type=float, default=-14, help="music bed level before ducking")
    ap.add_argument("--sfx-db", type=float, default=-6, help="default gain for effects")
    ap.add_argument("--voice-db", type=float, default=0)
    ap.add_argument("--duck-threshold", type=float, default=0.03, help="side-chain threshold (lower = more ducking)")
    ap.add_argument("--duck-ratio", type=float, default=4, help="higher = more ducking (8 ≈ -18 dB, 4 ≈ -11 dB)")
    ap.add_argument("--duck-attack", type=float, default=20, help="ms")
    ap.add_argument("--duck-release", type=float, default=400, help="ms")
    ap.add_argument("--music-fade-in", type=float, default=0.8)
    ap.add_argument("--music-fade-out", type=float, default=1.5)
    ap.add_argument("--lufs", type=float, default=-14, help="integrated loudness target; 0 disables")
    ap.add_argument("--out", default="public/audio/mix.wav")
    ap.add_argument("--stems", action="store_true", help="also write <out>_music.wav (ducked bed) for checking")
    ap.add_argument("--video", help="silent/rough video to put the mix on")
    ap.add_argument("--mux", help="output mp4 when --video is given")
    a = ap.parse_args()

    voices, sfx, music, music_db = [], [], a.music, a.music_db
    kit_root, fps, duration = a.kit, a.fps, a.duration
    if a.cues:
        C = json.load(open(a.cues))
        fps = C.get("fps", fps); kit_root = C.get("kit", kit_root); duration = C.get("duration_s", duration)
        if C.get("music"):
            music = C["music"]["file"]; music_db = C["music"].get("gain_db", music_db)
        voices += [(v["file"], v.get("start_s", 0.0), v.get("gain_db", a.voice_db)) for v in C.get("voice", [])]
        for c in C.get("cues", []):
            t = c["t"] if "t" in c else c["frame"] / fps
            sfx.append((c["sound"], t, c.get("gain_db", a.sfx_db)))
    for v in a.voice:
        voices.append(parse_at(v, a.voice_db) if "@" in v else (v, 0.0, a.voice_db))
    sfx += [parse_at(s, a.sfx_db) for s in a.sfx]
    if not (voices or music or sfx):
        ap.error("nothing to mix: give --voice / --music / --sfx or --cues")

    kit = Kit(kit_root)
    inputs, chains, ends = [], [], []

    def add_input(path, loop=False):
        inputs.extend((["-stream_loop", "-1"] if loop else []) + ["-i", path])
        return len([x for x in inputs if x == "-i"]) - 1

    norm = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"
    vo_labels = []
    for k, (f, start, g) in enumerate(voices):
        i = add_input(f)
        ms = max(0, int(round(start * 1000)))
        chains.append(f"[{i}:a]{norm},volume={g}dB,adelay={ms}:all=1[v{k}]")
        vo_labels.append(f"[v{k}]"); ends.append(start + ffprobe_dur(f))

    fx_labels = []
    for k, (spec, t, g) in enumerate(sfx):
        layers = spec.split("+")
        for j, layer in enumerate(layers):
            f, peak = kit.resolve(layer)
            start = max(0.0, t - peak)
            ms = int(round(start * 1000))
            gain = g - 4 * j  # later layers -4 dB (opus-sound-layer convention)
            i = add_input(f)
            lab = f"[s{k}_{j}]"
            chains.append(f"[{i}:a]{norm},volume={gain}dB,adelay={ms}:all=1{lab}")
            fx_labels.append(lab); ends.append(start + ffprobe_dur(f))
            print(f"  sfx {t:7.3f}s  {gain:+5.1f} dB  {os.path.relpath(f)}")

    D = duration or (max(ends) + a.tail if ends else None)
    if D is None:
        sys.exit("music only: give --duration")

    buses = []
    if vo_labels:
        chains.append("".join(vo_labels) + f"amix=inputs={len(vo_labels)}:normalize=0:duration=longest,"
                      f"apad=whole_dur={D},asplit=2[vo][vokey]" if len(vo_labels) > 1 else
                      f"{vo_labels[0]}apad=whole_dur={D},asplit=2[vo][vokey]")
        buses.append("[vo]")
    if music:
        i = add_input(music, loop=True)
        fo = min(a.music_fade_out, D / 2)
        chains.append(f"[{i}:a]{norm},atrim=0:{D},asetpts=N/SR/TB,volume={music_db}dB,"
                      f"afade=t=in:d={a.music_fade_in},afade=t=out:st={D - fo}:d={fo}[mus]")
        if vo_labels:
            chains.append(f"[mus][vokey]sidechaincompress=threshold={a.duck_threshold}:ratio={a.duck_ratio}:"
                          f"attack={a.duck_attack}:release={a.duck_release}:knee=3:link=maximum[musd]")
        else:
            chains.append("[mus]anull[musd]")
        if a.stems:
            chains.append("[musd]asplit=2[musd1][musstem]"); buses.append("[musd1]")
        else:
            buses.append("[musd]")
    elif vo_labels:
        chains.append("[vokey]anullsink")
    if fx_labels:
        chains.append("".join(fx_labels) + f"amix=inputs={len(fx_labels)}:normalize=0:duration=longest[fx]")
        buses.append("[fx]")

    master = (f"amix=inputs={len(buses)}:normalize=0:duration=longest," if len(buses) > 1 else "anull,")
    master += f"apad=whole_dur={D},atrim=0:{D}[out]"
    chains.append("".join(buses) + master)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    pre = os.path.splitext(a.out)[0] + ".premaster.wav" if a.lufs else a.out
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
           "-map", "[out]", "-c:a", "pcm_f32le", pre]
    if a.stems and music:
        stem = os.path.splitext(a.out)[0] + "_music.wav"
        cmd += ["-map", "[musstem]", "-c:a", "pcm_s24le", stem]
    subprocess.run(cmd, check=True)
    if a.lufs:
        loudnorm_two_pass(pre, a.out, a.lufs)
        os.remove(pre)
    print(f"mix       {a.out}  ({D:.2f} s, {len(voices)} voice, {'music' if music else 'no music'}, {len(fx_labels)} sfx layers)")

    if a.video:
        mux = a.mux or os.path.splitext(a.video)[0] + "_final.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-i", a.out, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", mux],
                       check=True)
        print(f"muxed     {mux}")


if __name__ == "__main__":
    main()
