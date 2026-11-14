/**
 * Effect transitions (additive to motion/transitions.ts): whip-pan, zoom-through, push, iris, light-leak, glitch.
 *
 * A scene's `transition` says how it ENTERS. When the NEXT scene enters with one of these, this scene EXITS with the
 * matching move (whip out, zoom into the cut, push away...), so the pair reads as one edit. As everywhere in the
 * engine, every exit reaches exactly 0 opacity at scene.end, and an entrance may start at most VISIBLE_PAD.before
 * before scene.start. Durations are seconds; the glitch is counted in output frames (≤ 6 in total at any fps).
 *
 * Scenes whose own transition and whose next scene's transition are both classic never reach this module
 * (Storyboard.tsx keeps the classic `sceneTransition` path for them, bit-identical). Pure (no React / Remotion).
 */
import {Format, Scene, Transition, TransitionDir} from '../types';
import {EASE} from './easings';
import {hash32} from './effects';
import {sceneTransition, SceneTransitionState} from './transitions';

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lin = (t: number, a: number, b: number) => (b <= a ? (t >= b ? 1 : 0) : clamp01((t - a) / (b - a)));
const inCubic = (x: number) => x * x * x;

export const FX_TRANSITIONS = ['whip-pan', 'zoom-through', 'push', 'iris', 'light-leak', 'glitch'] as const;
export type FxTransition = (typeof FX_TRANSITIONS)[number];
const FX_SET: ReadonlySet<string> = new Set(FX_TRANSITIONS);
export const isFxTransition = (tr: Transition | undefined): tr is FxTransition => !!tr && FX_SET.has(tr);

/** Timing / amplitude tokens (seconds; travel = fraction of the frame along the move axis). */
export const TR_FX = {
  whip: {out: 0.18, in: 0.3, lead: 0.06, travel: 0.45},
  push: {out: 0.3, outFade: 0.1, in: 0.32, lead: 0.12, travel: 0.4},
  zoom: {out: 0.22, in: 0.36, lead: 0.04, outScale: 0.32, inScale: 0.2, outBlur: 14, inBlur: 10},
  iris: {out: 0.2, in: 0.48, lead: 0.12, feather: 0.06, scaleFrom: 1.04},
  leak: {out: 0.3, in: 0.3, lead: 0.05, half: 0.32, peak: 0.5},
  /** frames of RGB split on each side of the cut (3 + 3 = 6 frames) */
  glitch: {frames: 3, split: [0, 5, 10, 16] as readonly number[], jitter: 10},
  /** directional blur levels (σ in px along the move) and the px/frame speed each level needs */
  blur: {sigma: [0, 4, 9, 16, 26] as readonly number[], speed: [0, 14, 34, 70, 120] as readonly number[]},
} as const;

export type FxTransitionState = SceneTransitionState & {
  dx: number;
  scale: number;
  /** directional motion blur level (index into TR_FX.blur.sigma) and its axis */
  blurLevel: number;
  blurAxis: 'x' | 'y';
  /** isotropic blur, px (zoom-through) */
  blur: number;
  /** RGB-split level 0..3 (glitch) and its horizontal jitter, px */
  glitch: number;
  glitchDx: number;
};

export type FxGeo = {width: number; height: number; cx: number; cy: number; format: Format};

const IDENT: FxTransitionState = {opacity: 1, dy: 0, dx: 0, scale: 1, blurLevel: 0, blurAxis: 'x', blur: 0, glitch: 0, glitchDx: 0};

/** Default move direction: whip-pan left; push up in 9:16 (a feed swipe), left in 16:9. */
export const defaultDir = (tr: FxTransition, format: Format): TransitionDir => (tr === 'push' && format === 'short' ? 'up' : 'left');
const dirVec = (d: TransitionDir): [number, number] => (d === 'left' ? [-1, 0] : d === 'right' ? [1, 0] : d === 'up' ? [0, -1] : [0, 1]);

const blurLevelFor = (speed: number) => {
  const sp = TR_FX.blur.speed;
  let k = 0;
  for (let i = 1; i < sp.length; i++) if (speed >= sp[i]) k = i;
  return k;
};

/** Displacement (output px along the move axis, signed) of the incoming / outgoing scene. */
const inDisp = (tr: FxTransition, B: number, t: number, L: number) => {
  if (tr === 'whip-pan') {
    const c = TR_FX.whip;
    return (1 - EASE.outCubic(lin(t, B - c.lead, B - c.lead + c.in))) * c.travel * L;
  }
  if (tr === 'push') {
    const c = TR_FX.push;
    return (1 - EASE.outCubic(lin(t, B - c.lead, B - c.lead + c.in))) * c.travel * L;
  }
  return 0;
};
const outDisp = (tr: FxTransition, E: number, t: number, L: number) => {
  if (tr === 'whip-pan') return inCubic(lin(t, E - TR_FX.whip.out, E)) * TR_FX.whip.travel * L;
  if (tr === 'push') return EASE.inOutCubic(lin(t, E - TR_FX.push.out, E)) * TR_FX.push.travel * L;
  return 0;
};

const frameIndex = (t: number, fps: number) => Math.round(t * fps);

/** Entrance part of an effect transition (scene starts at B). */
export const fxIn = (tr: FxTransition, dir: TransitionDir, B: number, t: number, fps: number, g: FxGeo): FxTransitionState => {
  const [mx, my] = dirVec(dir);
  const L = mx !== 0 ? g.width : g.height;
  switch (tr) {
    case 'whip-pan':
    case 'push': {
      const c = tr === 'whip-pan' ? TR_FX.whip : TR_FX.push;
      const d = inDisp(tr, B, t, L);
      const v = Math.abs(d - inDisp(tr, B, t - 1 / fps, L));
      const p = lin(t, B - c.lead, B - c.lead + c.in);
      const opacity = tr === 'whip-pan' ? clamp01(p * 4) : lin(t, B - c.lead, B - c.lead + 0.1);
      // the incoming scene arrives from the side the outgoing one left towards (-m)
      return {...IDENT, opacity, dx: -mx * d, dy: -my * d, blurLevel: tr === 'whip-pan' ? blurLevelFor(v) : Math.min(1, blurLevelFor(v)), blurAxis: mx !== 0 ? 'x' : 'y'};
    }
    case 'zoom-through': {
      const c = TR_FX.zoom;
      const p = EASE.outCubic(lin(t, B - c.lead, B - c.lead + c.in));
      return {...IDENT, opacity: clamp01(lin(t, B - c.lead, B - c.lead + c.in) * 3), scale: 1 + c.inScale * (1 - p), blur: c.inBlur * (1 - p)};
    }
    case 'iris': {
      const c = TR_FX.iris;
      const p = EASE.inOutCubic(lin(t, B - c.lead, B - c.lead + c.in));
      if (p <= 0) return {...IDENT, opacity: 0};
      if (p >= 1) return {...IDENT, scale: 1};
      const R = Math.hypot(Math.max(g.cx, g.width - g.cx), Math.max(g.cy, g.height - g.cy));
      const F = c.feather * Math.max(g.width, g.height);
      const r = p * (R + F);
      const f = (x: number) => x.toFixed(1);
      const mask = `radial-gradient(circle at ${f(g.cx)}px ${f(g.cy)}px, black ${f(Math.max(0, r - F))}px, transparent ${f(r)}px)`;
      return {...IDENT, mask, scale: c.scaleFrom + (1 - c.scaleFrom) * p};
    }
    case 'light-leak': {
      const c = TR_FX.leak;
      return {...IDENT, opacity: EASE.outCubic(lin(t, B - c.lead, B - c.lead + c.in))};
    }
    case 'glitch': {
      const f = frameIndex(t, fps) - frameIndex(B, fps);
      if (t < B - 1e-9) return {...IDENT, opacity: 0};
      if (f < 0 || f >= TR_FX.glitch.frames) return IDENT;
      const level = TR_FX.glitch.frames - f; // 3, 2, 1
      return {...IDENT, glitch: level, glitchDx: jitter(t, fps, level)};
    }
  }
};

const jitter = (t: number, fps: number, level: number) => (((hash32(`g${frameIndex(t, fps)}`) % 3) - 1) * TR_FX.glitch.jitter * level) / 3;

/** Exit part when the NEXT scene enters with effect transition `tr` (this scene ends at E; opacity is 0 at E). */
export const fxOut = (tr: FxTransition, dir: TransitionDir, E: number, t: number, fps: number, g: FxGeo): FxTransitionState => {
  if (t >= E) return {...IDENT, opacity: 0};
  const [mx, my] = dirVec(dir);
  const L = mx !== 0 ? g.width : g.height;
  switch (tr) {
    case 'whip-pan':
    case 'push': {
      const d = outDisp(tr, E, t, L);
      const v = Math.abs(d - outDisp(tr, E, t - 1 / fps, L));
      const opacity = tr === 'whip-pan' ? 1 - lin(t, E - TR_FX.whip.out, E) ** 4 : 1 - lin(t, E - TR_FX.push.outFade, E) ** 1.5;
      return {...IDENT, opacity, dx: mx * d, dy: my * d, blurLevel: tr === 'whip-pan' ? blurLevelFor(v) : Math.min(1, blurLevelFor(v)), blurAxis: mx !== 0 ? 'x' : 'y'};
    }
    case 'zoom-through': {
      const c = TR_FX.zoom;
      const q = lin(t, E - c.out, E);
      return {...IDENT, opacity: 1 - q ** 3, scale: 1 + c.outScale * q * q, blur: c.outBlur * q};
    }
    case 'iris': {
      const q = lin(t, E - TR_FX.iris.out, E);
      return {...IDENT, opacity: 1 - q * q, scale: 1 - 0.04 * q};
    }
    case 'light-leak':
      return {...IDENT, opacity: 1 - lin(t, E - TR_FX.leak.out, E) ** 1.5};
    case 'glitch': {
      const f = frameIndex(E, fps) - frameIndex(t, fps); // frames before the cut: 1, 2, 3
      if (f < 1 || f > TR_FX.glitch.frames) return IDENT;
      const level = TR_FX.glitch.frames + 1 - f; // 1 (3 frames before) … 3 (last frame)
      return {...IDENT, glitch: level, glitchDx: jitter(t, fps, level)};
    }
  }
};

type SceneLike = Pick<Scene, 'start' | 'end' | 'transition' | 'transitionDir'>;
const BIG = 1e9;

/** True when a scene needs the effect-transition path (its own entrance or its exit into the next scene). */
export const needsFxTransition = (s: Pick<Scene, 'transition'>, next?: Pick<Scene, 'transition'>) => isFxTransition(s.transition) || isFxTransition(next?.transition);

/**
 * Full transition state of a scene whose own or next transition is an effect transition: the entrance of its own
 * transition (classic or effect) combined with the exit into the next scene (the next scene's effect exit, else the
 * classic fade-out). Pure.
 */
export const sceneTransitionFx = (s: SceneLike, next: Pick<Scene, 'transition' | 'transitionDir'> | undefined, t: number, fps: number, g: FxGeo): FxTransitionState => {
  const own = s.transition;
  const inS: FxTransitionState = isFxTransition(own)
    ? fxIn(own, s.transitionDir ?? defaultDir(own, g.format), s.start, t, fps, g)
    : {...IDENT, ...sceneTransition({start: s.start, end: BIG, transition: own}, t)};
  const nx = next?.transition;
  const outS: FxTransitionState = isFxTransition(nx)
    ? fxOut(nx, next?.transitionDir ?? defaultDir(nx, g.format), s.end, t, fps, g)
    : {...IDENT, ...sceneTransition({start: -BIG, end: s.end, transition: isFxTransition(own) ? 'fade' : own}, t)};
  if (t >= s.end) return {...IDENT, opacity: 0};
  return {
    opacity: inS.opacity * outS.opacity,
    dy: inS.dy + outS.dy,
    dx: inS.dx + outS.dx,
    scale: inS.scale * outS.scale,
    mask: inS.mask ?? outS.mask,
    sweep: inS.sweep,
    blurLevel: Math.max(inS.blurLevel, outS.blurLevel),
    blurAxis: inS.blurLevel >= outS.blurLevel ? inS.blurAxis : outS.blurAxis,
    blur: Math.max(inS.blur, outS.blur),
    glitch: Math.max(inS.glitch, outS.glitch),
    glitchDx: inS.glitchDx + outS.glitchDx,
  };
};

/** Light-leak overlay at t: a warm light bloom peaking on the cut of every 'light-leak' scene (null when none).
 *  `p` is 0..1 across the bloom (the light drifts), `intensity` ≤ TR_FX.leak.peak. */
export const lightLeakAt = (scenes: Pick<Scene, 'id' | 'start' | 'transition'>[], t: number, allowed?: Set<string>) => {
  const h = TR_FX.leak.half;
  for (let k = 1; k < scenes.length; k++) {
    const s = scenes[k];
    if (s.transition !== 'light-leak' || (allowed && !allowed.has(`${s.id}#leak`))) continue;
    const tau = t - s.start;
    if (tau <= -h || tau >= h) continue;
    return {p: (tau + h) / (2 * h), intensity: TR_FX.leak.peak * (0.5 + 0.5 * Math.cos((Math.PI * tau) / h)), seed: k};
  }
  return null;
};

/** Seconds an effect transition's entrance starts before scene.start (all ≤ VISIBLE_PAD.before = 0.15). */
export const FX_IN_LEAD: Record<FxTransition, number> = {
  'whip-pan': TR_FX.whip.lead,
  push: TR_FX.push.lead,
  'zoom-through': TR_FX.zoom.lead,
  iris: TR_FX.iris.lead,
  'light-leak': TR_FX.leak.lead,
  glitch: 0,
};
