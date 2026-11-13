# Benchmark report — v0.3.0 vs v0.2.0

**Machine:** Apple M1 Pro (8P+2E), 16 GB RAM, macOS. **Date:** 2026-11-13. Other apps were open throughout
(swap 8.6–8.8 GB of 10 GB used before the runs), so numbers are realistic, not best-case.
Raw data: `.pipeline/benchmark.json` (current + history), `.pipeline/benchmark-v020-final.json`,
`output/eval-llm/bench-*.json`, `output/eval-voice/RESULTS.md`.

## Rendering (same fixture and settings as v0.2.0)

`video-pipeline benchmark`: `src/engine/fixtures/sample-short.json` / `sample-landscape.json` (contract v1
fixtures, all 14 v1 block types), 450 frames, PNG capture, BT.709, VideoToolbox 40 Mbps, 3 back-to-back runs per
configuration. Orphaned Chromium processes from earlier tooling were stopped first.

| Format | Tabs | v0.2.0 worst fps (Remotion 4.0.507) | **v0.3.0 worst fps (4.0.540)** | v0.3.0 runs | Peak RSS (tree) | Swap Δ / page-outs |
|---|---|---|---|---|---|---|
| short | 4 | 21.5 | **55.2** | 55.2 · 59.2 · 57.5 | 1.41–1.43 GB | 0 / 0 |
| short | 6 | 21.8 | **68.3** | 67.7 · 69.8 · 70.1 · 70.3 · 68.3 · 70.5 | 1.78 GB | 0 / 0 |
| short | 8 | 18.8 (unstable: +385 MB swap) | **72.5** | 72.5 · 74.3 · 72.5 | 2.14 GB | 0 / 0 |
| landscape | 4 | 21.6 | **59.2** | 59.2 · 59.2 · 60.7 | 1.40 GB | 0 / 0 |
| landscape | 6 | 21.8 | **70.3** | 70.5 · 70.3 · 72.9 | 1.77 GB | 0 / 0 |

**What changed:** the same frames render about **3.2× faster** at the default. The difference coincides with the
Remotion 4.0.507 → 4.0.540 upgrade; its Chromium runs with `--remotion-shared-memory-capture` (a shared-memory
frame-capture path), which removes most of the screenshot overhead that made v0.2.0 capture-bound. Not separately
bisected.

**Default changed with evidence: 4 → 6 tabs (both formats).** 4 → 6 tabs gains 18–24%; 6 → 8 gains only ~6% for
+360 MB. The selection rule now prefers fewer tabs within **10%** (was 5%). This machine's swap is ~85% full, v0.2.0
showed 8 tabs turning unstable under memory pressure, and 15-second runs can't show long-render behaviour.
One render job at a time remains the default.

## Production runs (end to end, real jobs)

| Run | v0.2.0 (Edge TTS, contract v1) | v0.3.0 (local Kokoro, contract v2, visual QA) |
|---|---|---|
| Shroti Host Short (9 scenes, ~34 s) render stage | 1061 frames in 51.6 s (20.6 fps, 4 tabs) | 1021 frames in 34.1 s (≈30 fps incl. chunk start-up; chunks reached 40–42 fps) |
| QA stage | 12.7 s (29 checks) | 18–19 s (41 checks: + layout manifest, OCR, logo/watermark/palette) |
| Voice stage | 15.5 s (online, 9 scenes) | 10.6 s uncached (local, 6 scenes; offline demo) · <1 s cached |
| **Offline demo (brief → AWAITING_APPROVAL)** | n/a | **238 s total**: concepts 70 s · storyboard 107 s · preview 8 s · render+QA 52 s |

## Local AI inference (from the creative and voice engineers' measurements)

| Workload | Model / runtime | Speed | Peak memory | Notes |
|---|---|---|---|---|
| Creative LLM | Qwen3-4B-Instruct Q4_K_M, Ollama 0.40.16 (Metal) | 36.6 tok/s output (31.7–39.2), load 1.0 s warm, prompt latency 0.8 s | 3.2 GB RSS | 57/57 schema-valid replies; **43k page-outs during a run → never alongside a render** (scheduler enforces) |
| Existing Qwen3.5 (7.6 GB) | Ollama | not loaded | needs ~8.6 GB | memory guard refused (5.7 GB available) |
| TTS | Kokoro-82M fp32, onnxruntime CPU (4 threads) | RTF 0.22–0.23 uncontended (≈4.4× real time) | ~0.6–0.7 GB | CoreML provider measured slower (RTF 0.25) and 1.8 GB |
| TTS | Piper medium voices | RTF ~0.03 | ~0.35 GB | lower intelligibility (WER 0.09–0.22) |
| Alignment fallback | Whisper base.en int8 (faster-whisper) | n/a (fallback only) | ~0.85 GB | native durations used in all demo scenes |
| OCR | Apple Vision (on-device) | ~1 s per frame batch | small | no download |

## Scheduling

The measured footprints (LLM 3.2 GB, render 1.8 GB at 6 tabs, TTS 0.7 GB) don't fit together on this machine
without swapping, so v0.3.0 runs one heavy workload at a time (render > TTS > LLM > background, configurable),
waits for reclaimable memory, and stops the LLM runtime before rendering. In the offline demo the runtime was
stopped at 21:00:13 and the render started at 21:00:21 (demo log); the scheduler granted render with 4.26 GB
available, and its four chunks rendered at 48–56 fps with swap Δ 0 MB and page-outs Δ ≤ 6 each (job log; that
render used the then-default 4 tabs).
