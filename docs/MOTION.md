# Motion & engine v2

The `Storyboard` engine (`src/engine/`) draws `RenderProps`. **Python owns time**; every animation is a
pure function of `t = frame / fps`: no `Math.random`, no `Date`, no CSS transitions/animations.
Render contract **v2** is a strict superset of v1. Props with `contractVersion: 1` render bit-identically to
the v1 engine, verified by decoding the v1 fixture before and after and comparing per-frame MD5s (0 of 638 frames differ).
All v2-only behaviour is gated on `contractVersion >= 2` (`isV2()` in `contract.ts`).

The engine has **32 block types** (14 from v1, 13 added in v2, 3 in the v2b look, plus `footage` and `composition`) and **6 scene backdrops**; the
authoritative list is `src/engine/types.ts`.

## Module map

| File | Role | Pure (no React/Remotion) |
|---|---|---|
| `motion/durations.ts` | DUR, LEAD, STAGGER, SCENE_DUR, ACCENT, envelopes, `appearTime` | yes |
| `motion/easings.ts` | EASE curves (bit-identical to Remotion `Easing`), SPRING configs | yes |
| `motion/exits.ts` | `life`, `exitFactor` | yes |
| `motion/transitions.ts` | `sceneTransition` (fade / slide-up / none / mask-wipe / gradient-sweep), `cameraAt`, `cameraReserve` | yes |
| `motion/typography.ts` | font-size scale, weights, `estimateTextWidth`, `fitFontSize` | yes |
| `motion/presets.ts` | `calm` / `standard` / `energetic` / `cinematic` | yes |
| `motion/entrances.ts` | `springAt`, `blockEntrance`, `wordEntrance`, motion-blur levels | no (Remotion `spring`) |
| `geometry.ts` | geometry of the v2 blocks (every text run / logo / shape rect) | yes |
| `layout.ts` | stack/split layout, `measureBlock`, `naturalWidth`, `firstInternalTime` | yes |
| `branding.ts` | logo/asset aspects, brand bar rect, watermark policy + suppression | yes |
| `plan.ts` | `makeEnv` / `planScene`: the scene plan used by **both** renderer and manifest | yes |
| `texts.ts`, `manifest.ts` | QA layout manifest | yes |
| `assets.ts` | intrinsic aspect from bytes (SVG viewBox, PNG, JPEG, GIF, WebP; MP4 / WebM display size + duration) | yes |
| `look.ts` | v2b gate (`isPolished`), backdrop weights / crossfades, split-panel geometry | yes |
| `geometry-v2b.ts` | geometry of `plan-card`, `install-flow`, `server-stack` (wide + tall layouts) | yes |
| `geometry-footage.ts` | `footage` geometry, clip time, last-frame hold, zoom keyframes | yes |
| `geometry-composition.ts` | `composition` canvas, element boxes per layout, deterministic text fitting, arc / connector paths | yes |
| `blocks.tsx`, `blocks-v2.tsx`, `blocks-v2b.tsx`, `backdrops.tsx`, `prim.tsx`, `Storyboard.tsx`, `ui.tsx` | drawing | no |

## Motion presets (`scene.motion` › `props.motion` › `standard`)

Presets change the *shape* of entrances (spring, travel, stagger, focus pull, motion blur, camera amplitude).
They never move a cue: every entrance starts at its Python-resolved `at` minus the same `LEAD`.

| preset | entrance spring (damping/mass) | travel | word stagger | motion blur | focus pull | camera amp |
|---|---|---|---|---|---|---|
| standard (= v1) | 15 / 0.8 | 40 | 0.08 s | off | off | 1 |
| calm | 22 / 1.0 | 26 | 0.10 s | off | off | 0.6 |
| energetic | 12 / 0.55 (+ scale 0.96→1) | 64 | 0.06 s | ≥ 7 px/frame | off | 1.25 |
| cinematic | 24 / 1.25 (+ scale 0.97→1) | 30 | 0.11 s | ≥ 9 px/frame | 6 px → 0 | 1 |

Motion blur is a vertical SVG `feGaussianBlur` (`stdDeviation="0 σ"`, σ ∈ {1.5, 3, 4.5}), chosen from the spring's
per-frame velocity. It is deterministic and only active during the fast part of an entrance.

## Scene transitions

`fade` and `slide-up` work as in v1. `mask-wipe` is a soft-edged (18 %) diagonal wipe in over 0.45 s
and out over the last 0.28 s. `gradient-sweep` fades the scene in while a brand light band crosses the
**content area only**, so the caption band is never touched. All exits reach exactly 0 at `scene.end`.

## Camera (`scene.camera`; absent = `push-in` = the v1 move)

Applied to the whole scene layer around the content centre. In v2 the layout **insets the safe area by the
camera's maximum displacement** (`cameraReserve`), so no camera move can push content into the caption band
or past the side margins. The manifest gives the settled position *before* the camera move. QA should allow
up to the following displacement (px, amp 1; multiply by the preset's camera amp):

| camera | max dx | max dy | short (no bar) | landscape |
|---|---|---|---|---|
| none | 0 | 0 | 0 / 0 | 0 / 0 |
| push-in (1 → 1.03) | 0.015·areaW | 0.015·areaH | 14.1 / 15.9 | 24.6 / 11.6 |
| pan-left / pan-right | 0.012·W | 0 | 13.0 / 0 | 23.0 / 0 |
| drift | 0.6·0.012·W + 0.0075·areaW | 0.4·0.012·W + 0.0075·areaH | 14.8 / 13.2 | 26.1 / 15.0 |

`areaW` = frame width − 2·side margin; `areaH` = caption band top − content top. v1 props keep the v1
push-in and no reserve, so they behave exactly as before.

## New blocks (all optional fields have defaults; times are absolute seconds)

| type | key fields | time keys |
|---|---|---|
| `kinetic-text` | `words[{text, at, emphasis?, tone?}]`, `size` xl/l/m, `align` | `words[].at` |
| `counter` | `to`, `from`=0, `prefix`, `suffix`, `decimals`=0, `grouping` none/western/indian, `label`, `tone`, `size` | `at` → `countEnd` (default at+0.8) |
| `price-compare` | `title`, `columns[]`, `rows[{label, values[], strike?[], hike?[], highlight?}]`, `winner`, `winnerLabel`="Best value" | `rows[].at`, `winnerAt` (default last row + 0.3) |
| `terminal` | `title`, `prompt`="$", `lines[{text, kind cmd/out/ok/err/dim}]` | `lines[].at`, `lines[].typeEnd` (default at + 0.04 s/char ≤ 1.2) |
| `dashboard` | `title`, `nav[]` (≤ 6), `active`, `stats[{label, value, delta?, tone?}]` (≤ 4), `chart{title?, bars[{label,value}], highlight?}` | `at`, `chart.growEnd` (default at+1.2) |
| `device` | `frame` phone/laptop, `asset` (public/ path) + `fit` contain/cover, or `screen{title, subtitle?, rows?[], button?}` | `at` |
| `image` | `asset`, `reveal` mask/fade/none, `kenBurns` (0.96→1, never crops), `caption`, `maxHeight`=760 | `at` |
| `footage` | `asset` (.mp4/.webm), `frame` browser/laptop/phone/none, `title`, `startFrom`, `playbackRate`, `zooms[]`, `caption` (see [below](#footage-block-real-video-clips-same-contract-version-2-additive)) | `at`, `zooms[].at` |
| `progress` | `title`, `steps[{label}]` | `steps[].at` |
| `scroll-demo` | `url`, `sections[{title, text?, kind hero/features/pricing/cta/plain}]` (`text` "a \| b \| c" → tiles) | `at` → `scrollEnd` |
| `chart` | `kind` bar/line, `title`, `data[{label,value}]`, `valuePrefix/Suffix`, `decimals`, `highlight`, `tone` | `at` → `growEnd` (default at+0.9) |
| `feature-compare` | `title`, `columns[]` (2–3), `rows[{label, values[(bool\|string)]}]`, `highlight` | `rows[].at`, `highlightAt` |
| `logo-sting` | `variant` onDark/onLight, `tagline` (~1.2 s reveal: glow, mask wipe, sheen) | `at` |
| `outro` | `url`, `cta`, `tagline` (logo + tagline + CTA + URL button) | `at`, `urlAt` (default at+0.6) |

New time keys: `typeEnd`, `scrollEnd`, `winnerAt`, `highlightAt` (`countEnd`, `growEnd`, `urlAt` already existed).
Text in the v2 blocks is auto-fitted (`fitFontSize`) to its box, so it can't overflow by design. The minimum
sizes are kept legible (≥ 18–22 design px).

**Branding choice.** Intro and outro branding are **block types** (`logo-sting`, `outro`), not scene presets.
They then compose with every transition, camera and preset, and the watermark logic can see them.

## Watermark (`props.watermark`, v2)

`policy`: `none` | `brand` (theme logo, default variant `onDark`) | `custom` (`asset` required) | `platform`
(brand **mark**, Shorts top-left at y ≥ 120 px below the status bar, landscape top-right; `position` ignored).
Defaults: opacity 0.9, short margin 0.045·W, mark width 0.085·W (logo 0.26·W), landscape margin 0.028·W, mark
0.042·W (logo 0.13·W). Height is capped at 10 % of H. Bottom positions sit between the caption box and the
platform overlay (Shorts), or outside the caption column (landscape).

- **Never distorted.** The rect follows the intrinsic aspect: `theme.logo.aspects`, else the file's own
  SVG viewBox / bitmap header (`calculateMetadata` fills `props.assetAspects`). The mark is 39/23 = 1.696
  from `icon.svg`'s viewBox, replacing the hard-coded 1.7, which v1 props keep for compatibility.
- **No duplicate branding.** The watermark is fully hidden while a `logo`, `cta`, `logo-sting` or `outro` block,
  an `image`/`device` showing a theme logo file, or the brand bar is visible. It fades over 0.3 s around those
  intervals. Gaps shorter than 0.6 s are skipped (no flicker).
- **Never on content.** If a top watermark would touch a block, that scene's stack starts below it.

## Hook-tag fix (v2)

With the brand bar (or a top-centre watermark) active, the hook-tag string hangs from just below the logo
(`ceilingY`) and the dropping tag is clipped there. It no longer crosses the logo.

## Layout manifest (QA)

```bash
node scripts/engine-layout.mjs output/<job>/metadata/props-short.json > layout.json   # ~0.1 s, no browser
```

It bundles `src/engine/manifest.ts` with esbuild (the same `plan.ts`/`layout.ts`/`geometry.ts` the renderer
uses) and reads asset aspects from `public/`. A vitest test checks that the CLI output equals the in-process manifest
and that the manifest boxes equal the renderer's `planScene` boxes. The output shape is the one QA asked for.
Coordinates are output px at the settled position, before the camera. Times are seconds. `fontSize` is in output px.

- `texts[].bbox`: estimated drawn rect (alignment-aware). `estWidth` > `maxWidth` ⇒ `overflow: true`.
  The width estimator (`estimateTextWidth`) is per-character and deliberately generous. Use OCR to confirm.
- `logos[].aspect`: aspect of the box the logo is laid out in. `expectedAspect`: the file's intrinsic aspect.
  Logos are always drawn `object-fit: contain`, so `bbox` (the drawn rect) is never distorted. For v1 marks,
  aspect 1.70 vs expected 1.696 shows the old hard-coded value.
- `scroll-demo` lists the texts visible before scrolling. `browser` reports `Loading… 0.0s` as the counter label.
  `domain-input` reports the button's final (`done`) label.
- `captionBand`: the reserved caption region (2 lines + 24 px). When captions are off, it's the bottom margin.
- `safeArea`: x = side margin, y = top without the brand bar. Scenes with the bar start lower (250 short / 150 landscape).

## Fixtures

`src/engine/fixtures/sample-{short,landscape}.json` (v1, unchanged) and `sample-v2-{short,landscape}.json`
(every new block, `platform` + `custom` watermark, all cameras, transitions and presets, hook-tag under the brand bar).

```bash
npx remotion render Storyboard out/engine-v2/v2-short.mp4 --props=src/engine/fixtures/sample-v2-short.json --concurrency=2 --muted --log=error
```

## v2b look (same contract version 2; all fields optional)

**Opt-in gate.** Props use the v2b look when `contractVersion >= 2` and any scene sets `backdrop` or any block is
`plan-card` / `install-flow` / `server-stack` (`look.ts isPolished`). Everything below is gated on it, so v1 props
and pre-v2b v2 props render as before: v1 fixture 0 / 638 frames differ (MD5); v2 fixture old-vs-new shows the same
noise as two runs of identical code (Chrome rasterises blur / drop-shadow filters non-bit-exactly under
concurrency: 1188 vs 1230 of 1344 frames identical, min PSNR 66.9 vs 66.5 dB).

### Scene `backdrop` (default `glow`)

| value | look | layout effect |
|---|---|---|
| `glow` | the v1/v2 dots + two drifting glows (unchanged) | – |
| `spotlight` | near-black, soft light cone from the top (slow sway), brand pool behind the content, no dots | – |
| `grid` | perspective floor grid (pinhole projection in SVG, drifting towards the viewer) with a horizon glow | – |
| `split` | diagonal brand panel: Shorts top band (13.5 % → 8.5 % of H), landscape left panel (30 % → 22 % of W) | content area starts below / right of the panel (`splitPanel().contentTop/contentLeft`) |
| `light` | `light.surface` (#f7f5fa) with soft highlights and a faint dot grid | free text uses the light tokens (`ctx.ink`), `onDark` logos switch to `onLight`, caption box darkens |
| `deep` | near-black, vignette, faint brand breath at the bottom | – |

Mood tints (`mood: danger/brand`) apply on every backdrop. Backdrops are crossfaded per scene boundary
(`backdropWeights`, eased, ±0.3 s; ±0.14 s between a light and a dark backdrop, where a long mix reads as grey);
weights always sum to 1. Brand bar and watermark (theme logos) stay legible: onDark ⇄ onLight over `light`, a white
silhouette over the Shorts `split` band.

### Layout (v2b only)

- **Hero scaling:** a scene whose blocks use little of the content area grows up to ×1.5 (one block) / ×1.18
  (several), limited by the column width and 90 % of the area height (`layout.ts HERO`).
- **Portrait proportions:** in a column < 1000 design px (Shorts) `dashboard` (620 → 820), `chart` (560 → 740),
  `price-compare` rows (100 → 120) and `feature-compare` rows (92 → 112) get taller, so width-limited cards fill the frame.
- `kinetic-text` emphasis is an underline below the baseline (the v2 marker bar sat on the glyphs).
- **Weighted split (16:9):** `layout: 'split'` with `splitAt` and `splitRatio` (0.3–0.7, default 0.5) gives the left
  column that share of the content width. `splitRatio` is a preference: the narrower column always keeps its content's
  minimum width (`minContentW`: a pill's single line; wrapping text needs none). The creative director splits every
  scene that has one `footage` block and one message at 0.66, recording first. A 1.6:1 recording then fills the content
  height (about 1000 px wide instead of 800 when stacked). Shorts ignore `split`.

### New blocks

| type | fields (defaults) | time keys |
|---|---|---|
| `plan-card` | `name`, `price` (number), `currency`='₹', `period`='/mo', `billing`, `badge` (pill beside the name, or above it when they don't fit), `features[{text, icon?, at}]`, `ctaLabel`, `countFrom`=0, `variant` light/dark (default light on a light backdrop, else dark) | `at`, `countEnd` (default at+0.8), `features[].at`, `highlightAt` (CTA ring + sheen + gentle pulse) |
| `install-flow` | `app` (title; its initial is the app tile), `title` (window title), `steps[{label, at}]`, `doneText`, `siteUrl` (browser preview of the new site), `appIcon{asset, bg?}` (a real, licensed product icon from `public/shared/assets.json` on the app tile instead of the initial; the hybrid engine sets it when one is registered) | `steps[].at` (step i spins until the next step / `doneAt`, then checks), `doneAt` (progress 100 %, success row, preview slides in) |
| `server-stack` | `title`, `nodes[{label, icon?, at}]` (≤ 4 rack units), `status{text, at, tone='success'}` | `nodes[].at` (unit lights up), `pulseAt` (default last node + 0.3: data pulses to the website node), `status.at` |

Each new block has a **wide** layout (box ≥ 1100 / 1250 / 1200 design px: landscape stack) and a **tall** one
(Shorts, landscape split columns). Manifest roles: price → `price`, `siteUrl` → `url`, plan name / app name /
`doneText` / stack title → `title`, features → `body`, step / node / status / badge / CTA labels → `label`. Texts are
reported at the settled end state (the install window's final position after the preview slides in).
New time key: `pulseAt`. The storyboard scene option `holdAfter` (0–3 s, `pipeline/storyboard.py`) adds silence after a
scene's last word so a payoff (count-up, install completion) can play out; Python extends the scene, the engine just
draws it. New icons: `app`, `cpu`, `memory`, `disk`, `refresh`, `plug`, `palette`, `settings`,
`download`, `gauge` (Lucide, ISC).

Fixtures: `sample-v2b-{short,landscape}.json` (~25 s, every backdrop, the three blocks, WP Starter facts only):

```bash
npx remotion render Storyboard out/engine-v2b/v2b-short.mp4 --props=src/engine/fixtures/sample-v2b-short.json --concurrency=4 --muted --log=error
```

## `footage` block (real video clips; same contract version 2, additive)

A real, **muted** video clip (screen recording, product footage) in browser / laptop / phone chrome or bare. The film's
audio always comes from the pipeline's mix. Geometry and timing live in `geometry-footage.ts` (pure; shared by the
renderer `blocks-footage.tsx` and the QA manifest).

| field | default | meaning |
|---|---|---|
| `asset` | (required) | public/-relative `.mp4` / `.webm` (e.g. `brands/<id>/footage/x.mp4`, or a licensed file under `shared/`) |
| `aspect` | from ffprobe | display width / height (sample aspect ratio and rotation applied). Python fills it; without it the engine reads the MP4 / WebM header |
| `duration` | from ffprobe | seconds of the video stream (needed for the last-frame hold). Filled the same way |
| `frame` | `browser` | `browser` (window chrome + optional `title` pill), `laptop`, `phone`, `none` |
| `title` | none | browser title-bar text, drawn only with `frame: 'browser'`. It must come from the storyboard; the engine never invents UI text |
| `startFrom` | 0 | seconds into the clip at which playback starts |
| `playbackRate` | 1 | 0 < rate ≤ 4 |
| `zooms[{at, x, y, scale}]` | none | focus keyframes: normalised centre (0..1) and scale 1–4 |
| `caption` | none | line under the clip (role `caption`) |

Time keys: `at`, `zooms[].at` (both accept `@word:` expressions). `startFrom` and `playbackRate` are clip seconds and
rates, not timeline times.

- **Playback.** Clip time = `startFrom + (t − appear) · playbackRate`, frozen at `startFrom` during the entrance. The
  engine renders `<Freeze frame={clipTime · fps}><OffthreadVideo muted …/></Freeze>`, so every frame asks the decoder
  for exactly that time. Frame-accurate: the 30 fps fixture advances exactly one clip frame per output frame, with no
  duplicates or skips. A 0.1 ms seek bias makes a time that lands exactly on a frame edge resolve to that frame.
- **Last-frame hold.** Once the clip time reaches `duration`, it is clamped to `duration − 1 ms`. The decoder then keeps
  returning the last frame until the scene ends, never black or an empty box.
- **Zoom.** Before the first keyframe the whole clip is shown. Each keyframe's move starts `LEAD.block` before its `at`
  and eases (`EASE.inOutCubic`) over `DUR.slower`, or less when the next keyframe starts sooner. Moves never overlap,
  and each one starts where the previous one left the view. Keyframes are clamped so the view stays inside the clip
  (centre at least ½ / scale from every edge). Centre and **log** scale are interpolated with one shared progress.
  Because ½ − ½/s is concave in ln s, every in-between view also stays inside the clip, so there is no empty edge and
  no kink. The zoom happens inside the viewport, so the camera reserve and safe area are unaffected. Add
  `{x: 0.5, y: 0.5, scale: 1}` to zoom back out.
- **Box.** The viewport always has the clip's aspect, and the frame chrome is built around it: browser chrome bar
  72 design px; laptop lid as `device`; phone bezel 16 px, with the island on the short side for landscape clips.
  Natural width: browser 940 / none 900 / laptop 900 / phone 400 (landscape phone up to 900), capped so the viewport
  is at most 760 / 760 / 640 / 1000 (landscape phone 600) design px tall. A wide clip therefore fills the column and a
  tall recording gets a narrower box. Hero scaling applies as for `image`. On a `light` backdrop the browser chrome
  uses the light tokens and every frame gets the softer light-surface shadow.
- **Manifest / QA.** Footage blocks carry `media: [{role: 'media', kind: 'video', asset, frame, bbox, aspect,
  expectedAspect}]`, where `bbox` is the clip viewport (no other block gets the key). The title is role `title`, the
  caption role `caption`. Visual QA fails `layout.media_aspect` if the viewport and clip aspects differ by more than
  1 %. Template-like words that OCR finds inside a viewport are reported as the advisory `ocr.footage_labels`, since
  they are recorded UI. Footage pixels are excluded from the palette check.
- **Pipeline.** `pipeline/footage.py` (called from `load_project`) rejects clips outside `public/`, non-video or
  undecodable files, and a `startFrom` past the end. It fills `aspect` / `duration` in memory; the storyboard file is
  not rewritten. Brand isolation uses the `asset` key like images, and the runner registers each clip in the job's
  asset manifest with its licence record (brand `assets.json` or `public/shared/assets.json`).
- **Preview stills / visual QA** use the same props, so `remotion still` and the QA frame grabs show the same clip
  frame as the render.

Fixtures: `sample-footage-{short,landscape}.json` cover browser + zooms, laptop with `startFrom` 1 and 0.5×, phone at
2× with hold (Short), bare clip with hold, and browser in a landscape split. The Short carries `aspect` / `duration`;
the landscape fixture leaves them to the file header. The clip is `public/shared/fixtures/footage-sample.mp4`
(self-generated testsrc2, public domain).

```bash
npx remotion render Storyboard out/engine-footage/footage-short.mp4 --props=src/engine/fixtures/sample-footage-short.json --concurrency=4 --muted --log=error
```

## `composition` block (generated scene graphics; same contract version 2, additive)

A small scene-level graphic made of primitives on a normalised canvas, designed per production by
`pipeline/creative/composer.py` (see [CREATIVE_SYSTEM.md](CREATIVE_SYSTEM.md#generated-components-components-generate)) or
written by hand. Geometry lives in `geometry-composition.ts` (pure; shared by the renderer `blocks-composition.tsx` and the
QA manifest), the Python mirror of the vocabularies in `pipeline/contract.py` (`COMPOSITION_*`), validation in
`pipeline/storyboard.py` (`composition_errors`).

| block field | default | meaning |
|---|---|---|
| `elements` | (required, 1–64) | the primitives, drawn in order (the composer puts shapes and connectors first) |
| `canvas` | `{tall: 1, wide: 1.9}` | canvas aspect (w / h) per layout, 0.4–3. The block's height is `width / aspect` |
| `design` | none | provenance, never drawn: `structure`, `variant`, `motion`, `signature`, `source`, `component` (the generated component id). Freshness reads it |

**Two layouts.** Natural width 1500 design px. A block at least `wideMin` = 1100 design px wide (a 16:9 stack) uses each
element's `wide` box on the wide canvas; anything narrower (the 940-unit Short column, a 16:9 split column) uses `box` on the
tall canvas. The composer always writes both, so one storyboard holds in 1080×1920 and 1920×1080.

| element field | kinds | meaning |
|---|---|---|
| `kind` | all | `text`, `shape`, `connector`, `icon`, `number`, `logo`, `media` |
| `id` | all | unique; connectors refer to it |
| `box` / `wide` | all | `[x, y, w, h]` fractions of the canvas (inside 0..1). Connectors ignore it (`[0,0,0,0]`) |
| `at`, `motion` | all | entrance time and preset: `fade-up`, `fade`, `scale-in`, `draw-on`, `pop`, `none`. Default per kind: text / number `fade-up`, shape `scale-in`, connector and ring / arc / line `draw-on`, icon `pop` |
| `pulseAt` | all | a 0.9 s highlight (brand glow + ×1.06) starting here |
| `opacity` | all | 0..1 |
| `text`, `role`, `align`, `color` | text | role `title` / `label` / `body` / `value` (manifest roles title / label / body / label) |
| `shape`, `fill`, `stroke`, `strokeW` | shape | `rect`, `roundrect`, `circle`, `ring`, `arc` (`sweep` degrees from `start`, 0 = top, clockwise), `line` (along the box's longer side) |
| `fromId`, `toId`, `curve`, `stroke`, `strokeW` | connector | joins the edges of two elements (circles at their radius); `curve` −1..1 bends it (quadratic) |
| `icon`, `color` | icon | the engine's `IconName` set, drawn in the box's largest square |
| `to`, `from`, `prefix`, `suffix`, `decimals`, `grouping`, `countEnd`, `color` | number | counts like `counter`: `from` (0) → `to` between `at` and `countEnd` (default at + 0.8), then lands with the counter's spring. Currency prefix / suffix → manifest role `price` (digit-exact OCR), else `title` |
| `variant` | logo | a theme logo (`onDark` / `onLight` / `mark`), contain-fitted |
| `asset` | media | a public/ image, contain-fitted (never distorted); it counts for brand isolation like any `asset` |

- **Colours are theme tokens only:** `brand`, `brandText`, `surface`, `card`, `raised`, `border`, `bg`, `text`, `muted`,
  `success`, `danger`, `warning`, `info`. Surfaces switch to the light tokens on a `light` backdrop; text follows the scene's ink.
  Validation rejects anything else (no raw colours from generation).
- **Text fitting is deterministic** (`fitTextBox`): the largest size ≤ the role's base (title 60, label 42, body 34, value
  46 design px) at which the string wraps into at most 2 / 2 / 3 / 1 lines inside its box, never below the role minimum
  (30 / 24 / 22 / 24). If even the minimum does not fit, the run is laid out on one line at the minimum and the manifest
  reports `overflow: true` (the composer rejects such candidates; the preview gate fails them). Every line is a manifest
  text box with its role, so the OCR and overflow checks see what is drawn.
- **Time keys:** `at`, `countEnd`, `pulseAt` inside `elements[]` are ordinary nested time keys (they accept `@word:`
  expressions and resolve like every other block). Geometry numbers (`start`, `sweep`, `curve`, boxes) are not times.
  An un-timed block appears at its earliest element − 0.1 s.
- **QA:** `sync_check` treats a counted `number` like a counter value (shown when the count lands); the preview gate
  checks every counted number against the verified facts. Auto-SFX: a whoosh on entry, a soft pop per label, ticks
  while a number counts.

Fixtures `sample-composition-{short,landscape}.json` (generated by the composer on verified web-hosting facts, times
resolved from estimated timings): one scene per structure (orbit, network, layers, grid, hero number, orbit with a
counted hub, ladder, path, funnel, stacked cards, split compare), every element kind, shape and motion preset.

```bash
npx remotion render Storyboard out/engine-composition/composition-short.mp4 --props=src/engine/fixtures/sample-composition-short.json --concurrency=4 --muted --log=error
npx remotion render Storyboard out/engine-composition/composition-landscape.mp4 --props=src/engine/fixtures/sample-composition-landscape.json --concurrency=4 --muted --log=error
```
