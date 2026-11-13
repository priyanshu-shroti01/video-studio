#!/usr/bin/env python3
"""RMS level (dBFS) of audio files over time windows — for checking ducking and mixes by numbers.

  python3 scripts/audio_levels.py public/audio/mix_music.wav 0-0.3 0.6-1.6 2.4-2.9
  python3 scripts/audio_levels.py ref.wav ducked.wav 0.6-1.6 --diff   # second minus first
"""
import array, math, subprocess, sys

SR = 48000


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return array.array("f", raw)


def rms_db(x, a, b):
    seg = x[int(a * SR):int(b * SR)]
    if not seg:
        return float("-inf")
    m = math.sqrt(sum(v * v for v in seg) / len(seg))
    return 20 * math.log10(m) if m > 0 else float("-inf")


def main():
    args = [x for x in sys.argv[1:] if x != "--diff"]
    files = [x for x in args if not x[0].isdigit()]
    wins = [tuple(map(float, x.split("-"))) for x in args if x[0].isdigit()]
    data = {f: decode(f) for f in files}
    for a, b in wins:
        vals = [rms_db(data[f], a, b) for f in files]
        line = f"{a:5.2f}-{b:<5.2f}s  " + "  ".join(f"{v:7.1f} dB" for v in vals)
        if "--diff" in sys.argv and len(vals) == 2:
            line += f"   diff {vals[1] - vals[0]:+5.1f} dB"
        print(line)


if __name__ == "__main__":
    main()
