# Creative system (`pipeline/creative`): hybrid templates + facts + optional local LLM

v0.3.0's creative engine (`pipeline/intelligence`) let a 4B local model design storyboards block by block.
That produced invented UI labels ("Browser: 39 rupees"), scenes that were mostly empty backdrop, a loading
browser passed off as the demo, and renewal claims built on an unverified brief price. This package splits
the work into four owners:

| who | owns |
|---|---|
| **Scene templates** (Python, deterministic) | composition: hero and supporting blocks, backdrop, camera, motion, transition, mood, word budget, cue mapping |
| **Facts** (`knowledge/<brand>/facts.json`) + **brand profile** (`brands/<id>/brand.json` → `creative`) | every price, plan, spec, feature label, URL, tagline, CTA default and banned word |
| **Copy bank** (generic layer + industry pack) | professional narration: the deterministic default and the style reference |
| **LLM** (optional, local Ollama) | picks a hook from the template's options and proposes narration inside budgets; each line is validated and replaced by bank copy if it fails |

Python owns timing, as it always has. Every visual beat is an `@word:` expression resolved from the real
voice timings.

## Use

```bash
uv run python -m pipeline.creative demo --brief projects/<brand>/briefs/<name>.json --out output/creative-eval/<name> [--provider none|mock|ollama] [--pick c2]
uv run python -m pipeline.creative templates --brand "Shroti Host" --product "WordPress Hosting"
```
```python
from pipeline.creative import generate_concepts, build_storyboard          # same signatures as pipeline.intelligence
res = generate_concepts(brief, request, provider="none", out_dir=out)      # "ollama" | "mock" | "none"/None | Provider
sb, project, reports = build_storyboard(res["brief"], res["concepts"][0], provider="none", out_dir=out)
```
`reports` contains `claims` {verified, needs_review}, `brief_claims`, `review` {status, blocking, reasons,
price_check}, `creative_plan` (music.mood ∈ cinematic|corporate|technology|energetic|minimal|educational|calm|
promotional), `copy_sources` (per scene: llm/bank, the model's proposal, and why it was rejected), `rules`,
`sync`, `labels` (every on-screen string with its source), `beats`, `price`, `path`. Files: `concepts.json`,
`concepts.md`, `<name>.storyboard.json`, `<name>.json`, `claims.json`, `review.json`, `creative-plan.json`,
`rules.json`, `copy-sources.json`, `storyboard-preview.md`, `generation-log.json`. Exit code 3 means the
output was produced but is BLOCKED.

## Brand neutrality
- No brand names, domains or brand copy appear in the code; a test greps for them. A brand opts in through
  `brands/<id>/brand.json`, which sets `creative: {industry, voice, cta, tagline: {<family>: {fact}}, banned,
  placeholderDomain}`. A missing brand, missing profile or missing `creative.industry` raises a clear `ConfigError`.
  There is no default brand.
- The domain comes from the facts (`company.url`) or from the profile's `website`. The URL beat anchors on the
  domain's first label. The engine matches *display* tokens: pronunciation turns `example.in` into spoken words,
  and their timings are mapped back onto the display token.
- **Industry packs** (`industries/<pack>.py`, selected by `creative.industry`) supply product families, the fact
  ids that gate statements, fact-bound feature labels and their cue words, industry templates, industry copy
  (which wins over the generic copy) and blueprints. Two packs exist: `web-hosting` and `software`. Hosting copy that
  names a technology (Imunify360, LiteSpeed, cPanel, WooCommerce…) is only used when the brand's facts back it
  (`TERM_ROLES`).

## Template catalogue (22)
**Generic, any industry (9):** `hook-kinetic-spotlight` (kinetic-text + pill · spotlight) · `turn-logo-sting`
(logo-sting + kinetic-text · glow) · `proof-feature-checklist` (checklist + pill · deep/glow) · `price-plan-card`
(plan-card + pill · spotlight/glow) · `price-compare-cycles` (price-compare + pill · split) · `price-plans-lineup`
(plans + pill · spotlight/glow) · `price-counter-flat` (counter + flat-line · deep/spotlight, needs the renewal fact)
· `cta-outro` (outro + pill · glow) · `cta-logo-lockup` (cta + logo · spotlight/glow).

**software (14, unpriced):** for launch films and product demos of software without a price (`Pack.priced = False`:
no plan placeholders, and the pricing rule fails any concept that shows a price). Templates: production chain
(progress), cold open and reveal on the brand's own recordings (`footage`), real-app footage of the brief, storyboard
and preview gate, render monitor and publishing pages, the product's pipeline stages (install-flow), architecture
(checklist of the product's principle), local stack (server-stack with a `play` target), measured QA (counter whose
spoken number comes from the fact's `value.spoken`), and an outro with the repository URL (`displayUrl`). Footage
templates exist only when the brand's clip (`creative.footage.<id>`) is on disk. Four blueprints: The Whole
Pipeline, It Created Itself, Proof First, From Brief to Film.

**web-hosting (13):** `hook-progress-promise` (progress + kinetic) · `hook-stalled-browser` (browser + kinetic · deep;
a *problem* visual, never the demo) · `hook-site-missing` (device + kinetic · deep/spotlight) · `problem-diy-terminal`
(terminal + kinetic · grid) · `problem-renewal-compare` (feature-compare + kinetic · split; only when the
typical-renewal and same-renewal facts exist) · `demo-install-flow` (install-flow with the site's own setup
steps + pill · light) · `demo-domain-search` (domain-input + checklist · grid) · `demo-dashboard` (cPanel dashboard
+ checklist · deep/grid) · `demo-device-site` (device + checklist · light/glow) · `demo-scroll-site` (scroll-demo +
checklist · light) · `proof-server-stack` (server-stack + pill · grid/deep) · `proof-checklist-counter` (counter +
checklist) · `proof-plan-compare` (feature-compare + pill · split).

No template uses `bars`: relative bar heights would imply competitor numbers that nobody sourced.

## Rules (checked per concept and on the final storyboard; any FAIL rejects the concept or blocks the review)
valid (validate_storyboard plus a mirror of the plan-card/install-flow/server-stack/backdrop field checks) ·
5–7 scenes · estimated 30–35 s at 2.33 words/s · a hero visual in every scene (never only headline/text/pill) · at
most one kinetic-text-led scene · ≥ 1.8 blocks per scene · ≥ 6 block types · ≥ 3 contract-v2/v2b types · no
consecutive repeated hero or backdrop · a real product demo (install-flow, domain-input, dashboard, scroll-demo or
device; a browser doesn't count) · a pricing scene with verified prices only · every claim verified · labels bound
(every on-screen string comes from a template constant, a fact, the brief CTA, or is spoken in that scene) · the
brief price is not rendered when it is unverified · renewal statements only with a fact · the CTA comes last with
the brand URL · every beat anchored on a spoken word (no `@start`) · **sync:** no more than 2.4 s of estimated narration
without a visual event (the QA limit is 2.5 s) and no number drawn more than
0.3 s before it is spoken · layout-fit (no text overflow in the engine's own layout manifest; reported as SKIP when
node/esbuild is unavailable).

## Price discipline
The product family comes from the brief's product. Its plans come from the facts. The featured plan is the
plan whose verified price equals the brief price. Otherwise it is the family's verified starting plan, and
`price.mismatch` records the brief price, the price used and its fact id. The claim checker sees a *trusted*
brief carrying the verified price, so real prices aren't flagged as contradicting the brief. A mismatch keeps
the review **BLOCKED** until the owner confirms the price, even though the video only renders verified prices.

## LLM gate (per scene slot)
The model never sees blocks, labels or times. A proposed line is rejected (and the bank line used instead) if it:
- breaks the schema or sends extra fields (e.g. a `pill`), which are ignored and recorded;
- is outside the word budget;
- contains a non-Latin character or a currency/percent symbol;
- uses a banned phrase (generic, pack or brand list);
- contains a number that isn't a bound fact value or narrative count for that template;
- names a URL that isn't the brand's;
- has an on-screen phrase not spoken verbatim in its narration;
- makes a claim the checker can't verify;
- names a technology the brand's facts don't back;
- loses the spoken word of a beat the bank line anchors;
- breaks sync for its scene.

If the accepted lines push the total outside 30–35 s, the lines that changed the length most are reverted.

Real example (mock provider proposing alternative bank-style lines, `output/creative-eval/wp39-mock`):
- Accepted: 4 of 6 scenes.
- Rejected, plan-card scene: "It all starts at 69 rupees a month on WP Starter, and renews at the same price."
  It drops "SSL" and "daily", so two feature ticks would lose their words.
- Rejected, outro scene: "Your site is one click away…". The trust pill would lose its word.

In tests, scripted "LLM" output containing "Browser: 39 rupees", the headline "Beginner pain", "seamless" and a
₹39 price was rejected each time. None of it reached the storyboard.

## Limitations
- Two packs exist (`web-hosting`, `software`). A new industry needs a pack: families, features, copy and at least one
  demo template. The generic templates and copy are a fallback for hooks, pricing, checklists and CTAs, not a
  complete video.
- The hosting pack relies on this knowledge base's fact-id convention (`policy.same_renewal`, `wp.setup_demo`…).
  A brand without a given fact silently loses the templates and lines that need it.
- Sync and duration use estimated timings calibrated to the local voice: Kokoro am_michael at +5% measured
  2.37 words/s over three renders, and the estimators use 2.33 (`anchors.WPS`). At that rate a 6-scene video
  fits 30–35 s with about 62–70 words (roughly 11 a scene; 9–10 a scene for 7 scenes). The copy bank keeps short
  variants for every template so the director can fit the window. A CTA that ends on "seven-day money-back
  guarantee" leaves 2.43 s after the pill's cue word, which is over the 2.4 s design gap. The bank says
  "Seven days, or your money back." instead. QA on real timings remains the final check.
- The two duration estimates disagree. `director.estimate` (used to pick copy) adds 0.5 s a scene and ignores
  `holdAfter`. `rules.estimate_seconds` (the duration rule) uses the per-token preview model and includes
  `holdAfter`. Plain copy with short words and digit prices therefore comes out up to ~3.5 s shorter under the
  rule, and a sequence with two demo holds (install-flow 1.3 s + domain-input 0.9 s, e.g. `three-moves` for
  WordPress) comes out ~2.4 s longer. Copy is balanced so the concepts the director builds pass both, but
  `three-moves` (WordPress) still fails the duration rule (~35.8 s) when it is planned.
- The claim checker is lexical (see CREATIVE_ENGINE.md). Number-free positioning lines in the copy bank were
  written to be true to the facts, but a human still reads `storyboard-preview.md`.

## Generated components (`"components": "generate"`)

The template library recombines a fixed set of parts, so a brand's videos start to look alike. With the brief option
`"components": "generate"` (also kept by the Studio's create-production endpoint) the director adds two things; without it
nothing changes (a test runs the default path with the generator, the freshness memory and the library patched to raise).

**1. Freshness memory** (`freshness.py`). From the brand's productions in `output/productions/` (never `output/_archive/`)
it collects the templates and blueprint of the selected concept (`concepts/creative-plan.json` → `concepts.json`), and the
hero blocks, backdrops and generated designs (`composition.design.signature` / `structure`) of `storyboard.json`. The newest
production counts 1, the one before ½, then ¼ … (ordered by production id, i.e. creation time). Penalty = 1 − e^(−usage). In
generate mode the director then orders a slot's candidate templates, the blueprints (rank position + 3 × penalty) and the
backdrop choice by penalty, falling back to the pack's order when the fresher sequence fails a rule. With no history every
penalty is 0 and the order is the default one. concepts.md gets a `freshness` row per concept.

**2. The composer** (`composer.py`) designs a new scene graphic (the engine's `composition` block, see
[MOTION.md](MOTION.md#composition-block-generated-scene-graphics-same-contract-version-2-additive)) for each demo / proof scene
whose template hero carries structure:

| template hero | content | structures that fit |
|---|---|---|
| `install-flow`, `progress` | sequence (+ title, done status) | ladder, grid, stacked, funnel, path |
| `server-stack` | stack (+ title, status) | ladder, orbit, grid, network, stacked, layers |
| `checklist` | set | ladder, orbit, grid, network, stacked, layers |
| `counter` (+ its checklist) | count: the number + satellites | orbit (number in the hub), hero number |
| `feature-compare` | compare | split compare |

- **Content, not invention.** Every label, icon, number and `@word:` anchor comes from the template's hero (and the
  checklist a counter absorbs): strings the template bound to verified facts or copy (`Ctx.labels`), timed on the spoken
  word they show. The composer only decides where and how they appear.
- **Search space:** 10 structures × 2 variants (ladder rail / links, orbit ring / spokes, grid tiles / rows, network star /
  mesh, stacked cascade / deck, compare cards / lines, funnel narrowing / widening, layers bars / pillars, hero number arc /
  chips, path snake / steps) × 2 seeded arrangement-parameter sets (node size, rail position, start angle, jitter, overlap,
  bend…) × 2 canvas aspects (the default and a 1.3× flatter one, which leaves room for a tall support block) × 4 motion
  schemes (cascade, pop, draw, focus = a pulse on each item as it is spoken), each laid out for the tall and the wide
  canvas. Typically 64–200 candidates per scene; plus any approved library design that fits the content (with the canvas
  it was approved on).
- **Rejected** (never chosen). Everything measured on the engine's own layout manifest is measured in **both** formats
  (one `scripts/engine-layout.mjs` run per format for all candidates; no node → nothing is replaced):
  - an invalid block; a text that is not a bound label and not spoken in the scene (the labels-bound rule);
  - a number drawn > 0.3 s before it is spoken, or > 2.4 s of narration without a visual event (`rules.sync_report`);
  - text overflow, in the component or in the scene's other blocks;
  - a **label / value text rendered below 34 px in 9:16 or 28 px in 16:9** (output px at the final hero scale,
    `MIN_LABEL_PX`). 34 px on a 1080-wide Short is the smallest size that still reads on a phone; a 1920-wide frame is
    watched larger, so 28 px there;
  - a **connector, line, ring or arc that runs through text**: the path is sampled exactly as the engine draws it (edge
    points, quadratic bends, arcs) against the manifest text boxes padded by 4 px; text inside the path's own endpoint
    elements (a label in the card a connector reaches) does not count;
  - overlapping text boxes, or an icon over text.
- **Scored:** 0.2 legibility + 0.25 sync (1 − ½ × largest gap / 2.4 s) + 0.35 balance + 0.2 freshness (1 − design penalty,
  +0.5 if the concept already uses that structure), + 0.04 for an approved library design, + 0.04 / 0.02 for the structure
  the local LLM named first / also named.
  - **Legibility** is judged on the texts that show the content items, which are the same strings in the template hero and
    in every candidate: the smallest of them per format, from 0 at half the format's minimum to 1 at 1.4×; the worse format
    counts. A template's decorative chrome (window titles, status pills) is not part of the comparison.
  - **Balance** = ½ drawn coverage of the hero box + ½ arrangement. Drawn coverage is measured in output px on the manifest:
    text extents, icons and filled shapes (rings and arcs count 35 % of what they enclose; lines and connectors nothing);
    0 at ≤ 12 % of the box, 1 from 38 %, easing off above 75 %. Arrangement = centre of mass, span and element count of the
    boxes in both canvases. A sparse design (a small ring of labels in an empty box) therefore stays below the template.
  - The template is scored the same way with balance fixed at 0.7. A generated component replaces the hero only when it
    scores **at least as well as the template**; a scene right after a generated one keeps its template (two generated
    heroes in a row would fail `no-repeat-hero`); then the whole concept is re-checked and any replacement under which a rule
    fails is undone (e.g. replacing the only product demo fails `product-demo`).
- **The LLM** (optional, local; provider `none` works) only answers which structure names from the list fit the scene idea.
  It never sees or writes geometry, labels, numbers or times; anything outside the list is dropped.
- **Deterministic:** the seed comes from brand, product family, template, content and the number of earlier productions;
  the same brief, facts and history give the same storyboard.

concepts.md marks generated scenes (`generated` row: design signature, what it replaces, its score vs the template). The
chosen design is stored in the concept's `scene_plan[*].component` (a recipe: structure, variant, parameters, motion,
canvas, seed) and rebuilt on the final copy when the storyboard is built.

**Files and human approval.** `production concepts` writes every generated component (scores, template baseline,
alternates, the block) to `output/productions/<P>/components/<id>.json`; `production select` writes `components/selected.json`.
A person decides which designs join the brand's library:

```bash
uv run video-pipeline component list --production <P>
uv run video-pipeline component approve --production <P> --id <cmp-…> --reviewer "<Name>" [--note "…"] [--name <entry>]
uv run video-pipeline component reject  --production <P> --id <cmp-…> --reviewer "<Name>" [--note "…"]
```

Approve copies the design (structure, variant, motion, parameters, an example block, the scores and the approval record)
to `brands/<brand>/components/<name>.json` and never overwrites an existing entry. Every decision is appended to
`components/decisions.json` and the registry's audit log (`component.approve` / `component.reject`). In later generate-mode
productions of that brand, library designs join the search (subject to freshness, so an approved design is not repeated
in every film).

**Limitations.** Only heroes with list-like structure are regenerated (no footage, device, dashboard, pricing or CTA
scenes). The balance metric is geometric (boxes), not perceptual: it cannot judge colour harmony or how the motion feels,
so a person still reviews the preview contact sheet. Legibility uses the engine's text-width estimate, which is deliberately
generous. Replacing several heroes with compositions lowers the block-type variety, so the `variety` rule sometimes undoes a
replacement.
