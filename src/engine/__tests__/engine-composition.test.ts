import {execFileSync} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
import {collectAssetPaths, intrinsicAspect} from '../assets';
import {AspectEnv, specWidth} from '../geometry';
import {COMPOSITION, compositionAspect, compositionFirstTime, compositionLayout, elementRect, fitTextBox, geomComposition, numberText} from '../geometry-composition';
import {firstInternalTime, layoutScene, measureBlock, naturalWidth} from '../layout';
import {buildManifest, withAssetAspects} from '../manifest';
import {makeEnv, planScene} from '../plan';
import {blockContent} from '../texts';
import {Block, COMPOSITION_COLORS, COMPOSITION_KINDS, COMPOSITION_MOTIONS, COMPOSITION_ROLES, COMPOSITION_SHAPES, RenderProps} from '../types';
import cShort from '../fixtures/sample-composition-short.json';
import cLand from '../fixtures/sample-composition-landscape.json';

const ROOT = resolve(__dirname, '../../..');
const readPublic = (p: string) => {
  const f = join(ROOT, 'public', p);
  return existsSync(f) ? new Uint8Array(readFileSync(f)) : undefined;
};
const withAspects = (p: RenderProps) => withAssetAspects(p, readPublic, collectAssetPaths, intrinsicAspect);
const CS = withAspects(cShort as unknown as RenderProps);
const CL = withAspects(cLand as unknown as RenderProps);
type C = Extract<Block, {type: 'composition'}>;
const comps = (p: RenderProps) => p.scenes.flatMap((s) => s.blocks).filter((b): b is C => b.type === 'composition');
const env: AspectEnv = {logo: {onDark: 5, onLight: 5, mark: 1.7}, asset: () => undefined};
const inside = (a: {x: number; y: number; w: number; h: number}, b: {x: number; y: number; w: number; h: number}, eps = 0.6) =>
  a.x >= b.x - eps && a.y >= b.y - eps && a.x + a.w <= b.x + b.w + eps && a.y + a.h <= b.y + b.h + eps;

const sample: C = {
  type: 'composition',
  at: 1,
  canvas: {tall: 1, wide: 1.9},
  elements: [
    {id: 'hub', kind: 'shape', shape: 'circle', box: [0.3, 0.3, 0.4, 0.4], wide: [0.4, 0.2, 0.2, 0.6], at: 1, fill: 'surface', stroke: 'brand'},
    {id: 'ring', kind: 'shape', shape: 'arc', box: [0.25, 0.25, 0.5, 0.5], at: 1.2, sweep: 270, start: 0, stroke: 'brand'},
    {id: 'a', kind: 'shape', shape: 'roundrect', box: [0.05, 0.05, 0.4, 0.15], at: 1.5},
    {kind: 'connector', fromId: 'hub', toId: 'a', box: [0, 0, 0, 0], at: 1.6, curve: 0.3},
    {kind: 'text', text: 'Daily backups', role: 'label', box: [0.07, 0.07, 0.36, 0.11], at: 1.6},
    {kind: 'text', text: 'Under the hood', role: 'title', box: [0.32, 0.4, 0.36, 0.2], wide: [0.41, 0.35, 0.18, 0.3], at: 1},
    {kind: 'number', to: 12, suffix: ' GB', box: [0.3, 0.8, 0.4, 0.15], at: 2, countEnd: 2.8},
    {kind: 'icon', icon: 'shield', box: [0.8, 0.05, 0.15, 0.1], at: 2.2},
  ],
};

describe('composition: contract', () => {
  it('mirrors the Python element vocabularies and time keys (pipeline/contract.py)', () => {
    const py = readFileSync(join(ROOT, 'pipeline/contract.py'), 'utf8');
    const pySet = (name: string) => new Set([...(new RegExp(`${name} = \\{([\\s\\S]*?)\\}`).exec(py)?.[1] ?? '').matchAll(/"([^"]+)"/g)].map((m) => m[1]));
    expect(pySet('COMPOSITION_KINDS')).toEqual(new Set(COMPOSITION_KINDS));
    expect(pySet('COMPOSITION_SHAPES')).toEqual(new Set(COMPOSITION_SHAPES));
    expect(pySet('COMPOSITION_MOTIONS')).toEqual(new Set(COMPOSITION_MOTIONS));
    expect(pySet('COMPOSITION_COLORS')).toEqual(new Set(COMPOSITION_COLORS));
    expect(pySet('COMPOSITION_ROLES')).toEqual(new Set(COMPOSITION_ROLES));
    expect(pySet('BLOCK_TYPES').has('composition')).toBe(true);
    // nested element times are ordinary time keys; geometry numbers (arc start / sweep, box) are not
    for (const k of ['at', 'countEnd', 'pulseAt']) expect(pySet('TIME_KEYS').has(k)).toBe(true);
    for (const k of ['start', 'sweep', 'box', 'wide', 'curve', 'from', 'to']) expect(pySet('TIME_KEYS').has(k)).toBe(false);
  });
});

describe('composition: geometry', () => {
  it('uses the tall canvas in a Short column and the wide one at ≥ wideMin design px', () => {
    expect(compositionLayout(940)).toBe('tall');
    expect(compositionLayout(COMPOSITION.wideMin)).toBe('wide');
    expect(naturalWidth(sample, 1929, env)).toBe(COMPOSITION.naturalW);
    expect(measureBlock(sample, 940, env)).toBe(940);
    expect(measureBlock(sample, 1500, env)).toBe(Math.round(1500 / 1.9));
    expect(compositionAspect({canvas: {tall: 99}}, 'tall')).toBe(COMPOSITION.aspectMax);
    expect(compositionAspect({}, 'wide')).toBe(COMPOSITION.aspect.wide);
  });

  it('places elements from the right box per layout; circles and arcs stay round', () => {
    for (const w of [940, 1500]) {
      const g = geomComposition(sample, w, env);
      const hub = g.parts[0];
      expect(hub.rect.w).toBeCloseTo(hub.rect.h, 6);
      const want = elementRect(sample.elements[0], g.layout, w, g.h);
      expect(inside(hub.rect, want)).toBe(true);
      expect(g.parts[1].path).toMatch(/^M [\d.]+ [\d.]+ A /);
      expect(g.parts[3].path).toMatch(/^M [\d.]+ [\d.]+ Q /);
    }
    const tall = geomComposition(sample, 940, env);
    const wide = geomComposition(sample, 1500, env);
    expect(tall.layout).toBe('tall');
    expect(wide.layout).toBe('wide');
    expect(wide.parts[0].rect.x).toBeGreaterThan(tall.parts[0].rect.x);
  });

  it('fits text deterministically: largest size, wraps to the role limit, never overflows a sane box', () => {
    const one = fitTextBox('Daily backups', 'label', 400, 60);
    expect(one).toEqual(fitTextBox('Daily backups', 'label', 400, 60));
    expect(one.lines).toEqual(['Daily backups']);
    expect(one.fs).toBe(COMPOSITION.fs.label);
    const two = fitTextBox('Imunify360 security scanning included', 'label', 300, 110);
    expect(two.fits).toBe(true);
    expect(two.lines.length).toBe(2);
    expect(two.fs).toBeGreaterThanOrEqual(COMPOSITION.minFs.label);
    const bad = fitTextBox('Supercalifragilisticexpialidocious', 'label', 120, 40);
    expect(bad.fits).toBe(false);
    expect(bad.fs).toBe(COMPOSITION.minFs.label);
  });

  it('reports every text line to the manifest (with roles), and flags an impossible box as overflow', () => {
    const {texts} = blockContent(sample, 940, measureBlock(sample, 940, env), env);
    expect(texts.map((t) => t.text)).toEqual(expect.arrayContaining(['Daily backups', '12 GB']));
    expect(texts.find((t) => t.text === '12 GB')?.role).toBe('title');
    expect(texts.find((t) => t.text === 'Daily backups')?.role).toBe('label');
    const price = {...sample, elements: [{kind: 'number' as const, to: 69, prefix: '$', box: [0, 0, 1, 0.3]}]};
    expect(blockContent(price, 940, 940, env).texts[0].role).toBe('price');
    const cramped: C = {type: 'composition', elements: [{kind: 'text', text: 'Supercalifragilisticexpialidocious', box: [0, 0, 0.1, 0.04]}]};
    const t = blockContent(cramped, 940, 940, env).texts[0];
    expect(specWidth(t)).toBeGreaterThan(t.w);
    expect(numberText({prefix: '₹', grouping: 'indian'}, 125000)).toBe('₹1,25,000');
  });

  it('first internal time is the earliest element (so an un-timed block never hides its parts)', () => {
    expect(compositionFirstTime(sample)).toBeCloseTo(0.9, 9);
    expect(firstInternalTime({...sample, at: undefined})).toBeCloseTo(0.9, 9);
    expect(compositionFirstTime({elements: [{kind: 'shape', shape: 'rect', box: [0, 0, 1, 1]}]})).toBeUndefined();
  });
});

describe('composition: fixtures (generated by pipeline/creative/composer.py, times resolved by Python)', () => {
  it('cover every structure, kind, shape and motion preset, with resolved (numeric) nested times', () => {
    for (const p of [CS, CL]) {
      const cs = comps(p);
      expect(new Set(cs.map((b) => b.design?.structure))).toEqual(
        new Set(['orbit', 'network', 'layers', 'grid', 'hero-number', 'ladder', 'path', 'funnel', 'stacked', 'compare']),
      );
      const els = cs.flatMap((b) => b.elements);
      for (const k of ['text', 'shape', 'connector', 'icon', 'number']) expect(els.some((e) => e.kind === k)).toBe(true);
      for (const m of ['fade-up', 'fade', 'scale-in', 'draw-on', 'pop']) expect(els.some((e) => e.motion === m)).toBe(true);
      expect(els.some((e) => typeof e.pulseAt === 'number')).toBe(true);
      for (const e of els) {
        expect(typeof e.at).toBe('number');
        if (e.countEnd !== undefined) expect(e.countEnd).toBeGreaterThan(e.at!);
      }
      for (const s of p.scenes)
        for (const b of s.blocks)
          if (b.type === 'composition') for (const e of b.elements) expect(e.at!).toBeGreaterThanOrEqual(s.start - 0.2);
    }
  });

  it('lay out in both formats inside the safe area, with no text overflow and every text inside its element box', () => {
    for (const p of [CS, CL]) {
      const m = buildManifest(p);
      const env2 = makeEnv(p);
      p.scenes.forEach((s, si) => {
        const P = planScene(env2, s);
        s.blocks.forEach((b, bi) => {
          const box = P.layout.boxes[bi];
          expect(box.y + box.h).toBeLessThanOrEqual(P.layout.bottom + 0.5);
          expect(box.x).toBeGreaterThanOrEqual(P.layout.side - 0.5);
          if (b.type !== 'composition') return;
          expect(compositionLayout(box.designW)).toBe(p.format === 'landscape' ? 'wide' : 'tall');
          const mb = m.scenes[si].blocks[bi];
          expect(mb.texts.length).toBeGreaterThan(0);
          for (const t of mb.texts) expect(t.overflow).toBe(false);
          const g = geomComposition(b, box.designW, env2.aspects);
          for (const part of g.parts) for (const t of part.texts) expect(inside({x: t.x, y: t.y, w: t.w, h: t.h}, elementRect(part.el, g.layout, box.designW, g.h), 1)).toBe(true);
        });
      });
    }
  });

  it('the layout CLI (scripts/engine-layout.mjs) reports the same composition texts as the in-process manifest', () => {
    const dir = mkdtempSync(join(tmpdir(), 'comp-'));
    try {
      const f = join(dir, 'props.json');
      writeFileSync(f, JSON.stringify(cShort));
      const cli = JSON.parse(execFileSync('node', [join(ROOT, 'scripts/engine-layout.mjs'), f], {encoding: 'utf8'}));
      const local = buildManifest(CS);
      const pick = (mm: typeof local) => mm.scenes.flatMap((s) => s.blocks.filter((b) => b.type === 'composition').map((b) => b.texts));
      expect(pick(cli)).toEqual(pick(local));
    } finally {
      rmSync(dir, {recursive: true, force: true});
    }
  });

  it('every planned block keeps a positive height at both widths (layout entries handle the block)', () => {
    for (const p of [CS, CL])
      for (const s of p.scenes) {
        const L = layoutScene(s, p.format, p.captions, false, makeEnv(p).aspects, {hero: true});
        for (const b of L.boxes) expect(b.h).toBeGreaterThan(0);
      }
  });
});

describe('composition: motion (pure functions of t)', () => {
  const row = {damping: 13, mass: 0.7};
  it('enters at its own `at` (minus the shared lead) and settles; draw-on draws, pulse fades out', async () => {
    const {elementState} = await import('../blocks-composition');
    const e = {kind: 'text' as const, text: 'x', box: [0, 0, 1, 1], at: 2};
    expect(elementState(e, 1.9, 0, 30, row).opacity).toBe(0);
    const late = elementState(e, 5, 0, 30, row);
    expect(late.opacity).toBe(1);
    expect(Math.abs(late.dy)).toBeLessThan(0.5);
    const line = {kind: 'connector' as const, box: [0, 0, 0, 0], at: 2, fromId: 'a', toId: 'b'};
    let prev = -1;
    for (let t = 1.9; t < 3; t += 1 / 30) {
      const d = elementState(line, t, 0, 30, row).draw;
      expect(d).toBeGreaterThanOrEqual(prev);
      prev = d;
    }
    expect(prev).toBe(1);
    const pulsing = {kind: 'shape' as const, shape: 'circle' as const, box: [0, 0, 1, 1], at: 1, pulseAt: 2};
    expect(elementState(pulsing, 2.4, 0, 30, row).pulse).toBeGreaterThan(0.5);
    expect(elementState(pulsing, 3.5, 0, 30, row).pulse).toBe(0);
    for (const motion of COMPOSITION_MOTIONS) {
      const s = elementState({...e, motion}, 2 - 0.2, 0, 30, row);
      expect(s.opacity).toBe(0);
      expect(elementState({...e, motion}, 6, 0, 30, row).opacity).toBe(1);
    }
  });

  it('colours come only from theme tokens; surfaces follow a light backdrop', async () => {
    const {paint} = await import('../blocks-composition');
    const theme = (CS as RenderProps).theme;
    const ink = {text: theme.colors.text, text2: theme.colors.text2, muted: theme.colors.muted, accent: theme.colors.brandText, success: theme.colors.success};
    const dark = {theme, surface: 'dark' as const, ink};
    const light = {theme, surface: 'light' as const, ink};
    expect(paint('brand', 'card', dark)).toBe(theme.colors.brand);
    expect(paint(undefined, 'card', dark)).toBe(theme.colors.card);
    expect(paint('card', 'card', light)).toBe(theme.colors.light.card);
    for (const tok of COMPOSITION_COLORS) expect(paint(tok, 'card', dark)).toMatch(/^#|^rgb/);
  });
});
