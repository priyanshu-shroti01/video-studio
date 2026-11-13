# Local TTS (narration never leaves the machine)

New jobs synthesise narration **locally** with Kokoro-82M (default) or Piper, on the CPU through
onnxruntime. Microsoft Edge TTS remains only as an opt-in legacy provider: it is refused unless the
project's voice section says `"allowOnline": true`, and nothing ever falls back to it.

```
narration (display text) ── pronunciation.prepare ──▶ spoken text ──▶ engine (Kokoro / Piper, local ONNX)
      ▲                                                                      │ audio + per-phoneme durations
      │ timing.map_to_display ◀── timing.align (spoken tokens) ◀── native.words_from_phonemes (+energy snap)
captions show "shrotihost.in", "₹49", "NVMe"            the engine said "Shro-tee Host dot in", "forty nine rupees", "N V M e"
```

## Providers

| provider | runs | word timings | notes |
|---|---|---|---|
| `kokoro` (default) | local, onnxruntime CPU | native: the ONNX export's `durations` output | 82M params, 24 kHz, ~0.7 GB peak RSS |
| `piper` | local, onnxruntime CPU | native: voice patched to expose `w_ceil` | 22 kHz, ~0.3 GB peak RSS, ~10x faster than Kokoro |
| `edge` | **online** (Microsoft) | service word boundaries | legacy; needs `"allowOnline": true` |
| `mock` | local | exact (tones) | tests only |

Voice config (`presets/*.json` → `voice`, overridable per project):

```json
"voice": {"provider": "kokoro", "voice": "am_michael", "rate": "+5%", "pitch": "+0Hz",
          "pronunciation": {"Shroti": "Shrow-tee"}, "maxPause": 0.35, "pad": 0.25, "sceneGap": 0.2}
```

* `rate` maps to Kokoro `speed` / Piper `length_scale`. `pitch` is ignored by local engines (warning).
* `lang` (Kokoro only): phonemizer accent, default from the voice prefix (`a*` en-us, `b*` en-gb, `h*` en-us).
* `pronunciation`: per-project `{display: spoken}` overrides; they win over the shared dictionary.
* Legacy online voice: `{"provider": "edge", "voice": "en-IN-PrabhatNeural", "allowOnline": true}`.

## Models (all in `models/voice/`, git-ignored; registry: `pipeline/voice/registry.json`)

| file(s) | size | licence | source (pinned revision) |
|---|---|---|---|
| Kokoro-82M v1.0 fp32 ONNX, timestamped export | 325.5 MB | Apache-2.0 | `onnx-community/Kokoro-82M-v1.0-ONNX-timestamped@dd4401a` (weights: `hexgrad/Kokoro-82M`) |
| 15 Kokoro voice styles (af_heart, af_bella, af_nicole, am_michael, am_fenrir, am_puck, bf_emma, bf_isabella, bm_george, bm_fable, bm_lewis, hf_alpha, hf_beta, hm_omega, hm_psi) | 7.8 MB | Apache-2.0 | same repo, `voices/*.bin` |
| Piper en_GB-cori-medium, en_GB-alba-medium, en_US-joe-medium (+ .onnx.json, MODEL_CARD) | 3 × 63.2 MB | model MIT; datasets CC BY 4.0, CC BY 4.0, CC0 | `rhasspy/piper-voices@2f358b6` |
| Whisper base.en, CTranslate2 int8-capable | 147.8 MB | MIT | `Systran/faster-whisper-base.en@3d3d5de` |

Downloaded: 333 MB Kokoro, 190 MB Piper, 148 MB Whisper. The `*.aligned.onnx` Piper files are derived
locally (weights unchanged; `w_ceil` marked as a graph output by `piper.patch_voice_with_alignment`,
using `onnx` only at patch time — it is not a runtime dependency).

```
uv run python -m pipeline.voice.registry status        # presence + sha256 of every file
uv run python -m pipeline.voice.registry fetch all     # (re)download, verify, patch Piper voices
```

A missing or modified file raises `VOICE_MODEL_MISSING` (non-transient, not retried) naming that
command; `validate` shows it as a warning.

**Rejected Piper voices** (licence, from each MODEL_CARD): everything trained or fine-tuned from
`lessac` (Blizzard 2013 *research* licence) — lessac, alan, aru, northern_english_male, vctk, kusal,
sam, hfc_male, arctic, l2arctic, hi_IN-rohan; CC BY-NC(-SA): semaine, hfc_female, ryan, l2arctic,
hi_IN-pratham, hi_IN-priyamvada. There is **no en_IN Piper voice**, and no commercially usable hi_IN one.
Kokoro has **no Indian-English voice**; its 4 Hindi voices were evaluated reading English.

## Software (pinned in pyproject.toml / uv.lock)

kokoro-onnx 0.6.1 (MIT; used for its espeak-ng phonemizer + vocab), onnxruntime 1.31.1 (MIT),
piper-tts 1.8.0 (**GPL-3.0-or-later**, bundles espeak-ng), phonemizer 3.4.0 (**GPL-3.0**),
espeakng-loader 0.2.4 (bundles **espeak-ng, GPL-3.0**), faster-whisper 1.2.1 (MIT), ctranslate2 4.8.4
(MIT), av 19.0.2 (BSD), numpy 2.5.4, tokenizers 0.23.3, huggingface-hub 2.3.0 (Apache-2.0; offline mode).
The GPL pieces run as local tools and are not redistributed (same posture as FFmpeg in LICENSING.md);
the audio they help generate is not covered by the GPL. If this repo is ever distributed, revisit this.

## Pronunciation

`pipeline/voice/pronunciation.json` (shared) + `voice.pronunciation` (per project), then rules:
currency (`₹49` → "forty nine rupees", `₹1` → "one rupee"), units (`10GB`, `1 GB`), percentages,
numbers (space-separated words, years as "twenty twenty six"), domains (`*.in`, `.com`, … → "dot"),
`/mo` → "a month", em-dash → comma. Multi-word entries ("Shroti Host") match across tokens. Every
display token maps to ≥ 1 spoken words (`Prepared.groups`); `timing.map_to_display` gives each display
token the span from its first to its last spoken word. Edge keeps its old behaviour (no layer).

Brand respelling is **"Shro-tee"** (hyphen keeps a real /t/; American espeak flaps "Shrotee" to
"Shro-dee" — ASR heard American voices say "Trody/Shrody host" with the flapped form). This is a
best guess at the Indian pronunciation and must be confirmed by ear.

## Word timing (no network)

1. Engines report per-phoneme durations; phonemes are grouped back into the spoken words. espeak
   sometimes merges words ("with the" → `wɪððə`), so then each word is phonemized alone and aligned
   to the sentence phonemes character-by-character (DP), splitting merged words at the phoneme level.
2. Kokoro calibration (measured, below): shift −2 frames, then word edges that touch a pause
   (punctuation, utterance start/end) snap to the audio's energy edges (−40 dB re. peak).
3. `timing.align` maps spoken boundaries onto spoken tokens (now also matching number forms in
   split/merged words), `map_to_display` onto display tokens, `validate_words(..., script=)` checks
   missing / repeated / reordered words, overlaps, bounds and near-zero words.
4. Fallback only if native grouping fails: local Whisper word timestamps (coarse, see below).

### Measured timing accuracy (honest version)

* **Kokoro raw durations vs audio energy** (15 voices × 9 scenes, before calibration): word onsets
  were 35–80 ms late (median ≈ 50 ms), and word ends before a pause were **200–350 ms late**
  (af_nicole: about 680 ms). After the −2-frame shift, the raw onset minus energy onset across 9
  sentences (af_heart) was −43…+50 ms (median −3 ms). This check is independent of the snapping
  step. Pause edges are then energy-snapped, so measuring them against energy afterwards is
  circular. They are exact to the −40 dB definition, nothing more.
* **Piper durations vs energy** (no correction): pause edges within −30…+6 ms, onsets −41…0 ms.
* **Whisper base.en word timestamps are coarse.** On synthetic audio with known boundaries
  (60 isolated words, 50–350 ms random gaps) the start error had a median of 371 ms and a p90 of
  532 ms, and only 9 % of starts were within 100 ms. On natural speech, against Piper's accurate
  native timings: median 118 ms, p90 224 ms (cori). Kokoro native vs Whisper improved after
  calibration from a median of 193 ms to 145 ms (af_heart) and from 225 ms to 180 ms (am_michael).
  So Whisper is only a fallback, and its timings are flagged in `meta.engine.timing_method`.
* Intra-phrase (no-pause) Kokoro edges have **no ground truth here**. Their accuracy is bounded only
  by the agreement figures above. Caption pages break at pauses, so the edges that matter most are
  the calibrated ones.

## Evaluation (output/eval-voice/, `uv run python -m pipeline.voice.evaluate run`)

Real narration: all 9 scenes of `projects/shrotihost/shrotihost-short.storyboard.json`, rate +5 %, M1 Pro, CPU,
4 threads, one fresh process per voice. ASR round-trip: Whisper base.en without a prompt, WER against
the *spoken* script, with "light"/"lite" counted as the same word. "Brand heard" counts scenes where
ASR wrote something within 0.7 similarity of shroti/shrotee/shrotihost.

| voice | accent | author grade | load s | RTF | peak RSS MB | narration s | words/s | WER | brand heard |
|---|---|---|---|---|---|---|---|---|---|
| **kokoro am_michael (default)** | US m | C+ | 0.71 | 0.33† | 596 | 33.3 | 2.59 | **0.024** | 2/2 ("Shroti Host", "shroteahost.in") |
| kokoro af_heart | US f | A | 0.90 | 0.28† | 679 | 30.2 | 2.90 | 0.047 | 2/2 ("Trotihost") |
| kokoro af_nicole | US f | B- | 0.74 | 0.30† | 677 | 41.4 | 1.87 | 0.024 | 2/2 (slow, breathy) |
| kokoro am_fenrir / am_puck | US m | C+ | 0.6–0.7 | 0.23 | 679–697 | 30.2–30.4 | 2.9 | 0.035 | 2/2 |
| kokoro bm_fable | GB m | C | 0.58 | 0.23 | 704 | 34.6 | 2.48 | 0.035 | 2/2 ("Shruti Host") |
| kokoro bm_george | GB m | C | 0.59 | 0.22 | 697 | 35.7 | 2.38 | 0.071‡ | 2/2 |
| kokoro bf_emma / bf_isabella | GB f | B- / C | 0.59 | 0.23 | 678 | 30.0–30.6 | 2.85–2.92 | 0.082 | 2/2 ("Shroti Host") |
| kokoro hm_omega (en-us) | Hindi m | C | 0.57 | 0.22 | 695 | 34.0 | 2.54 | 0.035 | 2/2 |
| kokoro hf_alpha (en-us / en-gb) | Hindi f | C | 0.58 | 0.23 | 694 | 33.7 | 2.57 | 0.059 | 2/2 |
| kokoro hf_beta / hm_psi | Hindi f / m | C | 0.58 | 0.22 | 681–699 | 30.7 / 33.7 | 2.6–2.9 | 0.129 / 0.106 | 1/2 |
| piper en_GB-cori-medium | GB f | – | 0.72 | 0.030 | 375 | 28.7 | 2.98 | 0.094 | 2/2 |
| piper en_GB-alba-medium | GB/Scot f | – | 0.70 | 0.027 | 320 | 30.5 | 2.84 | 0.118 | 1/2 |
| piper en_US-joe-medium | US m | – | 0.71 | 0.028 | 320 | 29.5 | 2.97 | 0.224 | 1/2 |

† Measured while another job was rendering (8–10 chrome-headless-shell processes; the swap delta
was +245 MB for af_bella). Uncontended Kokoro RTF was 0.22–0.23 for every voice. ‡ 3 of george's 6
errors were ASR inserting "www." before the domain. Swap delta was 0 ± 8 MB for every uncontended
run. Whisper: 0.34 s load warm (5.3 s cold), RTF ≈ 0.08–0.14, 850 MB peak RSS. CoreML execution provider (measured on
Kokoro): RTF 0.26 (ALL) / 0.25 (CPUAndGPU) vs 0.23 on CPU, load 4.5 s / 1.9 s vs 0.7 s, and
**1.8 GB** peak RSS vs 0.7 GB. So CPU it is.

Brand respelling A/B, 40 brand scenes over all voices: "Shrohtee" → ASR brand-like 28/40 (literal
"shroti" 2/40); **"Shro-tee"** → 35/40 (literal 5/40).

**Default: Kokoro `am_michael`.** It had the lowest measured WER (tied with af_nicole, which is much
slower), ASR transcribed "Shroti Host" verbatim, it's male like the previous default, and it's
Apache-2.0. The evidence is **weak**: 85 spoken words per voice, and most voices differ by one or
two words. Naturalness, accent and brand pronunciation **need a human**: see
`output/eval-voice/LISTENING_CHECKLIST.md`. No Indian-English voice exists in either engine. The Hindi
Kokoro voices reading English are the closest candidates and are in the checklist.

## Memory

Kokoro peaks at about 0.7 GB, Piper at 0.3 GB and Whisper at 0.85 GB, and they never load together.
By default the engine runs in a **worker process** (`pipeline/voice/worker.py`). It exits after 20 s
idle (`VIDEO_PIPELINE_TTS_IDLE_UNLOAD_S`), on `tts.unload_all()`, or when the parent exits.
Measured: freeing the onnxruntime session inside a long-lived process left RSS at about 620 MB, and
disabling the arena didn't help. With the worker, the parent stays at about 25 MB and the memory goes
back to the OS. The worker also makes `voice.timeout` enforceable (transient error, retried).
`VIDEO_PIPELINE_TTS_INPROCESS=1` runs in-process (evaluation, debugging).

## Caching

Same content-addressed cache (`.pipeline/cache/tts`). Local keys add the spoken text, the options and
the engine version (`kokoro-onnx0.6.1/<model sha>/t2`, `piper-tts1.8.0`). Edge keys are byte-for-byte
unchanged, so existing Edge entries stay valid. Nothing deletes them. Entries are re-validated on every
hit (sha256, full decode, duration, text) and rebuilt if corrupt. `tts.voice_fingerprint(v)`
(pronunciation dictionary and model hashes) should go into the runner's stage key.

## Known limitations

* Intra-phrase Kokoro word edges are calibrated by a global shift only, with no per-word ground truth.
* espeak-ng decides how unknown words sound. Brand respellings are guesses until a human confirms them.
* `pitch` is ignored by local engines. `&` and other symbol-only tokens are not spoken.
* Kokoro's context is 510 phonemes per pass. Longer scenes are split at sentence ends with a 0.25 s
  gap. The validator already limits a scene to 3,000 characters.
* The GPL components (espeak-ng, phonemizer, piper-tts) are fine for local use. Review them before
  redistributing this repo.
