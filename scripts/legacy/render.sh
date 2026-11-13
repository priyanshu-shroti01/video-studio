#!/usr/bin/env bash
# Render a composition with the Apple-Silicon settings from remotion.config.ts
# (h264_videotoolbox + ANGLE/Metal Chromium + 6 parallel tabs).
#
#   bash scripts/legacy/render.sh Short                       -> out/Short.mp4
#   bash scripts/legacy/render.sh Landscape out/yt.mp4
#   bash scripts/legacy/render.sh Short out/s.mp4 --props='{"voiceover":"voiceover/intro.json","audio":"audio/mix.wav"}'
#   REMOTION_HW=required bash scripts/legacy/render.sh Short   # fail instead of falling back to software x264
#   HQ=1 bash scripts/legacy/render.sh Short out/final.mp4     # final delivery: PNG frames, BT.709, 40 Mbps
set -euo pipefail
cd "$(dirname "$0")/../.."
COMP=${1:-Short}
OUT=${2:-out/${COMP}.mp4}
shift $(( $# >= 2 ? 2 : $# ))
mkdir -p "$(dirname "$OUT")"
# HQ=1: final-delivery quality — lossless PNG frame capture (no JPEG artefacts on text/gradients),
# BT.709 colour tagging (correct colours on YouTube/phones), 40 Mbps VideoToolbox encode.
HQ_FLAGS=()
[ "${HQ:-0}" = 1 ] && HQ_FLAGS=(--image-format=png --color-space=bt709 --video-bitrate="${REMOTION_BITRATE:-40M}")
start=$(date +%s)
npx remotion render "$COMP" "$OUT" ${HQ_FLAGS[@]+"${HQ_FLAGS[@]}"} "$@"
if [ "${HQ:-0}" = 1 ]; then
  # Remotion tags only the BT.709 matrix; add primaries + transfer too (lossless stream copy)
  ffmpeg -v error -y -i "$OUT" -map 0 -c copy \
    -bsf:v h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0 \
    -movflags +faststart "$OUT.tagged.mp4" && mv "$OUT.tagged.mp4" "$OUT"
fi
secs=$(( $(date +%s) - start ))
info=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,bit_rate:stream_tags=encoder -of compact=p=0:nk=0 "$OUT")
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")
echo "rendered  $OUT  in ${secs}s  (${dur}s)  $info"
