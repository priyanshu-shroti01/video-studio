# Licensing (v0.4.0)

**This project's own code is proprietary.** Copyright (c) 2026 Priyanshu Shroti. All rights reserved. See
[LICENSE](../LICENSE). Third-party components keep their own licences, listed below; nothing in this repository
changes them.

This file covers what each third-party component permits for **commercial** use. Every job also writes
`output/<job>/assets/manifest.json` (sha256, source, licence, attribution of every asset used); anything
without a licence record becomes a **blocking** review flag before approval.

## Decisions that need the owner's attention

1. **Remotion** (4.0.540) is free only for individuals, non-profits and for-profit organisations with **up to 3
   employees** (`node_modules/remotion/LICENSE.md`). A larger company needs a paid Company License. This is the
   one cost risk in the stack. Check the headcount.
2. **anything2explainer** (an optional third-party skill) is **PolyForm-Noncommercial-1.0.0**: "any commercial use of the toolkit requires
   prior authorization from the author". This project does **not** run, vendor or copy its code or text; only the
   MIT skills (demo-video-skill, opus-sound-layer) are used. Get the author's authorisation before using it.
3. **Default voice**: Kokoro `am_michael` (Apache-2.0). Its author grades it C+ and `af_heart` A; it was chosen on
   measured intelligibility, so a listening check is still needed (see [LOCAL_TTS.md](LOCAL_TTS.md) and each video's
   `reports/pronunciation-checklist.md`).

## Software

| Component | Licence | Notes |
|---|---|---|
| Remotion 4.0.540 (+ local loopback patch) | Remotion License | see decision 1 |
| React, TypeScript, esbuild, vitest, eslint | MIT / Apache-2.0 | |
| FFmpeg (Homebrew) | LGPL/GPL | local tool, not redistributed |
| kokoro-onnx 0.6.1, onnxruntime 1.31.1, faster-whisper 1.2.1, ctranslate2 4.8.4 | MIT | |
| **piper-tts 1.8.0, phonemizer 3.4.0, espeak-ng (bundled by espeakng-loader)** | **GPL-3.0(-or-later)** | used locally as tools/libraries. Private use creates no obligations; **if you ever distribute this software (or an app built on it), GPL terms apply** |
| Ollama 0.40.16 | MIT | bound to 127.0.0.1, cloud models refused |
| edge-tts 7.3.1 (legacy, opt-in) | LGPL-3.0 | Microsoft's online service; disabled unless `voice.allowOnline` |
| Skills: demo-video-skill, opus-sound-layer | MIT | optional local tooling; not part of this repository |
| mcp 2.3.0 (Python MCP SDK, `video-pipeline-mcp`) | MIT | stdio server, local only |

## AI models (all local, sha256-recorded)

| Model | Licence | Source |
|---|---|---|
| Kokoro-82M v1.0 (weights + 15 voices) | Apache-2.0 | hexgrad weights via onnx-community/Kokoro-82M-v1.0-ONNX-timestamped@dd4401a (`pipeline/voice/registry.json`) |
| Piper en_GB-cori-medium, en_GB-alba-medium | model MIT, **dataset CC BY 4.0: attribution required if used** | rhasspy/piper-voices@2f358b6 |
| Piper en_US-joe-medium | model MIT, dataset CC0 | same |
| Whisper base.en (CTranslate2) | MIT | Systran/faster-whisper-base.en@3d3d5de |
| Qwen3-4B-Instruct-2507 Q4_K_M (creative engine) | Apache-2.0 | Ollama registry; licence checked in the model's licence layer and the HF card (`pipeline/intelligence/model_registry.json`) |
| Qwen3.5 (pre-existing, not used by default) | Apache-2.0 | already on disk; too large for current memory |

**Rejected** (not cleared for commercial use): Lessac-derived Piper voices (research licence), CC BY-NC(-SA)
voices including the Hindi Piper voices, hi_IN-rohan. There is no en-IN voice in either Piper or Kokoro;
Kokoro's Hindi voices reading English were evaluated instead (see LOCAL_TTS.md).

## Media

| Asset | Licence | Records |
|---|---|---|
| Sound effects (`audio/kit/`, 830 files) | CC0, 619/619 Freesound sources declared CC0 in opus-sound-layer's pinned manifest | looked up by Freesound id (asset registry) |
| Music (`audio/music/`, 7 tracks, 12.5 MB) | **CC0-1.0, each verified twice** (Openverse API + the source landing page) | `audio/music/library.json` (creator, URLs, sha256) |
| `audio/music/test-bed.wav` | self-generated test tone, **not publishable** | blocks approval if used |
| Fonts (Plus Jakarta Sans, Geist Mono): shared copies in `public/shared/fonts/` (Studio UI, default for new brands) and per-brand copies in `public/brands/<id>/fonts/` | OFL-1.1 | `public/shared/fonts/LICENSES.md`, `public/shared/assets.json`; include the OFL text if you redistribute the font files |
| WordPress icon (`public/shared/logos/wordpress.svg`) | CC0-1.0, from [Simple Icons](https://simpleicons.org) 16.37.0 (fill set to white) | `public/shared/assets.json`. **Trademark:** WordPress® is a trademark of the WordPress Foundation; used unmodified, only to refer to WordPress (nominative use), without implying endorsement ([policy](https://wordpressfoundation.org/trademark-policy)) |
| UI icons in the engine (`src/engine/ui.tsx`) | ISC | paths simplified from Lucide |
| Studio icon (`public/shared/studio/icon.svg`) | self-made | `public/shared/assets.json` |
| Shroti Host logos | proprietary (owner's trademark) | `brands/shrotihost/assets.json` |
| Video Studio logos (`public/brands/videostudio/logos/`) | proprietary, self-made (wordmark outlined from Plus Jakarta Sans, OFL) | `brands/videostudio/assets.json` |
| Video Studio screen recordings (`public/brands/videostudio/footage/`) | proprietary, self-recorded with `scripts/capture_studio.mjs` from the running Studio | `brands/videostudio/assets.json`; the publishing clip shows a Shroti Host production's real Studio page |
| `acme-demo` brand | self-made test assets | fictional; tests only |

One downloaded track ("horror atmosphere") is CC0 but tagged horror/scary, so it's marked `brandSafe: false`
and never selected. Moods were assigned from search terms and tags, not by listening.

## Disclosure

Narration is synthetic. Export metadata sets YouTube's `containsSyntheticMedia: true`; keep it when uploading.
