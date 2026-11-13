#!/usr/bin/env python3
"""Beat sheet for the Shroti Host Short — the single source of timing for picture AND sound.

  python3 scripts/legacy/shrotihost_plan.py

Reads  public/voiceover/shrotihost.json   (word timings from scripts/legacy/voiceover.py)
Writes src/shrotihost/timeline.json       (acts, spoken beats, derived UI events -> Remotion scenes)
       audio/shrotihost-cues.json         (SFX cue sheet at the same times -> scripts/legacy/mix_audio.py)

Re-run after regenerating the voiceover: every visual and every sound moves with the narration.
"""
import json, os, re

FPS = 30
TAIL = 0.7            # hold after the last word
VOICE_START = 0.0     # narration offset inside the final mix
DOMAIN = "yourbrand.in"

vo = json.load(open("public/voiceover/shrotihost.json"))
words = vo["words"]
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())

# (beat name, spoken word) in narration order; searched sequentially so repeats resolve correctly
ORDER = [
    ("building", "building"), ("website", "website"), ("in", "in"), ("india", "india"),
    ("stop", "stop"), ("overpaying", "overpaying"), ("slow", "slow"), ("hosting", "hosting"),
    ("problem", "most"), ("hook", "hook"), ("cheap", "cheap"), ("intros", "intros"), ("then", "then"),
    ("triple", "triple"), ("renewal", "renewal"),
    ("turn", "meet"), ("shroti", "shroti"), ("host", "host"), ("fast", "fast"), ("nvme", "nvme"),
    ("starting", "starting"), ("n49", "49"), ("month", "month"), ("with", "with"), ("same", "same"),
    ("renewal2", "renewal"),
    ("journey", "pick"), ("grow", "grow"), ("n79", "79"), ("type", "type"), ("domain", "domain"),
    ("launch", "launch"), ("minutes", "minutes"), ("litespeed", "litespeed"), ("free", "free"),
    ("ssl", "ssl"), ("daily", "daily"), ("backups", "backups"),
    ("resolution", "no"), ("hidden", "hidden"), ("hikes", "hikes"), ("launch2", "launch"),
    ("today", "today"), ("url", "shrotihost"),
]
beats, i = {}, 0
for name, needle in ORDER:
    while i < len(words) and not norm(words[i]["text"]).startswith(needle):
        i += 1
    if i == len(words):
        raise SystemExit(f"beat '{name}' ('{needle}') not found in narration — script changed?")
    beats[name] = round(VOICE_START + words[i]["start"], 3)
    i += 1

end = round(VOICE_START + vo["duration"] + TAIL, 3)
b = beats
acts = {
    "hook": [0.0, b["problem"]],
    "problem": [b["problem"], b["turn"]],
    "turn": [b["turn"], b["journey"]],
    "journey": [b["journey"], b["resolution"]],
    "resolution": [b["resolution"], end],
}

# --- derived UI events (frame-quantised so picture and sound agree to the frame) ---
q = lambda s: round(round(s * FPS) / FPS, 3)
type_start = q(b["type"] + 0.10)
rhythm = [2, 2, 3, 2, 2, 2, 3, 2, 2, 3, 2, 2]     # frames per keystroke: human, not metronomic
key_times, f = [], round(type_start * FPS)
for k, _ in enumerate(DOMAIN):
    key_times.append(round(f / FPS, 3)); f += rhythm[k % len(rhythm)]
events = {
    "planCards": [q(b["journey"] + 0.05), q(b["journey"] + 0.15), q(b["journey"] + 0.25)],
    "growClick": q(b["grow"] + 0.45),
    "typeStart": type_start,
    "keyTimes": key_times,
    "available": q(key_times[-1] + 0.25),
    "launchClick": q(b["launch"]),
    "live": q(b["minutes"] + 0.2),
    "logoMove": q(b["fast"]),
    "priceCountEnd": q(b["n49"] + 0.5),
    "ctaClick": q(b["url"] + 0.55),
}
timeline = {"fps": FPS, "duration": end, "voiceStart": VOICE_START, "domain": DOMAIN,
            "acts": acts, "beats": beats, "events": events}
os.makedirs("src/shrotihost", exist_ok=True)
json.dump(timeline, open("src/shrotihost/timeline.json", "w"), indent=1)

# --- SFX cue sheet: subtle UI layer under the voice (gains in dB, kit peak-normalised to -3 dBFS) ---
K = ["key/fs-348239-mech-keyboard-01-wav-1", "key/fs-348238-mech-keyboard-02-wav-1", "key/fs-180974-key-1",
     "key/fs-194799-keyboard5-wav-1", "key/fs-442649-keyboard-click-mp3", "key/fs-539146-keyboard-typing-001-wav-2",
     "key/fs-539146-keyboard-typing-001-wav-3", "key/fs-570755-keyboard-key-release-1"]
POP = ["pop/fs-506546-pop-01-wav-1", "pop/fs-506545-pop-02-wav-1", "pop/fs-97978-pop-aif-1",
       "pop/fs-97978-pop-aif-2", "pop/fs-97978-pop-aif-3"]
CLICK = "click/fs-399443-mouse-clicks"
SWOOSH_SCENE = "transition/fs-444623-swoosh-10-wav-1"
SWOOP = ["whoosh/fs-30241-swoop2g-flac-1", "whoosh/fs-30240-swoop1-flac-1"]
SWISH = "swish/fs-14175-27-wav-2"
DING = ["chime/fs-404104-glass-ding-1", "chime/fs-404104-glass-ding-2", "chime/fs-404104-glass-ding-3"]
THUD = "thump/fs-405537-thud-2-wav-1"

cues = []
def cue(cid, t, sound, gain, visual="appear", align="peak"):
    cues.append({"id": cid, "t": round(t, 3), "sound": sound, "gain_db": gain, "visual": visual, "align": align})

cue("intro", 0.12, SWISH, -12, "move")
cue("stop-swap", b["stop"] - 0.05, SWOOSH_SCENE, -11, "cut")
cue("stop-stamp", b["stop"] + 0.08, THUD, -9, "land")
cue("overpay-tag", b["overpaying"] + 0.05, POP[0], -13)
cue("to-problem", b["problem"] - 0.05, SWOOSH_SCENE, -11, "cut")
cue("hook-tag", b["hook"] + 0.05, SWISH, -12, "move")
cue("intro-bar", b["cheap"] + 0.05, POP[1], -14)
cue("renewal-bar", b["triple"] + 0.45, SWOOP[0], -13, "move")
cue("3x-badge", b["triple"] + 0.6, THUD, -9, "land")
cue("logo-build", b["shroti"], "reverse/fs-503803-reverse-fx-13-wav-1", -14, "land", "end")
cue("logo-land", b["shroti"], THUD, -8, "land")
cue("logo-ding", b["shroti"] + 0.02, DING[2], -13, "land")
cue("logo-move", events["logoMove"] + 0.2, SWOOP[1], -15, "move")
cue("nvme-chip", b["nvme"], POP[2], -13)
for k in range(5):  # counter ticks while ₹0 -> ₹49 counts up
    cue(f"count-{k}", b["n49"] + k * 0.1, "tick/fs-386206-ratchet-stahlwille-tighten-1-3", -20)
cue("price-land", events["priceCountEnd"], POP[3], -12, "land")
cue("row-today", b["with"], POP[4], -15)
cue("row-renewal", b["same"], DING[0], -15)
cue("same-price", b["renewal2"] + 0.05, DING[1], -14)
cue("to-journey", b["journey"] - 0.05, SWOOSH_SCENE, -11, "cut")
for k, t in enumerate(events["planCards"]):
    cue(f"plan-{k}", t + 0.08, POP[k], -15)
cue("grow-click", events["growClick"], CLICK, -7)
cue("plans-out", b["type"] - 0.08, SWISH, -14, "move")
for k, t in enumerate(events["keyTimes"]):
    cue(f"key-{k}", t, K[k % len(K)], -13 - (k % 3))
cue("available", events["available"], DING[0], -15)
cue("launch-click", events["launchClick"], CLICK, -7)
cue("live", events["live"], DING[2], -12)
cue("feat-litespeed", b["litespeed"], POP[0], -13)
cue("feat-ssl", b["free"], POP[1], -13)
cue("feat-backups", b["daily"], POP[2], -13)
cue("to-resolution", b["resolution"] - 0.05, SWOOSH_SCENE, -11, "cut")
cue("hikes-strike", b["hikes"] + 0.15, SWISH, -13, "move")
cue("flat-line", b["hikes"] + 0.35, DING[1], -16)
cue("cta-in", b["launch2"] - 0.05, SWOOP[0], -14, "move")
cue("cta-url", b["url"], "shimmer/fs-388295-sparkles-and-percussion-1", -12)
cue("cta-click", events["ctaClick"], CLICK, -9)

sheet = {"fps": FPS, "duration_s": end, "energy": "punchy", "kit": "audio/kit",
         "music": {"file": "audio/music/test-bed.wav", "gain_db": -16, "start_s": 0, "loop": True, "fade_out_s": 1.5},
         "voice": [{"file": "public/voiceover/shrotihost.mp3", "start_s": VOICE_START}],
         "cues": sorted(cues, key=lambda c: c["t"])}
json.dump(sheet, open("audio/shrotihost-cues.json", "w"), indent=1)

print(f"duration {end}s ({round(end * FPS)} frames)")
for k, (a, z) in acts.items():
    print(f"  {k:<11} {a:6.2f} -> {z:6.2f}  ({z - a:4.2f}s)")
print(f"{len(cues)} sfx cues -> audio/shrotihost-cues.json; beats/events -> src/shrotihost/timeline.json")
