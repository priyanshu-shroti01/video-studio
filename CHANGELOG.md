# Changelog

## Unreleased

### Added
- **README teaser and walkthrough briefs** (projects/videostudio/briefs/) for the demo films.
- **"Zero Cost" teaser blueprint** (software pack): a 30–35 s film — the price promise, the real app, the local stack
  and the frame-by-frame preview — backed by a new `product.cost` fact taken verbatim from the README.
- **Footage of the redesigned Studio** (videostudio brand, `studio-*-v3.mp4` with region sidecars and plans in
  scripts/capture-plans/videostudio/): Home, the storyboard's frame-accurate player, "Your video is ready", Websites
  & facts (verified and suggested facts), the Render Monitor and the wizard's first step. Footage ids `app-tour`,
  `preview`, `self`, `render` and `publishing` now use them, plus new ids `home` and `facts`. `app-tour` is
  `studio-wizard-v3.mp4`: the wizard picking a website, typing the brief, then three ideas. Recorded with the new
  `phone-legible` approach (tight crops); every clip passes footage.legibility in 9:16 with fit "fill" (34–72 px
  median against 28.8 px). The older recordings stay in place.
- **capture_studio.mjs `hover` / `hoverText` steps:** glide the mouse onto a card or button (hover styles) without
  clicking or scrolling, for read-only tours.

### Fixed
- **capture_studio.mjs kept the time spent off camera:** after `record: false`, the last frame held until recording
  resumed, so a clip showed seconds of a still page while the script navigated away. That time is now cut from the
  clip and from region times.
- **capture_studio.mjs no longer builds page code from strings (CodeQL):** plan values (selectors, texts, numbers)
  go to one fixed in-page function as `Runtime.callFunctionOn` arguments.
- **Videos felt rushed:** the vertical presets spoke 5% fast, cut every pause to 0.35 s and left 0.2 s between
  scenes. They now speak at normal speed, keep pauses up to 0.5 s and leave 0.35 s between scenes (landscape
  too). Duration estimates stay at 2.33 words/s, so films run a little longer than the estimate.
- **Footage camera moved too often:** a beat whose words weren't spoken still zoomed, 0.45 s after the previous
  move, so a 5 s recording scene made 7 camera moves. Zooms now fire only on spoken words and at least 0.8 s apart.
- **A render killed mid-way left its production stuck in "rendering"** (the job was recovered as failed, the
  production wasn't), so it could neither render again nor be approved. Productions now follow their job: a dead
  render fails the production so it can render again, and a job finished through `video-pipeline retry` gets
  the usual QA and approval package.
- **An opening fade-in counted as black:** QA allowed 0.2 s of black at the start; a first word fading in over a
  dark backdrop takes about 0.22 s in 16:9. The allowance is now 0.25 s.
- **The brief's `voice` was ignored:** every production used the preset voice. It now applies to the production,
  and a new brief field `pace` (`calm`, `normal`, `brisk`) sets how fast the narrator speaks.
- **Films no longer open on silence and black:** the voice engine's own ~0.4 s lead-in before the first word was
  kept, so a hook that starts with text showed 0.45 s of near-black backdrop and failed QA's black-frame check.
  The first word now starts 0.05 s in, like every later scene already starts tight.
- **The teaser copy names no currency:** the software pack says the price through the brand's `product.cost` fact
  (`{cost_spoken}`), so shared code stays brand-neutral; the hook and stack lines now open on what they show.
- **More code-scanning hardening (CodeQL):** `safe_path` now checks a path lexically against the approved roots
  before touching the filesystem (and again after following symlinks), and the Studio serves frontend files by
  looking the requested name up in the built folder's listing instead of building a path from it.
- **Dependency alerts (Dependabot):** pytest 9.0.3 (tmpdir handling) and minimatch 11 through an npm override
  (a denial-of-service in glob patterns; only used by the linter). `npm audit` reports no vulnerabilities.
- **Code-scanning hardening (CodeQL):** the Studio server refuses any response header value that contains a line
  break, and checks a static file name's length before matching it. Neither was exploitable (header values were
  built from fixed types and numbers; the name regex is anchored), but both now hold by construction.
- **A word ending in "rs" followed by a number read as a rupee price** ("offers three ideas" → "Rs 3"), which
  rejected a whole concept as an unverified claim. The pattern now needs a word boundary.

## 0.5.0 — 2026-11-15

Usable without a terminal: a two-command install, a redesigned Studio with a guided "Create a video" wizard, and
videos with current caption styles, transitions and effects, 60 fps and 4K. The repository is now under PolyForm
Shield 1.0.0.

### Added
- **Studio redesign:** a Home page of video cards with plain statuses, a six-step "Create a video" wizard, and one
  design system across every page (spacing and type scales, aligned control heights, flat monochrome surfaces, one
  accent, no gradients or glows; Host Grotesk and Lucide icons vendored). See docs/STUDIO_GUIDE.md.
- **Suggested facts:** adding a website proposes prices, plans and features with the verbatim text they were found
  in (kept locally, not in facts.json); a named person confirms each one, after a re-check on the live page.
- **Archive restore:** Library → Archived, `video-pipeline archive --list` and `--restore <P> --actor "<name>"`.
- **Preview with the real voice:** "Use the real voice" records the narration locally, so the frame-accurate preview
  plays with sound and exactly the render's timing (estimated timing was about 15% long on a 96 s film).
- **Readable screen recordings:** `footage` can fill the 9:16 frame, zoom to a named UI region and show magnified
  callouts; the new `footage.legibility` QA check fails a 9:16 video whose recorded text renders below a
  phone-readable size; `capture_studio.mjs` records at a larger UI scale.
- **Licence:** PolyForm Shield 1.0.0 (source-available), with a plain-language NOTICE.md.

### Fixed
- **Fresh-Mac install:** Homebrew's Ollama pulls in Python 3.15, which onnxruntime (the voice engine) has no build
  for; the installer and launcher now pin Python 3.14. Also: resume checks for the browser and voice steps, sound
  kit updates, and backup pruning.
- **Tests could empty the real `video-out/` folder** (the Studio's archive refresh ran against a test registry).
  Tests now get a private folder, and `video-out` only prunes copies when the registry that made them asks.
- **Studio videos played silently in VS Code's browser** (it has no AAC decoder): in-app players now use a copy with
  Opus audio; downloads and approved files are unchanged.
- **Effects** (engine contract unchanged, additive; docs/MOTION.md#effects). Storyboards without effects render
  byte-identical.
  - **Transitions:** whip-pan, zoom-through, push or swipe, iris, light leak, and a short glitch of at most 6 frames.
    The previous scene exits with the matching move and still reaches 0 at its end.
  - **Word-anchored emphasis:** punch-zoom, impact shake (≤ 8 px), brightness flash (≤ 45 %, never full white),
    confetti burst when a count lands, hand-drawn underline / circle / arrow, cursor and click ripple on recordings,
    and a 3D tilt entrance.
  - **Optional film grain per brand** (`theme.grain`).
  - **Beat sync:** `pipeline/beats.py` detects the music's beats (numpy and ffmpeg, cached per sha256). Cuts and
    punch-zooms snap to a beat within ±120 ms only when the word rules still hold, and every decision is recorded.
  - **Effects director:** new concepts only, following the scene's mood (energetic: whip and punch; cinematic: zoom-through
    and light leak; calm: minimal), with restraint: one emphasis per scene, no repeated transition, at most 2 flashes or
    glitches.
  - **Photosensitivity guard:** at most 3 flashes in any second, in Python and in the engine. QA's sync check counts
    effects as visual events.
- **Caption styles** (`captions.style`, engine contract unchanged, additive): `pop` (1–3 words, big outlined
  type, the spoken word springs up in the brand colour), `highlight` (a brand block travels word to word),
  `karaoke` (words fill as spoken) and `minimal` (small and low, for 16:9), next to the unchanged classic box
  (`word` / `phrase` / `classic`; renders byte-identical). Word-synced pages never split names or leave "the" dangling;
  numbers, the brand name and the scene's emphasis words get extra emphasis; over `light` backdrops they switch to
  dark ink without an outline and a contrast-checked brand colour (≥ 4.5:1); the new looks stay out of the Shorts UI
  zones. New productions get brief → brand (`creative.captions.style`) → format default (`pop` Shorts, `minimal`
  16:9); existing projects stay classic. QA measures reading speed over 1.5 s windows for word-synced pages and adds
  an advisory `layout.caption_platform_ui` check. See docs/MOTION.md#captions.
- **Quality presets** (`quality` in a brief, `render.quality` in a project, "Quality" on the New Production form):
  `standard` 1080p · 30 fps (default, unchanged), `smooth` 1080p · 60 fps (~2× render time) and `ultra` 4K · 60 fps
  via Remotion `--scale=2` (2160×3840 Shorts, 3840×2160 landscape; ~4–6× render time, at most 2 Chromium tabs).
  Timeline, keystroke rhythm, end fade, render chunks, QA (resolution, fps, contact sheet, OCR on frames downscaled
  to the layout's design size) and thumbnails follow the preset. `ultra` Shorts are wider than Instagram's 1920-column
  limit, so they route to YouTube only.
- **Watch every frame:** the Storyboard page plays the real engine in the browser (play, scrub, step a frame or a
  second, loop a scene, both formats) before rendering, with estimated timing until the voice is recorded.
- **Install with one command** (`install.sh`) and open with `videostudio`; no VS Code, Git or developer tools.
- **No more terminal for daily work:** the AI model starts and stops by itself; websites and facts, library actions
  and a setup checklist are in the Studio; errors say what to do next; memory, disk and OCR are checked before
  rendering and QA.
- **Staged entrances:** a recording or diagram that appears before its message is first shown alone, centred, then
  moves to its place (sideways in 16:9, up in 9:16) just before the message enters, so it never waits off to one
  side for text that hasn't arrived.
- **Studio:** the dashboard opens at `http://127.0.0.1:8765/` in any browser, with no session token in the URL.
- **`production mark-published`** records a post a person made outside the pipeline (e.g. LinkedIn): same approval
  and hash gate as `publish`, nothing uploaded, production moves to PUBLISHED, audited with the person's name.
- **Optional blueprint slots** keep three concepts for long briefs (a ~110 s brief used to get two).
- **Studio:** "Generate new components" on the New Production form.
- **Self-launch film.** Video Studio's own 96-second launch film, made through the pipeline with real Studio
  footage and generated components, approved in both formats (production `P20261114-031556-9adf5`).
  - New `videostudio` brand: original logo, theme, verified facts and pronunciation.
- **`footage` block** (engine, CONTRACT_VERSION unchanged, additive): real video clips such as screen recordings of a
  product's UI, in `browser` (default), `laptop`, `phone` or no (`none`) chrome.
  - Frame-accurate and always muted (`OffthreadVideo` frozen at the computed clip time): clip time =
    `startFrom + (t − appear) · playbackRate`; the last frame holds when the scene outlasts the clip.
  - The box follows the clip's aspect (never distorted), with layout and hero scaling like `image` / `device`, for wide
    and tall clips in both formats. Browser chrome follows the light backdrop.
  - `zooms[{at, x, y, scale}]`: focus keyframes (normalised centre, scale 1–4) eased from each `at`, clamped so no
    view ever leaves the clip; `at` accepts `@word:` expressions.
  - Python: validation (`pipeline/storyboard.py`, hero block), `pipeline/footage.py` checks the file (inside
    `public/`, `.mp4` / `.webm`, decodable) and fills `aspect` (SAR and rotation applied) and `duration` from ffprobe.
    Brand isolation covers the `asset`. Clips are registered in the job's asset manifest with their licence record, so
    an unlicensed clip raises the blocking `license:unknown` flag.
  - QA: the layout manifest reports the clip viewport as a `media` box (`layout.media_aspect` check). Template-like
    words that OCR finds inside recorded footage are an advisory `ocr.footage_labels` warning, not a failure. Footage
    pixels are left out of the palette check.
  - Fixtures `sample-footage-{short,landscape}.json` with a self-generated public-domain test clip
    (`public/shared/fixtures/footage-sample.mp4`).

- **Unpriced products** (`Pack.priced = False`): packs for software and other products without a price. Unpriced
  products have no plan placeholders, and the pricing rule fails any concept that shows a price.
- **`software` industry pack** (`pipeline/creative/industries/software.py`):
  - 10 templates: production chain, real app footage, pipeline stages, local stack, measured QA counter, self-reveal
    and outro;
  - 3 distinct blueprints, and a brand-neutral copy bank.
- **Duration window from the brief** (`rules.windows`). Shorts (≤ 40 s) keep 30–35 s; longer briefs get ±~8%.
  `duration_flexible: true` lets the story set the length, capped at 175 s so vertical videos stay Shorts.
- **`formats` in briefs**: render several formats from one brief. The Studio's New Production form adds
  "Let the story set the length" and "Also render".
- **Brand `displayUrl`** (e.g. a repository path) for CTA buttons; the spoken cue stays the brand's `urlCue`.
- **Fact-driven spoken numbers.** A fact's `value.spoken` becomes the `{<role>_spoken}` placeholder in copy, so a
  count the narration says always comes from the verified fact, never from the copy bank.
- **`repo:` fact sources.** An excerpt can be verified against a file in this repository (e.g. a production evidence
  report) before that file is public. Paths cannot leave the repository.
- **`splitRatio` on scenes** (16:9 only). It sets the left column's share of a `split` layout (0.3–0.7), and the
  narrower column always keeps its content's minimum width. The director splits any scene that has one recording and
  one message at 0.66: in 16:9 the recording sits beside its message and fills the content height (+56% area
  compared with stacking). Shorts are unchanged.
- **`server-stack` `target.icon`** (e.g. `play` instead of the globe) and a `play` icon.
- **`scripts/capture_studio.mjs`** records real footage of the running Studio. It drives the actual UI in headless
  Chromium with scripted input and uses a Chrome DevTools Protocol screencast, with CSS zoom for sharp 2× frames and
  exact pause timing.

### Fixed
- **Preview approval was refused for any storyboard with footage** ("the storyboard changed after the preview").
  The gate hashed the loaded storyboard, which carries ffprobe-derived footage fields, while approval hashed the
  saved file. Both now use `preview_gate.saved_storyboard_hash`.
- **QA failed films whose own copy names Remotion** (e.g. "Remotion renderer"). `ocr.no_template_labels` now accepts
  a banned word only inside a text box the storyboard placed that contains the same word. A stray "Remotion"
  watermark anywhere else still fails.
- **The Studio server dropped `duration_flexible` and `formats`** from briefs created in the UI.
- **QA passed OCR checks when OCR itself had failed.** Apple Vision can fail at OS level (`e5rtError … 13`,
  seen under heavy memory pressure). The per-frame error was ignored, so frames read as "no text" and most OCR
  checks passed on no evidence. A blocking `ocr.engine` check now fails QA on any OCR error, after one retry.
- **Scenes could open on a bare backdrop.** A new `scene-opens` concept rule reports (WARN) a scene that shows only
  its backdrop for more than 0.6 s and rejects it beyond 2 s. A checklist counts as visible only from its first item.
- **`production create` accepted invalid briefs** and failed only later, leaving an empty production. It now
  validates the brief first.
- **`scripts/capture_studio.mjs` scrolled the wrong element** when the page itself scrolls (overflow `visible`).

### Component generator
- **`composition` block** (engine, CONTRACT_VERSION unchanged, additive): a generated scene graphic made of primitives
  (text, shape, connector, icon, number, logo, media) on a normalised canvas, with a tall and a wide box per element so one
  storyboard holds in 1080×1920 and 1920×1080.
  - Colours are theme tokens only; motion presets fade-up / fade / scale-in / draw-on / pop / none, `pulseAt` highlights,
    numbers count like `counter`. Nested `at` / `countEnd` / `pulseAt` accept `@word:` expressions.
  - Pure geometry (`src/engine/geometry-composition.ts`) with deterministic text fitting, shared by the renderer
    (`blocks-composition.tsx`) and the QA layout manifest (every text line reported with its role, overflow flagged).
  - Python: validation (`pipeline/storyboard.py composition_errors`, no raw colours, connectors must join elements),
    contract mirror (`COMPOSITION_*`), hero block, auto-SFX; `sync_check` and the preview gate check counted numbers.
  - Fixtures `sample-composition-{short,landscape}.json`: one scene per generated structure.
- **Composer** (`pipeline/creative/composer.py`): for demo / proof scenes whose hero carries structure (steps, a stack, a
  feature set, a count with satellites, a comparison) it searches 10 structures × variants × seeded arrangement parameters
  × 4 motion schemes, and scores them:
  - rejects invented labels, numbers shown before they are spoken, narration gaps, and, measured on the engine layout
    manifest in both formats, text overflow, labels rendered below 34 px (9:16) / 28 px (16:9), and connectors, lines or
    arcs that run through text (the drawn path, curves included);
  - scores legibility (the content's own item texts, the same strings for template and candidate), sync, balance (half
    of it is how much of the hero box is actually drawn, so sparse designs lose) and freshness, and keeps the template
    unless a candidate scores at least as well;
  - undoes any replacement that makes the concept fail a rule.
  The local LLM may only name structures. Brief option `"components": "generate"` (validated; kept by the Studio
  server); without it the output is unchanged.
- **Freshness memory** (`pipeline/creative/freshness.py`): recency-weighted usage of templates, blueprints, hero blocks,
  backdrops and generated designs across the brand's productions (archived ones excluded). In generate mode the director
  prefers what the brand has not used lately; concepts.md shows a freshness line and the generated scenes per concept.
- **Components store and brand library** (`pipeline/creative/components.py`): `output/productions/<P>/components/<id>.json`
  (scores, template baseline, alternates); `video-pipeline component list | approve | reject --reviewer "<Name>"`. Approve
  copies the design into `brands/<brand>/components/<name>.json` (never overwritten), which later productions may reuse.
  Every decision is audited.

## 0.4.0 — 2026-11-14

Fixes the v0.3.0 creative regression (see docs/reports/CREATIVE_COMPARISON.md) and makes the studio multi-brand.

### Added
- **Hybrid creative engine** (`pipeline/creative/`, docs/CREATIVE_SYSTEM.md), now the **default** (`"engine": "llm"` opts out).
  - 22 professionally designed scene templates (9 generic, 13 in the `web-hosting` industry pack). Templates own
    composition, animation and labels.
  - The local LLM may only propose hooks and draft copy in validated slots, with a hand-written copy bank as the fallback.
  - Rules reject any concept without a hero visual per scene, a real demo, verified pricing, word-anchored beats,
    ≤ 2.4 s of estimated narration without a visual event, or numbers shown before they are spoken.
  - Same-brief comparison: docs/reports/CREATIVE_COMPARISON.md. The reviewer approved B3, which is hybrid plus the
    v0.2 two-plan scene.
- **Engine v2b**, CONTRACT_VERSION unchanged:
  - six scene backdrops (glow, spotlight, grid, split, light, deep);
  - the `plan-card`, `install-flow` and `server-stack` blocks;
  - hero scaling;
  - `install-flow.appIcon` for real, licensed product icons (WordPress, from `public/shared/assets.json`).
- **Storyboard preview gate** (`pipeline/preview_gate.py`) and **human preview approval** before any full render:
  - `production approve-preview`, a Studio button, and an audited override;
  - checks for empty scenes, repetition, hero visuals, invented "Label: ₹N" text, unverified numbers, overflow and
    narration sync.
- **Narration ↔ visual sync** (`pipeline/sync_check.py`) in the gate and in QA. QA also measures the A/V offset of the
  final file against the voiceover (critical, ≤ 45 ms).
- Scene option `holdAfter`: silence after the last word, so a visual payoff plays out before the cut.
- **Multi-brand:**
  - `video-pipeline brand list|init`. `init` drafts a brand from the site's home page and never overwrites.
  - `pipeline.brands.resolve_brand`: briefs resolve to a brand by id, name or domain.
  - Per-brand `pronunciation.json`.
  - Shared licensed files live in `public/shared/` (fonts, the Studio icon, third-party product logos).
- **Archiving:** `video-pipeline archive --production/--job/--all-except`.
  - Archived productions and jobs are hidden from every list.
  - Their files move to `output/_archive/`, and the audit history is kept.
  - Registry migration v3 adds `archived_at`.
- **`video-out/`**: copies of finished videos by brand (`for-review/`, `approved/`) with readable names, synced on
  every production state change.
- **Studio:**
  - a brand-neutral look and a global brand filter;
  - a rebuilt dashboard ("needs your attention" queue, brand overview with fact and account status, pipeline
    funnel, preview-gate and QA columns);
  - a preview review panel with approval;
  - per-brand publishing status;
  - a connection banner;
  - a session token that survives restarts (`--new-token` rotates it).
- Creative metrics and comparison tooling: `scripts/creative_metrics.py`, `scripts/compare_creative.py`.
- **Social publishing layer** (`pipeline/social/`, docs/SOCIAL_PUBLISHING.md, docs/SOCIAL_SETUP.md):
  - platform routing from the real file (ffprobe): 9:16 ≤ 180 s → YouTube Shorts + Instagram Reels; longer 9:16 →
    YouTube long-form (+ Reels up to 15 min / 300 MB); 16:9 → YouTube with chapters, never Instagram;
  - per-platform metadata (`publishing/metadata.json`, versioned, part of the approval hash): YouTube title,
    description (hook + link in the first 150 chars, verified plan lines, chapters from voice timings, AI-voice
    disclosure, credits, 3 hashtags), tags ≤ 500, category, languages, `containsSyntheticMedia`, optional
    `publishAt`/thumbnail; Instagram caption (hook line, short paragraphs, link-in-bio CTA, 3–5 specific
    hashtags, cover frame, share_to_feed). Written by the local LLM (schema-constrained, scheduler-gated) with a
    deterministic template fallback per field; validated for lengths, hashtags, clichés, caps and unverified claims;
  - opt-in keyword research (YouTube autocomplete, optional Data API) that sends only generic seed phrases,
    shows every outgoing query and caches for 24 h;
  - Instagram Reels adapter (Facebook Login for Business, resumable upload, status polling, rate-limit check,
    permalink, optional first comment) and a token refresh helper;
  - `video-pipeline social plan|draft|keywords|status|list|accounts|token-refresh`; `publish --platform instagram`;
  - project MCP server `video-pipeline-mcp` (stdio; `mcp==2.3.0`) with annotated tools
    `list_publishable`, `plan_platforms`, `publication_status`, `draft_metadata`, `keyword_research`,
    `publish_youtube`, `publish_instagram_reel`;
  - `scripts/youtube_oauth.py` (loopback + PKCE, per brand).
- **Multi-brand publishing:** per-brand secrets `.pipeline/secrets/<brand>/{youtube,instagram}.json`; expected
  accounts in `brands/<brand>/brand.json → publishing.accounts`, verified against the platform before upload;
  brand voice, CTA, link, hashtag sets and keyword seeds in `publishing.social`.

### Changed
- **Timing calibrated to the real voice.**
  - Kokoro am_michael +5% speaks 2.37 words/s, measured on three renders.
  - Every estimator (preview, creative rules, concept fitting, Studio) uses 2.33 words/s instead of 2.6, which was
    10% optimistic and let a "35 s" storyboard render at 37.3 s.
  - The creative duration rule estimates the video length, including pauses and the end tail.
- **No brand defaults in code.** Removed every `"shrotihost"` default. The legacy engine's example CTA uses the
  brand's own domain. The claim checker finds any brand's coupon fact.
- **Folder structure:**
  - guides are in `docs/` and reports in `docs/reports/`;
  - per-brand `projects/<brand>/` (briefs in `projects/<brand>/briefs/`);
  - v0.1 hand-built scripts are in `scripts/legacy/`;
  - `README.md`, `CHANGELOG.md`, `LICENSE` and `SECURITY.md` stay at the root.
- Preview stills are sampled after each scene's latest event; contact sheets have dark padding.
- `publishing.publish()` verifies the destination account belongs to the production's brand, uses
  `metadata.json` for YouTube, refuses duplicate uploads, and allows the second platform after the first
  (`PUBLISHED` with a still-valid approval). YouTube `client_secret` is optional (Desktop clients).
- Export `platform-metadata.json` no longer suggests Instagram "feed" for landscape video (it is refused).
- The global `.pipeline/secrets/youtube.json` is no longer used (migration: move it into the brand's directory).

## 0.3.0 — 2026-11-13: local AI creative studio

Built on v0.2.0 (baseline commit `28a1b2c`); every v0.2.0 feature, preset, job and output is preserved.

### Added
- **Creative intelligence (local LLM):** `pipeline/intelligence/`, with Ollama 0.40.16 on 127.0.0.1 and Qwen3-4B-Instruct
  (Apache-2.0, 2.5 GB). Brief → 3 distinct concepts (6 narrative patterns, distinctness check) → schema-valid
  storyboard (scene-by-scene generation, repair loop, template fallback). Verified fact base
  (`knowledge/shrotihost/facts.json`, 80 facts with verbatim excerpts); claim verification on narration, blocks
  and metadata. Unverified claims → NEEDS_REVIEW → blocking review flags.
- **Fully local voice:** Kokoro-82M (default `am_michael`) and Piper behind the existing provider interface;
  native phoneme-duration word timing (calibrated), Whisper base.en fallback; pronunciation dictionary
  (display ↔ spoken mapping, captions keep display text); models sha256-registered; worker process unloads.
  Edge TTS becomes an opt-in legacy provider (`voice.allowOnline`).
- **Motion engine / contract v2:** motion tokens + presets, 13 new blocks, camera moves, mask-wipe and
  gradient-sweep transitions, watermark policies with duplicate-branding suppression, a deterministic
  layout manifest. v1 props render bit-identically.
- **Production lifecycle and approval gate:** DRAFT → … → AWAITING_APPROVAL → APPROVED → PUBLISHING →
  PUBLISHED; review flags (mandatory human pronunciation and final-watch checks); approval bound to sha256 of
  every package file and invalidated by any change; audit log.
- **Publishing:** export package (checksums, platform metadata, synthetic-media disclosure); YouTube Data API
  adapter (opt-in credentials). Never automatic, `--confirm` required.
- **Visual and brand QA:** layout-manifest checks; on-device Apple Vision OCR (digit-strict prices, exact URLs,
  template-label detection); logo/watermark pixel checks; palette check; branding report; pronunciation
  checklist; alignment report.
- **Local Video Studio:** web UI on 127.0.0.1 (`video-pipeline studio`): dashboard, new production, storyboard
  editor, asset library with audio preview, render monitor, preview & QA, publishing center.
- **Resource scheduler:** one memory-heavy workload at a time (render > tts > llm > background), memory-gated,
  cross-process. Configurable via `.pipeline/scheduler.json`.
- **Licensed music library:** 7 CC0 tracks, each verified twice; mood-based selection (`"mood:corporate"`).
- **Multi-brand:** `brands/<id>/brand.json`, per-brand asset roots and isolation, static and rendered brand
  validation; fictional `acme-demo` brand for tests.
- **Low-cost storyboard preview** (stills from estimated timings), DB migrations with automatic backups,
  `video-pipeline production|review|approve|reject|request-changes|export|publish|backup|scheduler|music|studio`.
- Git repository with secret-scanned commits.

### Changed
- Remotion 4.0.507 → 4.0.540 (zod advisory fixed); Studio bound to loopback by a verified postinstall patch.
- Theme assets moved under `public/brands/shrotihost/` (old paths kept for the legacy `Short`).
- Timeline construction extracted into `pipeline/timeline.py` (shared by renders and previews).

### Fixed
- Fresh registries were backed up as v0.2.0 databases on every open (found and fixed during this release).
- QA price checks: rupee-glyph OCR misreads; frames now sampled after every element has settled.

## 0.2.0 — 2026-11-13: production pipeline

### Added
- `pipeline/` Python package and `video-pipeline` CLI: `doctor`, `validate`, `create [--run] [--force]`, `render`,
  `retry`, `cancel`, `qa`, `status`, `clean` (dry run by default), `assets`, `benchmark`; `--json` output, exit codes.
- SQLite job registry with validated state machine (QUEUED → … → COMPLETED / FAILED / CANCELLED / RETRYING),
  per-stage records, events, heartbeats, stale-job recovery, duplicate-job prevention, global render slots.
- Stage caching by input hash and verified output sha256: retries resume, they don't start over.
- TTS provider interface (`edge`, offline `mock`), with a content-addressed cache that is re-validated on every hit, timeouts, transient-only exponential backoff.
- Word-timing alignment (merged and split boundaries, numbers ↔ words, contractions, em-dashes, punctuation) and validation (order, overlap, bounds, missing).
- Per-scene voiceover assembly with pause trimming. Caption pages → SRT + karaoke ASS, with validation.
- Storyboard schema + time-expression language (`@word:grow+0.45`, named cues) and automatic SFX from brand sound conventions.
- Data-driven Remotion `Storyboard` composition (`src/engine/`, 14 block types, responsive short/landscape layout, theme layer) behind a versioned render contract.
- Chunked, resumable rendering: VideoToolbox with automatic x264 fallback, Chromium crash/stall retry, process-group kill, memory-gated adaptive concurrency.
- Audio: voice levelling before ducking, measured ducking depth, two-pass EBU R128 master, clipping/silence/peak analysis.
- Automated QA (structure, full decode, black/frozen/blank frames, loudness/true peak/clipping/silence/voice presence, captions) → `qa-report.json`, `QA_REPORT.md`, contact sheets, preview frames.
- Asset registry with sha256 ids, licence lookup (never assumed), SVG safety scan, per-job manifest.
- Brand theme layer (`brands/shrotihost/`), presets (`shorts`, `landscape`, `product-demo`, `educational`), and the Shroti Host storyboard (`projects/`).
- Sustained-throughput benchmark (swap and page-out gated), tests (pytest 92 incl. 1 real-render e2e, vitest 15), eslint.
- Docs: ARCHITECTURE, AUDIT_REPORT, QA_GUIDE, TROUBLESHOOTING, PERFORMANCE, BENCHMARK_REPORT, SECURITY, LICENSING.

### Fixed during hardening
- Chromium (launched detached by Remotion) is now killed on timeout/cancel/interrupt and counted in memory measurements.
- Ducking no longer depends on the TTS provider's output level (voice levelled to −18 LUFS first).
- QA blank-frame detection (FFmpeg `metadata` filter only honours one `key=`).
- Ctrl-C / SIGTERM during a job marks it CANCELLED immediately (resumable) instead of leaving it active.

### Changed
- `src/shrotihost/scenes/Problem.tsx`: removed an unused import (lint). No behaviour change.
- `src/Root.tsx`: registers the `Storyboard` composition. Existing compositions are unchanged.

### Unchanged (backward compatible)
- `Short` / `StarterShort` / `Landscape` compositions and `scripts/*` (`npm run verify` still passes).

## 0.1.0 — 2026-11-13: initial workspace
- Remotion project, edge-tts voiceover script, FFmpeg mixer with ducking, opus-sound-layer CC0 kit, Shroti Host Short.
