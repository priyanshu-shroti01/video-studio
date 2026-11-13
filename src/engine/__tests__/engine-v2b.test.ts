import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
import {collectAssetPaths, intrinsicAspect} from '../assets';
import {installProgress} from '../blocks-v2b';
import {DIMENSIONS} from '../contract';
import {geomInstallFlow, geomPlanCard, geomServerStack, V2B_WIDE_MIN} from '../geometry-v2b';
import {captionBandTop, layoutScene} from '../layout';
import {BACKDROP_XFADE, BACKDROP_XFADE_LUMA, BACKDROPS, backdropWeights, isPolished, splitPanel} from '../look';
import {buildManifest, withAssetAspects} from '../manifest';
import {makeEnv, planScene} from '../plan';
import {BackdropKind, Block, Camera, RenderProps, Scene} from '../types';
import sampleShort from '../fixtures/sample-short.json';
import sampleLandscape from '../fixtures/sample-landscape.json';
import v2Short from '../fixtures/sample-v2-short.json';
import v2Land from '../fixtures/sample-v2-landscape.json';
import v2bShort from '../fixtures/sample-v2b-short.json';
import v2bLand from '../fixtures/sample-v2b-landscape.json';

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
const BS = withAspects(v2bShort as unknown as RenderProps);
const BL = withAspects(v2bLand as unknown as RenderProps);
const V2B_TYPES = ['plan-card', 'install-flow', 'server-stack'] as const;

const checkScene = (props: RenderProps, scene: Scene) => {
  const env = makeEnv(props);
  const P = planScene(env, scene);
  const {width} = DIMENSIONS[props.format];
  const band = captionBandTop(props.format, props.captions);
  for (const b of P.layout.boxes) {
    expect(b.y + b.h + P.reserve.y).toBeLessThanOrEqual(band + 1e-6);
    expect(b.y - P.reserve.y).toBeGreaterThanOrEqual(0);
    expect(b.x - P.reserve.x).toBeGreaterThanOrEqual(0);
    expect(b.x + b.w + P.reserve.x).toBeLessThanOrEqual(width + 1e-6);
  }
  return P;
};

describe('v2b look gate (backward compatibility)', () => {
  it('v1 and pre-v2b v2 props are not polished; using a backdrop or a v2b block opts in', () => {
    for (const p of [V1S, V1L, V2S, V2L]) expect(isPolished(p)).toBe(false);
    for (const p of [BS, BL]) expect(isPolished(p)).toBe(true);
    expect(isPolished({...V2S, scenes: [{...V2S.scenes[0], backdrop: 'glow'}]})).toBe(true);
    expect(isPolished({...V2S, scenes: [{...V2S.scenes[0], blocks: [BS.scenes[2].blocks[0]]}]})).toBe(true);
    // a v1 storyboard never gets the v2b look, whatever it says
    expect(isPolished({...V1S, scenes: V1S.scenes.map((s) => ({...s, backdrop: 'light' as const}))})).toBe(false);
  });

  it('un-opted props plan exactly the pre-v2b layout (no hero, no split inset)', () => {
    for (const p of [V2S, V2L]) {
      const e = makeEnv(p);
      expect(e.polish).toBe(false);
      for (const s of p.scenes) {
        const P = planScene(e, s);
        expect(P.backdrop).toBe('glow');
        expect(P.layout.fit).toBeLessThanOrEqual(1);
      }
    }
  });
});

describe('backdrops', () => {
  const scenes = (kinds: BackdropKind[]) => kinds.map((k, i) => ({start: i * 3, end: (i + 1) * 3, backdrop: k}));

  it('weights sum to 1, default glow, and every kind is exercised by the v2b fixtures', () => {
    const sc = scenes(['deep', 'spotlight', 'split', 'light', 'grid', 'glow']);
    for (let t = -1; t < 20; t += 0.07) {
      const w = backdropWeights(sc, t);
      const sum = Object.values(w).reduce((a, b) => a + (b ?? 0), 0);
      expect(sum).toBeCloseTo(1, 9);
    }
    expect(backdropWeights([{start: 0, end: 3}], 1)).toEqual({glow: 1});
    for (const p of [BS, BL]) expect(new Set(p.scenes.map((s) => s.backdrop))).toEqual(new Set(BACKDROPS));
  });

  it('crossfades are continuous (no jump between frames) and centred on the boundary', () => {
    const sc = scenes(['split', 'light', 'grid']);
    let prev = backdropWeights(sc, 0);
    for (let f = 1; f < 9 * 30; f++) {
      const w = backdropWeights(sc, f / 30);
      for (const k of BACKDROPS) expect(Math.abs((w[k] ?? 0) - (prev[k] ?? 0))).toBeLessThan(0.2);
      prev = w;
    }
    expect(backdropWeights(sc, 3).split).toBeCloseTo(0.5, 6);
    expect(backdropWeights(sc, 1.5)).toEqual({split: 1});
    // dark ⇄ light is short (a long 50/50 mix reads as grey); dark ⇄ dark uses the long crossfade
    expect(backdropWeights(sc, 3 - BACKDROP_XFADE_LUMA - 0.01)).toEqual({split: 1});
    const dd = scenes(['deep', 'grid']);
    expect(backdropWeights(dd, 3 - BACKDROP_XFADE + 0.05).grid).toBeGreaterThan(0);
  });

  it('equal neighbouring backdrops never dip; gaps take the nearest scene', () => {
    const sc = scenes(['grid', 'grid']);
    for (let t = 2; t < 4; t += 0.01) expect(backdropWeights(sc, t)).toEqual({grid: 1});
    expect(backdropWeights([{start: 0, end: 2, backdrop: 'deep'}, {start: 5, end: 7, backdrop: 'light'}], 4.6)).toEqual({light: 1});
  });

  it("'split' keeps content off the brand panel (short: below the band, landscape: right of the panel)", () => {
    for (const p of [BS, BL]) {
      const {width, height} = DIMENSIONS[p.format];
      const sp = splitPanel(p.format, width, height);
      const e = makeEnv(p);
      const s = p.scenes.find((x) => x.backdrop === 'split')!;
      for (const camera of ['none', 'push-in', 'drift', 'pan-right'] as Camera[]) {
        const P = checkScene(p, {...s, camera});
        for (const b of P.layout.boxes) {
          if (p.format === 'short') expect(b.y - P.reserve.y).toBeGreaterThanOrEqual(sp.contentTop - 1e-6);
          else expect(b.x - P.reserve.x).toBeGreaterThanOrEqual(sp.contentLeft - 1e-6);
        }
      }
      expect(planScene(e, s).backdrop).toBe('split');
    }
  });
});

describe('hero scaling (v2b)', () => {
  it('a sparse single-block scene grows, limited by the column width and the content area', () => {
    for (const p of [BS, BL]) {
      const e = makeEnv(p);
      const logo: Block = {type: 'logo', variant: 'onDark', width: 500};
      const s: Scene = {id: 'h', purpose: 'custom', start: 0, end: 3, transition: 'fade', layout: 'stack', camera: 'none', blocks: [logo]};
      const P = checkScene(p, s);
      expect(P.layout.fit).toBeGreaterThan(1);
      expect(P.layout.fit).toBeLessThanOrEqual(1.5);
      const plain = planScene(makeEnv(V2S.format === p.format ? V2S : V2L), s);
      expect(plain.layout.fit).toBe(1);
      expect(P.layout.boxes[0].w).toBeGreaterThan(plain.layout.boxes[0].w);
      void e;
    }
  });
});

describe('v2b blocks', () => {
  const blocks = [...BS.scenes, ...BL.scenes].flatMap((s) => s.blocks).filter((b) => (V2B_TYPES as readonly string[]).includes(b.type));

  it('fixtures exercise all three blocks in both formats', () => {
    for (const p of [BS, BL]) {
      const types = new Set(p.scenes.flatMap((s) => s.blocks.map((b) => b.type)));
      for (const t of V2B_TYPES) expect(types.has(t)).toBe(true);
    }
  });

  it('fit both formats alone, crowded and in split columns, with every camera and backdrop: out of the caption band, inside the frame', () => {
    for (const p of [BS, BL]) {
      for (const b of blocks) {
        for (const camera of ['none', 'push-in', 'pan-left', 'drift'] as Camera[]) {
          for (const backdrop of ['glow', 'split', 'light'] as BackdropKind[]) {
            const scene: Scene = {id: 'x', purpose: 'custom', start: 1, end: 4, transition: 'fade', layout: 'stack', camera, backdrop, blocks: [b]};
            checkScene(p, scene);
            checkScene(p, {...scene, blocks: [{type: 'headline', size: 'l', words: [{text: 'One-click'}, {text: 'WordPress'}]}, b, {type: 'text', size: 'm', text: 'Free SSL'}]});
            checkScene(p, {...scene, layout: 'split', blocks: [b, {type: 'pill', text: 'NEW', tone: 'brand'}, b]});
          }
        }
      }
    }
  });

  it('switch between the wide (landscape) and tall (Shorts / narrow column) layouts by width', () => {
    for (const b of blocks) {
      const lo = V2B_WIDE_MIN[b.type as keyof typeof V2B_WIDE_MIN];
      const g = b.type === 'plan-card' ? geomPlanCard : b.type === 'install-flow' ? geomInstallFlow : geomServerStack;
      expect((g as (x: Block, w: number) => {wide: boolean})(b, lo).wide).toBe(true);
      expect((g as (x: Block, w: number) => {wide: boolean})(b, lo - 1).wide).toBe(false);
    }
    const m = buildManifest(BL);
    const plan = m.scenes.find((s) => s.id === 'plan')!.blocks[0];
    expect(plan.bbox.w / plan.bbox.h).toBeGreaterThan(1.4); // wide card in landscape
    const ms = buildManifest(BS);
    const planS = ms.scenes.find((s) => s.id === 'plan')!.blocks[0];
    expect(planS.bbox.h / planS.bbox.w).toBeGreaterThan(1.1); // tall card in the Short
  });

  it('manifest: every text fits, with QA roles (price → price, URLs → url, names → title)', () => {
    for (const p of [BS, BL]) {
      const m = buildManifest(p);
      const all = m.scenes.flatMap((s) => s.blocks.flatMap((b) => b.texts));
      expect(all.filter((t) => t.overflow).map((t) => t.text)).toEqual([]);
      const of = (type: string) => m.scenes.flatMap((s) => s.blocks.filter((b) => b.type === type)).flatMap((b) => b.texts);
      const role = (type: string, text: string) => of(type).find((t) => t.text === text)?.role;
      expect(role('plan-card', '₹69')).toBe('price');
      expect(role('plan-card', 'WP Starter')).toBe('title');
      expect(role('plan-card', '10 GB NVMe storage')).toBe('body');
      expect(role('install-flow', 'WordPress')).toBe('title');
      expect(role('install-flow', 'yourbrand.in')).toBe('url');
      expect(role('install-flow', 'WordPress installed')).toBe('title');
      expect(role('install-flow', 'Installing plugins')).toBe('label');
      expect(role('server-stack', 'WP Starter infrastructure')).toBe('title');
      expect(role('server-stack', 'LiteSpeed Cache')).toBe('label');
      // legible minimum sizes (output px) for the facts that QA reads back
      for (const t of [...of('plan-card'), ...of('install-flow'), ...of('server-stack')]) expect(t.fontSize).toBeGreaterThanOrEqual(p.format === 'short' ? 18 : 16);
      for (const t of all.filter((x) => x.role === 'price' || x.role === 'url')) expect(t.fontSize).toBeGreaterThanOrEqual(20);
      // texts sit inside their block
      for (const s of m.scenes)
        for (const b of s.blocks)
          for (const t of b.texts) {
            expect(t.bbox.x).toBeGreaterThanOrEqual(b.bbox.x - 1);
            expect(t.bbox.x + t.bbox.w).toBeLessThanOrEqual(b.bbox.x + b.bbox.w + 1);
            expect(t.bbox.y + t.bbox.h).toBeLessThanOrEqual(b.bbox.y + b.bbox.h + 1);
          }
    }
  });

  it('scripts/engine-layout.mjs prints exactly the in-process manifest for the v2b fixtures', () => {
    for (const f of ['sample-v2b-short.json', 'sample-v2b-landscape.json']) {
      const file = join(ROOT, 'src/engine/fixtures', f);
      const out = JSON.parse(execFileSync('node', [join(ROOT, 'scripts/engine-layout.mjs'), file], {encoding: 'utf8'}));
      expect(out).toEqual(JSON.parse(JSON.stringify(buildManifest(withAspects(JSON.parse(readFileSync(file, 'utf8')) as RenderProps)))));
    }
  });

  it('install-flow progress is monotonic, < 1 before doneAt and exactly 1 from doneAt', () => {
    const b = BS.scenes.find((s) => s.id === 'install')!.blocks[0] as Extract<Block, {type: 'install-flow'}>;
    let prev = -1;
    for (let t = b.steps[0].at - 1; t < b.doneAt + 1; t += 1 / 30) {
      const p = installProgress(b, t);
      expect(p).toBeGreaterThanOrEqual(prev);
      if (t < b.doneAt) expect(p).toBeLessThan(1);
      prev = p;
    }
    expect(installProgress(b, b.doneAt)).toBe(1);
    expect(installProgress(b, b.steps[0].at - 0.5)).toBe(0);
  });

  it('server-stack links start at the rack and end at the website node; the status pill clears every link start', () => {
    for (const w of [940, 1400]) {
      const b = BS.scenes.find((s) => s.id === 'infra')!.blocks[0] as Extract<Block, {type: 'server-stack'}>;
      const g = geomServerStack(b, w);
      expect(g.links.length).toBe(b.nodes.length);
      for (const l of g.links) expect(Math.hypot(l.x1 - g.globe.cx, l.y1 - g.globe.cy)).toBeCloseTo(g.globe.r + 4, 6);
      if (g.status) for (const l of g.links) expect(g.status.y).toBeGreaterThan(l.y0);
      expect(g.h).toBeGreaterThan(0);
    }
  });
});

describe('contract mirror (TS ⇄ pipeline/contract.py)', () => {
  const py = readFileSync(join(ROOT, 'pipeline/contract.py'), 'utf8');
  const ts = readFileSync(join(ROOT, 'src/engine/types.ts'), 'utf8');
  const pySet = (name: string) => new Set([...(new RegExp(`${name} = \\{([\\s\\S]*?)\\}`).exec(py)?.[1] ?? '').matchAll(/"([^"]+)"/g)].map((m) => m[1]));

  it('icons, block types and the new time key match', () => {
    const icons = new Set([...(/export type IconName =([\s\S]*?);/.exec(ts)?.[1] ?? '').matchAll(/'([^']+)'/g)].map((m) => m[1]));
    expect(pySet('ICONS')).toEqual(icons);
    for (const t of V2B_TYPES) expect(pySet('BLOCK_TYPES').has(t)).toBe(true);
    expect(pySet('TIME_KEYS').has('pulseAt')).toBe(true);
    for (const k of ['doneAt', 'countEnd', 'highlightAt', 'at']) expect(pySet('TIME_KEYS').has(k)).toBe(true);
    const tsTypes = new Set([...ts.matchAll(/type: '([a-z-]+)'/g)].map((m) => m[1]));
    expect(pySet('BLOCK_TYPES')).toEqual(tsTypes);
  });

  it('every layout entry handles the v2b blocks (non-zero height at both widths)', () => {
    for (const p of [BS, BL]) {
      for (const s of p.scenes) {
        const L = layoutScene(s, p.format, p.captions, false, makeEnv(p).aspects, {hero: true});
        for (const b of L.boxes) expect(b.h).toBeGreaterThan(0);
      }
    }
  });
});
