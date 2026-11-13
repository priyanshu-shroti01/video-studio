# QA guide

Quality is checked twice: on the **storyboard preview**, before any voice or render is spent on it, and on the
**final file**, after the render. A person signs off after each.

| Step | What runs | Who decides |
|---|---|---|
| `production preview` | one still per scene + the storyboard preview gate (`pipeline/preview_gate.py`) | a named reviewer approves the preview (`production approve-preview`) |
| QA stage of the render job | file, audio, caption, visual, branding and sync checks on the real MP4 (`pipeline/qa.py`, `visual_qa/`, `sync_check.py`) | the job reaches `COMPLETED` only when no critical check fails |
| AWAITING_APPROVAL | review flags, including the mandatory pronunciation and final-watch checks | a named reviewer approves the package ([PUBLISHING_APPROVAL.md](PUBLISHING_APPROVAL.md)) |

## Storyboard preview gate

`uv run video-pipeline production preview --id <P>` renders one still per scene from **estimated** timings (no
TTS), builds `preview/contact-sheet.jpg`, and writes `preview/gate.json` and `preview/GATE.md`.

| Check | Fails / warns when |
|---|---|
| `preview.empty_scenes` | FAIL: a scene still is mostly backdrop (content density below 2.5 %) |
| `preview.repetition` | FAIL: two consecutive scene stills look alike |
| `storyboard.hero_visual` | FAIL: a scene has only headline/text/pill blocks (a hook may lead with a headline or kinetic text) |
| `storyboard.invented_labels` | FAIL: on-screen "Label: ₹N"-style text (invented UI) |
| `storyboard.numbers_verified` | FAIL: a number on screen (including `price.amount` and `plan-card.price`) that is not in `knowledge/<brand>/facts.json` |
| `layout.overflow` | FAIL: text overflows its box in the engine's layout manifest |
| `storyboard.narration_sync` | FAIL: narration runs more than 3 s with no visual event, or a number appears more than 0.3 s before it is spoken; WARN above 2.5 s (`pipeline/sync_check.py`) |
| `storyboard.variety` | WARN: fewer than 5 distinct block types in the video |
| `storyboard.backdrop_rhythm` | WARN: the same backdrop in more than 3 consecutive scenes |

The gate records the **storyboard hash** it checked.

### Human preview approval

Look at the contact sheet and `GATE.md`, then:

```bash
uv run video-pipeline production approve-preview --id <P> --reviewer "Your Name" [--note "what you checked"]
```

or press **Approve preview for rendering** in the Studio (Preview & QA). The approval is refused when the gate
FAILed, when there is no preview yet, or when the storyboard changed after the preview (re-run the preview).
It is bound to that storyboard hash: `production render` is refused for any other storyboard. An audited override
exists (`production render --skip-preview-review "<reason>"`); it leaves a blocking `human:preview-not-reviewed`
flag for the final approval.

### Timing estimates

Preview, creative rules, concept fitting and the Studio estimate durations at **2.33 words/s**. The local voice
(Kokoro `am_michael` at +5 %) measured **2.37 words/s** over three renders; the slightly lower estimate absorbs
pauses. QA on the real voice timings remains the final check.

## Checks on the final file

The pipeline never trusts an exit code. After POST_PROCESSING, the QA stage inspects each final MP4 and its caption
files. A job reaches `COMPLETED` only when **no critical check fails**. Warnings are reported but don't block.

Re-run QA at any time (reports are rewritten; videos never are):

```bash
uv run video-pipeline qa --job-id <JOB_ID>      # exit 0 = PASS/WARN, 3 = FAIL
```

| Id | Category | Critical | Fails when |
|---|---|---|---|
| `file.exists` / `file.nonempty` | structure | yes | file missing or < 10 kB |
| `container.valid` | structure | yes | ffprobe can't read it / not MP4 |
| `stream.video` / `stream.audio` | structure | yes | stream missing |
| `video.resolution` / `video.aspect` | structure | yes | not 1080×1920 (short) / 1920×1080 (landscape), or non-square pixels |
| `video.fps` | structure | yes | not 30.000 |
| `video.codec` | structure | yes | not H.264 yuv420p |
| `video.color_tags` | structure | no | primaries/transfer not BT.709 |
| `video.duration` | structure | yes | differs from the timeline by more than 1.5 frames |
| `audio.duration` | audio | yes | audio and video lengths differ by more than 120 ms (truncation) |
| `decode.full` | structure | yes | full `ffmpeg -f null` decode reports any error |
| `visual.black_frames` | visual | yes | black ≥ 0.1 s anywhere except the planned end fade |
| `visual.frozen` | visual | no | picture static ≥ 3 s (`qa.freezeWarnS`) |
| `visual.blank_scenes` | visual | yes | a scene sample frame is a flat colour (luma range < 24): missing images, failed fonts, empty scene |
| `visual.caption_safe_area` | visual | no | Shorts caption box below `qa.shortsOverlayFrac` (default 20%) |
| `visual.branding` | visual | no | no logo / CTA / brand bar in the storyboard |
| `audio.loudness` | audio | no | integrated loudness outside target ± `qa.lufsTolerance` |
| `audio.true_peak` | audio | yes | true peak above `qa.maxTruePeak` (default −1.0 dBTP) |
| `audio.clipping` | audio | yes | any sample at full scale |
| `audio.silence` | audio | yes | ≥ 0.5 s silence overlapping narration |
| `audio.voice_present` | audio | yes | more than 10% of words below −45 dBFS (silent or missing voiceover) |
| `audio.sfx_placed` | audio | no | fewer sound effects placed than planned |
| `captions.srt_valid` / `captions.ass_valid` | captions | yes / no | file unparsable / wrong dialogue count |
| `captions.within_audio` | captions | yes | any cue outside the voiceover |
| `captions.no_overlap` | captions | yes | cues overlap |
| `captions.complete` | captions | yes | caption word count ≠ spoken word count |
| `captions.reading_speed` | captions | no | any cue faster than `captions.maxCps` (25 chars/s) |
| `sync.av_offset` | sync | **yes** | the voice inside the final video lags or leads the voiceover it was built from by more than **45 ms** (≈ 1.4 frames), or drifts by more than 45 ms, measured by cross-correlating loudness envelopes in 4 s windows; also FAIL if it cannot be measured |
| `sync.narration_visual` | sync | no | on the rendered props and the real voice timings: narration runs more than 3 s with no visual event (FAIL) or more than 2.5 s (WARN), or a number appears more than 0.3 s before it is spoken (FAIL). Not critical for the job, because the preview gate blocks this earlier, but shown in QA and review |

### Visual and branding QA (layout manifest + OCR)

| Id | Critical | Fails when |
|---|---|---|
| `layout.text_overflow` / `layout.safe_area` / `layout.caption_band` | yes | text overflows its box, a block leaves the safe area, or a block enters the caption band (layout manifest) |
| `ocr.prices_urls_exact` | yes | on-device OCR (Apple Vision) doesn't read every price and URL back digit-exactly |
| `ocr.titles_legible` | no | a title reads back weakly |
| `ocr.no_template_labels` | yes | "template", "preview", "watermark", "lorem", "made with" … text appears in a frame |
| `brand.logo_aspect` / `brand.logo_present` | yes | a logo is distorted, missing, not in brand colour, or clipped |
| `brand.no_duplicate_branding` / `brand.watermark_safe` / `brand.watermark_render` | yes | the watermark shows together with a logo, touches the caption band, or doesn't render / hide as planned |
| `brand.palette` | no | saturated pixels sit far from the theme palette |

See [BRANDING.md](BRANDING.md) and [WATERMARK_POLICY.md](WATERMARK_POLICY.md).

Earlier stages also validate:
- **Word timestamps** (GENERATING_AUDIO): order, overlaps (fixed under 10 ms, otherwise an error), bounds vs measured audio duration, missing timestamps (over 20% fails).
- **Caption pages** (BUILDING_TIMELINE): coverage, overlap, end ≤ voiceover.

## Inspection artifacts

`previews/<fmt>/contact-sheet.jpg` (12 evenly spaced frames) and `previews/<fmt>/frames/`
(`first`, `middle`, `final`, and one frame 1 s into every scene), plus `previews/preview.mp4`
(640 px proxy). `reports/QA_REPORT.md` summarises every check and `reports/pronunciation-checklist.md` lists every
brand and technical term with its spoken form and timestamp. **Look at the contact sheet before approving.**
Automated checks catch broken files, not bad taste.

Check the length against the target too. The voice speaks about 2.37 words/s, so a six-scene 30–35 s video fits
about 62–70 words once scene gaps and the end tail are counted ([CREATIVE_SYSTEM.md](CREATIVE_SYSTEM.md)), and every
`holdAfter` adds its seconds after the scene's last word.

## What QA cannot detect

- **Pronunciation and delivery.** Listen to `audio/voiceover.wav` with `reports/pronunciation-checklist.md`; the
  `human:pronunciation` review flag stays open until a person has done so.
- **Overall quality.** Whether the video is clear, on-brand and persuasive. The `human:final-watch` flag requires
  a person to watch it end to end.
- **Number-free claims.** The claim checker is lexical: it catches numbers, plans, URLs and a list of risky words,
  but not positioning like "costs less than a coffee". A person reads the storyboard and the metadata.
