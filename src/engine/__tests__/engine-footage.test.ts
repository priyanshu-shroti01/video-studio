import {execFileSync} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
import {collectAssetPaths, collectFootageNeedingDuration, intrinsicAspect, videoInfo} from '../assets';
import {DIMENSIONS} from '../contract';
import {AspectEnv} from '../geometry';
import {clampZoom, clipHeld, clipTime, FOOTAGE, footageNaturalW, geomFootage, seekTime, ZOOM_IDENTITY, zoomAt, zoomRect} from '../geometry-footage';
import {captionBandTop, layoutScene, measureBlock, naturalWidth} from '../layout';
import {buildManifest, withAssetAspects} from '../manifest';
import {makeEnv, planScene} from '../plan';
import {BackdropKind, Block, Camera, RenderProps, Scene} from '../types';
import fShort from '../fixtures/sample-footage-short.json';
import fLand from '../fixtures/sample-footage-landscape.json';

const ROOT = resolve(__dirname, '../../..');
const CLIP = 'shared/fixtures/footage-sample.mp4';
const readPublic = (p: string) => {
  const f = join(ROOT, 'public', p);
  return existsSync(f) ? new Uint8Array(readFileSync(f)) : undefined;
};
const withAspects = (p: RenderProps) => withAssetAspects(p, readPublic, collectAssetPaths, intrinsicAspect);
const FS = withAspects(fShort as unknown as RenderProps);
const FL = withAspects(fLand as unknown as RenderProps);
type F = Extract<Block, {type: 'footage'}>;
const footages = (p: RenderProps) => p.scenes.flatMap((s) => s.blocks).filter((b): b is F => b.type === 'footage');
const env = (aspect?: number): AspectEnv => ({logo: {onDark: 5, onLight: 5, mark: 1.7}, asset: () => aspect});
const FRAMES = ['browser', 'laptop', 'phone', 'none'] as const;

describe('footage: fixtures', () => {
  it('exercise every frame, zooms, startFrom + playbackRate and a scene longer than the clip (last-frame hold)', () => {
    const all = [...footages(FS), ...footages(FL)];
    expect(new Set(all.map((b) => b.frame))).toEqual(new Set(FRAMES));
    expect(all.some((b) => (b.zooms?.length ?? 0) >= 2)).toBe(true);
    expect(all.some((b) => (b.startFrom ?? 0) > 0 && (b.playbackRate ?? 1) !== 1)).toBe(true);
    for (const p of [FS, FL]) {
      const held = p.scenes.filter((s) => s.blocks.some((b) => b.type === 'footage' && clipHeld({...b, duration: 4}, s.end - 0.1, b.at!)));
      expect(held.length).toBeGreaterThan(0);
    }
    // the Short carries Python-style aspect + duration; the landscape fixture leaves them to the file header
    expect(footages(FS).every((b) => b.aspect === 1.6 && b.duration === 4)).toBe(true);
    expect(footages(FL).every((b) => b.aspect === undefined && b.duration === undefined)).toBe(true);
  });
});

describe('footage: clip time', () => {
  const b = {startFrom: 1, playbackRate: 0.5, duration: 4};
  it('is startFrom + (t − appear) · playbackRate', () => {
    expect(clipTime(b, 6.3, 6.3)).toBe(1);
    expect(clipTime(b, 8.3, 6.3)).toBeCloseTo(2, 12);
    expect(clipTime({}, 2.4, 0.3)).toBeCloseTo(2.1, 12);
    expect(clipTime({playbackRate: 2}, 1.3, 0.3)).toBeCloseTo(2, 12);
  });
  it('holds the first frame before the block appears and the last frame after the clip ends', () => {
    expect(clipTime(b, 0, 6.3)).toBe(1);
    expect(clipTime(b, 100, 6.3)).toBe(4 - FOOTAGE.endEps);
    expect(clipHeld(b, 100, 6.3)).toBe(true);
    expect(clipHeld(b, 7, 6.3)).toBe(false);
    for (let t = 0; t < 30; t += 1 / 30) {
      const ct = seekTime(b, t, 6.3);
      expect(ct).toBeLessThan(4);
      expect(ct).toBeGreaterThanOrEqual(1);
    }
  });
  it('is monotonic, advances by playbackRate / fps per frame while playing, and ignores bad rates / offsets', () => {
    let prev = -1;
    for (let f = 0; f < 300; f++) {
      const ct = clipTime({playbackRate: 1.5, duration: 4}, f / 30, 1);
      expect(ct).toBeGreaterThanOrEqual(prev);
      if (ct > 0 && ct < 4 - FOOTAGE.endEps && prev > 0) expect(ct - prev).toBeCloseTo(1.5 / 30, 9);
      prev = ct;
    }
    expect(clipTime({playbackRate: 0, startFrom: -3}, 2, 1)).toBe(1);
    expect(clipTime({playbackRate: Number.NaN}, 2, 1)).toBe(1);
  });
  it('requests frame-boundary times slightly late so they resolve to the intended frame', () => {
    for (let k = 0; k < 120; k++) expect(Math.floor(seekTime({duration: 4}, (k + 9) / 30, 9 / 30) * 30 + 1e-9)).toBe(k);
  });
});

describe('footage: zoom', () => {
  it('clamps every keyframe inside the clip (scale 1..zoomMax, centre ≥ ½/scale from each edge)', () => {
    expect(clampZoom({x: 0, y: 1, scale: 2})).toEqual({x: 0.25, y: 0.75, scale: 2});
    expect(clampZoom({x: 0.9, y: 0.1, scale: 0.4})).toEqual({x: 0.5, y: 0.5, scale: 1});
    expect(clampZoom({x: 0.5, y: 0.5, scale: 99}).scale).toBe(FOOTAGE.zoomMax);
  });
  const zooms = [
    {at: 1.5, x: 0.08, y: 0.04, scale: 2.5},
    {at: 3.0, x: 0.6, y: 0.75, scale: 1.6},
    {at: 3.3, x: 1, y: 1, scale: 4}, // a keyframe soon after the previous one cuts that move short
    {at: 4.6, x: 0.5, y: 0.5, scale: 1},
  ];
  it('starts from the whole clip, eases to each keyframe from at − LEAD over zoomMove and settles exactly on it', () => {
    expect(zoomAt(zooms, 0)).toEqual(ZOOM_IDENTITY);
    expect(zoomAt(zooms, 1.44)).toEqual(ZOOM_IDENTITY);
    expect(zoomAt(zooms, 1.45 + FOOTAGE.zoomMove)).toEqual(clampZoom(zooms[0]));
    expect(zoomAt(zooms, 3.25)).toEqual(clampZoom(zooms[1]));
    expect(zoomAt(zooms, 20)).toEqual(ZOOM_IDENTITY);
    expect(zoomAt(undefined, 3)).toEqual(ZOOM_IDENTITY);
  });
  it('is smooth (no jump between frames) and never shows an empty edge, for any viewport', () => {
    let prev = zoomAt(zooms, 0);
    for (let f = 1; f < 7 * 120; f++) {
      const t = f / 120;
      const z = zoomAt(zooms, t);
      // per 1/120 s step: at most ~1.5 × (distance / move time) / 120 (inOutCubic peak slope), even for the cut-short move
      expect(Math.abs(z.x - prev.x)).toBeLessThan(0.04);
      expect(Math.abs(z.y - prev.y)).toBeLessThan(0.04);
      expect(Math.abs(Math.log(z.scale / prev.scale))).toBeLessThan(0.05);
      // the unclamped placement already covers the viewport (the rect clamp in zoomRect is only a float guard)
      const half = 0.5 / z.scale;
      expect(z.x).toBeGreaterThanOrEqual(half - 1e-9);
      expect(z.x).toBeLessThanOrEqual(1 - half + 1e-9);
      expect(z.y).toBeGreaterThanOrEqual(half - 1e-9);
      expect(z.y).toBeLessThanOrEqual(1 - half + 1e-9);
      for (const [w, h] of [[936, 585], [400, 820]]) {
        const r = zoomRect(z, w, h);
        expect(r.x).toBeLessThanOrEqual(1e-9);
        expect(r.y).toBeLessThanOrEqual(1e-9);
        expect(r.x + r.w).toBeGreaterThanOrEqual(w - 1e-9);
        expect(r.y + r.h).toBeGreaterThanOrEqual(h - 1e-9);
        expect(r.w / r.h).toBeCloseTo(w / h, 9); // never distorted
      }
      prev = z;
    }
  });
  it('puts the focus point in the middle of the viewport when it is not clamped', () => {
    const r = zoomRect({x: 0.5, y: 0.6, scale: 2}, 1000, 600);
    expect(r.x + 0.5 * r.w).toBeCloseTo(500, 9);
    expect(r.y + 0.6 * r.h).toBeCloseTo(300, 9);
  });
});

describe('footage: geometry + layout', () => {
  const block = (frame: F['frame'], extra: Partial<F> = {}): F => ({type: 'footage', asset: CLIP, frame, ...extra});

  it('the clip viewport always has the clip aspect (box follows the clip; never distorted)', () => {
    for (const aspect of [16 / 10, 16 / 9, 4 / 3, 1, 9 / 16, 9 / 19.5])
      for (const frame of FRAMES)
        for (const w of [300, 400, 760, 940, 1300]) {
          const g = geomFootage(block(frame, {aspect}), w, env());
          expect(g.screen.w / g.screen.h).toBeCloseTo(aspect, 9);
          expect(g.screen.x).toBeGreaterThanOrEqual(0);
          expect(g.screen.x + g.screen.w).toBeLessThanOrEqual(w + 1e-9);
          expect(g.screen.y + g.screen.h).toBeLessThanOrEqual(g.h + 1e-9);
          expect(measureBlock(block(frame, {aspect}), w, env())).toBe(g.h);
        }
  });

  it('aspect: block field, else the file header (assetAspects), else 16:9', () => {
    expect(geomFootage(block('none', {aspect: 2}), 900, env(1.25)).aspect).toBe(2);
    expect(geomFootage(block('none'), 900, env(1.25)).aspect).toBe(1.25);
    expect(geomFootage(block('none'), 900, env()).aspect).toBeCloseTo(16 / 9, 12);
    expect(geomFootage(block('none', {aspect: -1}), 900, env(1.25)).aspect).toBe(1.25);
  });

  it('natural width: wide clips fill the column, tall clips get a narrower box under the height cap', () => {
    // a 1.6 clip is bounded by the clip-height cap, not a fixed width; the 940-unit Short column caps it there
    const wide = footageNaturalW(block('browser', {aspect: 1.6}), env());
    expect(wide).toBeCloseTo(FOOTAGE.maxH.browser * 1.6 + 2 * FOOTAGE.border, 6);
    expect(wide).toBeGreaterThan(940);
    expect(naturalWidth(block('browser', {aspect: 1.6}), 2000, env())).toBeCloseTo(wide, 6);
    const tall = footageNaturalW(block('browser', {aspect: 9 / 16}), env());
    expect(tall).toBeLessThan(500);
    expect(geomFootage(block('browser', {aspect: 9 / 16}), tall, env()).screen.h).toBeCloseTo(FOOTAGE.maxH.browser, 6);
    expect(footageNaturalW(block('phone', {aspect: 9 / 19.5}), env())).toBe(FOOTAGE.naturalW.phone);
    expect(footageNaturalW(block('phone', {aspect: 1.6}), env())).toBeGreaterThan(FOOTAGE.naturalW.phone); // landscape phone
  });

  it('landscape splitRatio gives a recording a wide column beside its message; Shorts ignore it', () => {
    const blocks = [block('browser', {aspect: 1.6}), {type: 'pill', text: 'Recorded in the real app', at: 0} as unknown as Block];
    const cap = {enabled: true, bottomFrac: 0.07, fontSize: 52};   // the production default for 16:9
    const lay = (format: 'short' | 'landscape', extra: Partial<Scene>) =>
      layoutScene({layout: 'stack', blocks, ...extra} as Scene, format, cap, true, env(1.6), {hero: true});
    const stacked = lay('landscape', {});
    const split = lay('landscape', {layout: 'split', splitAt: 1, splitRatio: 0.66});
    const even = lay('landscape', {layout: 'split', splitAt: 1});
    expect(split.boxes[0].w).toBeGreaterThan(stacked.boxes[0].w * 1.1);     // the recording grows
    expect(split.boxes[0].w).toBeGreaterThan(even.boxes[0].w);
    expect(split.boxes[1].x).toBeGreaterThanOrEqual(split.boxes[0].x + split.boxes[0].w);   // message to its right
    expect(split.boxes[1].x + split.boxes[1].w).toBeLessThanOrEqual(DIMENSIONS.landscape.width - split.side + 1e-6);
    expect(split.boxes[0].y + split.boxes[0].h).toBeLessThanOrEqual(split.bottom + 1e-6);
    // the message column keeps its natural width: a long pill is never squeezed below it
    const longPill = {type: 'pill', text: 'A considerably longer message that needs room', at: 0} as unknown as Block;
    const L2 = layoutScene({layout: 'split', splitAt: 1, splitRatio: 0.7, blocks: [blocks[0], longPill]} as Scene, 'landscape', cap, true,
      env(1.6), {hero: true});
    expect(L2.boxes[1].w).toBeGreaterThan((1640 - 90) * 0.3 + 1);
    expect(L2.boxes[0].x + L2.boxes[0].w).toBeLessThanOrEqual(L2.boxes[1].x);
    const clamped = lay('landscape', {layout: 'split', splitAt: 1, splitRatio: 0.95});
    expect(clamped.boxes[1].w).toBeGreaterThan(0);                            // ratio clamped to 0.3–0.7
    expect(lay('short', {layout: 'split', splitAt: 1, splitRatio: 0.66}).boxes).toEqual(lay('short', {}).boxes);
    expect(lay('short', {}).boxes[0].w).toBe(940);                             // the Short column still caps it
  });

  it('fits both formats, wide and tall clips, alone / crowded / split, every camera and backdrop', () => {
    for (const p of [FS, FL]) {
      const {width} = DIMENSIONS[p.format];
      const band = captionBandTop(p.format, p.captions);
      for (const aspect of [16 / 10, 9 / 16, 9 / 19.5, 21 / 9])
        for (const frame of FRAMES)
          for (const camera of ['none', 'push-in', 'drift'] as Camera[])
            for (const backdrop of ['glow', 'split', 'light'] as BackdropKind[]) {
              const b = block(frame, {aspect, caption: 'A caption under the clip', title: frame === 'browser' ? 'A page title' : undefined});
              const base: Scene = {id: 'x', purpose: 'custom', start: 1, end: 4, transition: 'fade', layout: 'stack', camera, backdrop, blocks: [b]};
              for (const scene of [
                base,
                {...base, blocks: [{type: 'headline', size: 'l', words: [{text: 'Real'}, {text: 'footage'}]} as Block, b]},
                {...base, layout: 'split' as const, blocks: [{type: 'kinetic-text', words: [{text: 'Look'}]} as Block, b]},
              ]) {
                const P = planScene(makeEnv(p), scene);
                for (const box of P.layout.boxes) {
                  expect(box.y + box.h + P.reserve.y).toBeLessThanOrEqual(band + 1e-6);
                  expect(box.y - P.reserve.y).toBeGreaterThanOrEqual(0);
                  expect(box.x - P.reserve.x).toBeGreaterThanOrEqual(0);
                  expect(box.x + box.w + P.reserve.x).toBeLessThanOrEqual(width + 1e-6);
                }
              }
            }
    }
  });
});

describe('footage: layout manifest', () => {
  it('reports the clip viewport as a media box with the clip aspect, and the title / caption texts', () => {
    for (const p of [FS, FL]) {
      const m = buildManifest(p);
      const blocks = m.scenes.flatMap((s) => s.blocks).filter((b) => b.type === 'footage');
      expect(blocks.length).toBe(3);
      for (const b of blocks) {
        expect(b.media).toHaveLength(1);
        const md = b.media![0];
        expect(md.role).toBe('media');
        expect(md.asset).toBe(CLIP);
        expect(md.expectedAspect).toBe(1.6);
        expect(Math.abs(md.aspect - md.expectedAspect)).toBeLessThan(0.002);
        expect(md.bbox.x).toBeGreaterThanOrEqual(b.bbox.x - 0.01);
        expect(md.bbox.x + md.bbox.w).toBeLessThanOrEqual(b.bbox.x + b.bbox.w + 0.01);
        expect(md.bbox.y + md.bbox.h).toBeLessThanOrEqual(b.bbox.y + b.bbox.h + 0.01);
        for (const t of b.texts) {
          expect(t.overflow).toBe(false);
          expect(['title', 'caption']).toContain(t.role);
        }
      }
      const roles = blocks.flatMap((b) => b.texts.map((t) => `${t.role}:${t.text}`));
      expect(roles).toContain('title:Sample recording');
      expect(roles).toContain('caption:The last frame holds');
      // other blocks carry no `media` key (existing manifests are unchanged)
      for (const b of m.scenes.flatMap((s) => s.blocks).filter((x) => x.type !== 'footage')) expect('media' in b).toBe(false);
    }
  });

  it('scripts/engine-layout.mjs prints exactly the in-process manifest for the footage fixtures', () => {
    for (const f of ['sample-footage-short.json', 'sample-footage-landscape.json']) {
      const file = join(ROOT, 'src/engine/fixtures', f);
      const out = JSON.parse(execFileSync('node', [join(ROOT, 'scripts/engine-layout.mjs'), file], {encoding: 'utf8'}));
      expect(out).toEqual(JSON.parse(JSON.stringify(buildManifest(withAspects(JSON.parse(readFileSync(file, 'utf8')) as RenderProps)))));
    }
  });
});

describe('footage: video headers', () => {
  it('reads display size + duration from the MP4 fixture (moov › trak › tkhd / mdhd)', () => {
    const bytes = readPublic(CLIP)!;
    const v = videoInfo(bytes)!;
    expect([v.width, v.height]).toEqual([1280, 800]);
    expect(v.aspect).toBe(1.6);
    expect(v.duration).toBeCloseTo(4, 6);
    expect(intrinsicAspect(bytes, CLIP)).toBe(1.6);
    expect(videoInfo(new Uint8Array([0x89, 0x50, 0x4e, 0x47]))).toBeUndefined();
  });

  it('reads WebM (EBML) and rotated MP4 headers', () => {
    const dir = mkdtempSync(join(tmpdir(), 'footage-'));
    try {
      const ff = (...a: string[]) => execFileSync('ffmpeg', ['-v', 'error', '-y', ...a]);
      ff('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=1.5', '-c:v', 'libvpx-vp9', '-b:v', '100k', join(dir, 'a.webm'));
      const w = videoInfo(new Uint8Array(readFileSync(join(dir, 'a.webm'))))!;
      expect([w.width, w.height]).toEqual([320, 180]);
      expect(w.duration).toBeCloseTo(1.5, 1);
      ff('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-metadata:s:v', 'rotate=90', join(dir, 'r.mp4'));
      ff('-display_rotation', '90', '-i', join(dir, 'r.mp4'), '-c', 'copy', join(dir, 'r2.mp4'));
      const r = videoInfo(new Uint8Array(readFileSync(join(dir, 'r2.mp4'))))!;
      expect(r.aspect).toBeCloseTo(180 / 320, 6);
    } finally {
      rmSync(dir, {recursive: true, force: true});
    }
  });

  it('only footage without aspect / duration is read (the pipeline fills both, so production never reads videos)', () => {
    expect(collectAssetPaths(fShort as unknown as RenderProps)).not.toContain(CLIP);
    expect(collectAssetPaths(fLand as unknown as RenderProps)).toContain(CLIP);
    expect(collectFootageNeedingDuration(fShort as unknown as RenderProps)).toEqual([]);
    expect(collectFootageNeedingDuration(fLand as unknown as RenderProps)).toEqual([CLIP]);
  });
});
