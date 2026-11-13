# Performance and tuning

Measurements: [reports/BENCHMARK_REPORT_V030.md](reports/BENCHMARK_REPORT_V030.md) (v0.3.0).
**v0.3.0 default for this M1 Pro (16 GB): VideoToolbox + 6 Chromium tabs + 1 render job at a time**: 68–70 fps
worst case (≈2.3× real time for 1080p30), ~1.8 GB peak, no swap growth. Since Remotion 4.0.540 (shared-memory
frame capture), throughput is ~3.2× v0.2.0's 21.5 fps at 4 tabs. 8 tabs adds only ~6% for +360 MB, so the
selection rule (prefer fewer tabs within 10%) keeps 6.

## Where the time goes (~34 s Short, v0.3.0 production run)

| Stage | Time | Notes |
|---|---|---|
| PREPARING | 0.1 s | preflight + asset validation |
| GENERATING_AUDIO | 10.6 s uncached / < 1 s cached | local Kokoro voice (6 scenes); no network |
| BUILDING_TIMELINE | < 0.1 s | |
| RENDERING | ~34 s | 1021 frames; Chromium frame capture dominates |
| POST_PROCESSING | ~8 s | mix (with stems), two-pass loudnorm, mux, previews (v0.2.0 measurement) |
| QA | 18–19 s | full decode, black/freeze scans, audio analysis, layout manifest, OCR, logo/watermark/palette |

End to end, fully offline, a brief reached AWAITING_APPROVAL in **238 s** (concepts 70 s · storyboard 107 s ·
preview 8 s · render + QA 52 s); see the [benchmark report](reports/BENCHMARK_REPORT_V030.md). The local LLM and a
render never run at the same time (the scheduler enforces it); stopping the LLM runtime before rendering frees its
memory.

## Knobs (project `render` section or preset)

| Setting | Default | Effect |
|---|---|---|
| `concurrency` | `"auto"` → benchmark result (6 as of v0.3.0) | Chromium tabs per render. Integer to override |
| `maxJobs` | 1 | Global render slots across all processes. Raise only with more RAM |
| `chunkFrames` | 300 | Larger = fewer Chromium restarts (faster), smaller = less work lost on a crash |
| `encoder` | `auto` | `auto` = VideoToolbox with automatic x264 fallback; `x264` forces software |
| `bitrate` | `40M` | Delivery quality; platforms re-encode anyway |
| `imageFormat` | `png` | Lossless frame capture. `jpeg` is faster but softens text edges |
| `stallTimeout` / `timeoutPerChunk` | 120 s / 900 s | Stall and hard-timeout guards |

## Memory protection (automatic)

- Before each chunk: wait (up to 5 min) until `1500 MB + 350 MB × tabs` is reclaimable.
- After each chunk: if swap grew more than 64 MB or page-outs exceeded 2000, halve the tabs for the remaining chunks.
- Chromium crash or stall: retry the chunk with half the tabs (2 retries).
- Peak RSS of the whole process tree (node + detached Chromium + encoder) is logged per chunk and saved in `reports/render-report.json`.

## Re-benchmark when

the machine, macOS, Remotion or Chromium version changes, or the engine gains heavier effects:

```bash
uv run video-pipeline benchmark                                  # full sweep (~15 min)
uv run video-pipeline benchmark --formats short --workers 4 6 --encoders videotoolbox --repeats 3   # focused
```

Results merge into `.pipeline/benchmark.json`, and `concurrency: "auto"` picks them up immediately.
