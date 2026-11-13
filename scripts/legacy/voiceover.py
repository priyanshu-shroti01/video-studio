#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["edge-tts>=7"]
# ///
"""Free voiceover via Microsoft edge-tts (no API key) + exact duration + word timings.

  python3 scripts/legacy/voiceover.py "Your narration here." --name intro
  python3 scripts/legacy/voiceover.py --file script/intro.txt --name intro --voice en-US-AndrewNeural
  python3 scripts/legacy/voiceover.py --list-voices en-IN        # list voices for a locale

Writes (default --out-dir public/voiceover):
  <name>.mp3   the narration
  <name>.json  {text, voice, audio, duration, speechEnd, fps, durationInFrames, words:[{text,start,end}]}
  <name>.srt   word-grouped captions (handy for YouTube upload)

`duration` is measured by fully decoding the MP3 with ffmpeg (sample-exact), not read from
the header. Remotion's calculateMetadata uses it to size the composition.

Recommended voices: en-IN-PrabhatNeural (default, crisp Indian English male),
en-IN-NeerjaNeural (Indian English female), en-US-AndrewNeural (warm US male),
en-US-BrianNeural, en-US-AvaNeural, en-US-EmmaNeural.
"""
import argparse, asyncio, json, math, os, subprocess, sys

import edge_tts

DEFAULT_VOICE = "en-IN-PrabhatNeural"
TICKS = 10_000_000  # edge-tts offsets are in 100 ns units


def exact_duration(path: str) -> float:
    """Decode to raw PCM and count samples: exact regardless of MP3 header/VBR quirks."""
    sr = 48000
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    return len(raw) / 2 / sr


async def synth(text, voice, rate, pitch, volume, mp3_path):
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume, boundary="WordBoundary")
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS
                words.append({"text": chunk["text"], "start": round(start, 3),
                              "end": round(start + chunk["duration"] / TICKS, 3)})
    return words


def attach_punctuation(text: str, words: list) -> list:
    """WordBoundary drops punctuation; re-attach trailing punctuation from the source text
    so captions read naturally and can break on sentence ends."""
    pos = 0
    for w in words:
        i = text.find(w["text"], pos)
        if i < 0:
            continue
        j = i + len(w["text"])
        while j < len(text) and text[j] in ".,!?;:…—\"'”’)":
            j += 1
        w["text"] = text[i:j].rstrip("\"'”’)") or w["text"]
        pos = j
    return words


def srt_time(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000); m, ms = divmod(ms, 60_000); sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def write_srt(words, path, per=6):
    lines, n = [], 0
    for k in range(0, len(words), per):
        grp = words[k:k + per]
        n += 1
        lines += [str(n), f"{srt_time(grp[0]['start'])} --> {srt_time(grp[-1]['end'])}",
                  " ".join(w["text"] for w in grp), ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))


async def list_voices(prefix):
    for v in sorted(await edge_tts.list_voices(), key=lambda v: v["ShortName"]):
        if v["ShortName"].lower().startswith(prefix.lower()):
            print(f'{v["ShortName"]:32} {v["Gender"]:7} {", ".join(v.get("VoiceTag", {}).get("VoicePersonalities", []))}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?", help="narration text (or use --file)")
    ap.add_argument("--file", help="read narration from a text file")
    ap.add_argument("--name", default="voiceover", help="output basename")
    ap.add_argument("--voice", default=os.environ.get("EDGE_TTS_VOICE", DEFAULT_VOICE))
    ap.add_argument("--rate", default="+0%", help='e.g. "+8%%" faster, "-5%%" slower')
    ap.add_argument("--pitch", default="+0Hz")
    ap.add_argument("--volume", default="+0%")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out-dir", default="public/voiceover")
    ap.add_argument("--pad", type=float, default=0.3, help="seconds kept after the last word (default 0.3)")
    ap.add_argument("--keep-silence", action="store_true", help="don't trim edge-tts' trailing silence")
    ap.add_argument("--max-pause", type=float, default=0, help="shorten pauses between words to this many seconds (e.g. 0.35)")
    ap.add_argument("--list-voices", metavar="LOCALE_PREFIX", help='e.g. "en-IN" or "en"')
    a = ap.parse_args()

    if a.list_voices:
        asyncio.run(list_voices(a.list_voices)); return
    text = open(a.file, encoding="utf-8").read().strip() if a.file else (a.text or "").strip()
    if not text:
        ap.error("give narration text or --file")

    os.makedirs(a.out_dir, exist_ok=True)
    mp3 = os.path.join(a.out_dir, f"{a.name}.mp3")
    words = asyncio.run(synth(text, a.voice, a.rate, a.pitch, a.volume, mp3))
    if not os.path.exists(mp3) or os.path.getsize(mp3) == 0:
        sys.exit("edge-tts returned no audio (check network / voice name)")
    words = attach_punctuation(text, words)

    raw_dur = exact_duration(mp3)
    speech_end = words[-1]["end"] if words else raw_dur
    end = speech_end + a.pad if not a.keep_silence and speech_end + a.pad < raw_dur - 0.05 else raw_dur
    # pauses between words longer than --max-pause are shortened (cut out of the middle of the gap)
    cuts = []  # (cut_start, cut_len) in original time
    if a.max_pause and words:
        for w0, w1 in zip(words, words[1:]):
            gap = w1["start"] - w0["end"]
            if gap > a.max_pause:
                lead = a.max_pause * 0.6  # keep 60% of the allowed pause after the word (breath/decay)
                cuts.append((w0["end"] + lead, gap - a.max_pause))
    if cuts or end < raw_dur:
        keep, t = [], 0.0
        for cs, cl in cuts:
            keep.append((t, cs)); t = cs + cl
        keep.append((t, end))
        f = 0.012  # tiny fades at every splice to avoid clicks
        parts = [f"[0:a]atrim={s:.3f}:{e:.3f},asetpts=N/SR/TB,afade=t=in:d={f},"
                 f"afade=t=out:st={max(0, e - s - f):.3f}:d={f}[p{i}]" for i, (s, e) in enumerate(keep)]
        graph = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=0:a=1[o]"
        tmp = mp3 + ".tmp.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp3, "-filter_complex", graph, "-map", "[o]",
                        "-c:a", "libmp3lame", "-q:a", "2", tmp], check=True)
        os.replace(tmp, mp3)
        for w in words:  # shift timings by everything cut before each word
            shift = sum(cl for cs, cl in cuts if cs < w["start"])
            w["start"] = round(w["start"] - shift, 3); w["end"] = round(w["end"] - shift, 3)
        if cuts:
            print(f"pauses    shortened {len(cuts)} gaps to {a.max_pause}s, removed {sum(c for _, c in cuts):.2f}s")
    speech_end = words[-1]["end"] if words else raw_dur
    dur = exact_duration(mp3)
    # audio path relative to public/ so Remotion's staticFile() can load it
    pub = os.path.relpath(mp3, "public") if os.path.abspath(mp3).startswith(os.path.abspath("public")) else mp3
    meta = {"text": text, "voice": a.voice, "rate": a.rate, "pitch": a.pitch, "audio": pub,
            "duration": round(dur, 3), "speechEnd": round(speech_end, 3), "fps": a.fps,
            "durationInFrames": math.ceil(dur * a.fps), "words": words}
    js = os.path.join(a.out_dir, f"{a.name}.json")
    json.dump(meta, open(js, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    write_srt(words, os.path.join(a.out_dir, f"{a.name}.srt"))

    print(f"voice     {a.voice}  rate {a.rate}")
    print(f"audio     {mp3}")
    print(f"timing    {js}  ({len(words)} words)")
    print(f"duration  {dur:.3f} s  = {meta['durationInFrames']} frames @ {a.fps} fps  (speech ends {speech_end:.3f} s)")


if __name__ == "__main__":
    main()
