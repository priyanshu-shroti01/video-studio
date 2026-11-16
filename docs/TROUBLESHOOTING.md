# Troubleshooting

Start with `uv run video-pipeline doctor` and `uv run video-pipeline status --job-id <id>`.
The job's full log is `output/<id>/logs/pipeline.jsonl` (one JSON object per line); a production's render log is
`output/productions/<P>/render.log`, and `uv run video-pipeline production show --id <P>` lists its state and
review flags.

## Workflow and review

| Symptom / error | Cause | Fix |
|---|---|---|
| Preview gate **FAIL** (`production preview`, `preview/GATE.md`) | The storyboard has an empty or repeated scene, a scene without a hero visual, invented "Label: ₹N" text, an on-screen number that isn't a verified fact, overflowing text, or narration over a frozen screen / a number shown before it is spoken | Read the failing checks in `GATE.md` and look at `preview/contact-sheet.jpg`. Fix the storyboard (Studio Storyboard Editor, or `pipeline.api.save_storyboard`), then run `production preview` again. See [QA_GUIDE.md](QA_GUIDE.md#storyboard-preview-gate) |
| `the storyboard preview has not been approved by a person for this storyboard` (render refused) | `production render` needs a preview approval for the current storyboard | Run `production preview`, review the contact sheet and `GATE.md`, then `production approve-preview --id <P> --reviewer "Name"` (or **Approve preview for rendering** in the Studio) |
| `the storyboard changed after the preview; re-run the preview before approving it` | The approval is bound to the storyboard hash; any edit after the preview needs a new one | `production preview` again, then approve |
| `the preview quality gate FAILED; fix the storyboard first` | A FAILing gate can't be approved | See the preview-gate row above |
| Rendered video is longer than the target | The local voice speaks about 2.3 words/s (a brief's `pace` can make it calm or brisk); long copy, many scenes and `holdAfter` (silence after a scene's last word) all add time | Compare the length in `reports/QA_REPORT.md` with the brief's `duration_seconds`. Trim narration (a six-scene 30–35 s video fits about 62–70 words), shorten or remove `holdAfter`, or drop a scene. The Studio's storyboard editor shows an estimate at 2.33 words/s (2.0 for a Hinglish storyboard) |
| `concepts.md` says **"The local AI model isn't installed, so the copy came from the built-in copy bank"** (or **"couldn't start"**) | The local AI model is managed automatically: concepts and concept selection start Ollama when needed and stop it afterwards (only if they started it; a render also stops a pipeline-started one). Ollama is not installed, the model isn't pulled, or the server didn't come up, so the engine used the copy bank. The video is still valid; the copy is just less varied | Run `videostudio doctor` and follow its fix (typically `brew install ollama`, then `ollama pull qwen3:4b-instruct-2507-q4_K_M`), then run concepts again. Developers can still use `python -m pipeline.intelligence runtime start|stop|status` |
| `CONFIG_INVALID ... no creative.industry` | The brand has no `creative` section for the hybrid engine (brands drafted with `brand init --industry …` have one) | Add `creative.industry` (e.g. `web-hosting`) and the rest of the section to `brands/<id>/brand.json` ([BRANDING.md](BRANDING.md)) |
| `no brand matches ...` / `... matches several brands` | The brief's `brand` doesn't resolve to exactly one brand by id, name or domain | Fix the brief's `brand`, or pass `--brand <id>` to `production create`; `video-pipeline brand list` shows the brands |
| `approval would be invalidated: request changes first` (social draft) | Metadata is part of the approved package and can't change after approval | Draft before approving. To redraft an approved, unpublished production: `video-pipeline social draft --id <P> --reopen-review --actor "Name"` (audited) |

## Studio

| Symptom | Cause | Fix |
|---|---|---|
| Banner **"The Studio server is not running"** | The Studio process stopped (closed terminal, Ctrl-C, reboot) | `uv run video-pipeline studio`. The page keeps its last data and reconnects by itself; the session token survives restarts |
| Banner **"Not signed in to this Studio"** (or `401 UNAUTHORIZED`) | This browser has no valid session cookie (for example the token was rotated with `--new-token`) | Open `http://127.0.0.1:8765/` in the browser's address bar; that signs the browser in |
| Help chat says **"The helper is paused while a video renders"** | The help chat uses the local AI model, which never runs alongside a render (memory) | Wait for the render to finish (Render Monitor shows it), then ask again |
| Help chat says **"The helper needs the local AI model, and it isn't installed"** (or **"couldn't start"**, **"low on free memory"**) | Ollama or the model is missing, the runtime didn't come up, or there isn't enough free memory to load the model | Open **Setup** (or run `videostudio doctor`) and follow its fix for the AI model; close apps if memory is low. The guides answer the same questions meanwhile |
| "Dashboard unavailable" with no banner | An error from the service layer | Read the error box; the CLI equivalent (`video-pipeline production show`, `status`) shows the same detail |

## Publishing

| Symptom / error | Cause | Fix |
|---|---|---|
| `PUBLISH_ACCOUNT_MISMATCH ... credentials belong to account X ..., not brand B's account Y; refusing to publish` | The credentials in `.pipeline/secrets/<brand>/` are for a different channel / Instagram account than `brands/<brand>/brand.json → publishing.accounts` | Re-run the brand's OAuth setup with the right account, or correct the expected account id if it was entered wrongly ([SOCIAL_SETUP.md](SOCIAL_SETUP.md)). Nothing was uploaded |
| `PUBLISH_NOT_CONFIGURED ... has no publishing.accounts.<platform>` | The brand has no expected account for that platform | Add the channel id / `ig_user_id` to `brand.json → publishing.accounts` ([SOCIAL_SETUP.md](SOCIAL_SETUP.md)) |
| `found the legacy global youtube.json, which is not tied to a brand and is never used` | An old single-account credentials file | Move it into the brand's directory with the command printed in the message (`.pipeline/secrets/<brand>/`, mode 600) |
| `no approved Instagram caption: run video-pipeline social draft before approval` | The approved package has no Instagram entry in `publishing/metadata.json` | Request changes (or reopen review, above), run `video-pipeline social draft --id <P>`, then approve again |
| `publishing/metadata.json failed validation; redraft it before approval` | The approved metadata has a blocking validation error | Redraft before approval; the blocking `metadata:invalid` flag lists the problems |
| `not publishable to Instagram Reels: ...` | The file isn't 9:16 or is outside the Reels limits (3 s – 15 min, ≤ 300 MB) | Render the 9:16 `short` format; `video-pipeline social plan --id <P>` shows the routing |

## Render and jobs

| Symptom / error code | Cause | Fix |
|---|---|---|
| `CONFIG_INVALID` | Schema or storyboard error. Every problem is listed with its JSON path | Fix the listed fields; `video-pipeline validate <config>` has no side effects |
| `... word 'X' is not in this scene's narration` | A `@word:X` cue doesn't match the narration (compound tokens like `shrotihost.in` match by part) | Use a word that is actually spoken in that scene, or define a named cue |
| `DUPLICATE_JOB` (exit 5) | An identical config already has a live or completed job | `render`/`retry` that job, or `create --force` for a deliberate second copy |
| `TTS_FAILED ... timed out` / `network/service error` | Only with the opt-in Edge TTS voice: it is an online Microsoft service (no network or a service hiccup) | Retried automatically (4 attempts, exponential backoff); then `video-pipeline retry --job-id <id>`. The default local voice needs no network |
| `TTS_FAILED ... rejected the request` | Edge TTS: invalid voice / rate / pitch | `python3 scripts/legacy/voiceover.py --list-voices en-IN` |
| `TIMING_INVALID ... no provider timestamp` | The provider returned too few word boundaries (more than 20% missing) | Retry. If it persists, simplify the narration (unusual symbols) |
| `RESOURCES_INSUFFICIENT` | Under 2 GB disk free (`render.minFreeGb`) or under 800 MB memory | `video-pipeline clean --dry-run` then `--yes`; close apps |
| `memory is short: rendering chunk … with N tabs` in the log | Fewer than `1500 + 350×tabs` MB reclaimable | Nothing to do: the render uses as many Chromium tabs as fit (down to 2) and runs a little slower instead of waiting. Close apps for full speed |
| `waiting for memory: ...` in the log | Not even 2 tabs fit (under about 2.2 GB reclaimable) | Close apps (a pipeline-started LLM runtime is stopped automatically before rendering; one you started yourself is left running, so quit it); the job continues by itself (it waits up to 5 minutes, then runs with what's available) |
| `memory pressure detected -> lowering Chromium tabs` | Swap grew or page-outs spiked during a chunk | Expected protective behaviour. Lower `render.concurrency` if it happens every time |
| `chunk ... failed (Target closed / Page crashed)` | Chromium crash | Retried with half the tabs (2 retries per chunk) |
| `PROCESS_STALLED` | No render output for `render.stallTimeout` s (default 120 s) | Retried automatically. If it repeats, a composition is blocked in `delayRender` (font or asset missing) |
| `VideoToolbox failed ... falling back to software x264` | Hardware encoder unavailable or busy | Automatic when `render.encoder` is `auto`. Force with `"encoder": "x264"` |
| `INVALID_STATE_TRANSITION ... already COMPLETED` | Completed outputs are immutable | `create --force` for a new job |
| Job stuck in an active state after a crash or reboot | Worker died | Any `status`/`render` call marks it `FAILED` (stale heartbeat > 120 s); then `retry` (cached stages are reused) |
| QA `audio.loudness` WARN | Mix outside −14 ± 1 LUFS | Check `reports/audio-report.json`; adjust `audio.musicDb` / `sfxDb` |
| QA `visual.frozen` WARN | A scene is static for 3 s or more | Add a block with a later `at`, or split the scene |
| `render contract mismatch` | `src/engine/types.ts` and `pipeline/contract.py` versions differ | Update both sides together |

## Install

| Symptom | Cause | Fix |
|---|---|---|
| `npm ci` fails on vitest peers | npm 10.9 resolver bug with vitest's optional browser peers | `npm ci --legacy-peer-deps` |
| `pip3 install` affects a different Python | `pip3` is the Xcode Python 3.9 | Use `uv sync` / `uv run` (the project venv pins its own Python) |

## Plain-language hints and pre-flight checks

Known failures carry a plain sentence for non-technical users. The catalogue is
[`pipeline/error_hints.py`](../pipeline/error_hints.py): each rule matches an error code and a message pattern and
gives a `hint` plus an optional `action` id (`rebuild-preview`, `approve-preview`, `edit-storyboard`, `fix-brief`,
`choose-brand`, `retry`, `close-apps`, `free-disk`, `start-ai`, `review-flags`, `re-review`, `redraft-metadata`,
`check-account`, `approve`). Every serialised error (`--json` output, the job's `error` in the registry, Studio task
errors) has `hint` and `action` keys (`null` when nothing matches), and the CLI prints `hint: …` under the error.
When you add a row to the tables above for a new error, add a matching rule there too (tests:
`tests/test_error_hints.py`).

| Symptom / error code | Cause | Fix |
|---|---|---|
| `PREFLIGHT ... disk` | Under 2 GB free on the disk that holds `output/` (checked before every render and QA run) | Empty the Trash, `video-pipeline archive` old productions, or `video-pipeline clean --yes`; then render again |
| `PREFLIGHT ... memory` | Swap is at least 90% full **and** under 1 GB of memory is reclaimable | Close apps (browsers, the LLM runtime) or restart the Mac; then render again. Either signal alone only logs a `preflight (...): memory is tight` warning |
| `PREFLIGHT ... ocr` | The Apple Vision OCR tool didn't answer on a tiny test image (usually memory pressure), or it isn't built and `swiftc` is missing | Close apps or restart, then retry; install Xcode Command Line Tools (`xcode-select --install`) if `swiftc` is missing. A passing probe is cached for 10 minutes (`.pipeline/cache/preflight-ocr.json`) |
| `PREFLIGHT ... ffmpeg` | `ffmpeg` or `ffprobe` isn't on `PATH` | `brew install ffmpeg` |
| Pre-flight in tests / CI | The checks read the real machine | Set `VIDEO_PREFLIGHT=0` to skip them |
