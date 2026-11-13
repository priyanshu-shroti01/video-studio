# Self-launch film: repository audit

Scope: what Video Studio can actually do today, verified against the code and real production records, before
producing its own launch film. Date: 2026-11-14. Starting point: `main` at `11587ed`, clean working tree.

Every number below was checked in this audit, either by reading the code or by reading a real job's reports.
README statements were not taken on trust.

## 1. Production architecture (verified in code)

| Layer | Where | What it does |
|---|---|---|
| Lifecycle | `pipeline/productions.py`, `pipeline/api.py` | DRAFT → STORYBOARD_READY → PREVIEW_READY → (human preview approval) → RENDERING → QA_COMPLETE → AWAITING_APPROVAL → APPROVED → PUBLISHED; CHANGES_REQUESTED / REJECTED; every decision audited |
| Creative (default) | `pipeline/creative/` | Hybrid engine. Industry packs give templates, blueprints and a copy bank. The director builds three concepts as template sequences. Rules reject anything without hero visuals, a real demo, verified claims or word-anchored beats |
| Creative (opt-in) | `pipeline/intelligence/` | LLM-only engine (`"engine": "llm"`) |
| Facts | `knowledge/<brand>/facts.json`, `pipeline/intelligence/claims.py` | Every number and claim on screen or spoken must match a fact with a verbatim source excerpt |
| Timing | `pipeline/timeline.py`, `pipeline/storyboard.py` | Python owns time: `@word:X+0.3` expressions resolve against the real voice's word timings |
| Voice | `pipeline/voice/`, `pipeline/tts.py` | Local Kokoro (15 voices installed) and Piper (3 voices), word-level timing, per-brand pronunciation |
| Render | `src/engine/` (Remotion 4.0.540) | `Storyboard` composition with 30 block types and 6 backdrops (counted in `pipeline/contract.py` / `src/engine/types.ts`) |
| Mix and master | `pipeline/audio.py` | FFmpeg: voice, licensed music with ducking, CC0 sound effects, loudness normalisation |
| QA | `pipeline/qa.py`, `pipeline/visual_qa/`, `pipeline/sync_check.py` | Checks run on the rendered file: structure, decode, loudness, captions, layout manifest, digit-exact OCR, branding, A/V offset, narration sync |
| Gates | `pipeline/preview_gate.py`, `pipeline/publishing.py` | Storyboard preview gate plus human preview approval; final approval bound to SHA-256 of every file; publishing only after an explicit confirm |
| Studio | `studio/` | Local web UI covering the whole lifecycle |

## 2. Creative capabilities (verified)

- **Templates:** 22 (9 generic in `pipeline/creative/templates.py`, 13 in the `web-hosting` pack). There was only one industry pack.
- **Blocks:** 30 types, including kinetic text, progress, install-flow, server-stack, dashboard, device, image, terminal, plan cards, logo sting and outro.
- **Backdrops:** 6.
- **Copy:** a local LLM (Qwen3-4B via Ollama) may rewrite copy-bank lines. In practice the 4B model mostly echoes the bank. Rejected lines fall back to the bank.

## 3. Evidence behind the numbers the film may use

| Claim | Evidence checked |
|---|---|
| QA 43 / 43 PASS on the approved WordPress Short | `output/20261113-230607-3af663/reports/qa-report.json` (PASS 43, WARN 0, FAIL 0) |
| 0 ms A/V offset | the same report, check `sync.av_offset`: max lag 0 ms, drift 0 ms |
| 0 unverified claims | `claims-report.json` of that job |
| Render ≈ 54 fps for that Short | `render-report.json`: 53.86 fps; the benchmark's 68–70 fps is for a fixture (`.pipeline/benchmark.json`) |
| Stage times for that Short | voice 3.6 s (cached), render 20.5 s, mixing 11.8 s, QA 21.4 s (job stage records) |
| Speaking rate | 2.37 words/s, measured on three renders; estimators use 2.33 |
| Tests | pytest 331 passed, 1 skipped (live local model); vitest 55; e2e 1, all run in this session |

## 4. Gaps between the docs and what the product could do

These were found during the audit and had to be fixed for this film. All fixes are generic, not specific to the film:

1. **No video inside a scene.** The engine had images and device frames with still screenshots, but no way to show
   real screen recordings. Fix: a `footage` block (muted `OffthreadVideo`, browser or laptop frame, word-anchored zooms,
   last-frame hold), with Python validation, licensing and QA.
2. **Pricing was mandatory.** The hybrid engine required a priced plan, a pricing scene and plan facts, so it could not
   make a film about software with no price. Fix: `Pack.priced = False` (unpriced packs), with the pricing rule
   applying only to priced products.
3. **Length was fixed at 30–35 s with at most 7 scenes.** Fix: the window now comes from the brief. Shorts (≤ 40 s)
   keep exactly 30–35 s. `duration_flexible: true` lets the story set the length, capped below 3 minutes so vertical
   videos stay Shorts.
4. **One format per brief.** Fix: an optional `formats` list in briefs, and an "Also render" option in the Studio form.
5. **Only one industry pack (web hosting).** Fix: a `software` pack with real-workflow templates (production chain,
   real app footage, pipeline stages, local stack, QA dashboard, self-reveal) and three distinct blueprints.
6. **CTA URLs had to be a bare domain.** Fix: an optional brand `displayUrl` (here, the repository path), while the spoken cue stays "GitHub".
7. **`server-stack` always ends in a "globe" node**, which suggests a web server. This is noted, and is addressed with
   a generic target-icon option once the engine's footage work lands.

## 5. Screen capture and visual review

- **No screen capture exists in the product.** Footage is recorded from the real running Studio with Chrome DevTools
  Protocol screencasts (the same headless Chromium that Remotion uses), driven by scripted input. Each frame is the
  actual UI; nothing is mocked.
- **Review tools:**
  - scene preview contact sheets (`production preview`);
  - QA contact sheets;
  - exact-frame extraction (`ffmpeg select=eq(n,N)`; QA seeking was verified frame-accurate);
  - `scripts/creative_metrics.py`.

## 6. Limitations and risks for this production

| Risk | Mitigation |
|---|---|
| The self-referential footage can't exist before the production does | Iterate: the first render uses footage of the brief being entered and the Studio pages; later iterations re-record this production's own concepts, render and output |
| Small UI text in 9:16 | Footage recorded at a higher resolution plus word-anchored zooms; frames inspected at phone size |
| Memory (16 GB), with recording, LLM and renders competing | One heavy job at a time; the LLM stops before rendering; recordings are made outside renders |
| The 4B LLM adds little to copy | Hand-written bank lines carry the copy; the LLM's role is stated honestly |
| Pronunciation of Remotion, FFmpeg, Ollama, Kokoro and GitHub | Per-brand pronunciation file; listening check before final approval |
| Remotion licence | Free for individuals and companies up to 3 employees (docs/LICENSING.md) |

## 7. Plan

1. Engine: a `footage` block (generic).
2. Creative: unpriced packs, a duration window from the brief, multi-format briefs, and a `software` pack with three blueprints.
3. Brand `videostudio`: theme, original logo, facts verified against the public repository, pronunciation.
4. Record real Studio footage, create the production through the Studio, and generate concepts through the real pipeline.
5. Preview, then human preview approval (delegated in chat for iterations), then render in 9:16 and 16:9, then QA.
6. Review the rendered output frame by frame and by listening, then iterate, re-recording the self-referential footage.
7. Evidence, creative review, launch materials, README, then a full regression run. Nothing is published or pushed without approval.
