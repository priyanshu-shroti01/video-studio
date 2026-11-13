/**
 * Easing + spring tokens. The curves are written with exactly the arithmetic of Remotion's `Easing`
 * (Easing.out(Easing.cubic) etc.), so they are bit-identical to v1 while staying a pure module that the
 * Node layout manifest can import without Remotion. Springs themselves are evaluated in entrances.ts.
 */
type Curve = (x: number) => number;
const out = (e: Curve): Curve => (t) => 1 - e(1 - t);
const inOut = (e: Curve): Curve => (t) => (t < 0.5 ? e(t * 2) / 2 : 1 - e((1 - t) * 2) / 2);
const quad: Curve = (t) => t * t;
const cubic: Curve = (t) => t * t * t;
const sin: Curve = (t) => 1 - Math.cos((t * Math.PI) / 2);
const exp: Curve = (t) => 2 ** (10 * (t - 1));
const poly = (n: number): Curve => (t) => t ** n;

export const EASE = {
  linear: ((x: number) => x) as Curve,
  outCubic: out(cubic),
  inOutCubic: inOut(cubic),
  outQuad: out(quad),
  inOutSine: inOut(sin),
  outExpo: out(exp),
  inOutQuart: inOut(poly(4)),
} as const;
export type EaseName = keyof typeof EASE;

export type SpringCfg = {damping: number; mass: number};

/**
 * Spring tokens. `entrance`/`word`/`row`/`card` are the 'standard' preset values (presets.ts swaps them per
 * preset); the accents below keep their character in every preset.
 */
export const SPRING = {
  entrance: {damping: 15, mass: 0.8},
  word: {damping: 13, mass: 0.6},
  row: {damping: 13, mass: 0.7},
  card: {damping: 15, mass: 0.8},
  logo: {damping: 13, mass: 0.8},
  pop: {damping: 12, mass: 0.6},
  stamp: {damping: 11, mass: 0.6},
  sticker: {damping: 10, mass: 0.6},
  badge: {damping: 9, mass: 0.6},
  land: {damping: 8, mass: 0.5},
  button: {damping: 14, mass: 0.7},
  drop: {damping: 12, mass: 0.8},
  soft: {damping: 20, mass: 1},
} as const satisfies Record<string, SpringCfg>;
