import {Camera, Scene, Transition} from '../types';
import {SCENE_DUR} from './durations';
import {EASE} from './easings';
import {life} from './exits';

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lin = (t: number, a: number, b: number) => (b <= a ? (t >= b ? 1 : 0) : clamp01((t - a) / (b - a)));
const mix = (a: number, b: number, p: number) => a + (b - a) * p;

export type SceneTransitionState = {
  opacity: number;
  dy: number;
  /** CSS mask-image for 'mask-wipe' (soft-edged wipe), undefined otherwise */
  mask?: string;
  /** 0..1 progress of the 'gradient-sweep' light band (undefined when not sweeping) */
  sweep?: number;
};

/** Soft edge width of the mask wipe, % of the gradient line. */
export const WIPE_FEATHER = 18;

/** Scene opacity / offset / mask for its transition. Every exit reaches exactly 0 at scene.end. Pure. */
export const sceneTransition = (s: Pick<Scene, 'start' | 'end'> & {transition: Transition}, t: number): SceneTransitionState => {
  const tr = s.transition;
  if (tr === 'none') return {opacity: t >= s.start && t < s.end ? 1 : 0, dy: 0};
  if (tr === 'mask-wipe') {
    if (t >= s.end) return {opacity: 0, dy: 0};
    const pIn = EASE.inOutCubic(lin(t, s.start - SCENE_DUR.inLead, s.start - SCENE_DUR.inLead + SCENE_DUR.wipeIn));
    const pOut = EASE.inOutCubic(lin(t, s.end - SCENE_DUR.wipeOut, s.end));
    const F = WIPE_FEATHER;
    const b = pIn * (100 + F) - F; // reveal edge
    const a = pOut * (100 + F) - F; // hide edge
    const r = (x: number) => x.toFixed(2);
    const mask = `linear-gradient(100deg, transparent ${r(a)}%, black ${r(a + F)}%, black ${r(b)}%, transparent ${r(b + F)}%)`;
    return {opacity: pIn > 0 && pOut < 1 ? 1 : 0, dy: 0, mask};
  }
  const o = life(t, s.start - SCENE_DUR.inLead, s.end, SCENE_DUR.fadeIn, SCENE_DUR.fadeOut);
  if (tr === 'slide-up') {
    const inP = EASE.outCubic(lin(t, s.start - SCENE_DUR.inLead, s.start + 0.3));
    const outP = lin(t, s.end - SCENE_DUR.slideOut, s.end);
    return {opacity: o, dy: (1 - inP) * 70 - outP * 50};
  }
  if (tr === 'gradient-sweep') {
    const p = lin(t, s.start - 0.1, s.start - 0.1 + SCENE_DUR.sweep);
    return {opacity: o, dy: 0, sweep: p > 0 && p < 1 ? p : undefined};
  }
  return {opacity: o, dy: 0};
};

/** v1 push-in: 1 → 1.03 over the scene. */
export const PUSH_SCALE = 1.03;
/** Pan / drift amplitude as a fraction of the frame width. */
export const PAN_FRAC = 0.012;

export type CameraState = {scale: number; dx: number; dy: number};

/** Scene camera (applied to the whole scene layer around the content centre). Absent = 'push-in'. Pure. */
export const cameraAt = (camera: Camera | undefined, s: Pick<Scene, 'start' | 'end'>, t: number, frameW: number, amp = 1): CameraState => {
  const cam = camera ?? 'push-in';
  const p = lin(t, s.start, s.end);
  const A = PAN_FRAC * frameW * amp;
  switch (cam) {
    case 'none':
      return {scale: 1, dx: 0, dy: 0};
    case 'push-in':
      return {scale: mix(1, amp === 1 ? PUSH_SCALE : 1 + (PUSH_SCALE - 1) * amp, p), dx: 0, dy: 0};
    case 'pan-left': {
      const q = EASE.inOutSine(p);
      return {scale: 1, dx: mix(A, -A, q), dy: 0};
    }
    case 'pan-right': {
      const q = EASE.inOutSine(p);
      return {scale: 1, dx: mix(-A, A, q), dy: 0};
    }
    case 'drift':
      return {scale: mix(1, 1 + 0.015 * amp, p), dx: mix(-0.6 * A, 0.6 * A, p), dy: mix(0.4 * A, -0.4 * A, p)};
  }
};

/**
 * Maximum displacement (output px) of any point of the content area [areaW × areaH] under the camera,
 * relative to its settled position. The v2 layout insets the safe area by this much, so a camera move
 * can never push content into the caption band or past the side margins. QA tolerance = these numbers.
 */
export const cameraReserve = (camera: Camera | undefined, areaW: number, areaH: number, frameW: number, amp = 1) => {
  const cam = camera ?? 'push-in';
  const A = PAN_FRAC * frameW * amp;
  switch (cam) {
    case 'none':
      return {x: 0, y: 0};
    case 'push-in': {
      const k = (amp === 1 ? PUSH_SCALE : 1 + (PUSH_SCALE - 1) * amp) - 1;
      return {x: (areaW * k) / 2, y: (areaH * k) / 2};
    }
    case 'pan-left':
    case 'pan-right':
      return {x: A, y: 0};
    case 'drift':
      return {x: 0.6 * A + (areaW * 0.015 * amp) / 2, y: 0.4 * A + (areaH * 0.015 * amp) / 2};
  }
};
