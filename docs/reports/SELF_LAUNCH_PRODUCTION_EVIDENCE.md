# Self-launch film: production evidence

This film was produced with Video Studio itself. It went through the studio's own production pipeline as
production `P20261114-014553-24d69` (brand `videostudio`). The brief was entered in the studio's New Production
form while being recorded; that recording appears in the film.

This report records how, so another engineer can trace every step. It grows with each iteration.

## Production record

| | |
|---|---|
| Production | `P20261114-014553-24d69` (`video-studio-self-launch`), created 2026-11-14 through the Studio UI |
| Brief | brand Video Studio; product Video Studio; audience "Developers, creators and product teams"; goal launch; target 80 s with `duration_flexible`; formats short + landscape; CTA "Explore the code" |
| An earlier attempt | `P20261114-014429-c3acf`, archived: the Studio server dropped `duration_flexible` / `formats` from briefs (bug found by this production, fixed in `studio/server.py`, test added) |

## Iteration 1

| | |
|---|---|
| Concept | `c1` "It Created Itself" (9 scenes), chosen in the Studio; storyboard built by the hybrid engine |
| Preview | gate PASS on 9/9 checks; preview approval recorded for "Priyanshu Shroti", delegated in chat for iteration previews |
| Render job | `20261114-020340-1b4478`: 1080×1920 and 1920×1080, 61.0 s each, Kokoro `am_fenrir`, licensed music (mood: technology) |
| Audio | −14.2 LUFS integrated, −1.4 dBTP true peak, 0 clipped samples |
| Sync | voice in video vs voice-over: max lag 0 ms, drift 0 ms over 14 windows |

### Two pipeline bugs this production found

1. **Preview approval refused for every storyboard with footage.** The preview gate hashed the *loaded* storyboard,
   into which loading writes each recording's ffprobe aspect and duration, while approval hashed the file as saved.
   Both now use one digest of the saved files (`preview_gate.saved_storyboard_hash`), with a regression test.
2. **QA failed the film for saying "Remotion renderer".** The stray-label check bans the word "remotion" anywhere in
   frame to catch a leftover Remotion watermark. It now accepts such a word only where the storyboard itself placed
   text containing it (inside that text's box); a "Remotion" anywhere else still fails. Regression test added.

With check 2 fixed, QA was re-run on the same job (`video-pipeline qa --job-id 20261114-020340-1b4478`):

| Format | Checks | PASS | WARN | FAIL | Blocking checks |
|---|---|---|---|---|---|
| 1080×1920 | 42 | 40 | 2 | 0 | 30 / 30 PASS |
| 1920×1080 | 41 | 39 | 2 | 0 | 30 / 30 PASS |

Blocking QA checks: 30 / 30 PASS in both formats.

The two advisory warnings, reviewed by hand:

- `ocr.footage_labels`: words such as "template-composed" and "made with" appear *inside* the screen recordings. They
  are the Studio's real interface text (the concept page and the brief), not overlays. Kept as recorded.
- `captions.reading_speed`: one caption reaches 25 characters per second, at the advisory limit.

### Review of iteration 1 (exact frames, both formats)

- Works: hook, the five-step chain, the logo wipe, the word-anchored zooms into the real recording, the pipeline
  card ending on "Waiting for a person's approval", the local stack, the counter, the outro.
- 16:9 was not truly recomposed: the 1.6:1 recording sat above its caption in a stack, height-bound to 799 px wide
  (42% of the frame). Fix (generic): scenes may set `splitRatio`; the director now lays a recording and its one
  message side by side at 0.66, which lets the recording fill the content height (1000 px wide, about 56% more area).
  Shorts are unchanged (`split` only applies to 16:9).
- The QA scene said "forty-three", the count of an earlier, different video. Iteration 2 states this film's own
  result instead (30 blocking checks), and the copy now takes the spoken number from the fact (`{qa_spoken}`).
- The self-reveal scene shows this production as an empty draft: iteration 2 re-records it with the film itself.

## Iteration 2

Production `P20261114-014553-24d69`, concept `c1` rebuilt with the 16:9 split layout, this film's own QA count
(30 then) and a re-recorded self clip (the Studio's Preview & QA page playing iteration 1). Render job
`20261114-022615-51dce0`, 66.1 s. **QA failed** (`visual.black_frames`, both formats): the QA scene opened on about
1 s of bare dark backdrop, because its first element was anchored to a later word. Fix (generic): a `scene-opens`
rule reports any scene that shows only its backdrop for more than 0.6 s and rejects one beyond 2 s.

## Iteration 3 — the whole pipeline

New brief (`projects/videostudio/briefs/self-launch-full-pipeline.json`): the architecture and every stage of the
real pipeline. Production `P20261114-024949-5e2b5` (an earlier `P20261114-024936-1ec62` with an invalid `voice`
field was archived). Concept `c1` "The Whole Pipeline", 12 scenes: cold open on this film, the usual chain, reveal,
architecture, brief and concepts, pipeline, storyboard and preview gate, local stack, render monitor, QA, approval
and publishing, outro. New recordings of the real Studio: the storyboard page and low-cost preview of this very
production, the render monitor of a completed job, and the publishing page of a published production.

| Run | Job | Result |
|---|---|---|
| 3 | `20261114-025310-92a595` | QA failed: black frames at 0–0.37 s (cold open) and 16.2–17.8 s (architecture opening); and Apple Vision OCR failed at OS level on every frame, which QA had treated as empty frames |
| 3b | `20261114-032249-2034ce` | 9:16 passed; 16:9 failed on the architecture opening (a small pill on a dark frame for 1.6 s) |
| 3c | `20261114-032943-8a5e91` | **QA passed in both formats**, 95.1 s each |

Fixes found by these runs (all generic, with tests): a checklist counts as visible only from its first item; a cold
open shows its recording from the first frame; an OCR engine error is now a blocking `ocr.engine` failure (with
one retry) instead of silently reading as frames without text; the recorder scrolls the page itself.

Iteration 3c QA:

| Format | Checks | PASS | WARN | FAIL | Blocking checks |
|---|---|---|---|---|---|
| 1080×1920 | 43 | 42 | 1 | 0 | 31 / 31 PASS |
| 1920×1080 | 42 | 41 | 1 | 0 | 31 / 31 PASS |

Blocking QA checks: 31 / 31 PASS in both formats.

Audio −14.2 LUFS, −1.4 dBTP; A/V offset 0 ms over 23 windows; no black or frozen frames. The one warning is
`ocr.footage_labels` (the real interface text "template-composed" inside the brief recording). The film said
"thirty blocking checks": with the new `ocr.engine` check there are 31, so the next iteration states 31.

## Iteration 4: generated components (approved)

Brief `projects/videostudio/briefs/self-launch-generated.json` (the full-pipeline brief plus `"components": "generate"`).
Production `P20261114-031556-9adf5`, concept "The Whole Pipeline". The component generator designed four scenes,
each kept only because it scored at least as well as the template it replaced:

| Scene | Generated design | Replaces |
|---|---|---|
| Architecture | stacked cards with accent rails | checklist |
| Pipeline | funnel (9:16) / tile row (16:9) | install-flow card |
| Local stack | stacked cascade | server-stack |
| QA | ring with the count, result chips | counter + checklist |

The first generated preview showed two defects that the scores had missed: connectors crossing labels, and a sparse
orbit with small labels. The composer now rejects both (text-crossing paths, a minimum label size of 34 px in 9:16
and 28 px in 16:9, and balance that rewards filling the space). After the render, one more motion defect was fixed
for future productions: a card no longer scales in while its own label stays put.

Render job `20261114-033942-53ff9d`, 96.3 s in both formats:

| Format | Checks | PASS | WARN | FAIL | Blocking checks |
|---|---|---|---|---|---|
| 1080×1920 | 43 | 42 | 1 | 0 | 31 / 31 PASS |
| 1920×1080 | 42 | 41 | 1 | 0 | 31 / 31 PASS |

Audio: −14.23 LUFS integrated, −1.46 dBTP true peak, 0 clipped samples, music ducked 9.4 dB under the voice.
Sync: max lag 0 ms, drift 0 ms over 23 windows. The film says "thirty-one blocking checks", matching this report.

### Approval

On 2026-11-14 the reviewer, Priyanshu Shroti, approved this production in chat for both formats, after confirming
that they had watched it end to end and listened to the voice. Recorded with the note "given in chat": flags #28
(pronunciation) and #29 (final watch) resolved, the two advisory `ocr.footage_labels` flags (#26, #27: the real
interface text "template-composed" inside the recording) resolved, then `approve` (package `d4e43c53…`). Nothing
was published. The reviewer will post the film on LinkedIn; it is not going to YouTube or Instagram.

Approved files: `video-out/videostudio/approved/2026-11-14 Video Studio (9adf5) short.mp4` and `… landscape.mp4`.

## Asset and licence manifest (approved job)

| Asset | Licence | Source |
|---|---|---|
| Video Studio logos (`public/brands/videostudio/logos/`) | Proprietary (all rights reserved) | made for this brand; wordmark outlined from Plus Jakarta Sans |
| Plus Jakarta Sans, Geist Mono (`public/brands/videostudio/fonts/`) | OFL-1.1 | copies of the open fonts |
| Screen recordings (`public/brands/videostudio/footage/`) | Proprietary (self-recorded product footage) | `scripts/capture_studio.mjs` on the running Studio |
| Music: "minimal space ambient music fragment" | CC0-1.0 | freesound.org/people/Clacksberg/sounds/491288 |
| Sound effects (pop, shimmer, thump, tick, transition, whoosh) | CC0 | freesound.org (ids 506545, 506546, 97978, 388295, 405537, 386206, 444623, 30241) |
| Voice | Kokoro-82M (Apache-2.0), voice `am_fenrir`, generated locally | `pipeline/voice/` |
| Renderer | Remotion (free for individuals and companies up to 3 employees) | docs/LICENSING.md |

The job's own manifest is `output/20261114-033942-53ff9d/assets/manifest.json`; an unlicensed asset would have
raised the blocking `license:unknown` flag.

## Publication

The reviewer posted the approved film on LinkedIn themselves on 2026-11-14: https://lnkd.in/p/gTd-psxr. The pipeline published nothing; the
film was not uploaded to YouTube or Instagram. The earlier self-launch productions (iterations 1–3c) were archived at
the reviewer's request, leaving the approved production as the record.
