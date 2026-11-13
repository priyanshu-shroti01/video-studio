# Creative comparison: same brief, three approaches

**Brief:** `projects/shrotihost/briefs/wordpress-hosting-69.json` (Shroti Host WordPress Hosting, verified WP Starter ₹69/month,
beginners, 33 s Short). All three run on the same v0.3 infrastructure: local Kokoro voice, mastering, captions,
licensed music and the same QA. Every number below comes from the productions' own files (`scripts/compare_creative.py`).

| | Production | Render job | Length |
|---|---|---|---|
| **v0.3-LLM**: the regressed demo (LLM designs every block) | P20261113-205715-f428a | 20261113-210021-0ef602 | 36.9 s |
| **A**: v0.2 handcrafted design language, verified facts, v1 blocks only | P20261113-212256-2b739 | 20261113-224339-bf08fa | 36.8 s |
| **B2**: hybrid (templates compose, facts label, LLM drafts copy), trimmed | P20261113-223903-970bc | 20261113-224240-90c6aa | **32.8 s** |

(B, the untrimmed first hybrid render at 37.3 s, was rejected by the reviewer as superseded by B2.)

## Reading the numbers

**Where B2 is clearly better than A:**
- Passes the preview gate on every check; A only gets WARN (the same backdrop in all 7 scenes).
- Scene-to-scene visual change is 2.3× A's (18.9 vs 8.2); the rest of A's motion comes from small UI moves.
- 4 backdrop styles vs 1, 4 camera moves vs 0, 3 transition types vs 2.
- A real product demo: a one-click WordPress install with the real WordPress icon, ending on "Your site is live" with a site preview. A uses domain typing and a plan grid.
- A premium plan card for the verified ₹69.
- On-target length: 32.8 s vs 36.8 s.
- 0 unverified claims.

**Where A is better than B2:**
- Higher mean content density: 3.84% vs 2.89%. Fewer frames counted as "empty" by the edge-density metric: 24% vs 33%.
- 10 distinct block types vs 7.

Most of B2's "empty" seconds fall at scene transitions (0, 9, 13, 21–22, 27 s) or in the terminal scene (4–7 s). That
scene is a small window of thin text on a dark grid, so it is not blank, but it is the sparsest moment in the video.

**Both beat v0.3 by a wide margin.** v0.3 had 51% empty frames, a failed gate (5 checks), invented labels, an unverified ₹39 and a cliché.

**Verdict (automated):** B2 is better on composition, motion, demo realism, pricing presentation, fact discipline and
length. A is denser. The metrics are not unanimous, so the decision to make the hybrid engine the default is the
reviewer's after watching both videos. Suggested improvement for B2: a larger terminal window or a second visual in the problem scene.

## Human verdict (2026-11-13)

The reviewer (Priyanshu Shroti) liked both A and B2, and especially A's two-plan scene. So **B3** was built: B2's
hybrid composition plus A's two-plan scene (verified WP Starter ₹69 / WP Business ₹119), followed by the WP Starter card.
B3 (P20261113-230456-ba8ec, job 20261113-230607-3af663, 36.7 s, QA PASS 43/43) was **approved**; A, B and B2 were
rejected as superseded. **The hybrid engine is now the default** (`pipeline/intelligence_bridge.DEFAULT_ENGINE = "hybrid"`;
use `"engine": "llm"` in a brief to opt out). Follow-up: give the hybrid catalogue a two-plans-then-card pricing
sequence, so B3's structure can be generated rather than hand-assembled.

## Metrics
| Metric | v0.3-LLM | A-restored-v0.2 | B2-hybrid |
|---|---|---|---|
| `production` | P20261113-205715-f428a | P20261113-212256-2b739 | P20261113-223903-970bc |
| `state` | CHANGES_REQUESTED | AWAITING_APPROVAL | AWAITING_APPROVAL |
| `gate` | FAIL | WARN | PASS |
| `gate_fail` | ['preview.empty_scenes', 'storyboard.hero_visual', 'storyboard.invented_labels', 'storyboard.numbers_verified', 'storyboard.narration_sync'] | [] | [] |
| `qa` | PASS | PASS | PASS |
| `qa_counts` | {'PASS': 41, 'WARN': 0, 'FAIL': 0} | {'PASS': 43, 'WARN': 0, 'FAIL': 0} | {'PASS': 43, 'WARN': 0, 'FAIL': 0} |
| `branding` | PASS | PASS | PASS |
| `sb_scenes` | 6 | 7 | 6 |
| `sb_blocks` | 9 | 16 | 12 |
| `sb_blocks_per_scene` | 1.5 | 2.29 | 2.0 |
| `sb_single_block_scenes` | 3 | 0 | 0 |
| `sb_distinct_block_types` | 7 | 10 | 7 |
| `sb_v2_blocks` | [] | [] | ['install-flow', 'kinetic-text', 'logo-sting', 'outro', 'plan-card', 'terminal'] |
| `sb_demo_blocks` | ['browser'] | ['browser', 'domain-input', 'plans'] | ['install-flow', 'plan-card', 'terminal'] |
| `sb_backdrops` | ['glow'] | ['glow'] | ['glow', 'grid', 'light', 'spotlight'] |
| `animated_blocks` | 2 | 5 | 6 |
| `camera_moves` | 0 | 0 | 4 |
| `transitions` | ['fade'] | ['fade', 'slide-up'] | ['fade', 'mask-wipe', 'slide-up'] |
| `v_density_mean` | 2.27 | 3.84 | 2.89 |
| `v_empty_frames_pct` | 51.4 | 24.3 | 33.3 |
| `v_frame_change_mean` | 4.14 | 8.23 | 18.86 |
| `words` | 78 | 71 | 63 |
| `avg_sentence_words` | 3.5 | 7.1 | 5.7 |
| `cliches` | ['No tech skills'] | [] | [] |
| `claims_unverified` | 7 | — | 0 |
| `render_fps` | 51.61 | 57.27 | 52.42 |
| `render_s` | 21.45 | 19.26 | 18.79 |
| `v_frames` | 37 | 37 | 33 |
