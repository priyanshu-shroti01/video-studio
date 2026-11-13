# Architecture (v0.4.0)

A local-first, multi-brand creative production platform. A **product brief** becomes concepts, a storyboard, a
reviewed preview, a local voice, an animated video, a QA report and an approval package. Everything runs on this
Mac. The only network use is optional and explicit: dependency and model installs, onboarding a brand from its
website (`brand init`), the public-site fact refresh, the CC0 music fetch, opt-in keyword research, and (after
human approval and an explicit confirmation) uploads to YouTube or Instagram.

```
                ┌────────────── Studio UI (studio/, 127.0.0.1) ─────┐   ┌──── CLI: video-pipeline ────┐
                └───────────────────────────┬───────────────────────┘   └──────────────┬──────────────┘
                                            ▼                                            ▼
                          pipeline/api.py — the service layer (every workflow rule lives below it)
   ┌──────────────────────────────┬───────────────────────────────┬──────────────────────────────────────┐
   │ CREATIVE                      │ PRODUCTION ENGINE             │ PLATFORM                              │
   │ intelligence_bridge.py picks  │ pipeline/runner.py stages:    │ productions.py  lifecycle + approval  │
   │ the engine per brief:         │ PREPARING → GENERATING_AUDIO  │ publishing.py   gate, export, YouTube │
   │  creative/  hybrid (default): │ → BUILDING_TIMELINE →         │ social/         routing, metadata,    │
   │   scene templates, copy bank, │ RENDERING → POST_PROCESSING   │                 Instagram, MCP server │
   │   industry packs, rules       │ → QA → COMPLETED              │ brands.py       profiles + isolation  │
   │  intelligence/  LLM-only      │ jobs.py SQLite registry       │ scheduler.py    one heavy job at once │
   │   (opt-in), fact base, claims │ timeline.py (pure)            │ archive.py · video_out.py             │
   │ preview.py + preview_gate.py  │ voice/ + tts.py (Kokoro/Piper)│ music.py · assets.py · shared_assets  │
   │ sync_check.py                 │ qa.py + visual_qa/            │ migrations.py   schema + backups      │
   └──────────────────────────────┴───────────────────────────────┴──────────────────────────────────────┘
                                            ▼  RenderProps v2 (contract.py ⇄ src/engine/types.ts)
               src/engine/ — Remotion `Storyboard` composition: motion tokens, 32 block types, 6 backdrops,
               watermark, layout manifest (scripts/engine-layout.mjs)  ·  src/shrotihost/ — legacy hand-built `Short`
```

## Production lifecycle

`DRAFT → STORYBOARD_READY → PREVIEW_READY → RENDERING → QA_COMPLETE → AWAITING_APPROVAL → APPROVED →
PUBLISHING → PUBLISHED` (+ CHANGES_REQUESTED, REJECTED, FAILED, CANCELLED). Two steps wait for a person:

1. **Preview approval** (before the expensive render). `production preview` renders one still per scene from
   estimated timings and runs the storyboard quality gate. A named reviewer then approves that exact storyboard
   (`production approve-preview`, or the Studio's Preview & QA). `production render` is refused without it.
2. **Final approval** (after QA). A successful job stops at AWAITING_APPROVAL; see
   [PUBLISHING_APPROVAL.md](PUBLISHING_APPROVAL.md).

A production owns a render *job*, which runs the job state machine (`pipeline/jobs.py`).

## Creative engines

The engine is chosen per brief by `pipeline/intelligence_bridge.py`:

| `"engine"` | Package | What it does |
|---|---|---|
| `"hybrid"` (default) | `pipeline/creative` | Deterministic scene templates own composition, animation and every on-screen label. Prices and features come only from verified facts. The local LLM may propose a hook and draft narration inside validated slots, with a hand-written copy bank as the fallback. See [CREATIVE_SYSTEM.md](CREATIVE_SYSTEM.md) |
| `"llm"` (opt-in) | `pipeline/intelligence` | The v0.3.0 engine: the local LLM designs the storyboard scene by scene, with a repair loop and a template fallback. See [CREATIVE_ENGINE.md](CREATIVE_ENGINE.md) |

Both share the fact base (`knowledge/<brand>/facts.json`), the claim checker and the output files, and run their
LLM work under the scheduler. The hybrid engine selects its templates and copy through an **industry pack**
(`pipeline/creative/industries/`, chosen by `brand.json → creative.industry`; today `web-hosting`).

## Quality gates

| Gate | When | Module | Blocks |
|---|---|---|---|
| Storyboard preview gate | after `production preview`, before any voice or render | `pipeline/preview_gate.py` (+ `sync_check.py` on estimated timings) | preview approval while it FAILs |
| Human preview approval | before `production render` | `pipeline/api.py` (`approve_preview`, bound to the storyboard hash) | the render |
| QA on the final file | QA stage of the job | `pipeline/qa.py`, `visual_qa/`, `sync_check.py` | the job (critical checks) |
| Review flags + final approval | AWAITING_APPROVAL | `pipeline/productions.py` | approval, export, publishing |

Details: [QA_GUIDE.md](QA_GUIDE.md).

## Multi-brand

- Each brand is data: `brands/<id>/` (`brand.json`, `theme.json`, `assets.json`, `pronunciation.json`),
  `public/brands/<id>/`, `knowledge/<id>/facts.json`, `projects/<id>/`. There are no brand constants in code.
- `pipeline/brands.py` loads profiles, enforces asset isolation and resolves a brief to a brand by id, name or
  domain (`resolve_brand`). Brands marked `"hidden": true` (test fixtures such as `acme-demo`) are usable by
  exact id but never listed.
- `pipeline/brand_init.py` (`video-pipeline brand init`) drafts a new brand from its home page. It never invents
  prices and never overwrites an existing brand.
- Shared, licensed files every brand may use live in `public/shared/` (records in `public/shared/assets.json`,
  looked up by `pipeline/shared_assets.py`).

See [BRANDING.md](BRANDING.md).

## Publishing

`pipeline/publishing.py` owns the publish gate, the export package and the YouTube adapter. `pipeline/social/`
adds routing from the real file (ffprobe), per-platform metadata (`publishing/metadata.json`, part of the approval
hash), opt-in keyword research, the Instagram Reels adapter and a stdio MCP server (`uv run video-pipeline-mcp`).
Credentials are per brand (`.pipeline/secrets/<brand>/`), and every upload is refused unless the platform confirms
the account named in `brand.json → publishing.accounts`. See [SOCIAL_PUBLISHING.md](SOCIAL_PUBLISHING.md).

## Archive and video-out

- **Archive** (`pipeline/archive.py`, `video-pipeline archive --production/--job/--all-except`) hides productions
  and jobs from every list and the dashboard and moves their files to `output/_archive/`. Nothing is deleted;
  approvals and the audit history stay in the registry. Running or publishing work is refused. Registry migration
  v3 adds the `archived_at` columns.
- **video-out** (`pipeline/video_out.py`) keeps copies of finished videos by brand with readable names:
  `video-out/<brand>/for-review/` and `video-out/<brand>/approved/`. It syncs on every production state change
  and on demand (`video-pipeline video-out`). The originals, whose hashes the approval is bound to, stay in
  `output/`.

## Components

| Module | Responsibility |
|---|---|
| `pipeline/api.py` | service layer for CLI + Studio: dashboard (attention queue, brand overview), productions, concepts, storyboard save (validated, versioned), preview + preview approval, render, monitor, assets, safe file serving |
| `pipeline/intelligence_bridge.py` | engine selection per brief, scheduler-gated LLM work, claim reports |
| `pipeline/creative/` | hybrid engine: templates, copy bank, copywriter (LLM slots), director, rules, anchors, industry packs; opt-in (`"components": "generate"`) component generator (`composer.py`), freshness memory, component store + brand library (`components.py`) |
| `pipeline/intelligence/` | local LLM provider (Ollama, mock), model registry, brief schema, narrative patterns, LLM-only concepts and storyboards, claim verification, fact base refresh, benchmarks |
| `pipeline/preview.py`, `preview_gate.py`, `sync_check.py` | preview stills and contact sheet, storyboard quality gate, narration ↔ visual sync and measured A/V offset |
| `pipeline/voice/`, `pipeline/tts.py` | Kokoro / Piper / mock (+ gated Edge) providers, worker process, pronunciation, native timing, Whisper fallback, model registry |
| `pipeline/timing.py`, `captions.py`, `audio.py` | alignment + validation, caption pages/SRT/ASS, voiceover assembly (incl. `holdAfter`), voice-levelled ducking, two-pass mastering |
| `pipeline/storyboard.py`, `timeline.py`, `contract.py` | storyboard schema (v2/v2b blocks), time expressions, auto-SFX conventions, RenderProps build, estimated timings |
| `pipeline/render.py` | bundle cache, chunked resumable renders, VideoToolbox/x264, memory-aware tabs, crash/stall retry |
| `pipeline/qa.py`, `visual_qa/` | structural/visual/audio/caption/sync QA, layout-manifest checks, OCR (Apple Vision via `tools/ocr/ocr.swift`), logo/watermark/palette checks, pronunciation checklist |
| `pipeline/productions.py`, `publishing.py` | lifecycle, review flags, package hash, approvals, invalidation, export, publish gate, YouTube adapter |
| `pipeline/social/` | routing, metadata drafting + validation, keywords, Instagram adapter, per-brand accounts and secrets, CLI, MCP server |
| `pipeline/brands.py`, `brand_init.py`, `shared_assets.py` | brand profiles, isolation, validation, `resolve_brand`, hidden brands, onboarding, shared licensed assets |
| `pipeline/archive.py`, `video_out.py` | archiving, finished-video copies by brand |
| `pipeline/scheduler.py` | cross-process heavy-workload queue with priorities and memory gating |
| `pipeline/music.py`, `assets.py` | licensed music library, asset licences |
| `pipeline/jobs.py`, `migrations.py` | SQLite registry (jobs, stages, events, productions, approvals, flags, publications, scheduler, audit) and migrations |
| `studio/` | local web UI (stdlib server + React/esbuild frontend) on `pipeline/api.py` |
| `src/engine/` | data-driven Remotion engine (contract v2, v2b look), motion library (`motion/`), layout manifest |

## Key design decisions

- **Python owns time; Remotion only draws.** Cue times, keystrokes and SFX come from the real voice timings. The
  same pure `timeline.build_timeline` feeds renders and low-cost previews.
- **Templates own design; facts own numbers.** In the default engine the LLM never places blocks or writes
  labels. Every price, plan, spec and URL is checked against the verified fact base. Brief-supplied claims that
  aren't on the site become blocking review flags rather than being silently trusted or dropped.
- **Look before rendering.** The preview gate and a person's preview approval catch empty, repetitive or
  out-of-sync storyboards before any voice or full render is spent on them.
- **Local by default, offline after install.** TTS, alignment, LLM, OCR, rendering and QA are local. The
  Ollama runtime is loopback-only with cloud models refused; Edge TTS needs an explicit opt-in.
- **One heavy workload at a time.** Measured on this M1 Pro: the LLM peaks ~3.2 GB with heavy page-outs, a
  6-tab render ~1.8 GB, Kokoro ~0.6 GB. The scheduler serialises them (render > tts > llm > background) and
  waits for memory. The LLM runtime unloads after each request and is stopped before rendering.
- **Approval is bound to content.** The package hash covers every file a reviewer sees, including the social
  metadata. Any change invalidates approval; publishing re-hashes the video right before upload.
- **QA reads the pixels.** The layout manifest says where every text/logo should be; OCR and pixel checks
  confirm the rendered frames match. Prices are checked digit-exactly.
- **Brands are data and isolated.** No brand constants in code; per-brand asset roots, facts, pronunciation,
  credentials and expected accounts.

## Folder layout

```
brands/<id>/{brand,theme,assets,pronunciation}.json   public/brands/<id>/   public/shared/ (+ assets.json)
knowledge/<id>/facts.json      projects/<id>/*.json, projects/<id>/briefs/*.json      presets/*.json
audio/kit (CC0 SFX)            audio/music (CC0 library + library.json)               tools/ocr/
models/{voice,llm}/ (git-ignored)     .pipeline/{registry.db, backups/, bundles/, cache/, studio/, secrets/<brand>/}
output/<job>/                  output/productions/<id>/      output/_archive/          video-out/<brand>/
docs/ (guides)   docs/reports/ (benchmarks, creative comparison)   docs/images/   scripts/   scripts/legacy/ (v0.1 scripts)
```

`output/productions/<id>/` holds `brief.json`, `concepts/`, `storyboard.json` (+ history), `project.json`,
`preview/` (stills, `contact-sheet.jpg`, `gate.json`, `GATE.md`), `approval/` and `export/`.

The job output layout (`video/ audio/ captions/ assets/ previews/ reports/ metadata/ publishing/ logs/ work/`) is
unchanged from v0.2. Reports include `qa-report.json`, `QA_REPORT.md`, `visual-qa-<fmt>.json`,
`branding-report.json`, `alignment-report.json`, `pronunciation-checklist.md`, and (for productions)
`claims-report.json`, `review.json`, `creative-plan.json`.
