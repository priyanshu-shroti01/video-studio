import {existsSync, readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
import {collectAssetPaths, intrinsicAspect} from '../assets';
import {DIMENSIONS} from '../contract';
import {AspectEnv} from '../geometry';
import {
  activeCallouts,
  baseWindow,
  calloutLife,
  calloutRects,
  calloutSettled,
  calloutWindows,
  clampZoom,
  FOOTAGE,
  footageFit,
  geomFootage,
  regionZoom,
  zoomAt,
  zoomRect,
  zoomSettleTimes,
  zoomTarget,
} from '../geometry-footage';
import {captionBandTop} from '../layout';
import {buildManifest, withAssetAspects} from '../manifest';
import {LEAD} from '../motion/durations';
import {makeEnv, planScene} from '../plan';
import {Block, RenderProps, Scene} from '../types';
import fShort from '../fixtures/sample-footage-short.json';
import fLand from '../fixtures/sample-footage-landscape.json';

const ROOT = resolve(__dirname, '../../..');
const readPublic = (p: string) => {
  const f = join(ROOT, 'public', p);
  return existsSync(f) ? new Uint8Array(readFileSync(f)) : undefined;
};
const withAspects = (p: RenderProps) => withAssetAspects(p, readPublic, collectAssetPaths, intrinsicAspect);
const FS = withAspects(fShort as unknown as RenderProps);
const FL = withAspects(fLand as unknown as RenderProps);
type F = Extract<Block, {type: 'footage'}>;
const A = 1.415; // the -v2 Studio recordings (2716 × 1920)
const env = (format: 'short' | 'landscape', aspect = A): AspectEnv => ({logo: {onDark: 5, onLight: 5, mark: 1.7}, asset: () => aspect, format});
const fill = (extra: Partial<F> = {}): F => ({type: 'footage', asset: 'shared/fixtures/footage-sample.mp4', aspect: A, frame: 'browser', fit: {short: 'fill'}, title: 'A page', at: 1, ...extra});

/** The normalised window of the clip shown for view z in a w × h viewport (from the drawn rect). */
const shown = (z: {x: number; y: number; scale: number}, w: number, h: number, a: number) => {
  const r = zoomRect(z, w, h, a);
  return {x0: -r.x / r.w, y0: -r.y / r.h, x1: (w - r.x) / r.w, y1: (h - r.y) / r.h, r};
};

describe('footage fill: fit per format', () => {
  it("resolves 'frame' | 'fill' | {short, landscape} (default frame)", () => {
    expect(footageFit({}, 'short')).toBe('frame');
    expect(footageFit({fit: 'fill'}, 'landscape')).toBe('fill');
    expect(footageFit({fit: {short: 'fill'}}, 'short')).toBe('fill');
    expect(footageFit({fit: {short: 'fill'}}, 'landscape')).toBe('frame');
    expect(footageFit({fit: {short: 'fill'}}, undefined)).toBe('frame');
  });
  it('drops the chrome and the title; Short viewport at fillAspectShort, 16:9 at the clip aspect', () => {
    const gs = geomFootage(fill(), 940, env('short'));
    expect(gs.fit).toBe('fill');
    expect(gs.screen).toEqual({x: 0, y: 0, w: 940, h: 940 / FOOTAGE.fillAspectShort});
    expect(gs.title).toBeUndefined();
    expect(gs.texts).toHaveLength(0);
    expect(gs.win.w).toBeCloseTo(FOOTAGE.fillAspectShort / A, 9); // a cover crop: part of the width, all the height
    expect(gs.win.h).toBe(1);
    const gl = geomFootage(fill({fit: 'fill'}), 1000, env('landscape'));
    expect(gl.screen.w / gl.screen.h).toBeCloseTo(A, 9);
    expect(gl.win).toEqual({w: 1, h: 1});
    // frame fit is unchanged
    const gf = geomFootage(fill({fit: undefined}), 940, env('short'));
    expect(gf.fit).toBe('frame');
    expect(gf.title?.text).toBe('A page');
    expect(gf.win).toEqual({w: 1, h: 1});
  });
  it('fits the Short and 16:9 safe areas, alone and with a message', () => {
    for (const p of [FS, FL]) {
      const {width} = DIMENSIONS[p.format];
      const band = captionBandTop(p.format, p.captions);
      const b = fill({fit: 'fill'});
      const base: Scene = {id: 'x', purpose: 'custom', start: 1, end: 4, transition: 'fade', layout: 'stack', camera: 'none', backdrop: 'glow', blocks: [b]};
      for (const scene of [base, {...base, blocks: [b, {type: 'pill', text: 'Recorded in the real app'} as Block]}]) {
        const P = planScene(makeEnv(p), scene);
        for (const box of P.layout.boxes) {
          expect(box.y + box.h + P.reserve.y).toBeLessThanOrEqual(band + 1e-6);
          expect(box.x + box.w + P.reserve.x).toBeLessThanOrEqual(width + 1e-6);
        }
      }
    }
  });
});

describe('footage fill: crop window driven by the zooms', () => {
  const W = 940;
  const H = 940 / FOOTAGE.fillAspectShort;
  const win = baseWindow(A, W / H);
  it('scale 1 is the cover crop: covers the viewport, keeps the clip aspect, shows the full height', () => {
    const s = shown({x: 0.5, y: 0.5, scale: 1}, W, H, A);
    expect(s.r.w / s.r.h).toBeCloseTo(A, 9);
    expect(s.y0).toBeCloseTo(0, 9);
    expect(s.y1).toBeCloseTo(1, 9);
    expect(s.x1 - s.x0).toBeCloseTo(win.w, 9);
  });
  it('clamps per axis so every keyframe and every in-between view stays inside the clip (no empty edge)', () => {
    expect(clampZoom({x: 0, y: 0, scale: 1}, win)).toEqual({x: win.w / 2, y: 0.5, scale: 1});
    const zooms = [
      {at: 1, x: 0, y: 0, scale: 1.3},
      {at: 2, x: 1, y: 1, scale: 3.5},
      {at: 2.3, x: 0.2, y: 0.9, scale: 9},
      {at: 4, x: 0.5, y: 0.5, scale: 1, region: {x: 0.9, y: 0.02, w: 0.08, h: 0.04}},
    ];
    for (let f = 0; f < 6 * 120; f++) {
      const z = zoomAt(zooms, f / 120, win);
      const s = shown(z, W, H, A);
      expect(s.x0).toBeGreaterThanOrEqual(-1e-9);
      expect(s.y0).toBeGreaterThanOrEqual(-1e-9);
      expect(s.x1).toBeLessThanOrEqual(1 + 1e-9);
      expect(s.y1).toBeLessThanOrEqual(1 + 1e-9);
      // the unclamped placement already covers (zoomRect's clamp is only a float guard)
      expect(z.x - win.w / (2 * z.scale)).toBeGreaterThanOrEqual(-1e-9);
      expect(z.y + win.h / (2 * z.scale)).toBeLessThanOrEqual(1 + 1e-9);
    }
  });
  it('a region beat frames the named element: centred, fully in view, as close as the margin allows', () => {
    const r = {x: 0.4, y: 0.3, w: 0.25, h: 0.1};
    for (const [w, h, a] of [[W, H, A], [1000, 1000 / A, A]] as const) {
      const wn = baseWindow(a, w / h);
      const z = regionZoom(r, wn);
      expect(z.x).toBeCloseTo(0.525, 9);
      expect(z.y).toBeCloseTo(0.35, 9);
      const s = shown(z, w, h, a);
      expect(s.x0).toBeLessThanOrEqual(r.x + 1e-9);
      expect(s.x1).toBeGreaterThanOrEqual(r.x + r.w - 1e-9);
      expect(s.y0).toBeLessThanOrEqual(r.y + 1e-9);
      expect(s.y1).toBeGreaterThanOrEqual(r.y + r.h - 1e-9);
      // exactly the margin on the tighter axis
      expect(Math.max(r.w / (s.x1 - s.x0), r.h / (s.y1 - s.y0))).toBeCloseTo(1 / FOOTAGE.regionMargin, 6);
    }
    // stronger than a hand-set scale for a small element; the hand-set scale is ignored when a region is given
    expect(zoomTarget({x: 0.525, y: 0.35, scale: 1.2, region: r}, win).scale).toBeGreaterThan(1.2);
    // limits: zoomMax for a tiny element, 1 for one larger than the window; a region at the edge is clamped inside
    expect(regionZoom({x: 0.5, y: 0.5, w: 0.01, h: 0.01}, win).scale).toBe(FOOTAGE.zoomMax);
    expect(regionZoom({x: 0, y: 0, w: 1, h: 0.9}, win).scale).toBe(1);
    const edge = regionZoom({x: 0.95, y: 0.96, w: 0.05, h: 0.04}, win);
    expect(edge).toEqual(clampZoom(edge, win));
    // invalid regions fall back to the keyframe's own centre and scale
    expect(zoomTarget({x: 0.3, y: 0.4, scale: 2, region: {x: 0, y: 0, w: 0, h: 0.1}})).toEqual(clampZoom({x: 0.3, y: 0.4, scale: 2}));
  });
  it('reports settle times (the end of each zoom move) for QA sampling', () => {
    expect(zoomSettleTimes([{at: 3, x: 0, y: 0, scale: 2}, {at: 1, x: 0, y: 0, scale: 2}, {at: 1.3, x: 0, y: 0, scale: 2}])).toEqual([1.25, 1.25 + FOOTAGE.zoomMove, 3 - LEAD.block + FOOTAGE.zoomMove]);
  });
});

describe('footage callouts ("zoom lens")', () => {
  const cs = [
    {at: 2, x: 0.1, y: 0.1, w: 0.2, h: 0.06},
    {at: 4, x: 0.6, y: 0.8, w: 0.3, h: 0.1, hold: 1},
    {at: 7, x: 0.3, y: 0.3, w: 0.1, h: 0.05},
  ];
  it('is anchored on its word: pops in from at − LEAD.block, stays until the next callout / hold / block end', () => {
    const ws = calloutWindows(cs, 9);
    expect(ws.map((w) => [w.from, w.to])).toEqual([[2 - LEAD.block, 4 - LEAD.block], [4 - LEAD.block, 5], [7 - LEAD.block, 9]]);
    expect(calloutLife(ws[0], 2 - LEAD.block - 0.01)).toBe(0);
    expect(calloutLife(ws[0], 2 - LEAD.block + FOOTAGE.callout.pop)).toBe(1);
    expect(calloutLife(ws[0], 4 - LEAD.block)).toBe(0);
    expect(calloutLife(ws[1], 5 - FOOTAGE.callout.out / 2)).toBeCloseTo(0.5, 9);
    // the next zoom beat after a callout replaces the lens; a zoom at the callout's own word does not
    const wz = calloutWindows(cs, 9, [{at: 2, x: 0.5, y: 0.5, scale: 1.5}, {at: 3, x: 0.5, y: 0.5, scale: 1}]);
    expect(wz[0].to).toBeCloseTo(3 - LEAD.block, 9);
    // invalid regions are dropped
    expect(calloutWindows([{at: 1, x: 0, y: 0, w: 0, h: 1}])).toHaveLength(0);
  });
  it('panel: inside the viewport, region aspect, magnified, in the half away from its source, connector between', () => {
    for (const [w, h, a, fmt] of [[940, 940 / FOOTAGE.fillAspectShort, A, 'short'], [1000, 1000 / A, A, 'landscape']] as const) {
      const wn = baseWindow(a, w / h);
      for (const z of [{x: 0.5, y: 0.5, scale: 1}, regionZoom({x: 0.1, y: 0.1, w: 0.4, h: 0.3}, wn)]) {
        for (const c of [cs[0], cs[1], {at: 1, x: 0.4, y: 0.45, w: 0.2, h: 0.08}]) {
          const v = clampZoom(z, wn);
          const k = calloutRects(c, v, w, h, a);
          const m = FOOTAGE.callout.inset * Math.min(w, h) - 1e-9;
          expect(k.panel.x).toBeGreaterThanOrEqual(m);
          expect(k.panel.y).toBeGreaterThanOrEqual(m);
          expect(k.panel.x + k.panel.w).toBeLessThanOrEqual(w - m + 2e-9);
          expect(k.panel.y + k.panel.h).toBeLessThanOrEqual(h - m + 2e-9);
          expect(k.panel.w / k.panel.h).toBeCloseTo((c.w / c.h) * a, 6);
          expect(k.panel.w).toBeLessThanOrEqual(w * FOOTAGE.callout.maxW + 1e-9);
          expect(k.panel.h).toBeLessThanOrEqual(h * FOOTAGE.callout.maxH + 1e-9);
          expect(k.mag).toBeGreaterThan(1.2);
          const scy = k.src.y + k.src.h / 2;
          if (scy > 0 && scy < h) expect(k.below ? k.panel.y >= h / 2 - 1e-9 || k.panel.y >= scy : k.panel.y + k.panel.h <= h / 2 + 1e-9 || k.panel.y + k.panel.h <= scy).toBe(true);
          expect(k.connector.to.y).toBeCloseTo(k.below ? k.panel.y : k.panel.y + k.panel.h, 9);
          void fmt;
        }
      }
    }
  });
  it('skips a callout that would not magnify its source (a lens no bigger than the view already shows)', () => {
    const W = 940;
    const H = 940 / FOOTAGE.fillAspectShort;
    const win = {...baseWindow(A, W / H), min: FOOTAGE.fillMinScale};
    const b = {zooms: [{at: 1, x: 0.5, y: 0.5, scale: 1}], callouts: [{at: 1, x: 0.05, y: 0.4, w: 0.9, h: 0.12}, {at: 2, x: 0.3, y: 0.3, w: 0.1, h: 0.05}]};
    const act = activeCallouts(b, W, H, A, win);
    expect(act).toHaveLength(1);
    expect(act[0].c.at).toBe(2);
    expect(act[0].rects.mag).toBeGreaterThanOrEqual(FOOTAGE.callout.minMag);
    // the 9:16 fill never shows the crop below fillMinScale, also before the first beat
    expect(zoomAt(b.zooms, 0, win).scale).toBe(FOOTAGE.fillMinScale);
    expect(zoomAt(b.zooms, 5, win).scale).toBe(FOOTAGE.fillMinScale);
  });
  it('the manifest reports settled panels and zoom settle times; a fill viewport is a crop, not a distortion', () => {
    const b = fill({at: 1.2, zooms: [{at: 1.5, x: 0.5, y: 0.5, scale: 1, region: {x: 0.2, y: 0.2, w: 0.3, h: 0.1}}], callouts: [{at: 2.2, x: 0.6, y: 0.7, w: 0.25, h: 0.08}]});
    for (const p of [FS, FL]) {
      const scene: Scene = {id: 'f', purpose: 'custom', start: 1, end: 4, transition: 'fade', layout: 'stack', camera: 'none', backdrop: 'glow', blocks: [b]};
      const m = buildManifest({...p, scenes: [scene], durationInFrames: 4 * p.fps});
      const md = m.scenes[0].blocks[0].media![0];
      expect(md.settle).toEqual([+(1.5 - LEAD.block + FOOTAGE.zoomMove).toFixed(3)]);
      expect(md.callouts).toHaveLength(1);
      const c = md.callouts![0];
      expect(c.from).toBeCloseTo(2.2 - LEAD.block, 3);
      expect(c.bbox.x).toBeGreaterThanOrEqual(md.bbox.x);
      expect(c.bbox.y + c.bbox.h).toBeLessThanOrEqual(md.bbox.y + md.bbox.h + 0.01);
      expect(Math.abs(md.aspect - md.expectedAspect)).toBeLessThan(0.002);
      if (p.format === 'short') {
        expect(md.fit).toBe('fill');
        expect(md.clipAspect).toBeCloseTo(A, 3);
        expect(md.expectedAspect).toBeCloseTo(FOOTAGE.fillAspectShort, 2);
      } else expect(md.fit).toBeUndefined();
      // the settled panel equals the geometry's own
      const g = geomFootage(b, m.scenes[0].blocks[0].bbox.w / (m.scenes[0].blocks[0].bbox.w / (md.bbox.w)), {...makeEnv(p).aspects});
      expect(calloutSettled(b, b.callouts![0], g.screen.w, g.screen.h, g.aspect, g.win).mag).toBeGreaterThan(1);
    }
  });
});
