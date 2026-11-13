/**
 * RENDER CONTRACT — the only interface between the Python orchestrator (pipeline/) and the
 * Remotion engine (src/engine/). Python resolves ALL timing (scene bounds, cue times, key times)
 * from the TTS word timings; the engine only draws. The engine never fetches files except
 * theme / block assets (fonts, logos, images) via staticFile(), so concurrent jobs never share mutable state.
 *
 * Mirror: pipeline/contract.py (keep both in sync; CONTRACT_VERSION must match).
 *
 * v2 is a strict superset of v1: every v2 field is optional, and props with contractVersion 1 render
 * exactly as they did under v1 (v2-only behaviour is gated on `contractVersion >= 2`).
 */
export const CONTRACT_VERSION = 2;
/** Versions this engine can draw. */
export const SUPPORTED_CONTRACT_VERSIONS: readonly number[] = [1, 2];

export type Format = 'short' | 'landscape';
export type Tone = 'text' | 'muted' | 'brand' | 'danger' | 'success' | 'warning' | 'info';

/** A spoken word, absolute seconds on the final timeline. `text` is the SCRIPT token (keeps punctuation/casing). */
export type Word = {text: string; start: number; end: number; interpolated?: boolean};

export type FontFile = {src: string; unicodeRange?: string; weight?: string};
export type LogoVariant = 'onDark' | 'onLight' | 'mark';
export type Theme = {
  name: string;
  colors: {
    bg: string; surface: string; card: string; raised: string; border: string; borderStrong: string;
    text: string; text2: string; muted: string;
    brand: string; brandHover: string; brandActive: string; brandText: string;
    success: string; danger: string; warning: string; info: string;
    light: {card: string; surface: string; border: string; text: string; text2: string; muted: string; success: string};
  };
  fonts: {sans: {family: string; files: FontFile[]}; mono: {family: string; files: FontFile[]}};
  /** paths relative to public/. `aspect` = width/height of onDark/onLight (v1). v2: optional per-variant
   *  intrinsic aspects; when absent the engine reads each SVG's own viewBox (never a hard-coded value). */
  logo: {onDark: string; onLight: string; mark: string; aspect: number; aspects?: Partial<Record<LogoVariant, number>>};
  background: {style: 'dots-glow' | 'plain'; glowA: string; glowB: string};
  caption: {highlight: string; box: string; text: string; dim: string};
  radius: {card: number; pill: number};
};

export type CaptionConfig = {
  enabled: boolean;
  /** 'word': karaoke highlight of the current word; 'phrase': whole page, no per-word highlight */
  style: 'word' | 'phrase';
  maxWords: number;
  fontSize: number;
  /** distance of the caption box's bottom edge from the frame bottom, as a fraction of height */
  bottomFrac: number;
  maxWidthFrac: number;
  /** pages = groups of word indices into RenderProps.words, precomputed by Python (single source) */
  pages: {start: number; end: number; wordIdx: number[]}[];
};

/** Every block has an optional `at` (absolute seconds; default = scene start + stagger) and optional `exitAt`. */
type BlockBase = {id?: string; at?: number; exitAt?: number};

/** v1 blocks (unchanged). */
export type BlockV1 =
  | {type: 'logo'; variant: LogoVariant; width?: number}
  | {
      type: 'headline';
      size: 'xl' | 'l' | 'm';
      /** words of the headline; each may carry its own reveal time and tone */
      words: {text: string; at?: number; tone?: Tone}[];
      /** optional strike-through drawn across word index `word` at time `at` */
      strike?: {word: number; at: number; tone?: Tone};
      align?: 'center' | 'left';
    }
  | {type: 'text'; text: string; size: 'l' | 'm' | 's'; tone?: Tone}
  | {type: 'pill'; text: string; tone: Tone; icon?: IconName; stamp?: boolean}
  | {type: 'price'; currency: string; amount: number; period?: string; label?: string; note?: string; countFrom?: number; countEnd?: number}
  | {type: 'checklist'; items: {text: string; icon?: IconName; at: number}[]}
  | {
      type: 'bars';
      title: string;
      bars: {label: string; value: number; tone: Tone; at: number; growEnd?: number}[];
      badge?: {text: string; bar: number; at: number; tone: Tone};
    }
  | {type: 'compare-rows'; rows: {label: string; value: string; at: number}[]; badge?: {text: string; tone: Tone; at: number}}
  | {
      type: 'plans';
      plans: {name: string; price: string; period?: string; detail?: string; badge?: string}[];
      select?: {index: number; cursorStart: number; clickAt: number};
      emphasizeAt?: number;
    }
  | {
      type: 'domain-input';
      title: string;
      domain: string;
      /** absolute seconds of each keystroke (Python computes them; the sound layer uses the same list) */
      keyTimes: number[];
      availableAt: number;
      availableText: string;
      button: {idle: string; busy: string; done: string; clickAt: number; doneAt: number};
    }
  | {type: 'browser'; url: string; loadUntil: number; stallAt?: number; tag?: {text: string; at: number}}
  | {type: 'hook-tag'; label: string; text: string; sub?: string}
  | {type: 'flat-line'; title: string; points: {label: string; value: string}[]; drawEnd: number}
  | {type: 'cta'; text: string; url: string; urlAt: number; clickAt?: number; sub?: string};

/** v2 blocks (additive). All times are absolute seconds resolved by Python. */
export type BlockV2 =
  /** Kinetic typography: each word lands at its own `at`; `emphasis` words are larger and coloured. */
  | {
      type: 'kinetic-text';
      words: {text: string; at?: number; emphasis?: boolean; tone?: Tone}[];
      size?: 'xl' | 'l' | 'm';
      align?: 'center' | 'left';
    }
  /** Animated number from `from` (default 0) to `to` between `at` and `countEnd` (default at+0.8). */
  | {
      type: 'counter';
      to: number;
      from?: number;
      prefix?: string;
      suffix?: string;
      decimals?: number;
      grouping?: 'none' | 'western' | 'indian';
      label?: string;
      countEnd?: number;
      tone?: Tone;
      size?: 'l' | 'm';
    }
  /** Pricing table. `strike`: column indices whose value is struck through (renewal-hike visual);
   *  `hike`: column indices shown in danger with an up arrow; `highlight`: one cell tinted brand;
   *  `winner` column gets an outline + badge at `winnerAt`. */
  | {
      type: 'price-compare';
      title?: string;
      columns: string[];
      rows: {label: string; values: string[]; at: number; strike?: number[]; hike?: number[]; highlight?: number}[];
      winner?: number;
      winnerAt?: number;
      winnerLabel?: string;
    }
  /** Terminal window. `cmd` lines type between `at` and `typeEnd` (default at + 0.04 s/char, ≤ 1.2 s). */
  | {
      type: 'terminal';
      title?: string;
      prompt?: string;
      lines: {text: string; kind?: 'cmd' | 'out' | 'ok' | 'err' | 'dim'; at: number; typeEnd?: number}[];
    }
  /** Product dashboard mock: sidebar + stat tiles + a bar chart growing between `at` and `chart.growEnd`. */
  | {
      type: 'dashboard';
      title?: string;
      nav?: string[];
      active?: number;
      stats: {label: string; value: string; delta?: string; tone?: Tone}[];
      chart?: {title?: string; bars: {label: string; value: number}[]; growEnd?: number; highlight?: number};
    }
  /** Phone / laptop frame around an image asset (public/ path) or a simple built-in screen UI. */
  | {
      type: 'device';
      frame: 'phone' | 'laptop';
      asset?: string;
      fit?: 'contain' | 'cover';
      screen?: {title: string; subtitle?: string; rows?: string[]; button?: string};
    }
  /** Image asset (public/ path); never distorted (box follows the intrinsic aspect). */
  | {
      type: 'image';
      asset: string;
      reveal?: 'mask' | 'fade' | 'none';
      kenBurns?: boolean;
      caption?: string;
      /** design-unit height cap (default 760) */
      maxHeight?: number;
    }
  /** Step indicator; step i becomes active at steps[i].at. */
  | {type: 'progress'; title?: string; steps: {label: string; at: number}[]}
  /** Browser frame whose page (stack of simple sections) scrolls between `at` and `scrollEnd`. */
  | {
      type: 'scroll-demo';
      url: string;
      sections: {title: string; text?: string; kind?: 'hero' | 'features' | 'pricing' | 'cta' | 'plain'}[];
      scrollEnd: number;
    }
  /** Bar or line chart with labelled values; grows/draws between `at` and `growEnd` (default at+0.9). */
  | {
      type: 'chart';
      kind: 'bar' | 'line';
      title?: string;
      data: {label: string; value: number}[];
      valuePrefix?: string;
      valueSuffix?: string;
      decimals?: number;
      highlight?: number;
      growEnd?: number;
      tone?: Tone;
    }
  /** ✓ / ✗ feature matrix across 2–3 columns; `highlight` column outlined at `highlightAt`. */
  | {
      type: 'feature-compare';
      title?: string;
      columns: string[];
      rows: {label: string; values: (boolean | string)[]; at: number}[];
      highlight?: number;
      highlightAt?: number;
    }
  /** Branding intro: short animated logo reveal (glow + mask wipe + sheen), optional tagline. */
  | {type: 'logo-sting'; variant?: 'onDark' | 'onLight'; tagline?: string}
  /** Branding outro layout: logo + tagline + CTA line + URL button (button lands at `urlAt`, default at+0.6). */
  | {type: 'outro'; url: string; cta?: string; tagline?: string; urlAt?: number}
  /** v2b: one premium pricing card. Price counts `countFrom` (default 0) → `price` between `at` and `countEnd`
   *  (default at+0.8); each feature row checks in at its `at`; the CTA button pulses from `highlightAt`.
   *  `variant` default: 'light' on a light backdrop, else 'dark'. Wide (2-column) layout when the box is ≥ 1100 design px. */
  | {
      type: 'plan-card';
      name: string;
      price: number;
      currency?: string;
      period?: string;
      billing?: string;
      badge?: string;
      features: {text: string; icon?: IconName; at: number}[];
      ctaLabel?: string;
      countFrom?: number;
      countEnd?: number;
      highlightAt?: number;
      variant?: 'light' | 'dark';
    }
  /** v2b: one-click installer window. Step i spins from steps[i].at and is checked when the next step starts
   *  (the last one at `doneAt`); at `doneAt` the success row (`doneText`) lands and, with `siteUrl`, a small
   *  browser preview of the new site slides in. All visible words come from the props. `appIcon` puts the
   *  product's real (licensed, public/shared/assets.json) icon on the app tile instead of the app's initial. */
  | {type: 'install-flow'; app: string; title?: string; steps: {label: string; at: number}[]; doneAt: number; doneText: string; siteUrl?: string;
      appIcon?: {asset: string; bg?: string}}
  /** v2b: server rack (2–4 units). Node i lights up at its `at`; data pulses flow to the website node from
   *  `pulseAt` (default: last node `at` + 0.3); optional status pill lands at `status.at`. */
  | {
      type: 'server-stack';
      title?: string;
      nodes: {label: string; icon?: IconName; at: number}[];
      pulseAt?: number;
      status?: {text: string; at: number; tone?: Tone};
      /** what the data flows into (default: a globe, i.e. the web); e.g. {icon: 'play'} for a rendered film */
      target?: {icon?: IconName};
    }
  /** A real video clip (screen recording, product footage), always muted (the film's audio is the pipeline's mix).
   *  Clip time = startFrom + (t − appear) · playbackRate; after the clip's end the last frame holds. The box follows
   *  the clip's aspect (never distorted); `zooms` are focus keyframes (normalised centre + scale ≥ 1) the view eases
   *  to from each `at`, always clamped inside the clip. `frame` draws browser / laptop / phone chrome around it. */
  | {
      type: 'footage';
      /** public/-relative .mp4 / .webm */
      asset: string;
      /** width / height of the clip (Python fills it from ffprobe; else read from the file's header) */
      aspect?: number;
      /** clip length in seconds (Python fills it from ffprobe; else read from the file's header) */
      duration?: number;
      frame?: 'browser' | 'laptop' | 'phone' | 'none';
      /** browser title-bar text (only drawn with frame 'browser') */
      title?: string;
      /** seconds into the clip at which playback starts (default 0) */
      startFrom?: number;
      /** default 1 */
      playbackRate?: number;
      zooms?: {at: number; x: number; y: number; scale: number}[];
      caption?: string;
    }
  /** A generated scene graphic (pipeline/creative/composer.py): primitives on a normalised canvas. Every element has a
   *  `box` [x, y, w, h] (0..1 of the canvas) for the tall layout (Shorts, narrow columns) and optionally a `wide` box
   *  (used when the block is ≥ COMPOSITION.wideMin design px wide). Colours are theme tokens only; text is fitted
   *  deterministically to its box (geometry-composition.ts). Times (`at`, `countEnd`, `pulseAt`) are resolved by Python. */
  | {
      type: 'composition';
      /** canvas aspect (width / height) per layout (defaults COMPOSITION.aspect) */
      canvas?: {tall?: number; wide?: number};
      elements: CompositionElement[];
      /** generator provenance (structure / variant / motion signature); never drawn */
      design?: {structure?: string; variant?: string; motion?: string; signature?: string; source?: string};
    };

/** Element kinds, shapes, motion presets, colour tokens and text roles of a `composition` (mirrored in pipeline/contract.py). */
export const COMPOSITION_KINDS = ['text', 'shape', 'connector', 'icon', 'number', 'logo', 'media'] as const;
export const COMPOSITION_SHAPES = ['rect', 'roundrect', 'circle', 'ring', 'arc', 'line'] as const;
export const COMPOSITION_MOTIONS = ['fade-up', 'fade', 'scale-in', 'draw-on', 'pop', 'none'] as const;
export const COMPOSITION_COLORS = ['brand', 'brandText', 'surface', 'card', 'raised', 'border', 'bg', 'text', 'muted', 'success', 'danger', 'warning', 'info'] as const;
export const COMPOSITION_ROLES = ['title', 'label', 'body', 'value'] as const;
export type CompositionKind = (typeof COMPOSITION_KINDS)[number];
export type CompositionShape = (typeof COMPOSITION_SHAPES)[number];
export type CompositionMotion = (typeof COMPOSITION_MOTIONS)[number];
export type CompositionColor = (typeof COMPOSITION_COLORS)[number];
export type CompositionRole = (typeof COMPOSITION_ROLES)[number];
/** One primitive of a composition. Unused fields are ignored for a kind. */
export type CompositionElement = {
  id?: string;
  kind: CompositionKind;
  /** [x, y, w, h], fractions of the canvas (tall layout) */
  box: number[];
  /** [x, y, w, h] in the wide layout (default: `box`) */
  wide?: number[];
  /** when the element enters (absolute seconds; default: the block's appear time) */
  at?: number;
  /** entrance preset (default per kind: text/number fade-up, shape scale-in, connector + ring/arc/line draw-on, icon pop) */
  motion?: CompositionMotion;
  /** a highlight pulse (brand glow + gentle scale) starting here */
  pulseAt?: number;
  /** text: the string (must come from facts / copy), role, alignment, colour */
  text?: string;
  role?: CompositionRole;
  align?: 'left' | 'center' | 'right';
  color?: CompositionColor;
  /** shape */
  shape?: CompositionShape;
  fill?: CompositionColor;
  stroke?: CompositionColor;
  /** stroke width, design px (1–40) */
  strokeW?: number;
  /** 0..1 */
  opacity?: number;
  /** arc: degrees drawn (0–360) from `start` (degrees, 0 = top, clockwise) */
  sweep?: number;
  start?: number;
  /** connector: element ids it joins, and a bend (-1..1, 0 = straight) */
  fromId?: string;
  toId?: string;
  curve?: number;
  /** icon */
  icon?: IconName;
  /** number: counts from `from` (default 0) to `to` between `at` and `countEnd` (default at + 0.8), like `counter` */
  to?: number;
  from?: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  grouping?: 'none' | 'western' | 'indian';
  countEnd?: number;
  /** logo: a theme logo variant; media: a public/ image (drawn contain, never distorted) */
  variant?: LogoVariant;
  asset?: string;
};

export type Block = BlockBase & (BlockV1 | BlockV2);
export type BlockType = Block['type'];

export type IconName =
  | 'zap' | 'lock' | 'server' | 'cloud' | 'globe' | 'arrowUp' | 'arrowRight' | 'check'
  | 'shield' | 'rocket' | 'clock' | 'database' | 'mail' | 'users' | 'chart' | 'star'
  // v2b
  | 'app' | 'cpu' | 'memory' | 'disk' | 'refresh' | 'plug' | 'palette' | 'settings' | 'download' | 'gauge'
  | 'play';

export type Transition = 'fade' | 'slide-up' | 'none' | 'mask-wipe' | 'gradient-sweep';
/** Scene camera. Absent = 'push-in' (the v1 behaviour: scale 1 → 1.03 over the scene). */
export type Camera = 'none' | 'push-in' | 'pan-left' | 'pan-right' | 'drift';
/** Motion preset: entrance springs / offsets / stagger only — never cue times. */
export type MotionPresetName = 'calm' | 'standard' | 'energetic' | 'cinematic';
/** v2b scene backdrop (absent = 'glow' = the v1/v2 dots-glow). Scenes with different backdrops crossfade. */
export type BackdropKind = 'glow' | 'spotlight' | 'grid' | 'split' | 'light' | 'deep';

export type Scene = {
  id: string;
  /** hook | problem | turn | journey | resolution | cta | intro | point | example | conclusion | custom */
  purpose: string;
  start: number;
  end: number;
  transition: Transition;
  /** 'stack': blocks stacked vertically (default; both formats). 'split': landscape-only two columns
   *  (first `splitAt` blocks left, rest right); falls back to 'stack' in short format. */
  layout: 'stack' | 'split';
  splitAt?: number;
  /** 'split' only: share of the content width given to the LEFT column (0.3–0.7, default 0.5), e.g. 0.62 for a
   *  screen recording beside its message in 16:9. */
  splitRatio?: number;
  /** red tint on the backdrop (e.g. problem scenes) */
  mood?: 'neutral' | 'danger' | 'brand';
  /** v2 */
  camera?: Camera;
  /** v2: overrides RenderProps.motion for this scene */
  motion?: MotionPresetName;
  /** v2b: scene backdrop (default 'glow'). 'split' moves the content off the brand panel; 'light' switches
   *  free-standing text to the theme's light tokens. Setting it on any scene opts the video into the v2b look. */
  backdrop?: BackdropKind;
  blocks: Block[];
};

export type WatermarkPosition = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'top-center';
/** v2 watermark. Defaults per format live in src/engine/branding.ts (WATERMARK_DEFAULTS). */
export type Watermark = {
  /** none: nothing. brand: theme logo. custom: `asset` (public/ path, required). platform: brand mark in the
   *  platform-safe corner (Shorts top-left below the status bar, landscape top-right; `position` ignored). */
  policy: 'none' | 'brand' | 'custom' | 'platform';
  asset?: string;
  variant?: LogoVariant;
  /** 0.05–1 */
  opacity?: number;
  position?: WatermarkPosition;
  /** watermark width as a fraction of the frame width */
  widthFrac?: number;
  /** corner margin as a fraction of the frame width */
  marginFrac?: number;
};

export type RenderProps = {
  contractVersion: number;
  format: Format;
  fps: number;
  durationInFrames: number;
  theme: Theme;
  captions: CaptionConfig;
  words: Word[];
  scenes: Scene[];
  /** persistent brand logo shown top-centre between these times (null = none) */
  brandBar: {from: number; to: number} | null;
  /** v2: default motion preset (scene.motion overrides). Default 'standard' (= v1 motion). */
  motion?: MotionPresetName;
  /** v2: corner watermark; hidden automatically while a logo / cta / logo-sting / outro block or the brand bar is visible */
  watermark?: Watermark | null;
  /** v2, optional: intrinsic width/height per asset path (public/). Filled by the engine's calculateMetadata
   *  (and by scripts/engine-layout.mjs) from the files themselves when absent; Python may pre-fill it. */
  assetAspects?: Record<string, number>;
};
