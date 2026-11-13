# Self-launch film: creative review

Each iteration was reviewed by exact frame extraction (`ffmpeg select=eq(n,N)`) in both formats, the QA contact
sheets and the QA, audio and sync reports. Scores are 1–10 and honest: a score is only as high as the weakest
thing a viewer would notice. Listening for pronunciation and a final end-to-end watch are human checks that remain
open until the reviewer signs them off.

Evidence for every run (production ids, jobs, QA tables) is in
[SELF_LAUNCH_PRODUCTION_EVIDENCE.md](SELF_LAUNCH_PRODUCTION_EVIDENCE.md).

## Creative directions

The hybrid engine produced three distinct concepts from the first brief. They differ in hook, structure, demo and
pacing:

| Concept | Structure | Hook |
|---|---|---|
| It Created Itself | question → the usual way → reveal → real app → pipeline → stack → proof → twist → close | "What if the software you built could make its own launch film?" |
| Proof First | cold open on the film itself → reveal → pipeline → real app → proof → close | "You are watching a film that was made by the software it is about." |
| From Brief to Film | the chain → inside the storyboard → what it runs on → proof → twist → close | "Script. Storyboard. Voice. Animation. Render. Every launch film is a long chain." |

After review, the brief was widened to show the architecture and every stage of the pipeline. That added a fourth
blueprint, The Whole Pipeline: a cold open on this film, then architecture, then every stage in the real app.

## Iterations

| Iteration | What changed | Length | QA | Score | Main problems seen |
|---|---|---|---|---|---|
| 1 | First render of "It Created Itself" | 61.0 s | FAIL (false positive: "Remotion renderer" read as a watermark) | 6 | 16:9 not recomposed (recording 42% of frame width); QA scene quoted another video's count; self-reveal showed an empty draft; 1.8 s empty opening in scene 2 |
| 2 | 16:9 side-by-side layout, own QA count, re-recorded self clip | 66.1 s | FAIL (black frames, QA scene opening) | 6 | Empty scene openings; the film still skipped most of the workflow |
| 3 | New brief and blueprint: architecture plus every stage, three new recordings | 97.2 s | FAIL (black openings; OCR engine failure hidden by QA) | 7 | Cold open and architecture opened on bare backdrop |
| 3c | Opening fixes, tighter architecture line | 95.1 s | **PASS** (31/31 blocking, both formats) | 8 | Library visuals only, so it looks like earlier videos; QA scene said 30 while QA ran 31 |
| 4 | Generated components for architecture, pipeline, stack and QA; 31/31 stated | 96.3 s | **PASS** (31/31 blocking, both formats) | 8.5 | One status card still scaling in at the cut (fixed for future productions); recordings of a dense desktop UI read small on a phone |

**Approved:** iteration 4, both formats, by the reviewer on 2026-11-14 after watching and listening.

### What a 9 needs, and where the film stands

- **Story:** the whole pipeline, in order, each stage on screen in the real app. Done from iteration 3.
- **Truth:** every number and claim is a verified fact; the QA count is this film's own. Done from iteration 3c,
  with 31 stated in iteration 4.
- **Craft:** no empty or frozen openings, every visual beat on its spoken word, both formats composed for their
  frame. Done in 3c.
- **Distinctiveness:** visuals that don't repeat earlier videos. Iteration 4's generated components address this.
  The remaining limits are that generated designs are geometric (cards, rings, funnels, stacked bars) rather than
  illustrative, and the screen recordings are of a dense desktop UI that reads small on a phone even with zooms.

A human score requires listening to the Kokoro voice (am_fenrir) on "Remotion", "FFmpeg", "Kokoro" and "GitHub",
and watching the film end to end.
