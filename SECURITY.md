# Security

Threat model: a single-user workstation that produces videos for several brands from project files written
by the operator (or drafted by the local creative engine), plus third-party assets (SVG, audio, fonts). Online
services are used only when explicitly invoked: the opt-in Edge TTS voice, brand onboarding and fact refresh
(the brand's own website), opt-in keyword research, and the YouTube / Instagram APIs for a confirmed upload. The
main risks are command injection, path traversal, malicious SVG, destructive cleanup, leaked secrets, publishing
to the wrong account and vulnerable dependencies.

## Controls in place

| Risk | Control | Where / test |
|---|---|---|
| Command injection | Every subprocess uses an argument list; `shell=True`, `os.system`, `eval` and `pickle` are absent (grep-verified); `procs.run` rejects string commands | `pipeline/procs.py`, `test_shell_strings_rejected` |
| Path traversal / absolute-path injection | Every config path is resolved through `safe_path` (realpath, must stay inside the workspace, NUL bytes rejected, symlink escapes rejected); job and brand names must match `[A-Za-z0-9][A-Za-z0-9._-]*` | `pipeline/paths.py`, `test_path_traversal_rejected`, `test_symlink_escape_rejected`, `test_safe_names` |
| Malicious SVG / HTML | Brand and asset SVGs are scanned before use: `<script>`, `<foreignObject>`, `on*=` handlers, `javascript:` and external/`data:text` hrefs are rejected. The engine never uses `dangerouslySetInnerHTML`, `eval` or `new Function` (grep-verified) | `pipeline/assets.py`, `test_unsafe_svg_rejected` |
| Untrusted JSON | Project, storyboard, voice, audio, caption and render sections are schema-validated (types, ranges, enums, patterns, unknown fields rejected) before any work; time expressions are parsed by a strict regex, never evaluated | `pipeline/config.py`, `pipeline/storyboard.py`, `test_storyboard_validation_errors` |
| Destructive deletion | `clean` is dry-run by default, deletes only `work/` of COMPLETED jobs, `.pipeline/tmp` and stale bundle temp dirs, and re-checks each path with `safe_path`. Final videos, reports and sources are never deleted. Completed outputs are never overwritten | `pipeline/runner.py:clean`, `test_publish_refuses_overwrite` |
| Partial / corrupt writes | Atomic temp-file + `fsync` + `os.replace` for JSON, text and media; renders and muxes write `.part` files first | `paths.atomic_write_*`, `test_atomic_write_leaves_no_partial_file` |
| Runaway processes | Own process group per child, hard timeout, stall timeout; on kill, **all remembered descendants' process groups** are terminated (Remotion launches Chromium detached) | `pipeline/procs.py`, `test_timeout_kills_detached_grandchildren` |
| State-file exposure | `.pipeline/` (registry, caches, bundles) is `0700`; the Studio session token `.pipeline/studio/session-token` is `0600` (directory `0700`) | `paths.ensure_dirs`, `studio/server.py:persistent_token`, `tests/test_studio_token.py` |
| Secrets | Platform credentials are per brand in `.pipeline/secrets/<brand>/{youtube,instagram}.json`. Files must be `0600` and the brand directory `0700`, or they are refused. Logs record messages and error tails, never secret values or environment variables | `pipeline/social/brandcfg.py`, social publishing tests |
| External URLs | The pipeline fetches nothing at render time. Network use, each explicitly invoked: installs (`npm ci`, `uv sync`, model fetches), the sound kit and CC0 music fetch, `brand init` (one GET of the brand's home page plus its logo), the fact refresh (the brand's own pages), opt-in keyword research (generic seed phrases only), opt-in Edge TTS, and confirmed uploads to YouTube / Instagram | — |
| Dependency pinning | `package-lock.json` (exact versions), `uv.lock`, `pyproject.toml` exact pins | — |

## Scan results (2026-11-13)

| Tool | Scope | Result |
|---|---|---|
| `gitleaks dir` 8.x | whole workspace (files ≤ 5 MB) | 1 finding: an Algolia search key inside a **cached Remotion Studio bundle** (`.pipeline/bundles/*/399.bundle.js`). It's Remotion's public docs-search key shipped in `@remotion/studio`, not a secret of this project, and the bundle is a gitignored build artifact. **False positive.** No secrets in project files |
| `shellcheck` | `scripts/*.sh` | 1 info (SC2015 in `verify.sh`: `A && B || C`). Intentional: both branches are reporting calls |
| `npm audit` | node deps | **5 high**, all one advisory: `zod` < 4.6.6, GHSA-mrhx-c7xc-m3w5 (memory exhaustion validating oversized collections), via `@remotion/cli`/`studio`/`bundler` 4.0.507. **14 moderate**, dev-only: `minimatch` ReDoS via eslint / typescript-eslint |
| `pip-audit` 2.9.0 | locked runtime deps (37) | No known vulnerabilities |
| `semgrep` 1.179.0 (p/python, p/typescript, p/react, p/secrets, p/command-injection) | `pipeline/`, `scripts/`, `src/`, `tests/` (89 files) | 2 findings, both triaged. (1) `paths.py:74` chmod `0o700` flagged "permissive": **false positive** (owner-only). (2) `scripts/legacy/mix_audio.py:202` subprocess with CLI-supplied args (legacy script): **low**. Argument list, no shell, so no command injection. A file name starting with `-` could still be read as an FFmpeg option, but only the operator's own CLI is exposed; the pipeline always passes absolute workspace paths |
| grep audit | `pipeline/`, `scripts/`, `src/` | No `shell=True` / `os.system` / `eval` / `exec` / `pickle` / string subprocess commands / `dangerouslySetInnerHTML` |

## Accepted risks and actions

1. **zod advisory (high, via Remotion 4.0.507).** Exposure: zod validates composition props inside Remotion's own CLI/Studio, on this machine, with props we generate and schema-check ourselves. Exploiting it needs attacker-controlled oversized props. Fixed upstream in `@remotion/cli` ≥ 4.0.540 (2026-11-02). **Action:** upgrade all `remotion`/`@remotion/*` packages together to ≥ 4.0.540, then run `uv run pytest`, `npm test`, both e2e renders and `video-pipeline benchmark` before using it for production. It wasn't upgraded here so this hardening release keeps the renderer it was verified on. `npm audit fix --force` is **not** a safe shortcut (it moves Remotion versions independently).
2. **Remotion Studio bound all interfaces. Fixed in v0.3.0.** Correction to the v0.2.0 note: the render-time file server already binds `127.0.0.1` (verified in 4.0.540 source and with lsof). Only `remotion studio` used `0.0.0.0`/`::`. A postinstall patch (`scripts/patch-remotion-loopback.mjs`) now binds Studio to `::1`/`127.0.0.1`. Verified: patched `[::1]:3199`, stock `*:3199`. The patch fails loudly if upstream code changes. Opt out per process with `REMOTION_BIND_ALL=1`.
3. **Edge TTS is an unofficial client to an online Microsoft service.** Narration text leaves the machine when it is used. It is off by default (local Kokoro is the default voice) and needs `voice.allowOnline: true`. Don't use it for confidential narration.
4. **Dev-only `minimatch` ReDoS (moderate).** Reachable only through eslint glob patterns we write ourselves. Upgrade eslint/typescript-eslint when compatible versions are available.

## v0.3.0 additions

| Area | Control | Verified by |
|---|---|---|
| zod advisory (was accepted risk #1) | **Fixed:** Remotion 4.0.540 ships zod 4.6.7; `npm audit --omit=dev` = 0 vulnerabilities (10 moderate remain in dev-only lint tooling) | npm audit |
| Privacy: no external AI | Narration, briefs, scripts and voice audio stay on the machine. TTS (Kokoro/Piper), alignment (Whisper) and the LLM (Ollama) run locally. Edge TTS needs explicit `voice.allowOnline: true`. Ollama is bound to 127.0.0.1 with cloud models refused and remote hosts rejected | voice/intelligence tests; offline demo network log (below) |
| Local model integrity | Every voice model file is pinned to a source revision with a sha256 (`pipeline/voice/registry.json`); `doctor` re-verifies all 35 | `doctor` |
| Studio server | 127.0.0.1 only, random session token → HttpOnly SameSite=Strict cookie (the token persists across restarts in `.pipeline/studio/session-token`, mode 0600; `--new-token` rotates it), Host-header allow-list (DNS rebinding), same-origin JSON-only writes, strict CSP, file serving confined to `output/`, `public/` and audio libraries (no dotfiles, no `.pipeline`, no secrets), no shell execution | `tests/test_studio_server.py` (8 tests) |
| Publishing | Never automatic; gate = APPROVED + valid package hash + QA + destination + content hash, re-checked before upload; `--confirm` / typed-id confirmation; per-brand credentials (0600) | `tests/test_v030_core.py`, `tests/test_social_publishing.py` |
| Audit log | Every human decision (flag resolution, approve/reject, export/publish) and approval invalidation is appended to `audit_log` | core tests |
| Database backups | Automatic online backup before schema migrations; `video-pipeline backup` on demand; backups stay next to their database | `test_fresh_registry_is_stamped_and_never_backed_up` |
| Process isolation | Heavy workloads run as child processes (TTS worker, Remotion, Ollama) under the cross-process scheduler; descendant process groups are killed on cancel/timeout | procs + scheduler tests |
| Secrets | `.pipeline/secrets/<brand>/` only; never logged; gitleaks clean on every commit | gitleaks |

## Publishing accounts (multi-brand)

| Area | Control | Verified by |
|---|---|---|
| Per-brand credentials | Each brand has its own `.pipeline/secrets/<brand>/` (directory `0700`, files `0600`). A legacy global `.pipeline/secrets/<platform>.json` is never used; publishing explains how to move it into the brand's directory | `pipeline/social/brandcfg.py` |
| Account verification | `brands/<brand>/brand.json → publishing.accounts` names the only YouTube channel / Instagram account the brand may publish to. Before any upload, the platform's own "who am I" answer must match it; otherwise the publish is refused (`PUBLISH_ACCOUNT_MISMATCH`) and nothing is sent | `pipeline/publishing.py:_verify_account`, `tests/test_social_publishing.py` |
| Studio and MCP | The Studio and the MCP server show whether credentials are present and which account is expected, never secret values. The MCP publish tools go through the same gate, confirmation and account check | `studio/server.py:destination_status`, `pipeline/social/mcp_server.py` |
