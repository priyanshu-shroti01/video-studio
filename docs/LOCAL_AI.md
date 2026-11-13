# Local AI runtime

Briefs, scripts and project data go **only** to a local model on `127.0.0.1`. There are no hosted AI APIs.

## What the LLM does

The model is an assistant inside fixed structures, never the owner of layout, timing or facts. It is optional:
every task has a deterministic fallback, so the pipeline also runs with the runtime stopped.

| Where | Role of the LLM | Fallback |
|---|---|---|
| Hybrid creative engine (`pipeline/creative`, the default) | picks a hook from the template's options and drafts narration **inside validated slots** (word budget, banned phrases, bound numbers, verifiable claims, anchored cue words, sync). It never sees or places blocks, labels or times | the hand-written copy bank, per line ([CREATIVE_SYSTEM.md](CREATIVE_SYSTEM.md)) |
| LLM-only engine (`pipeline/intelligence`, opt-in with `"engine": "llm"`) | writes concepts and storyboards scene by scene, with a repair loop | template concepts and scenes ([CREATIVE_ENGINE.md](CREATIVE_ENGINE.md)) |
| Social metadata (`pipeline/social/metadata.py`, `video-pipeline social draft`) | drafts free text only: YouTube title, hook and summary, Instagram hook and body, optional first comment, extra tags. Links, prices, chapters, hashtags and disclosures are added by code | the deterministic template, per field ([SOCIAL_PUBLISHING.md](SOCIAL_PUBLISHING.md)) |

Every reply is JSON-schema constrained and validated, and all LLM work runs under the cross-process scheduler, so it
never overlaps a render.

## Decision: Ollama 0.40.16 + `qwen3:4b-instruct-2507-q4_K_M`

| | Ollama (chosen) | llama.cpp `llama-server` | MLX-LM |
|---|---|---|---|
| Apple Silicon | Metal (GGUF) + MLX runner (safetensors) | Metal | MLX (native) |
| Schema-constrained JSON | `format: <JSON schema>` → grammar (anyOf, enum, min/maxItems, maxLength) | `json_schema` → GBNF | outlines-style libs only (extra Python deps) |
| Memory control | `keep_alive: 0` unloads per request; `OLLAMA_MAX_LOADED_MODELS=1` | kill the process | in-process; unload = free the Python objects |
| Install (Homebrew bottles, measured) | ollama 67.6 MB + mlx 240 MB + mlx-c 1 MB (~99 MB download) | ~11 MB download (llama.cpp 8.6 + ggml 2.0 MB) | mlx-lm + numpy + python@3.15 … |
| Licence | MIT | MIT | MIT |
| Loads the existing `qwen3.5:latest` (safetensors NVFP4/MXFP8) | **yes** (MLX runner; metadata parsed by `/api/show`) | no (needs GGUF) | maybe (different packaging) |
| New Python deps | none (HTTP via urllib) | none | yes (not allowed right now) |

Ollama wins on three counts: it's the only runtime that can read the model already on disk, it unloads per
request, and its HTTP API with JSON-schema `format` works from stdlib `urllib`. llama.cpp would be the leaner
choice (about 11 MB) if the existing model weren't a factor.

**Model:** Qwen3-4B-Instruct-2507, Q4_K_M GGUF, 2,497,293,444 bytes (registry manifest sum). It's the
non-thinking instruct variant with a 256K context, of which the pipeline uses 6,144. Licence is Apache-2.0,
verified from the licence layer shipped with the model (sha256:d18a5cc71b84) and from the Hugging Face card
(`license: apache-2.0`, LICENSE file). Source:
`ollama pull qwen3:4b-instruct-2507-q4_K_M`, upstream `Qwen/Qwen3-4B-Instruct-2507`. The sha256 was
verified by Ollama on pull. Candidates considered are listed in `pipeline/intelligence/model_registry.json`.

## Running it

```bash
brew install ollama                                   # no service is installed or started
python -m pipeline.intelligence runtime start         # loopback-only server, env below, pid in models/llm/runtime/
python -m pipeline.intelligence runtime status
python -m pipeline.intelligence runtime stop          # stops only a server the pipeline started
```
Server environment set by `runtime start` (`providers.SERVER_ENV`):
`OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_NO_CLOUD=1`, **`OLLAMA_NOPRUNE=1`** (by default Ollama prunes blobs
on startup, which could touch the pre-existing qwen3.5 store), `OLLAMA_KEEP_ALIVE=0`,
`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
`OLLAMA_CONTEXT_LENGTH=8192`. Models live in the default `~/.ollama/models` (shared with the existing qwen3.5).

## Guards in the provider (`pipeline/intelligence/providers.py`)
- **Loopback only:** a non-loopback host is refused. Any model the server reports with `remote_host`
  (e.g. `glm-5.3:cloud`, which is in this store) is refused before a request is sent.
- **Memory guard:** before each request, `pipeline.system.mem_snapshot()` must show at least
  measured requirement + 400 MB reclaimable. Otherwise it raises `LLMUnavailable` and the deterministic planner
  is used.
- **One model at a time:** any other resident model is unloaded first. `keep_alive` is 30 s within a batch,
  with an explicit unload at the end of every concepts/storyboard call.
- Timeout (240–420 s), retries on transport errors, JSON parse and schema check on every reply. A missing
  binary, server or model is a graceful `LLMUnavailable` and falls back to the template path.

## Measured on this machine (M1 Pro, 8P+2E, 16 GB, macOS 27.2, Ollama 0.40.16, 2026-11-13)
These runs measured the LLM-only engine (concepts and per-scene storyboards).
Raw: `output/eval-llm/bench-qwen3_4b-instruct-2507-q4_K_M-*.json` · run: `python -m pipeline.intelligence bench`

| metric | run 1 (20:05, one-shot storyboards) | run 2 (20:28, final per-scene path) |
|---|---|---|
| contention | voice ASR eval (~370% CPU) started mid-run | none (checked before and after) |
| generations (JSON-schema validity) | 11/11 valid | **57/57 valid** (8 concepts, 46 scenes, 3 publishing) |
| model load (cold → Ollama `load_duration`) | 2.56 s | 1.04 s (file cache warm) |
| prompt eval latency (mean / max) | 2.03 s / 4.57 s | 0.80 s / 3.69 s (1.5–1.9k-token prompts, prefix cache) |
| output tokens/s (mean, min–max) | 33.5 (29.2–36.2) | **36.6 (31.7–39.2)** |
| wall per concept / per scene | 10.2 s / — | 9.8 s / 3.9 s; full storyboard 55–74 s incl. repairs |
| peak RSS of ollama processes | 3,118 MB | **3,206 MB** (registry `memory_required_mb`) |
| reclaimable memory before → after load | 4,667 → 2,267 MB | 5,190 → 3,570 MB |
| swap delta / page-outs | +2,238 MB (+613 MB during load; rest overlapped the ASR run) / 284 | −56 MB / **43,311 page-outs** |

Page-outs in run 2 show real memory pressure even without swap growth. Don't run the model while a
Remotion render is active; the memory guard (≥ 3.6 GB reclaimable) and the `bench` contention check exist for
this reason.

**Quality rubric (run 2, automatic scores plus a manual reading of the outputs):**
- **Hook strength:** automatic score 2.75/3 (length, speaks to the viewer, tension). Read by hand, the hooks
  are serviceable but generic ("Starting a website? You're paying way too much.") and repeat across seeds.
- **Fact discipline:** 1 of 8 concepts invented a price ("₹60/month"); the pipeline catches and regenerates
  these. 0 of 3 final storyboards kept an invented claim. In demo runs the checker caught "₹100/month",
  "₹40", "247", "30 seconds", "affordable", "built for", "guarantee" and "hidden". It did not catch number-free
  comparisons like "costs less than a coffee" or "no tech skills needed".
- **Distinctness:** before enforcement, the model chose the same animation, music and CTA style for all 3
  concepts and often the same 5–7 hero blocks. Pattern, animation, music and CTA are now restricted in the
  grammar to unused values. Hook and block similarity is still checked, and repeated near-duplicates fall back
  to a template concept (this happened for 1 of 3 concepts in the final demo).
- **Storyboards:** one-shot whole-storyboard generation (run 1) failed. Every draft had 4 short scenes,
  missing beats and anchors outside the scene. Generating scene by scene with required blocks in the schema
  (run 2) gave 3/3 valid storyboards that fit the duration: 14/18 scenes from the model (13 after repair),
  4/18 from the template.

**qwen3.5:latest (pre-existing, 7.64 GB, 9.7B, safetensors NVFP4, MLX runner):** Ollama 0.40.16 lists it and
`/api/show` parses it (`format: safetensors`, `quantization_level: nvfp4`, `runner: mlx`). It was **not loaded**:
the memory guard recorded 5,673 MB available against 8,600 MB needed (swap already 8.8 GB). So whether this
runtime can actually run it on this machine is unverified. Raw: `output/eval-llm/bench-qwen3.5_latest-*.json`.

## Privacy notes
- The Ollama server has a scheduled "model recommendations" catalog refresh (log: `model_recommendations.go`).
  It is a catalog fetch, not prompt data. `OLLAMA_NO_CLOUD=1` disables remote inference and web search.
- Internally Ollama runs `llama-server` on a random 127.0.0.1 port.
