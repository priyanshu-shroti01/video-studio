/**
 * Emphasis effects (scene.effects): pure per-frame state functions. Every function is a pure function of the
 * timeline time t (seconds) and the effect's own fields: no Math.random, no Date. Seeded "randomness" (shake phase,
 * confetti) comes from a hash of the scene id + effect index, so a frame renders the same on every run, at every
 * concurrency and in every format. Every effect is exactly at identity outside its window
 * (scale 1, offset 0, intensity 0, nothing drawn).
 *
 * Pure module (no React / Remotion): imported by the renderer (effects.tsx) and by vitest.
 */
import {Scene, SceneEffect} from '../types';
import {LEAD} from './durations';
import {EASE} from './easings';

const clamp = (x: number, a: number, b: number) => Math.min(b, Math.max(a, x));
const clamp01 = (x: number) => clamp(x, 0, 1);
const lin = (t: number, a: number, b: number) => (b <= a ? (t >= b ? 1 : 0) : clamp01((t - a) / (b - a)));
const num = (x: unknown, d: number) => (typeof x === 'number' && Number.isFinite(x) ? x : d);

/** Effect tokens (seconds, output px, ratios). Python mirror: pipeline/effects.py (limits only). */
export const FX = {
  punch: {scale: 1.06, min: 1.01, max: 1.12, lead: 0.03, attack: 0.08, dur: 0.55},
  shake: {amp: 6, max: 8, dur: 0.36, hz: 17},
  /** brightness pulse: an overlay of at most 45 % (never a full-white frame) */
  flash: {intensity: 0.3, max: 0.45, attack: 0.05, decay: 0.3},
  burst: {count: 22, max: 40, life: 1.0, speed: 820, gravity: 1500, drag: 2.4},
  annotate: {dur: 0.5, lead: LEAD.word},
  cursor: {glide: 0.6, arrive: 0.1, fadeIn: 0.15, press: 0.18, ripple: 0.5, linger: 0.55, fadeOut: 0.25},
  tilt: {rx: 9, ry: -14, max: 25, dur: 0.95, perspective: 1600, parallax: 3},
  grain: {opacity: 0.045, max: 0.09, hz: 24},
  /** photosensitivity (WCAG 2.3.1): at most 3 flashes in any 1-s window */
  photo: {maxPerWindow: 3, window: 1.0},
} as const;

export const EFFECT_TYPES = ['punch-zoom', 'shake', 'flash', 'burst', 'annotate', 'cursor', 'tilt'] as const;

// ------------------------------------------------------------------------------------------------ seeded noise
/** FNV-1a 32-bit hash of a string. */
export const hash32 = (s: string) => {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
};
/** mulberry32 PRNG: deterministic sequence in [0, 1) from a 32-bit seed. */
export const prng = (seed: number) => {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};
export const effectSeed = (sceneId: string, index: number) => hash32(`${sceneId}#fx${index}`);

// ------------------------------------------------------------------------------------------------ camera effects
/** Punch-zoom ("camera kick + settle"): a fast push to `scale` that lands on the word, then a damped settle back to 1
 *  (a slight undershoot, then exactly 1 at at + dur). Returns the scale multiplier. */
export const punchScale = (e: {at: number; scale?: number; dur?: number}, t: number) => {
  const S = clamp(num(e.scale, FX.punch.scale), FX.punch.min, FX.punch.max);
  const t0 = e.at - FX.punch.lead;
  const dur = clamp(num(e.dur, FX.punch.dur), 0.25, 1.5);
  const ta = t0 + FX.punch.attack;
  const t1 = ta + dur;
  if (t < t0 || t >= t1) return 1;
  if (t < ta) return 1 + (S - 1) * EASE.outCubic((t - t0) / FX.punch.attack);
  const q = (t - ta) / dur;
  return 1 + (S - 1) * (1 - q) * (1 - q) * Math.cos(1.5 * Math.PI * q);
};

/** Impact shake: a small eased damped wobble (≤ FX.shake.max px), exactly 0 outside [at, at + dur]. */
export const shakeOffset = (e: {at: number; amp?: number; dur?: number}, t: number, seed = 0) => {
  const A = clamp(num(e.amp, FX.shake.amp), 0, FX.shake.max);
  const dur = clamp(num(e.dur, FX.shake.dur), 0.1, 0.8);
  const tau = t - e.at;
  if (t < e.at || t >= e.at + dur || A === 0) return {dx: 0, dy: 0};
  const q = tau / dur;
  const env = Math.min(1, tau / 0.03) * (1 - q) * (1 - q);
  const r = prng(seed);
  const p1 = r() * Math.PI * 2;
  const p2 = r() * Math.PI * 2;
  const w = 2 * Math.PI * FX.shake.hz;
  // the two axes have incommensurate frequencies, so the path never repeats into a visible pattern;
  // the envelope keeps |offset| ≤ A (and the vertical axis smaller)
  return {dx: A * env * Math.sin(w * tau + p1), dy: 0.6 * A * env * Math.sin(1.37 * w * tau + p2)};
};

/** Flash: brightness-pulse intensity 0..FX.flash.max (an overlay alpha; never a full-white frame). */
export const flashIntensity = (e: {at: number; intensity?: number}, t: number) => {
  const I = clamp(num(e.intensity, FX.flash.intensity), 0, FX.flash.max);
  const t0 = e.at - FX.flash.attack * 0.5;
  const tau = t - t0;
  const {attack, decay} = FX.flash;
  if (t < t0 || t >= t0 + attack + decay) return 0;
  if (tau < attack) return I * EASE.outQuad(tau / attack);
  const q = (tau - attack) / decay;
  return I * (1 - q) * (1 - q);
};

/** Combined camera of a scene's punch-zoom + shake effects at t (identity when none is active). */
export const effectCamera = (effects: SceneEffect[] | undefined, sceneId: string, t: number) => {
  let scale = 1;
  let dx = 0;
  let dy = 0;
  (effects ?? []).forEach((e, i) => {
    if (e.type === 'punch-zoom') scale *= punchScale(e, t);
    else if (e.type === 'shake') {
      const o = shakeOffset(e, t, effectSeed(sceneId, i));
      dx += o.dx;
      dy += o.dy;
    }
  });
  return {scale, dx, dy};
};
export const isIdentityCamera = (c: {scale: number; dx: number; dy: number}) => c.scale === 1 && c.dx === 0 && c.dy === 0;

// ------------------------------------------------------------------------------------------------ burst
export type Particle = {x: number; y: number; size: number; rot: number; opacity: number; color: number; shape: 'rect' | 'dot'};

/** Confetti / particle burst from a ring of radius r0 around the origin (0, 0), design px. Seeded per effect; nothing outside [at, at + life). */
export const burstParticles = (e: {at: number; count?: number; spread?: 'radial' | 'up'}, t: number, seed: number, r0 = 0): Particle[] => {
  const tau = t - e.at;
  const {life, speed, gravity, drag} = FX.burst;
  if (tau < 0 || tau >= life) return [];
  const n = Math.round(clamp(num(e.count, FX.burst.count), 4, FX.burst.max));
  const r = prng(seed);
  const decay = (1 - Math.exp(-drag * tau)) / drag;
  const out: Particle[] = [];
  for (let i = 0; i < n; i++) {
    const a = e.spread === 'up' ? -Math.PI / 2 + (r() - 0.5) * Math.PI * 0.9 : ((i + r() * 0.8) / n) * Math.PI * 2;
    const v = speed * (0.45 + 0.55 * r());
    const size = 12 + r() * 14;
    const spin = (r() - 0.5) * 900;
    const rot0 = r() * 360;
    const color = Math.floor(r() * 4);
    const shape: Particle['shape'] = r() < 0.62 ? 'rect' : 'dot';
    const fadeStart = 0.45 + r() * 0.2;
    const q = tau / life;
    const opacity = q < fadeStart ? 1 : 1 - EASE.inOutSine((q - fadeStart) / (1 - fadeStart));
    out.push({
      // particles start on a ring of radius r0 around the origin (outside the number they celebrate)
      x: Math.cos(a) * (r0 + v * decay),
      y: Math.sin(a) * (r0 + v * decay) + 0.5 * gravity * 0.35 * tau * tau,
      size: size * (1 - 0.35 * q),
      rot: rot0 + spin * tau,
      opacity: clamp01(opacity),
      color,
      shape,
    });
  }
  return out;
};

// ------------------------------------------------------------------------------------------------ annotations
export type R = {x: number; y: number; w: number; h: number};

/** Draw-on progress 0..1 of an annotation (eased), 0 before at − lead; holds at 1 (the stroke stays until the scene exits). */
export const drawProgress = (e: {at: number; dur?: number}, t: number) => {
  const dur = clamp(num(e.dur, FX.annotate.dur), 0.2, 1.5);
  return EASE.inOutCubic(lin(t, e.at - FX.annotate.lead, e.at - FX.annotate.lead + dur));
};

const f2 = (x: number) => x.toFixed(2);
/** Hand-drawn annotation path around/under rect `r` (design px). Deterministic: the wobble comes from `seed`.
 *  Returns the stroke path and, for arrows, the head path (drawn once the shaft has landed). */
export const annotationPath = (kind: 'underline' | 'circle' | 'arrow', r: R, seed: number, areaW?: number): {d: string; head?: string; stroke: number} => {
  const rnd = prng(seed);
  const j = (k: number) => (rnd() - 0.5) * k;
  const fs = Math.max(18, Math.min(r.h, 160));
  const stroke = clamp(fs * 0.085, 5, 12);
  if (kind === 'underline') {
    const y = r.y + r.h + stroke * 0.9;
    const x0 = r.x - fs * 0.06;
    const x1 = r.x + r.w + fs * 0.06;
    const mid = (x0 + x1) / 2;
    return {d: `M ${f2(x0)} ${f2(y + j(4))} Q ${f2(mid)} ${f2(y + fs * 0.09 + j(3))} ${f2(x1)} ${f2(y - fs * 0.05 + j(3))}`, stroke};
  }
  if (kind === 'circle') {
    const cx = r.x + r.w / 2;
    const cy = r.y + r.h / 2;
    const rx = r.w / 2 + fs * 0.42;
    const ry = r.h / 2 + fs * 0.36;
    const a0 = -2.4 + j(0.3);
    const turns = 1.08;
    const steps = 28;
    let d = '';
    for (let i = 0; i <= steps; i++) {
      const a = a0 + (i / steps) * turns * Math.PI * 2;
      const k = 1 + 0.035 * Math.sin(i * 0.9 + seed % 7) + (i / steps) * 0.04;
      d += `${i ? ' L' : 'M'} ${f2(cx + Math.cos(a) * rx * k)} ${f2(cy + Math.sin(a) * ry * k)}`;
    }
    return {d, stroke};
  }
  // arrow: a curved shaft coming in level with the target from the side with more room (never from below, where the
  // captions sit), landing just beside the target's mid-height; then a two-stroke head
  const fromRight = areaW === undefined ? true : r.x + r.w / 2 < areaW / 2;
  const sgn = fromRight ? 1 : -1;
  const tx = fromRight ? r.x + r.w + fs * 0.18 : r.x - fs * 0.18;
  const ty = r.y + r.h * 0.5;
  const sx = tx + sgn * fs * 1.6;
  const sy = ty - fs * 0.75;
  const c1x = sx - sgn * fs * 0.15 + j(6);
  const c1y = ty + fs * 0.05;
  const d = `M ${f2(sx)} ${f2(sy)} Q ${f2(c1x)} ${f2(c1y)} ${f2(tx)} ${f2(ty)}`;
  const ang = Math.atan2(ty - c1y, tx - c1x);
  const hl = fs * 0.42;
  const h1 = {x: tx - Math.cos(ang - 0.5) * hl, y: ty - Math.sin(ang - 0.5) * hl};
  const h2 = {x: tx - Math.cos(ang + 0.5) * hl, y: ty - Math.sin(ang + 0.5) * hl};
  return {d, head: `M ${f2(h1.x)} ${f2(h1.y)} L ${f2(tx)} ${f2(ty)} L ${f2(h2.x)} ${f2(h2.y)}`, stroke};
};

// ------------------------------------------------------------------------------------------------ cursor
export type CursorState = {opacity: number; x: number; y: number; press: number; ripple: {r: number; opacity: number} | null};

/** Cursor + click ripple on a footage clip. Positions are normalised clip coordinates (0..1). The cursor glides in from
 *  `from` (default: below-right of the target), arrives just before `at`, clicks on `at` (press dip + ripple), lingers,
 *  then fades. Undefined outside its window (nothing drawn). */
export const cursorState = (e: {at: number}, target: {x: number; y: number}, t: number): CursorState | undefined => {
  const c = FX.cursor;
  const tArrive = e.at - c.arrive;
  const t0 = tArrive - c.glide;
  const tEnd = e.at + c.linger + c.fadeOut;
  if (t < t0 - c.fadeIn || t >= tEnd) return undefined;
  const from = {x: clamp(target.x + 0.2, 0.05, 0.95), y: clamp(target.y + 0.24, 0.05, 0.95)};
  const p = EASE.inOutCubic(lin(t, t0, tArrive));
  // slight arc: the path bows sideways, like a hand-moved mouse
  const bow = Math.sin(Math.PI * p) * 0.04;
  const x = from.x + (target.x - from.x) * p + bow;
  const y = from.y + (target.y - from.y) * p;
  const opacity = Math.min(lin(t, t0 - c.fadeIn, t0), 1 - lin(t, e.at + c.linger, tEnd));
  const pt = t - e.at;
  const press = pt >= 0 && pt < c.press ? Math.sin((Math.PI * pt) / c.press) : 0;
  const rp = pt >= 0 && pt < c.ripple ? pt / c.ripple : -1;
  return {opacity: clamp01(opacity), x, y, press, ripple: rp >= 0 ? {r: EASE.outCubic(rp), opacity: (1 - rp) ** 1.5} : null};
};

// ------------------------------------------------------------------------------------------------ tilt
/** 3D tilt / parallax entrance: the block starts rotated (rx, ry degrees) and settles flat (exactly 0) over `dur`. */
export const tiltAt = (e: {at?: number; rx?: number; ry?: number; dur?: number}, t: number, appear: number) => {
  const rx0 = clamp(num(e.rx, FX.tilt.rx), -FX.tilt.max, FX.tilt.max);
  const ry0 = clamp(num(e.ry, FX.tilt.ry), -FX.tilt.max, FX.tilt.max);
  const dur = clamp(num(e.dur, FX.tilt.dur), 0.3, 2);
  const s = num(e.at, appear) - LEAD.block;
  if (t >= s + dur) return {rx: 0, ry: 0, dx: 0, active: false};
  const q = EASE.outCubic(lin(t, s, s + dur));
  return {rx: rx0 * (1 - q), ry: ry0 * (1 - q), dx: -ry0 * FX.tilt.parallax * (1 - q), active: true};
};

// ------------------------------------------------------------------------------------------------ grain
/** Film-grain noise seed for a frame: changes ~24 times per second whatever the frame rate. */
export const grainSeed = (frame: number, fps: number) => Math.floor((frame / fps) * FX.grain.hz + 1e-9) % 97;
export const grainOpacity = (g: {opacity?: number} | undefined) => (g ? clamp(num(g.opacity, FX.grain.opacity), 0, FX.grain.max) : 0);

// ------------------------------------------------------------------------------------------------ photosensitivity
export type FlashEvent = {key: string; t: number};
/** Every luminance flash of the video: flash effects and light-leak transitions (in time order). */
export const flashEvents = (scenes: Pick<Scene, 'id' | 'start' | 'transition' | 'effects'>[]): FlashEvent[] => {
  const ev: FlashEvent[] = [];
  scenes.forEach((s, k) => {
    if (k > 0 && s.transition === 'light-leak') ev.push({key: `${s.id}#leak`, t: s.start});
    (s.effects ?? []).forEach((e, i) => {
      if (e.type === 'flash' && Number.isFinite(e.at)) ev.push({key: `${s.id}#${i}`, t: e.at});
    });
  });
  return ev.sort((a, b) => a.t - b.t || (a.key < b.key ? -1 : 1));
};
/** The flashes the engine may draw: chronological greedy, at most FX.photo.maxPerWindow in any FX.photo.window seconds
 *  (WCAG 2.3.1 "three flashes"). Python validation rejects storyboards that break the rule; this is the engine's guard. */
export const allowedFlashes = (scenes: Pick<Scene, 'id' | 'start' | 'transition' | 'effects'>[]): Set<string> => {
  const ok: FlashEvent[] = [];
  for (const e of flashEvents(scenes)) {
    const recent = ok.filter((x) => e.t - x.t < FX.photo.window);
    if (recent.length < FX.photo.maxPerWindow) ok.push(e);
  }
  return new Set(ok.map((x) => x.key));
};
/** Max number of flashes in any window of FX.photo.window seconds. */
export const maxFlashesPerWindow = (times: number[]) => {
  const ts = [...times].sort((a, b) => a - b);
  let best = 0;
  for (let i = 0, j = 0; i < ts.length; i++) {
    while (ts[i] - ts[j] >= FX.photo.window) j++;
    best = Math.max(best, i - j + 1);
  }
  return best;
};

/** True when a scene uses any emphasis effect (the renderer's gate: scenes without effects take the unchanged path). */
export const hasEffects = (s: Pick<Scene, 'effects'>) => Array.isArray(s.effects) && s.effects.length > 0;
