# Changelog

## Unreleased

### Added
- **Self-launch film.** Video Studio's own 96-second launch film, made through the pipeline with real Studio
  footage and generated components, approved in both formats (production `P20261114-031556-9adf5`).
  - New `videostudio` brand: original logo, theme, verified facts and pronunciation.
  - Reports in `docs/reports/SELF_LAUNCH_*.md`; LinkedIn post text in `docs/launch/`.
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
