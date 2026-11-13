import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {Easing} from 'remotion';
import {describe, expect, it} from 'vitest';
import {collectAssetPaths, intrinsicAspect, svgAspect} from '../assets';
import {aspectEnv, planWatermark, watermarkFactor, WATERMARK_DEFAULTS} from '../branding';
import {assertContract, DIMENSIONS} from '../contract';
import {captionBandTop, layoutScene, MARK_ASPECT} from '../layout';
import {buildManifest, withAssetAspects} from '../manifest';
import {ACCENT, LEAD} from '../motion/durations';
import {EASE, SPRING} from '../motion/easings';
import {blockEntrance} from '../motion/entrances';
import {MOTION_PRESETS} from '../motion/presets';
import {cameraAt, cameraReserve, sceneTransition} from '../motion/transitions';
import {estimateTextWidth} from '../motion/typography';
import {makeEnv, planScene} from '../plan';
import {Block, BlockV2, Camera, Format, RenderProps, Scene, Transition} from '../types';
import sampleShort from '../fixtures/sample-short.json';
import sampleLandscape from '../fixtures/sample-landscape.json';
import v2Short from '../fixtures/sample-v2-short.json';
import v2Land from '../fixtures/sample-v2-landscape.json';

const ROOT = resolve(__dirname, '../../..');
const readPublic = (p: string) => {
  const f = join(ROOT, 'public', p);
  return existsSync(f) ? new Uint8Array(readFileSync(f)) : undefined;
};
const withAspects = (p: RenderProps) => withAssetAspects(p, readPublic, collectAssetPaths, intrinsicAspect);
const V1S = sampleShort as unknown as RenderProps;
const V1L = sampleLandscape as unknown as RenderProps;
const V2S = withAspects(v2Short as unknown as RenderProps);
const V2L = withAspects(v2Land as unknown as RenderProps);

const NEW_TYPES: BlockV2['type'][] = [
  'kinetic-text', 'counter', 'price-compare', 'terminal', 'dashboard', 'device', 'image', 'progress', 'scroll-demo', 'chart',
  'feature-compare', 'logo-sting', 'outro',
];

describe('motion tokens', () => {
  it('easing curves are bit-identical to Remotion Easing (v1 output unchanged)', () => {
    for (let i = 0; i <= 200; i++) {
      const x = i / 200;
      expect(EASE.outCubic(x)).toBe(Easing.out(Easing.cubic)(x));
      expect(EASE.inOutCubic(x)).toBe(Easing.inOut(Easing.cubic)(x));
      expect(EASE.outQuad(x)).toBe(Easing.out(Easing.quad)(x));
      expect(EASE.inOutSine(x)).toBe(Easing.inOut(Easing.sin)(x));
    }
  });

  it("'standard' preset carries exactly the v1 numbers", () => {
    const m = MOTION_PRESETS.standard;
    expect(m.entrance).toEqual({spring: {damping: 15, mass: 0.8}, offsetY: 40, opacityGain: 1.4, scaleFrom: 1});
    expect(m.word).toEqual({spring: {damping: 13, mass: 0.6}, stagger: 0.08, ctaStagger: 0.12, rise: 0.33});
    expect(m.row.spring).toEqual(SPRING.row);
    expect(m.motionBlur).toBe(0);
    expect(m.focusPull).toBe(0);
    expect(LEAD.block).toBe(0.05);
    expect(ACCENT.strike).toBe(0.35);
  });

  it('presets change shape, never cue timing: every entrance is 0 before appear-LEAD and settles to 1', () => {
    for (const m of Object.values(MOTION_PRESETS)) {
      expect(blockEntrance(9.94, 10, 30, m).p).toBe(0);
      expect(blockEntrance(9.94, 10, 30, m).opacity).toBe(0);
      const settled = blockEntrance(13, 10, 30, m);
      expect(settled.p).toBeCloseTo(1, 2);
      expect(Math.abs(settled.dy)).toBeLessThan(1);
      // deterministic
      expect(blockEntrance(10.1, 10, 30, m)).toEqual(blockEntrance(10.1, 10, 30, m));
    }
    expect(blockEntrance(10.05, 10, 30, MOTION_PRESETS.standard).blurY).toBe(0);
    const levels = Array.from({length: 20}, (_, i) => blockEntrance(9.95 + i / 30, 10, 30, MOTION_PRESETS.energetic, 1).blurY);
    expect(Math.max(...levels)).toBeGreaterThan(0);
    expect(levels[levels.length - 1]).toBe(0);
  });

  it('every scene transition is gone exactly at scene.end and full mid-scene', () => {
    const s = {start: 2, end: 6};
    for (const tr of ['fade', 'slide-up', 'none', 'mask-wipe', 'gradient-sweep'] as Transition[]) {
      expect(sceneTransition({...s, transition: tr}, 6).opacity).toBe(0);
      expect(sceneTransition({...s, transition: tr}, 4).opacity).toBe(1);
    }
    expect(sceneTransition({...s, transition: 'gradient-sweep'}, 2.1).sweep).toBeGreaterThan(0);
    expect(sceneTransition({...s, transition: 'gradient-sweep'}, 4).sweep).toBeUndefined();
    expect(sceneTransition({...s, transition: 'mask-wipe'}, 2.1).mask).toMatch(/linear-gradient/);
  });

  it('camera moves stay within the documented reserve', () => {
    const W = 1080;
    const areaW = 940;
    const areaH = 1060;
    for (const cam of ['none', 'push-in', 'pan-left', 'pan-right', 'drift', undefined] as (Camera | undefined)[]) {
      for (const amp of [0.6, 1, 1.25]) {
        const r = cameraReserve(cam, areaW, areaH, W, amp);
        for (let i = 0; i <= 20; i++) {
          const c = cameraAt(cam, {start: 0, end: 4}, (i / 20) * 4, W, amp);
          // corners of the content area relative to its centre
          for (const [x, y] of [[-areaW / 2, -areaH / 2], [areaW / 2, areaH / 2]]) {
            expect(Math.abs(x * c.scale + c.dx - x)).toBeLessThanOrEqual(r.x + 1e-9);
            expect(Math.abs(y * c.scale + c.dy - y)).toBeLessThanOrEqual(r.y + 1e-9);
          }
        }
      }
    }
    expect(cameraAt(undefined, {start: 0, end: 4}, 4, W).scale).toBe(1.03);
  });
});

describe('v2 blocks: measure + placement (both formats)', () => {
  it('fixtures exercise every new block type, transition, camera and preset', () => {
    const scenes = [...V2S.scenes, ...V2L.scenes];
    const types = new Set(scenes.flatMap((s) => s.blocks.map((b) => b.type)));
    for (const t of NEW_TYPES) expect(types.has(t)).toBe(true);
    expect(new Set(scenes.map((s) => s.transition))).toEqual(new Set(['fade', 'slide-up', 'none', 'mask-wipe', 'gradient-sweep'].filter((x) => scenes.some((s) => s.transition === x))));
    for (const t of ['mask-wipe', 'gradient-sweep', 'slide-up', 'fade']) expect(scenes.some((s) => s.transition === t)).toBe(true);
    for (const c of ['none', 'push-in', 'pan-left', 'pan-right', 'drift']) expect(scenes.some((s) => s.camera === c)).toBe(true);
    for (const m of ['calm', 'standard', 'energetic', 'cinematic']) expect(scenes.some((s) => s.motion === m)).toBe(true);
    expect(new Set([V2S.watermark?.policy, V2L.watermark?.policy])).toEqual(new Set(['platform', 'custom']));
  });

  const checkScene = (props: RenderProps, scene: Scene) => {
    const env = makeEnv(props);
    const P = planScene(env, scene);
    const {width} = DIMENSIONS[props.format];
    const band = captionBandTop(props.format, props.captions);
    for (const b of P.layout.boxes) {
      // settled box + the maximum camera displacement never reaches the caption band or the frame edges
      expect(b.y + b.h + P.reserve.y).toBeLessThanOrEqual(band + 1e-6);
      expect(b.y - P.reserve.y).toBeGreaterThanOrEqual(0);
      expect(b.x - P.reserve.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w + P.reserve.x).toBeLessThanOrEqual(width + 1e-6);
      if (env.watermark && env.watermark.visibleRanges.some(([a, z]) => a < scene.end && z > scene.start)) {
        const r = env.watermark.rect;
        const hit = b.x < r.x + r.w && b.x + b.w > r.x && b.y < r.y + r.h && b.y + b.h > r.y;
        expect(hit).toBe(false);
      }
    }
    return P;
  };

  it('every fixture scene stays out of the caption band, inside the frame, clear of the watermark', () => {
    for (const p of [V2S, V2L]) for (const s of p.scenes) checkScene(p, s);
  });

  it('each new block alone and in a crowded 3-block scene fits both formats, with every camera', () => {
    const all: Block[] = [...V2S.scenes, ...V2L.scenes].flatMap((s) => s.blocks).filter((b) => (NEW_TYPES as string[]).includes(b.type));
    for (const p of [V2S, V2L]) {
      for (const b of all) {
        for (const camera of ['none', 'push-in', 'pan-left', 'drift'] as Camera[]) {
          const scene: Scene = {id: 'x', purpose: 'custom', start: 1, end: 4, transition: 'fade', layout: 'stack', camera, blocks: [b]};
          checkScene(p, scene);
          checkScene(p, {...scene, blocks: [{type: 'headline', size: 'l', words: [{text: 'Fast'}, {text: 'hosting'}]}, b, {type: 'text', size: 'm', text: 'Same price on renewal'}]});
          checkScene(p, {...scene, layout: 'split', blocks: [b, {type: 'pill', text: 'NEW', tone: 'brand'}, b]});
        }
      }
    }
  });

  it('new blocks have deterministic, positive measurements and fitted text (no overflow) in the fixtures', () => {
    for (const p of [V2S, V2L]) {
      const m = buildManifest(p);
      const texts = m.scenes.flatMap((s) => s.blocks.flatMap((b) => b.texts));
      expect(texts.length).toBeGreaterThan(80);
      expect(texts.filter((t) => t.overflow).map((t) => t.text)).toEqual([]);
      for (const s of m.scenes) for (const b of s.blocks) expect(b.bbox.h).toBeGreaterThan(0);
    }
  });
});

describe('branding / watermark', () => {
  const env = (p: RenderProps) => aspectEnv(p);
  const wm = (p: RenderProps, w: RenderProps['watermark'], busy: [number, number][] = []) => planWatermark({...p, watermark: w}, env(p), busy);

  it('platform policy: Shorts top-left below the status bar, landscape top-right', () => {
    const s = wm(V2S, {policy: 'platform'})!;
    expect(s.position).toBe('top-left');
    expect(s.rect.x).toBeLessThan(200);
    expect(s.rect.y).toBeGreaterThanOrEqual(WATERMARK_DEFAULTS.short.topInset);
    expect(s.variant).toBe('mark');
    const l = wm(V2L, {policy: 'platform', position: 'bottom-left'})!;
    expect(l.position).toBe('top-right');
    expect(l.rect.x + l.rect.w).toBeGreaterThan(1920 - 200);
    expect(l.rect.y).toBeLessThan(120);
  });

  it('never distorts: rect aspect equals the asset aspect (mark from the SVG viewBox, not 1.7)', () => {
    const markSvg = readFileSync(join(ROOT, 'public/brand/icon.svg'), 'utf8');
    const markAspect = svgAspect(markSvg)!;
    expect(markAspect).toBeCloseTo(39 / 23, 9);
    expect(env(V2S).logo.mark).toBeCloseTo(markAspect, 9);
    expect(env(V1S).logo.mark).toBe(MARK_ASPECT); // v1 keeps its numbers
    for (const policy of ['platform', 'brand'] as const) {
      for (const p of [V2S, V2L]) {
        const r = wm(p, {policy})!;
        expect(r.rect.w / r.rect.h).toBeCloseTo(r.aspect, 9);
      }
    }
    const c = wm(V2L, {policy: 'custom', asset: 'brand/icon.svg', position: 'bottom-right'})!;
    expect(c.rect.w / c.rect.h).toBeCloseTo(markAspect, 9);
    // the watermark's own logo in the manifest
    const m = buildManifest(V2S);
    for (const l of m.scenes.flatMap((s) => s.blocks.flatMap((b) => b.logos))) expect(l.aspect).toBeCloseTo(l.expectedAspect, 2);
  });

  it('every position stays clear of the caption box in both formats', () => {
    for (const p of [V2S, V2L]) {
      const {width, height} = DIMENSIONS[p.format];
      const capBottom = height - height * p.captions.bottomFrac;
      const capTop = captionBandTop(p.format, p.captions);
      const colX0 = (width * (1 - p.captions.maxWidthFrac)) / 2;
      for (const position of ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'top-center'] as const) {
        for (const policy of ['brand', 'custom'] as const) {
          const r = wm(p, {policy, position, asset: 'brand/icon.svg'})!.rect;
          const overlapsBand = r.y < capBottom && r.y + r.h > capTop && r.x < width - colX0 && r.x + r.w > colX0;
          expect(overlapsBand).toBe(false);
          expect(r.x).toBeGreaterThanOrEqual(0);
          expect(r.x + r.w).toBeLessThanOrEqual(width);
          expect(r.y + r.h).toBeLessThanOrEqual(height);
        }
      }
    }
  });

  it('policy none / null / v1 → no watermark; custom without asset is an error', () => {
    expect(wm(V2S, {policy: 'none'})).toBeNull();
    expect(wm(V2S, null)).toBeNull();
    expect(planWatermark({...V1S, watermark: {policy: 'platform'}}, env(V1S), [])).toBeNull();
    expect(() => wm(V2S, {policy: 'custom'})).toThrow(/asset/);
    expect(wm(V2S, {policy: 'brand', opacity: 7})!.opacity).toBe(1);
    expect(wm(V2S, {policy: 'brand', opacity: 0})!.opacity).toBe(0.05);
  });

  it('no duplicate branding: hidden whenever a logo / cta / sting / outro block or the brand bar is visible', () => {
    const e = makeEnv(V2S);
    const w = e.watermark!;
    expect(w).not.toBeNull();
    const branding = V2S.scenes.flatMap((s) => {
      const P = planScene(e, s);
      return s.blocks.flatMap((b, i) => (['logo', 'cta', 'logo-sting', 'outro'].includes(b.type) || (b.type === 'image' && b.asset.startsWith('brand/')) ? [P.visible[i]] : []));
    });
    expect(branding.length).toBeGreaterThan(2);
    const hidden = (t: number) => watermarkFactor(w, t) === 0;
    for (const v of branding) for (let t = v.from; t <= v.to; t += 0.05) expect(hidden(t)).toBe(true);
    for (let t = V2S.brandBar!.from; t <= V2S.brandBar!.to; t += 0.05) expect(hidden(t)).toBe(true);
    // visibleRanges = exactly where it can be drawn
    for (const [a, b] of w.visibleRanges) expect(watermarkFactor(w, (a + b) / 2)).toBeGreaterThan(0);
    for (const [a, b] of w.busy) expect(watermarkFactor(w, (a + b) / 2)).toBe(0);
  });

  it('hook-tag hangs from below the brand bar in v2 (string never crosses the logo), from the frame top in v1', () => {
    const e = makeEnv(V2S);
    const s = V2S.scenes.find((x) => x.blocks.some((b) => b.type === 'hook-tag'))!;
    const P = planScene(e, s);
    expect(P.bar).toBe(true);
    expect(P.ceilingY).toBeGreaterThan(e.brandBar!.y + e.brandBar!.h);
    expect(P.layout.boxes[0].y).toBeGreaterThan(P.ceilingY);
    const v1Scene = {...s, blocks: s.blocks};
    expect(planScene(makeEnv({...V2S, contractVersion: 1}), v1Scene).ceilingY).toBe(0);
  });
});

describe('assets', () => {
  it('reads intrinsic aspects from PNG / JPEG / GIF / SVG bytes', () => {
    const png = new Uint8Array(32);
    png.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    png.set([0, 0, 0x07, 0x80], 16); // 1920
    png.set([0, 0, 0x04, 0x38], 20); // 1080
    expect(intrinsicAspect(png)).toBeCloseTo(16 / 9, 9);
    const jpg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 4, 0, 0, 0xff, 0xc0, 0, 17, 8, 0x02, 0xd0, 0x05, 0x00, 3, 0, 0, 0]);
    expect(intrinsicAspect(jpg)).toBeCloseTo(1280 / 720, 9);
    const gif = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 100, 0, 50, 0, 0, 0]);
    expect(intrinsicAspect(gif)).toBe(2);
    expect(svgAspect('<svg xmlns="x" width="200" height="40" viewBox="0 0 150 30.000001">')).toBeCloseTo(5, 5);
    expect(svgAspect('<svg width="300px" height="100px">')).toBe(3);
    expect(intrinsicAspect(new TextEncoder().encode('hello'))).toBeUndefined();
  });
});

describe('v1 backward compatibility', () => {
  it('accepts contractVersion 1 and 2, rejects others', () => {
    expect(() => assertContract({...V1S, contractVersion: 1})).not.toThrow();
    expect(() => assertContract({...V1S, contractVersion: 2})).not.toThrow();
    expect(() => assertContract({...V1S, contractVersion: 0})).toThrow(/contractVersion/);
  });

  it('v1 props are planned exactly like the v1 engine (no reserves, legacy aspects, push-in, no watermark)', () => {
    for (const p of [V1S, V1L]) {
      const e = makeEnv({...p, watermark: {policy: 'platform'}});
      expect(e.watermark).toBeNull();
      for (const s of p.scenes) {
        const bar = !!p.brandBar && p.brandBar.from < s.end && p.brandBar.to > s.start;
        const legacy = layoutScene(s, p.format, p.captions, bar, p.theme.logo.aspect);
        const P = planScene(e, s);
        expect(P.layout).toEqual(legacy);
        expect(P.reserve).toEqual({x: 0, y: 0});
        expect(P.ceilingY).toBe(0);
        expect(P.preset.name).toBe('standard');
      }
      expect(e.brandBar && e.brandBar.w / e.brandBar.h).toBeCloseTo(p.theme.logo.aspect, 9);
    }
  });

  it('v1 manifest: same boxes, watermark null, and QA sees the real mark aspect vs the v1 layout box', () => {
    const m = buildManifest(withAspects(V1S));
    expect(m.contractVersion).toBe(1);
    expect(m.watermark).toBeNull();
    const mark = m.scenes.flatMap((s) => s.blocks.flatMap((b) => b.logos)).find((l) => l.variant === 'mark')!;
    expect(mark.aspect).toBeCloseTo(1.7, 2); // v1 layout box (height rounded to whole px)
    expect(mark.expectedAspect).toBeCloseTo(39 / 23, 3); // file's viewBox; drawn with object-fit: contain
    expect(mark.bbox.w / mark.bbox.h).toBeCloseTo(39 / 23, 1);
  });
});

describe('layout manifest', () => {
  it('is deterministic and matches the renderer planning (same boxes, same visibility)', () => {
    for (const p of [V2S, V2L, withAspects(V1S), withAspects(V1L)]) {
      const a = buildManifest(p);
      expect(buildManifest(p)).toEqual(a);
      const e = makeEnv(p);
      p.scenes.forEach((s, si) => {
        const P = planScene(e, s);
        a.scenes[si].blocks.forEach((b, bi) => {
          const box = P.layout.boxes[bi];
          expect(b.bbox.x).toBeCloseTo(box.x, 1);
          expect(b.bbox.y).toBeCloseTo(box.y, 1);
          expect(b.bbox.w).toBeCloseTo(box.w, 1);
          expect(b.bbox.h).toBeCloseTo(box.h, 1);
          expect(b.visible.from).toBeCloseTo(P.visible[bi].from, 3);
        });
      });
      expect(a.width).toBe(DIMENSIONS[p.format].width);
      expect(a.captionBand.y).toBeCloseTo(captionBandTop(p.format, p.captions), 1);
    }
  });

  it('has the documented shape', () => {
    const m = buildManifest(V2S);
    expect(Object.keys(m)).toEqual(['contractVersion', 'format', 'width', 'height', 'fps', 'safeArea', 'captionBand', 'scenes', 'watermark', 'brandBar']);
    const b = m.scenes[1].blocks[0];
    expect(Object.keys(b)).toEqual(['index', 'type', 'bbox', 'visible', 'texts', 'logos']);
    expect(Object.keys(b.texts[0])).toEqual(['text', 'bbox', 'fontSize', 'fontWeight', 'estWidth', 'maxWidth', 'overflow', 'role']);
    expect(Object.keys(m.watermark!)).toEqual(['policy', 'bbox', 'variant', 'opacity', 'visibleRanges']);
    expect(Object.keys(m.brandBar!)).toEqual(['bbox', 'from', 'to']);
  });

  it('flags overflow whenever the estimated width exceeds the box', () => {
    const base = V2S.scenes[1];
    const mk = (blocks: Block[]) => buildManifest({...V2S, scenes: [{...base, blocks}]}).scenes[0].blocks[0].texts;
    const long = mk([{type: 'checklist', items: [{text: 'Unmetered bandwidth with free daily offsite backups', at: 3}]}]);
    expect(long[0].overflow).toBe(true);
    expect(long[0].estWidth).toBeGreaterThan(long[0].maxWidth);
    const ok = mk([{type: 'checklist', items: [{text: 'Free SSL', at: 3}]}]);
    expect(ok[0].overflow).toBe(false);
    const word = mk([{type: 'text', size: 'l', text: 'Supercalifragilisticexpialidocious-hosting'}]);
    expect(word[0].overflow).toBe(true);
    // estimator is monotonic and consistent with the flag
    expect(estimateTextWidth('WWW', 50)).toBeGreaterThan(estimateTextWidth('iii', 50));
  });

  it('scripts/engine-layout.mjs prints exactly the in-process manifest', () => {
    for (const f of ['sample-v2-short.json', 'sample-v2-landscape.json', 'sample-short.json']) {
      const file = join(ROOT, 'src/engine/fixtures', f);
      const out = JSON.parse(execFileSync('node', [join(ROOT, 'scripts/engine-layout.mjs'), file], {encoding: 'utf8'}));
      const props = withAspects(JSON.parse(readFileSync(file, 'utf8')) as RenderProps);
      expect(out).toEqual(JSON.parse(JSON.stringify(buildManifest(props))));
    }
  });

  it('covers both formats with a non-empty safe area above the caption band', () => {
    for (const fmt of ['short', 'landscape'] as Format[]) {
      const m = buildManifest(fmt === 'short' ? V2S : V2L);
      expect(m.safeArea.h).toBeGreaterThan(500);
      expect(m.safeArea.y + m.safeArea.h).toBeCloseTo(m.captionBand.y, 1);
    }
  });
});
