import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

/** Current time in seconds. All scene logic is written in absolute seconds against the beat sheet. */
export const useT = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return frame / fps;
};

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
/** 0..1 linear progress of t through [a, b] */
export const lin = (t: number, a: number, b: number) => clamp01((t - a) / (b - a));
export const easeOut = (t: number, a: number, b: number) => Easing.out(Easing.cubic)(lin(t, a, b));
export const easeInOut = (t: number, a: number, b: number) => Easing.inOut(Easing.cubic)(lin(t, a, b));

/** Spring progress starting at second `at` (damping 14 / mass 0.7 = quick, slight overshoot). */
export const sp = (t: number, at: number, damping = 14, mass = 0.7, fps = 30) =>
  t < at ? 0 : spring({frame: (t - at) * fps, fps, config: {damping, mass}});

/** Fade in over `inDur` after `start`, fade to exactly 0 by `end` (anything2explainer: exits must reach 0 before the cut). */
export const life = (t: number, start: number, end: number, inDur = 0.18, outDur = 0.22) =>
  Math.min(easeOut(t, start, start + inDur), 1 - Math.pow(lin(t, end - outDur, end), 1.5));

export const mix = (a: number, b: number, p: number) => a + (b - a) * p;
export const range = (t: number, inp: number[], out: number[]) =>
  interpolate(t, inp, out, {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
