import {EASE, SpringCfg} from './motion/easings';
import {springAt} from './motion/entrances';

/** Pure timing helpers. Everything in the engine is a function of absolute time `t` (seconds). */
export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const lin = (t: number, a: number, b: number) => (b <= a ? (t >= b ? 1 : 0) : clamp01((t - a) / (b - a)));
export const easeOut = (t: number, a: number, b: number) => EASE.outCubic(lin(t, a, b));
export const easeInOut = (t: number, a: number, b: number) => EASE.inOutCubic(lin(t, a, b));
export const mix = (a: number, b: number, p: number) => a + (b - a) * p;

/** Spring progress from second `at` (quick, slight overshoot). */
export const sp = (t: number, at: number, fps: number, damping = 14, mass = 0.7) => springAt(t, at, fps, {damping, mass});
/** Spring progress with a token config (motion/easings.ts SPRING or a preset's spring). */
export const spc = (t: number, at: number, fps: number, cfg: SpringCfg) => springAt(t, at, fps, cfg);

export {exitFactor, life} from './motion/exits';

export {appearTime} from './motion/durations';

/** Count-up value (integer) from `from` to `to` between `at` and `end`. */
export const countValue = (t: number, at: number, end: number, from: number, to: number) => {
  if (t <= at) return from;
  if (t >= end) return to;
  return Math.round(mix(from, to, EASE.outQuad(lin(t, at, end))));
};

/** Count value with `decimals` (rounded, never past `to`). */
export const countValueDec = (t: number, at: number, end: number, from: number, to: number, decimals = 0) => {
  if (t <= at) return from;
  if (t >= end) return to;
  const k = 10 ** decimals;
  return Math.round(mix(from, to, EASE.outQuad(lin(t, at, end))) * k) / k;
};
