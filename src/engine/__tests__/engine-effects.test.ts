import {describe, expect, it} from 'vitest';
import {
  allowedFlashes,
  annotationPath,
  burstParticles,
  cursorState,
  drawProgress,
  EFFECT_TYPES,
  effectCamera,
  flashEvents,
  flashIntensity,
  FX,
  grainOpacity,
  grainSeed,
  hasEffects,
  maxFlashesPerWindow,
  punchScale,
  shakeOffset,
  tiltAt,
} from '../motion/effects';
import {defaultDir, FX_TRANSITIONS, FxGeo, isFxTransition, lightLeakAt, needsFxTransition, sceneTransitionFx, TR_FX} from '../motion/fx-transitions';
import {sceneTransition} from '../motion/transitions';
import {fxLayerFilter, fxLayerTransform, blockTiltTransform, usesFx} from '../effects';
import {Scene, SceneEffect, Transition} from '../types';
import v2short from '../fixtures/sample-v2-short.json';
import v2bshort from '../fixtures/sample-v2b-short.json';

const FPS = [30, 60];
const frames = (a: number, b: number, fps: number) => {
  const out: number[] = [];
  for (let f = Math.floor(a * fps); f <= Math.ceil(b * fps); f++) out.push(f / fps);
  return out;
};
const geo = (format: 'short' | 'landscape' = 'short'): FxGeo =>
  format === 'short' ? {width: 1080, height: 1920, cx: 540, cy: 900, format} : {width: 1920, height: 1080, cx: 960, cy: 520, format};

describe('emphasis effects: pure, deterministic, end at identity', () => {
  it('punch-zoom kicks to its scale on the word and settles exactly to 1', () => {
    const e = {at: 5, scale: 1.08};
    expect(punchScale(e, 4.9)).toBe(1);
    expect(punchScale(e, 5 - FX.punch.lead + FX.punch.attack)).toBeCloseTo(1.08, 6);
    for (const fps of FPS) for (const t of frames(4.8, 6, fps)) expect(punchScale(e, t)).toBe(punchScale(e, t));
    expect(punchScale(e, 5 - FX.punch.lead + FX.punch.attack + FX.punch.dur)).toBe(1);
    expect(punchScale(e, 9)).toBe(1);
    // clamped to the limits whatever the props say
    expect(punchScale({at: 1, scale: 3}, 1 - FX.punch.lead + FX.punch.attack)).toBeCloseTo(FX.punch.max, 6);
  });

  it('shake stays within 8 px, is seeded (same every run) and is exactly 0 outside its window', () => {
    const e = {at: 2, amp: 50};
    let peak = 0;
    for (const fps of FPS)
      for (const t of frames(1.9, 2.6, fps)) {
        const a = shakeOffset(e, t, 42);
        const b = shakeOffset(e, t, 42);
        expect(a).toEqual(b);
        peak = Math.max(peak, Math.hypot(a.dx, a.dy), Math.abs(a.dx));
        expect(Math.abs(a.dx)).toBeLessThanOrEqual(FX.shake.max + 1e-9);
      }
    expect(peak).toBeGreaterThan(1);
    expect(shakeOffset(e, 1.99, 42)).toEqual({dx: 0, dy: 0});
    expect(shakeOffset(e, 2 + FX.shake.dur, 42)).toEqual({dx: 0, dy: 0});
  });

  it('flash never exceeds 45 % and returns to 0', () => {
    for (const t of frames(0.8, 1.6, 60)) {
      const i = flashIntensity({at: 1, intensity: 1}, t);
      expect(i).toBeGreaterThanOrEqual(0);
      expect(i).toBeLessThanOrEqual(FX.flash.max);
    }
    expect(flashIntensity({at: 1}, 2)).toBe(0);
    expect(flashIntensity({at: 1}, 0.9)).toBe(0);
  });

  it('effect camera is the identity without active effects', () => {
    expect(effectCamera(undefined, 's', 1)).toEqual({scale: 1, dx: 0, dy: 0});
    const fx: SceneEffect[] = [{type: 'punch-zoom', at: 3}, {type: 'shake', at: 3}];
    expect(effectCamera(fx, 's', 10)).toEqual({scale: 1, dx: 0, dy: 0});
    expect(effectCamera(fx, 's', 3.05).scale).toBeGreaterThan(1);
  });

  it('burst particles are seeded, start on the ring and vanish after their life', () => {
    const e = {at: 1, count: 20};
    const a = burstParticles(e, 1.3, 7, 100);
    expect(a).toEqual(burstParticles(e, 1.3, 7, 100));
    expect(a).toHaveLength(20);
    expect(burstParticles(e, 1.3, 8, 100)).not.toEqual(a);
    const first = burstParticles(e, 1, 7, 100);
    for (const p of first) expect(Math.hypot(p.x, p.y)).toBeCloseTo(100, 6);
    expect(burstParticles(e, 0.99, 7)).toEqual([]);
    expect(burstParticles(e, 1 + FX.burst.life, 7)).toEqual([]);
  });

  it('annotations draw on from their word (never before) and hold; paths are deterministic', () => {
    const e = {at: 4};
    expect(drawProgress(e, 4 - FX.annotate.lead - 0.001)).toBe(0);
    expect(drawProgress(e, 4 - FX.annotate.lead + FX.annotate.dur)).toBe(1);
    expect(drawProgress(e, 20)).toBe(1);
    const r = {x: 100, y: 200, w: 300, h: 80};
    for (const kind of ['underline', 'circle', 'arrow'] as const) {
      const p = annotationPath(kind, r, 3, 900);
      expect(p).toEqual(annotationPath(kind, r, 3, 900));
      expect(p.d.startsWith('M ')).toBe(true);
      expect(p.d).not.toMatch(/NaN|Infinity/);
    }
    expect(annotationPath('arrow', r, 3, 900).head).toBeDefined();
    // an underline sits below the text, never on it
    const ys = annotationPath('underline', r, 3).d.match(/-?\d+\.\d+/g)!.map(Number).filter((_, i) => i % 2 === 1);
    for (const y of ys) expect(y).toBeGreaterThan(r.y + r.h - 6);
  });

  it('cursor glides in, clicks on the word (press + ripple) and is gone afterwards', () => {
    const e = {at: 10};
    const tgt = {x: 0.4, y: 0.3};
    expect(cursorState(e, tgt, 9)).toBeUndefined();
    const arrive = cursorState(e, tgt, 10 - FX.cursor.arrive)!;
    expect(arrive.x).toBeCloseTo(0.4, 6);
    expect(arrive.y).toBeCloseTo(0.3, 6);
    const click = cursorState(e, tgt, 10.05)!;
    expect(click.press).toBeGreaterThan(0);
    expect(click.ripple).not.toBeNull();
    expect(cursorState(e, tgt, 9.9)!.ripple).toBeNull();
    expect(cursorState(e, tgt, 10 + FX.cursor.linger + FX.cursor.fadeOut)).toBeUndefined();
  });

  it('tilt settles flat (identity transform string) after its duration', () => {
    expect(tiltAt({}, 1, 1).active).toBe(true);
    expect(tiltAt({}, 1 + FX.tilt.dur, 1)).toEqual({rx: 0, ry: 0, dx: 0, active: false});
    const fx: SceneEffect[] = [{type: 'tilt', target: 0}];
    expect(blockTiltTransform(fx, 0, 1.2, 1, 800, 500)).toContain('perspective(');
    expect(blockTiltTransform(fx, 0, 5, 1, 800, 500)).toBe('');
    expect(blockTiltTransform(fx, 1, 1.2, 1, 800, 500)).toBe('');
  });

  it('grain seed changes ~24×/s at any frame rate; opacity is capped', () => {
    expect(grainSeed(0, 30)).toBe(grainSeed(0, 60));
    expect(grainSeed(2, 60)).toBe(grainSeed(1, 30));
    expect(grainOpacity({opacity: 1})).toBe(FX.grain.max);
    expect(grainOpacity(undefined)).toBe(0);
  });
});

describe('photosensitivity', () => {
  const sc = (id: string, start: number, tr: Transition, effects?: SceneEffect[]) => ({id, start, end: start + 2, transition: tr, effects});
  it('allows at most 3 flashes (flash effects + light leaks) in any second', () => {
    const scenes = [sc('a', 0, 'fade', [0.1, 0.2, 0.3, 0.4, 0.5].map((at) => ({type: 'flash' as const, at}))), sc('b', 2, 'light-leak', [{type: 'flash', at: 2.1}])];
    const ok = allowedFlashes(scenes);
    const times = flashEvents(scenes).filter((e) => ok.has(e.key)).map((e) => e.t);
    expect(maxFlashesPerWindow(times)).toBeLessThanOrEqual(3);
    expect(ok.has('a#0') && ok.has('a#1') && ok.has('a#2')).toBe(true);
    expect(ok.has('a#3')).toBe(false);
    expect(ok.has('b#leak')).toBe(true);
  });
  it('a light leak peaks at ≤ 50 % and is absent away from its cut', () => {
    const scenes = [sc('a', 0, 'fade'), sc('b', 3, 'light-leak')];
    expect(lightLeakAt(scenes, 3)!.intensity).toBeCloseTo(TR_FX.leak.peak, 6);
    expect(lightLeakAt(scenes, 2)).toBeNull();
    expect(lightLeakAt(scenes, 3, new Set())).toBeNull();
  });
});

describe('effect transitions at scene boundaries', () => {
  const A = {start: 0, end: 4, transition: 'fade' as Transition};
  for (const tr of FX_TRANSITIONS)
    for (const format of ['short', 'landscape'] as const)
      for (const fps of FPS)
        it(`${tr} (${format}, ${fps} fps): the outgoing scene reaches 0 at its end, the incoming one settles to identity`, () => {
          const B = {start: 4, end: 9, transition: tr};
          const g = geo(format);
          expect(sceneTransitionFx(A, B, 4, fps, g).opacity).toBe(0);
          expect(sceneTransitionFx(A, B, 4 + 1 / fps, fps, g).opacity).toBe(0);
          expect(sceneTransitionFx(A, B, 3.5, fps, g)).toMatchObject({opacity: 1, dx: 0, dy: 0, scale: 1, blurLevel: 0, blur: 0, glitch: 0});
          // the entrance never starts before the mount window (VISIBLE_PAD.before = 0.15 s)
          expect(sceneTransitionFx(B, undefined, 4 - 0.16, fps, g).opacity).toBe(0);
          const settled = sceneTransitionFx(B, undefined, 5, fps, g);
          expect(settled).toMatchObject({opacity: 1, dx: 0, dy: 0, scale: 1, blurLevel: 0, blur: 0, glitch: 0, glitchDx: 0});
          expect(settled.mask).toBeUndefined();
          expect(fxLayerTransform(settled, {scale: 1, dx: 0, dy: 0})).toBe('');
          expect(fxLayerFilter(settled)).toBeUndefined();
          for (const t of frames(3.5, 4.6, fps)) expect(sceneTransitionFx(A, B, t, fps, g)).toEqual(sceneTransitionFx(A, B, t, fps, g));
        });

  it('the glitch lasts at most 6 frames in total, at any frame rate', () => {
    for (const fps of FPS) {
      const A2 = {start: 0, end: 4.0123, transition: 'fade' as Transition};
      const B2 = {start: 4.0123, end: 9, transition: 'glitch' as Transition};
      const n = frames(3, 5, fps).filter((t) => sceneTransitionFx(A2, B2, t, fps, geo()).glitch > 0 || sceneTransitionFx(B2, undefined, t, fps, geo()).glitch > 0).length;
      expect(n).toBeGreaterThan(0);
      expect(n).toBeLessThanOrEqual(6);
    }
  });

  it('whip-pan moves the outgoing scene along its direction with directional blur', () => {
    const B = {start: 4, end: 9, transition: 'whip-pan' as Transition, transitionDir: 'left' as const};
    const s = sceneTransitionFx(A, B, 4 - 1 / 30, 30, geo());
    expect(s.dx).toBeLessThan(-100);
    expect(s.blurLevel).toBeGreaterThan(0);
    expect(s.blurAxis).toBe('x');
    expect(defaultDir('push', 'short')).toBe('up');
    expect(defaultDir('push', 'landscape')).toBe('left');
  });

  it('classic pairs never take the effect path; classic entrances keep their exact numbers inside it', () => {
    expect(needsFxTransition({transition: 'fade'}, {transition: 'slide-up'})).toBe(false);
    expect(needsFxTransition({transition: 'fade'}, {transition: 'push'})).toBe(true);
    expect(isFxTransition('mask-wipe')).toBe(false);
    const s = {start: 2, end: 6, transition: 'slide-up' as Transition};
    for (const t of frames(1.8, 3, 30)) {
      const a = sceneTransitionFx(s, {transition: 'push'}, t, 30, geo());
      const b = sceneTransition(s, t);
      expect(a.opacity).toBeCloseTo(b.opacity, 12);
      expect(a.dy).toBeCloseTo(b.dy, 12);
    }
  });
});

describe('gate: props without effects take the unchanged path', () => {
  it('the fixtures use no effect, so no effect layer is mounted and every scene keeps the classic transition', () => {
    for (const fx of [v2short, v2bshort] as unknown as {scenes: Scene[]; theme: {grain?: unknown}}[]) {
      expect(usesFx(fx as never)).toBe(false);
      fx.scenes.forEach((s, i) => {
        expect(hasEffects(s)).toBe(false);
        expect(needsFxTransition(s, fx.scenes[i + 1])).toBe(false);
      });
    }
  });
  it('fxLayerTransform / fxLayerFilter add nothing at identity (the scene style stays byte-identical)', () => {
    expect(fxLayerTransform(undefined, undefined)).toBe('');
    expect(fxLayerTransform(undefined, {scale: 1, dx: 0, dy: 0})).toBe('');
    expect(fxLayerFilter(undefined)).toBeUndefined();
  });
});

describe('contract mirror (pipeline/effects.py)', () => {
  it('effect types, effect transitions and limits match the Python side', async () => {
    const {readFileSync} = await import('node:fs');
    const {join, resolve} = await import('node:path');
    const py = readFileSync(join(resolve(__dirname, '../../..'), 'pipeline/effects.py'), 'utf8');
    const tuple = (name: string) => [...(new RegExp(`^${name} = \\(([^)]*)\\)`, 'm').exec(py)?.[1] ?? '').matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(tuple('EFFECT_TYPES')).toEqual([...EFFECT_TYPES]);
    expect(tuple('FX_TRANSITIONS')).toEqual([...FX_TRANSITIONS]);
    expect(py).toContain(`"scale": (${FX.punch.min}, ${FX.punch.max})`);
    expect(py).toContain(`"amp": (0.0, ${FX.shake.max.toFixed(1)})`);
    expect(py).toContain(`"intensity": (0.0, ${FX.flash.max})`);
    expect(py).toContain(`PHOTO_MAX, PHOTO_WINDOW = ${FX.photo.maxPerWindow}, ${FX.photo.window.toFixed(1)}`);
  });
});
