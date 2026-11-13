# Launch text: Video Studio's self-made launch film

Channel: **LinkedIn only**, posted by the reviewer: https://lnkd.in/p/gTd-psxr. The film is not published to YouTube or Instagram.
Approved film: production `P20261114-031556-9adf5`, job `20261114-033942-53ff9d`, 96 s, approved by
Priyanshu Shroti on 2026-11-14 (both formats). Files: `video-out/videostudio/approved/`.

Every claim below is backed by `knowledge/videostudio/facts.json` or
`docs/reports/SELF_LAUNCH_PRODUCTION_EVIDENCE.md`.

## LinkedIn post

I built Video Studio, a local pipeline that turns a product brief into a narrated, animated, fact-checked video on
one Mac. Its launch film was made with Video Studio itself.

I wrote a brief. The studio drafted three concepts and built a storyboard where every animation is tied to the word
that names it. It rendered a quick preview of each scene and waited for my approval. Then it recorded the voice
locally with Kokoro, rendered the frames with Remotion, mixed the sound with FFmpeg, and ran QA on the finished file:
31 of 31 blocking checks passed in both the vertical and the landscape version.

Four of the scenes use designs the studio generated for this film. It searched layouts, scored each one on
legibility, timing and fit, and kept a design only when it beat the template it replaced.

Making the film exposed bugs in the pipeline, and each one is now fixed with a test:

- Preview approval refused every storyboard that contained a screen recording.
- QA rejected the film for showing the words "Remotion renderer", because it treated them as a leftover watermark.
- A scene opened on an empty dark frame for about a second.
- When Apple's on-device OCR failed, QA counted the unreadable frames as frames with no text and passed checks it
  could not run.

The footage in the film is the real app, recorded while it ran. Every number on screen comes from a verified fact,
and I approved the film before posting it.

The code is on GitHub: github.com/priyanshu-shroti01/video-studio

## Which file to upload

- LinkedIn feed (mobile-first): `2026-11-14 Video Studio (9adf5) short.mp4` (1080×1920).
- For a desktop-first post, `2026-11-14 Video Studio (9adf5) landscape.mp4` (1920×1080) is laid out for 16:9.
- Captions are burned in, so the film reads with the sound off.
