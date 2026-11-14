# Product plan: Video Studio for non-technical marketers

Status: draft for the owner's review, 2026-11-14. Nothing below is built yet.

## Goal

A marketer with no technical background installs Video Studio on a Mac, opens it like any app, and gets an approved,
on-brand video from a product brief without touching a terminal or asking for help. The video should be as good as
what paid SaaS video tools produce, at zero running cost, with everything kept on the machine.

**Done means:** a new user on a clean Apple-silicon Mac gets from download to a first approved video in under
30 minutes (most of it unattended downloads and rendering), with no terminal and no outside help. Then repeat
videos take under 10 minutes of the user's time.

## Decisions taken

| Decision | Choice | Consequence |
|---|---|---|
| Who it is for | Non-technical marketers | Everything happens in the browser app; the CLI stays for developers |
| Platforms | Mac (Apple silicon) first, then Linux and Windows | Apple's on-device OCR stays for now; a cross-platform OCR comes with the Docker phase |
| Licence | **PolyForm Shield 1.0.0** | Anyone, including businesses, may use it free; nobody may sell it, host it as a service or build a competing product |

### Licence wording

PolyForm Shield makes the project **source-available, not open source**: anyone may use and change it for their own
work, including marketers at businesses, but not sell it, host it as a service or use it to compete. The README and
any launch post should say "free" and "source-available", never "open source".

Third-party terms that stay in force: Remotion (free for individuals and companies up to 3 employees; larger
companies need a Remotion licence), the OFL fonts, CC0 music and sound effects, and the Kokoro voice model
(Apache-2.0). These need a plain-language NOTICE.

## Where it stands today (why it needs help to run)

| Problem | Evidence |
|---|---|
| Install takes 7 manual terminal steps | Homebrew packages, npm, uv, an 840 MB voice download, an Ollama model pull, a sound kit and a Studio build, with no checks or resume |
| Starting it needs a terminal and a developer command | `uv run video-pipeline studio --open`, and the dashboard needs a session-token URL, so it opens only in one browser |
| Several steps exist only as commands | starting and stopping the AI model, adding a website (`brand init`), verifying facts, recording product footage, archiving, recording a manual post |
| Errors read like developer errors | e.g. "storyboard changed after the preview", an invalid brief field reported late, OCR failing silently when the Mac was low on memory |
| The dashboard is an internal tool | no onboarding, no guided "make a video" path, no live preview, no templates gallery, no video library with thumbnails |
| Footage needs a developer | real product recordings need JSON plans and a script |

What already works and is worth keeping: the hybrid creative engine (three concepts, verified facts, word-anchored
animation), generated components, local voice, render, QA on the real file, hash-bound human approval, publishing
gates, multi-brand isolation.

## Why use this instead of asking ChatGPT (or any AI video generator) for a video?

Text-to-video models (Sora in ChatGPT, Veo, Runway, Kling) make striking, cinematic footage, and they will keep
improving. A marketer still struggles to use them for a product video:

| | AI video generators | Video Studio |
|---|---|---|
| Cost | subscription or credits per clip | ₹0 per video, no subscription, no API key |
| Your real product on screen | invents a product that looks plausible | screen recordings of the real app or website |
| Prices, plans, URLs, claims | text in frames is often wrong or garbled; nothing is checked | every number checked against the brand's own site; digit-exact OCR on the final file |
| Brand | approximates logos and colours | the brand's real logo, colours, fonts and pronunciation |
| Length and structure | short clips you stitch together yourself | a complete 30 s–3 min video with voice, music, captions and both formats |
| Editing | regenerate and hope | edit any line or scene; the rest stays as it is |
| Privacy | brief and assets go to a provider | nothing leaves the Mac |
| Accountability | none | a named person approves the exact file before it is published |

The honest weakness is the look. Template-built motion graphics can look alike from one video to the next, and none
of it is photographic. The plan answers that in two ways: generated components and product footage make each video
specific (Phase 5), and clips from any AI video tool can be imported as `footage`, so generative shots and
Video Studio's accuracy can be used together.

## The "videos look like templates" problem

The problem is real. A video is a sequence of designed templates, and the generator so far only re-arranges
list-like scenes into cards, rings and stacks. To make each video look made for its product:

1. **The product is the hero.** By default, show the brand's own website or app, recorded automatically (Phase 5),
   instead of abstract cards.
2. **Generated components by default** (once they win head-to-head reviews), with a much larger search space:
   illustration-like layouts, data visuals, device scenes, kinetic typography styles, transitions.
3. **Per-brand visual identity:** each brand gets its own motion style, backdrop set, type scale and pacing, so two
   brands never look like the same template.
4. **Freshness across videos:** already in place. A brand's next video avoids designs its recent videos used.
5. **Measured, not assumed:** a blind side-by-side review against SaaS output on the same brief, scored by people,
   before claiming quality.

## What paid SaaS video tools give that Video Studio does not (yet)

This is by category, not a claim about any one product: a web app with nothing to install; a guided script-to-video
wizard; a template gallery; a brand kit (logo, colours, fonts); live preview and inline editing; a stock media
library; many voices and languages; captions and multiple aspect ratios; one-click export and sharing; a project
library; and help inside the app.

Where Video Studio already competes or wins: zero running cost and no credits; private by design (nothing leaves the
Mac); every number fact-checked against the brand's own site; designed motion graphics instead of stock slideshows;
a person approves before anything ships.

## Roadmap

Effort is in focused working sessions of roughly 2–3 hours each. Each phase ends in something a marketer can use.

### Phase 0: licence and wording (½ session)

- Replace `LICENSE` with PolyForm Shield 1.0.0 (required notice line naming the licensor).
- README says it near the top, plainly: **₹0 per video. No subscription, no API keys, no LLM account.** The AI (the
  Qwen3-4B writing model, the Kokoro voice) runs on the Mac.
- Add `NOTICE.md`: third-party licences in plain language (Remotion's company-size rule included).
- Update README, `package.json` and `pyproject.toml` licence fields, and the wording ("free, source-available").

### Phase 1: install and launch with at most three Terminal commands (2–3 sessions)

No VS Code, no Git, no developer tools. The user opens the Mac's Terminal app once and pastes at most three
commands, copied from the README:

```bash
curl -fsSL https://raw.githubusercontent.com/priyanshu-shroti01/video-studio/main/install.sh | bash   # installs everything
videostudio                                                                                     # opens the Studio
```

- **`install.sh`** checks or installs Homebrew, ffmpeg, uv, node and Ollama, and downloads the release (no Git
  needed). It installs dependencies, builds the Studio and adds a `videostudio` command. It shows plain progress,
  resumes after a failure, and is safe to run again.
- **Downloads in the background:** voices (840 MB), the AI model and the sound kit download after the first launch,
  with progress shown in the app.
- **`videostudio`** starts the local server and opens the browser at `http://127.0.0.1:8765`. The dashboard opens in
  any browser on the Mac, with no session token in the URL; requests are protected by Host and Origin checks
  instead. `videostudio stop`, `videostudio update` and `videostudio doctor` cover the rest.
- **The AI model looks after itself:** it starts when concepts are needed and stops before rendering. The two
  runtime commands disappear.
- **First-run screen:** a checklist of setup steps with live status, each with a **Fix** button, built from the
  existing `doctor` checks.
- **Updates:** "Check for updates" in the app (or `videostudio update`) fetches the latest release, with a backup of
  the user's data first.

Acceptance: on a fresh macOS user account, the owner installs with the README commands and makes a video without
any other tool.

### Phase 2: every step in the browser (3–4 sessions)

- **"Create a video" wizard,** one page at a time:
  1. which website (brand);
  2. what to promote (product, price, audience, goal);
  3. length and formats;
  4. three concepts as cards with a preview still;
  5. storyboard review;
  6. render;
  7. approve;
  8. download or share.
- **Add-a-website wizard:** enter a URL. The app drafts the brand (logo, colours, fonts, pronunciation) and lists
  the facts it found with their source text. The user ticks the ones that are right. This replaces `brand init`
  and the facts command.
- **Facts screen:** add, edit, re-check or retire a fact, always with its source.
- **Product footage without scripts:** "Record my website" captures a scroll-through of any URL, using the
  existing recorder behind a form. Recording the user's own web app with clicks comes later.
- **Voice and music pickers** with play buttons.
- **Library actions:** archive, restore, "I posted it on…" (mark-published), export package.
- **Frame-accurate preview before rendering:** the current preview is one still per scene, which is not enough to
  judge every frame. The storyboard plays in the browser with the real engine (Remotion Player), and the user can
  scrub to any frame, step frame by frame and loop a scene. Because voice timing is estimated until the voice is
  recorded, the voice is generated first (seconds, locally), so the preview plays with the real voice and exact
  timing. The full render then only encodes what the user already watched. (Moved here from Phase 4.)

Acceptance: the whole Shroti Host and Video Studio workflows run start to finish in the browser.

### Phase 3: errors that say what to do (1–2 sessions)

- Each known failure gets a plain sentence and one action. Examples:
  - "The storyboard changed after the preview; build the preview again" → **Rebuild preview**;
  - "Your Mac is low on memory; close other apps and retry" → **Retry**.
- **Pre-flight before heavy work:** free memory and swap, disk space, OCR working, model present. It explains,
  then waits or offers a fix, instead of failing mid-render.
- **Recovery:** interrupted jobs resume after a restart, and a finished render sends a macOS notification.
- **"Send a report" button:** saves a redacted diagnostics zip for the user to share. It contains no secrets and
  nothing is uploaded.

### Phase 4: SaaS-grade dashboard (3–4 sessions)

- **Home:** a project grid with thumbnails and status ("Needs your review", "Rendering", "Ready to post").
- **Inline editing:** click a headline or label in the preview to edit it; the rules re-check instantly.
- **Template gallery:** the blueprints and generated components shown as watchable examples.
- **Brand kit page:** logo, colours, fonts, voice and pronunciation in one place.
- **Design system pass:** spacing, type, empty states, loading states, keyboard support, accessibility.
- **Onboarding:** a sample project and a short guided tour.

Acceptance: five people who have never seen it each make a video unaided. Measure the time and where they hesitate,
and fix the top three issues.

### Phase 5: video quality that beats the paid tools (ongoing)

- Generated components become the default once they win most head-to-head reviews.
- **Automatic website footage:** every brand gets recordings of its own site, made by the recorder, so videos show
  the real product.
- **More industry packs:** e-commerce, SaaS, local services, education, events.
- **More voices and languages:** Kokoro and Piper voices with a listening test per language (Hindi first for
  Indian brands).
- **Larger music library:** licence-checked, with mood previews.
- **Illustrations without stock libraries:** evaluate local image models on Apple silicon, keeping memory limits
  in mind (one heavy job at a time).

### Phase 6: Linux and Windows (2–3 sessions)

- A Docker image (Linux, and Windows through WSL), with a cross-platform OCR fallback (Tesseract or similar).
  Apple Vision stays the default on Macs.
- A cross-platform launcher.

### Phase 7: release and community (1–2 sessions)

- Versioned releases with a downloadable installer, a changelog and a short demo video made by Video Studio.
- A docs site written for marketers, not developers.
- An issue templates and a contribution policy that matches the licence.

## Order and timeline

| Order | Phase | Sessions | What the user notices |
|---|---|---|---|
| 1 | 0 Licence and README | ½ | Clear terms; "₹0 per video" up front |
| 2 | 1 Install and launch | 2–3 | Two Terminal commands to install and open; any browser |
| 3 | 2 Browser for everything | 4–5 | No more terminal; watch every frame before rendering |
| 4 | 3 Errors | 1–2 | Problems explain themselves |
| 5 | 4 SaaS-grade dashboard | 3–4 | Feels like a product |
| 6 | 5 Quality | ongoing | Better videos |
| 7 | 6 Cross-platform | 2–3 | Runs on Linux and Windows |
| 8 | 7 Release | 1–2 | Others can find and install it |

About 14–20 sessions for phases 0–4, the part that makes it usable without help.

## Principles that stay fixed

- Zero running cost: no paid APIs, no cloud AI. Online features stay opt-in.
- Facts are verified; a person approves before anything is published.
- One heavy job at a time (16 GB Macs).
- Every change ships with tests; the Studio is checked in the real app, not only in tests.

## Questions for the owner

1. Is Hindi (or another language) needed early for your brands?
2. Should updates come from GitHub releases (simplest), or should installs never contact GitHub automatically?
3. Who are the five first users for the Phase 4 test?
