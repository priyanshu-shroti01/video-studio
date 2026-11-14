# Notice

Required Notice: Copyright (c) 2026 Priyanshu Shroti (https://github.com/priyanshu-shroti01/video-studio)

Video Studio is source-available under the [PolyForm Shield License 1.0.0](LICENSE). It is free to use, but it is
not open source.

## What the licence allows, in plain language

> **This section is a summary, not the licence.** It is here to help you read the licence, and it may leave things
> out. If this summary and [LICENSE](LICENSE) ever differ, LICENSE is what counts.

You may:
- use Video Studio for free, whoever you are, including at a business, to make videos for your own brands and
  products;
- change the code for your own use;
- share copies, with or without your changes, as long as whoever gets a copy also gets the licence terms (or their
  URL) and the `Required Notice:` line above.

You may not use it to provide a product that competes with Video Studio, or with any product the licensor provides
using it. For example, you may not:
- sell Video Studio, or a modified version of it;
- offer it to others as a hosted or online service;
- build a competing video tool on it.

Counting as "competing" does not depend on price: a free product can compete too. Read the Noncompete, Competition
and New Products sections of [LICENSE](LICENSE) for the exact rules.

The software comes as is, with no warranty.

The licence covers copyright and patents only. It gives no right to use the names or logos of Video Studio, Shroti
Host or any other brand in this repository.

## Third-party terms

Parts of Video Studio are other people's work and keep their own licences. Nothing in this repository changes those
terms. [docs/LICENSING.md](docs/LICENSING.md) has the full list with versions and sources, and every rendered video
records the licence of each asset it used in `output/<job>/assets/manifest.json`.

### Remotion (the video renderer)

Remotion has its own licence (`node_modules/remotion/LICENSE.md`). It is free, including for commercial videos, if
you are:
- an individual;
- a for-profit company with up to 3 employees;
- a non-profit;
- still evaluating it, without using it commercially.

**A larger company needs a paid Remotion Company License** ([remotion.pro/license](https://www.remotion.pro/license)).
This applies to you even though Video Studio itself is free, so check your headcount before using it at work.

### AI models (all run on your Mac)

| Model | Licence | Notes |
|---|---|---|
| Kokoro-82M v1.0 voice model and its voices | Apache-2.0 | the default voice |
| Piper voices en_GB-cori-medium, en_GB-alba-medium | model MIT; training data CC BY 4.0 | **attribution required if you use these voices** |
| Piper voice en_US-joe-medium | model MIT; training data CC0 | |
| Qwen3-4B-Instruct-2507 (writing model, run through Ollama) | Apache-2.0 | |
| Whisper base.en (speech alignment) | MIT | |

Piper voices whose licences don't clearly allow commercial use (Lessac-derived and CC BY-NC voices) are not used.

### Software tools

| Component | Licence | Notes |
|---|---|---|
| piper-tts, phonemizer, espeak-ng | GPL-3.0 (or later) | used locally as tools; using them privately creates no obligations, but GPL terms apply if you distribute software or an app built on them |
| FFmpeg | LGPL/GPL | installed separately (Homebrew), not shipped with Video Studio |
| Ollama | MIT | runs only on 127.0.0.1 |
| edge-tts (optional online voice, off by default) | LGPL-3.0 | uses Microsoft's online service; only used if you turn it on |
| React, TypeScript, esbuild, vitest, eslint, kokoro-onnx, onnxruntime, faster-whisper, ctranslate2, mcp | MIT or Apache-2.0 | |

### Fonts, music, sound and icons

| Asset | Licence | Notes |
|---|---|---|
| Fonts: Plus Jakarta Sans, Geist Mono | SIL Open Font License 1.1 (OFL-1.1) | include the OFL text if you pass the font files on (`public/shared/fonts/LICENSES.md`) |
| Music (`audio/music/`) | CC0-1.0 | each track's source is recorded in `audio/music/library.json` |
| Sound effects (`audio/kit/`) | CC0 | from Freesound, through the opus-sound-layer manifest |
| UI icons in the video engine | ISC | simplified from [Lucide](https://lucide.dev) |
| WordPress icon | CC0-1.0 | from [Simple Icons](https://simpleicons.org) |

### Trademarks

WordPress® is a trademark of the WordPress Foundation. The WordPress icon is used unmodified, only to refer to
WordPress, and does not imply endorsement ([WordPress trademark policy](https://wordpressfoundation.org/trademark-policy)).

The Shroti Host and Video Studio logos are their owner's trademarks and are not covered by the licence. Other brand
logos belong to their owners.

### Synthetic voice

Narration is made by a synthetic voice. Exported YouTube metadata marks videos as containing synthetic media; keep
that setting when you upload.
