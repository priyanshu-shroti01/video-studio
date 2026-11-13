/**
 * Duration tokens (seconds). Everything in the engine is a pure function of t = frame / fps, so these
 * numbers fully determine the motion — no CSS transitions, no wall clock, no randomness.
 * Pure module (no Remotion import): safe for the Node layout manifest.
 */
export const DUR = {
  micro: 0.12,
  fast: 0.2,
  base: 0.3,
  medium: 0.4,
  slow: 0.5,
  slower: 0.8,
  sting: 1.2,
} as const;

/** Entrances start slightly before their cue, so the motion peaks on the spoken word. */
export const LEAD = {block: 0.05, word: 0.06, row: 0.08, card: 0.1, button: 0.12, drop: 0.1} as const;

/** Default stagger of un-timed blocks after the scene start. */
export const STAGGER = {blockFirst: 0.1, block: 0.12} as const;

/** Scene transitions (all exits reach exactly 0 at scene.end). */
export const SCENE_DUR = {
  fadeIn: 0.2,
  fadeOut: 0.22,
  inLead: 0.05,
  slideIn: 0.35,
  slideOut: 0.22,
  wipeIn: 0.45,
  wipeOut: 0.28,
  sweep: 0.65,
} as const;

/** Generic life envelope (fade in / fade out) and block exits. */
export const LIFE = {in: 0.18, out: 0.22, outPower: 1.5} as const;
export const EXIT = {dur: 0.2, power: 1.5} as const;

/** Frames of the global end-of-video fade. */
export const VIDEO_FADE_FRAMES = 12;

/** Brand bar and watermark envelopes. */
export const BRANDBAR_DUR = {fadeIn: 0.25, fadeOut: 0.22, pad: 0.05} as const;
export const WATERMARK_DUR = {fade: 0.3} as const;

/** Visible window padding around a scene (mount window). */
export const VISIBLE_PAD = {before: 0.15, after: 0.05} as const;

/** When a block appears: its explicit `at`, else staggered after the scene start. */
export const appearTime = (sceneStart: number, index: number, at?: number, stagger: number = STAGGER.block) =>
  at ?? sceneStart + STAGGER.blockFirst + index * stagger;

/** Accent timings of individual block parts (seconds, relative to the part's own cue). */
export const ACCENT = {
  strike: 0.35,
  noteFade: 0.3,
  checkDrawFrom: 0.08,
  checkDrawTo: 0.35,
  grow: 0.5,
  count: 0.5,
  select: 0.2,
  emphasizeBackFrom: 0.3,
  emphasizeBackTo: 0.6,
  pulseDelay: 0.4,
  ring: 1.0,
  /** caret blink frequency (Hz) — derived from t, so deterministic */
  caretHz: 2.2,
} as const;
