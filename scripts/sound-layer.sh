#!/usr/bin/env bash
# Thin passthrough to the opus-sound-layer tools in skills/ (run via uv, which
# installs numpy/scipy/soundfile/pyloudnorm on the fly). Run from the project root.
#
#   bash scripts/sound-layer.sh kit                               # (re)build audio/kit (CC0 library)
#   bash scripts/sound-layer.sh browse --type whoosh --like "air soft"   # rank + draw audio/browse.png
#   bash scripts/sound-layer.sh search "camera shutter" --type click     # find more CC0 via Openverse
#   bash scripts/sound-layer.sh mix audio/cues.json               # full designer mix -> audio/mix.wav
#   bash scripts/sound-layer.sh mix --schema                      # cue sheet format
#   bash scripts/sound-layer.sh qa out/final.mp4                  # sync / loudness / audibility QA
set -euo pipefail
cd "$(dirname "$0")/.."
S=skills/opus-sound-layer/scripts
cmd=${1:-help}; shift || true
case "$cmd" in
  kit|browse|search|add|analyze|sheet) exec uv run "$S/sfx.py" "$cmd" "$@" ;;
  mix) exec uv run "$S/mix.py" "$@" ;;
  qa)  exec uv run "$S/qa.py" "$@" ;;
  *)   sed -n 2,11p "$0" ;;
esac
