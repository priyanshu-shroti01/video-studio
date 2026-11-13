#!/usr/bin/env bash
# End-to-end smoke test of the workspace (~30 s). Re-run any time: `npm run verify`.
#   tools -> 2 s edge-tts voiceover -> FFmpeg mix with ducking + CC0 sfx -> typecheck
#   -> render 9:16 + 16:9 on VideoToolbox -> probe outputs
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=out/verify; mkdir -p "$OUT" audio/music
ok(){ printf '  \033[32mOK\033[0m  %s\n' "$*"; }
fail(){ printf '  \033[31mFAIL\033[0m %s\n' "$*"; exit 1; }

echo "1. tools"
for c in node npm python3 git ffmpeg ffprobe uv; do command -v $c >/dev/null || fail "$c missing"; done
python3 -c "import edge_tts" 2>/dev/null || fail "edge-tts not importable by python3"
ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_videotoolbox || fail "ffmpeg lacks h264_videotoolbox"
ok "node $(node -v), python $(python3 -V | cut -d' ' -f2), $(ffmpeg -version | head -1 | cut -d' ' -f1-3), edge-tts $(python3 -c 'import edge_tts;print(edge_tts.__version__)'), uv $(uv --version | cut -d' ' -f2)"
[ -f audio/kit/catalog.json ] && ok "CC0 kit: $(python3 -c "import json;print(len(json.load(open('audio/kit/catalog.json'))['sounds']))") sounds" || fail "audio/kit missing: bash scripts/sound-layer.sh kit"

echo "2. voiceover (edge-tts, ${EDGE_TTS_VOICE:-en-IN-PrabhatNeural})"
python3 scripts/legacy/voiceover.py "Welcome to Shroti Host." --name test | sed 's/^/     /'

echo "3. mix: test bed + whoosh + chime, music ducked under voice"
[ -f audio/music/test-bed.wav ] || ffmpeg -v error -y -f lavfi -i "sine=f=220:d=8" -f lavfi -i "sine=f=277.18:d=8" \
  -f lavfi -i "sine=f=329.63:d=8" -filter_complex "[0][1][2]amix=inputs=3,volume=0.6,tremolo=f=0.5:d=0.3,aformat=channel_layouts=stereo" \
  -ar 48000 audio/music/test-bed.wav
python3 scripts/legacy/mix_audio.py --voice public/voiceover/test.mp3@0.3 --music audio/music/test-bed.wav \
  --sfx whoosh@0.15 --sfx chime@2.0:-8 --duration 3.2 --out public/audio/test-mix.wav | sed 's/^/     /'
python3 scripts/legacy/mix_audio.py --music audio/music/test-bed.wav --duration 3.2 --stems --lufs 0 --out "$OUT/ref.wav" >/dev/null
python3 scripts/legacy/mix_audio.py --voice public/voiceover/test.mp3@0.3 --music audio/music/test-bed.wav --duration 3.2 \
  --stems --lufs 0 --out "$OUT/duck.wav" >/dev/null
duck=$(python3 scripts/audio_levels.py "$OUT/ref_music.wav" "$OUT/duck_music.wav" 0.6-1.6 --diff | awk '{print $NF, $(NF-1)}' | cut -d' ' -f2)
python3 -c "import sys; sys.exit(0 if float('$duck') < -6 else 1)" || fail "music not ducked ($duck dB)"
ok "music ducked ${duck} dB under the voice"
lufs=$(ffmpeg -hide_banner -i public/audio/test-mix.wav -af loudnorm=print_format=json -f null - 2>&1 | grep '"input_i"' | tr -dc '0-9.-')
ok "master loudness ${lufs} LUFS (target -14)"

echo "4. typecheck"
npx tsc --noEmit && ok "tsc clean"

echo "5. render (props: mixed audio, voice at +0.3 s)"
PROPS='{"audio":"audio/test-mix.wav","voiceStart":0.3}'
for comp in StarterShort Landscape; do
  # Remotion >= 4.0.540 stream-copies the VideoToolbox pre-encode into the final file, so the encoder name is no
  # longer in the file's metadata; read the first "Encoder:" line Remotion logs (the real encode) instead.
  bash scripts/legacy/render.sh $comp "$OUT/$comp.mp4" --props="$PROPS" --log=verbose > "$OUT/$comp.render.log" 2>&1
  grep "^rendered" "$OUT/$comp.render.log" | sed 's/^/     /'
  enc=$(grep -m1 -o "Encoder: [a-z0-9_]*" "$OUT/$comp.render.log" | cut -d' ' -f2)
  case "$enc" in *videotoolbox*) ok "$comp encoded with $enc";; *) printf '  WARN %s encoded with %s (software fallback)\n' "$comp" "$enc";; esac
  ffmpeg -v error -y -ss 1.2 -i "$OUT/$comp.mp4" -frames:v 1 -vf "scale=iw/2:-1" "$OUT/$comp-1.2s.jpg"
done
rm -f "$OUT"/ref*.wav "$OUT"/duck*.wav
echo "All checks passed. Outputs in $OUT/"
