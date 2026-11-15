import {execFileSync} from 'node:child_process';
import {existsSync, readdirSync, readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
import {collectAssetPaths, intrinsicAspect} from '../assets';
import {rectsIntersect} from '../branding';
import {
  captionMetrics,
  captionToneBlock,
  captionToneColor,
  captionToneColorLight,
  captionToneMap,
  contrast,
  HEADLINE_SIDE,
  speakerOf,
  speakerTagMetrics,
} from '../captions';
import {assertContract, DIMENSIONS} from '../contract';
import {HUD, hudBottomFor, hudTexts, hudTracks, planHud, segmentAt, stakesText} from '../hud';
import {captionBandTop, CaptionBandCfg, FORMAT_SPEC} from '../layout';
import {buildManifest, withAssetAspects} from '../manifest';
import {makeEnv, planScene, sceneTops} from '../plan';
import {CAPTION_TONES, CaptionTone, HUD_KINDS, HUD_OPS, Hud, RenderProps, Theme} from '../types';
import hShort from '../fixtures/sample-hud-short.json';
import hLand from '../fixtures/sample-hud-landscape.json';
import v2Short from '../fixtures/sample-v2-short.json';

const ROOT = resolve(__dirname, '../../..');
const readPublic = (p: string) => {
  const f = join(ROOT, 'public', p);
  return existsSync(f) ? new Uint8Array(readFileSync(f)) : undefined;
};
const withAspects = (p: RenderProps) => withAssetAspects(p, readPublic, collectAssetPaths, intrinsicAspect);
const HS = withAspects(hShort as unknown as RenderProps);
const HL = withAspects(hLand as unknown as RenderProps);
const V2 = v2Short as unknown as RenderProps;
const FIXTURES = readdirSync(join(ROOT, 'src/engine/fixtures')).filter((f) => f.endsWith('.json') && !f.startsWith('sample-hud'));

const hudProps = (hud: Hud, extra: Partial<RenderProps> = {}): RenderProps => ({...HS, hud, ...extra});

describe('HUD: contract', () => {
  it('v3 is accepted, and the vocabularies mirror pipeline/contract.py', () => {
    expect(() => assertContract({...HS, contractVersion: 3})).not.toThrow();
    const py = readFileSync(join(ROOT, 'pipeline/contract.py'), 'utf8');
    const pySet = (name: string) => new Set([...(new RegExp(`${name} = \\{([\\s\\S]*?)\\}`).exec(py)?.[1] ?? '').matchAll(/"([^"]+)"/g)].map((m) => m[1]));
    expect(pySet('HUD_KINDS')).toEqual(new Set(HUD_KINDS));
    expect(pySet('HUD_OPS')).toEqual(new Set(HUD_OPS));
    expect(pySet('CAPTION_TONES')).toEqual(new Set(CAPTION_TONES));
    expect(HEADLINE_SIDE.short).toBe(FORMAT_SPEC.short.side);
    expect(HEADLINE_SIDE.landscape).toBe(FORMAT_SPEC.landscape.side);
  });

  it('is off without a hud, below contract v3, and for every older fixture (layout unchanged)', () => {
    expect(planHud({...HS, contractVersion: 2}, null)).toBeNull();
    expect(planHud({...HS, hud: null}, null)).toBeNull();
    expect(planHud({...HS, hud: {elements: [], events: []}}, null)).toBeNull();
    for (const f of FIXTURES) {
      const p = JSON.parse(readFileSync(join(ROOT, 'src/engine/fixtures', f), 'utf8')) as RenderProps;
      const env = makeEnv(p);
      expect(env.hud).toBeNull();
      for (const s of p.scenes) expect(sceneTops(env, s)).toEqual({});
    }
  });
});

describe('HUD: state from events', () => {
  const hud: Hud = {
    elements: [
      {id: 'h', kind: 'header', prefix: 'Round', steps: ['Hook', 'Script', 'Edit']},
      {id: 'c', kind: 'chips'},
      {id: 'p', kind: 'progress', total: 4, value: 1, style: 'segments'},
      {id: 's', kind: 'stakes', parts: [{value: 212, label: 'applications'}, {value: 0, label: 'replies', tone: 'danger'}]},
    ],
    events: [
      {at: 1, target: 'h', op: 'show'},
      {at: 2, target: 'c', op: 'add', text: 'Hash'},
      {at: 3, target: 'h', op: 'advance'},
      {at: 3.5, target: 'c', op: 'add', text: 'TTL', tone: 'info'},
      {at: 4, target: 'p', op: 'set', value: 3},
      {at: 5, target: 's', op: 'show'},
      {at: 6, target: 's', op: 'set', part: 1, value: 2, tone: 'success'},
      {at: 7, target: 'h', op: 'set', index: 0},
      {at: 8, target: 'h', op: 'hide'},
      {at: 9, target: 'p', op: 'advance'},
      {at: 9.5, target: 'p', op: 'advance'},
    ],
  };
  const tracks = hudTracks(hud, 12);
  const tr = (id: string) => tracks.find((x) => x.el.id === id)!;
  const at = (id: string, t: number) => segmentAt(tr(id), t).seg;

  it('an element is hidden until its first event, and a change starts HUD.lead before its word', () => {
    expect(at('h', 0.5).visible).toBe(false);
    expect(at('h', 1 - HUD.lead).visible).toBe(true);
    expect(at('h', 1 - HUD.lead - 0.01).visible).toBe(false);
    expect(at('c', 1.5).visible).toBe(false);
    expect(at('c', 2).visible).toBe(true);            // an add shows the chips row
  });

  it('header advances / sets / hides; progress clamps at total; chips accumulate; stakes count', () => {
    expect(at('h', 2).state).toEqual({kind: 'header', index: 0});
    expect(at('h', 3.2).state).toEqual({kind: 'header', index: 1});
    expect(at('h', 7.2).state).toEqual({kind: 'header', index: 0});
    expect(at('h', 8.5).visible).toBe(false);
    expect(tr('h').ranges).toEqual([[1 - HUD.lead, 8 - HUD.lead + HUD.fadeOut]]);
    expect(at('p', 4.2).state).toEqual({kind: 'progress', value: 3});
    expect(at('p', 10).state).toEqual({kind: 'progress', value: 4});
    const chips = at('c', 4).state;
    expect(chips.kind === 'chips' && chips.chips.map((c) => [c.text, c.tone])).toEqual([['Hash', undefined], ['TTL', 'info']]);
    const s = at('s', 6.5).state;
    expect(s).toEqual({kind: 'stakes', values: [212, 2], tones: [undefined, 'success']});
    expect(stakesText(hud.elements[3] as Extract<Hud['elements'][number], {kind: 'stakes'}>, [212, 0])).toBe('212 applications  ·  0 replies');
  });

  it('geometry: one row per kind, top to bottom, inside the side margins; a scene reserves only what it shows', () => {
    const plan = planHud(hudProps(hud), null)!;
    const b = plan.boxes;
    // "ROUND 3 · EDIT" + the stakes chip fit one Short row: stakes on the right of the header
    expect(b.s.x).toBeGreaterThanOrEqual(b.h.x + b.h.w - 0.01);
    expect(b.s.y).toBeGreaterThanOrEqual(b.h.y - 0.01);
    // the fixture's wider header does not: the stakes chip gets its own centred row above it
    const f = makeEnv(HS).hud!.boxes;
    expect(f.stakes.y + f.stakes.h).toBeLessThanOrEqual(f.step.y + 0.01);
    expect(f.stakes.x + f.stakes.w / 2).toBeCloseTo(DIMENSIONS.short.width / 2, 6);
    expect(b.h.y + b.h.h).toBeLessThanOrEqual(b.p.y + 0.01);
    expect(b.p.y + b.p.h).toBeLessThanOrEqual(b.c.y + 0.01);
    for (const r of Object.values(b)) {
      expect(r.x).toBeGreaterThanOrEqual(HUD.side.short - 0.01);
      expect(r.x + r.w).toBeLessThanOrEqual(DIMENSIONS.short.width - HUD.side.short + 0.01);
    }
    expect(hudBottomFor(plan, 0, 0.5)).toBeUndefined();
    expect(hudBottomFor(plan, 1, 1.5)).toBeCloseTo(b.h.y + b.h.h, 6);   // header only
    expect(hudBottomFor(plan, 2, 2.5)).toBeCloseTo(b.c.y + b.c.h, 6);   // header + chips
  });

  it('stakes share the header row in 16:9 and keep one width while counting', () => {
    const plan = planHud({...hudProps(hud), format: 'landscape'}, null)!;
    expect(plan.boxes.s.y).toBeGreaterThanOrEqual(plan.boxes.h.y - 0.01);
    expect(plan.boxes.s.y + plan.boxes.s.h).toBeLessThanOrEqual(plan.boxes.h.y + plan.boxes.h.h + 0.01);
    expect(plan.boxes.s.x + plan.boxes.s.w).toBeCloseTo(DIMENSIONS.landscape.width - HUD.side.landscape, 6);
    expect(plan.boxes.h.x + plan.boxes.h.w).toBeLessThanOrEqual(plan.boxes.s.x + 0.01);
  });

  it('many chips shrink, then wrap to two rows; more than that is reported as overflow', () => {
    const many = (n: number): Hud => ({elements: [{id: 'c', kind: 'chips'}], events: Array.from({length: n}, (_, i) => ({at: 1 + i, target: 'c', op: 'add' as const, text: `Term ${i}`}))});
    const one = planHud(hudProps(many(2)), null)!.boxes.c;
    const two = planHud(hudProps(many(7)), null)!.boxes.c;
    const lots = planHud(hudProps(many(30)), null)!.boxes.c;
    expect(one.kind === 'chips' && one.h).toBeCloseTo(HUD.chips.h, 6);
    expect(two.kind === 'chips' && two.items.at(-1)!.y).toBeGreaterThan(two.y);
    expect(two.kind === 'chips' && two.overflow).toBe(false);
    expect(lots.kind === 'chips' && lots.overflow).toBe(true);
  });

  it('starts below the brand bar when both are on screen', () => {
    const bar = {x: 350, y: 122, w: 380, h: 76, from: 0, to: 3};
    expect(planHud(hudProps(hud), bar)!.y0).toBeCloseTo(bar.y + bar.h + HUD.barGap, 6);
    expect(planHud(hudProps(hud), {...bar, from: 0, to: 0.5})!.y0).toBe(HUD.top.short);   // gone before the HUD shows
  });
});

describe('HUD: fixture layout (both formats)', () => {
  for (const [name, P] of [['short', HS], ['landscape', HL]] as const) {
    it(`${name}: scene content never sits under a visible HUD element, captions keep their band`, () => {
      const env = makeEnv(P);
      expect(env.hud).not.toBeNull();
      const plan = env.hud!;
      for (const s of P.scenes) {
        const pl = planScene(env, s);
        for (const tr of plan.tracks) {
          if (!tr.ranges.some(([a, b]) => a < s.end && b > s.start)) continue;
          const box = plan.boxes[tr.el.id];
          for (const b of pl.layout.boxes) expect(rectsIntersect(b, box, pl.reserve.y)).toBe(false);
          expect(box.y + box.h).toBeLessThan(captionBandTop(P.format, P.captions));
        }
        if (pl.tops.hud !== undefined) for (const b of pl.layout.boxes) expect(b.y).toBeGreaterThanOrEqual(pl.tops.hud - 0.01);
      }
    });
  }

  it('landscape headline captions: a band per scene below the HUD, content below the band, bottom kept for the platform', () => {
    const env = makeEnv(HL);
    expect(captionBandTop('landscape', HL.captions)).toBeCloseTo(Math.min(1080 - 90 * 0.85, 1080 * (1 - 0.035) - 90 * 0.85), 6);
    for (const s of HL.scenes) {
      const tops = sceneTops(env, s);
      const pl = planScene(env, s);
      expect(tops.headline).toBeDefined();
      if (tops.hud !== undefined) expect(tops.headline!.y).toBeGreaterThanOrEqual(tops.hud - 0.01);
      for (const b of pl.layout.boxes) expect(b.y).toBeGreaterThanOrEqual(tops.headline!.y + tops.headline!.h);
      expect(tops.headline!.x).toBe(HEADLINE_SIDE.landscape);
    }
    const m = buildManifest(HL);
    expect(m.scenes.every((s) => s.captionBand && s.captionBand.y < 400)).toBe(true);
    expect(m.captionBand).toEqual(m.scenes[0].captionBand);
  });

  it('a top watermark hides while the HUD is on screen', () => {
    const env = makeEnv({...HS, watermark: {policy: 'platform'}});
    const wm = env.watermark!;
    for (const [a, b] of wm.visibleRanges) for (const [x, y] of env.hud!.ranges) expect(a < y && b > x).toBe(false);
  });

  it('manifest: HUD elements with windows and text runs; a counted value is shown once it lands', () => {
    const m = buildManifest(HS);
    expect(m.hud!.elements.map((e) => e.kind)).toEqual(['stakes', 'header', 'progress', 'chips']);
    const st = m.hud!.elements[0];
    expect(st.texts.map((x) => x.text)).toEqual(['4s to load  ·  on mobile', '1s to load  ·  on mobile']);
    const setAt = HS.hud!.events.find((e) => e.op === 'set')!.at;
    expect(st.texts[1].from).toBeCloseTo(setAt + HUD.count, 3);
    for (const e of m.hud!.elements) for (const x of e.texts) expect(x.overflow).toBe(false);
    expect(Object.keys(hudTexts(makeEnv(HS).hud!, 30))).toEqual(['stakes', 'step', 'series', 'terms']);
    expect(m.scenes.slice(1, 4).every((s) => typeof s.hudBottom === 'number')).toBe(true);
  });

  it('scripts/engine-layout.mjs prints exactly the in-process manifest for the HUD fixtures', () => {
    for (const f of ['sample-hud-short.json', 'sample-hud-landscape.json']) {
      const file = join(ROOT, 'src/engine/fixtures', f);
      const out = JSON.parse(execFileSync('node', [join(ROOT, 'scripts/engine-layout.mjs'), file], {encoding: 'utf8'}));
      expect(out).toEqual(JSON.parse(JSON.stringify(buildManifest(withAspects(JSON.parse(readFileSync(file, 'utf8')) as RenderProps)))));
    }
  });
});

describe('caption tones and speakers', () => {
  const theme = V2.theme as Theme;
  it('pages carry tones per word; no tones = an empty map (the looks draw as before)', () => {
    expect(captionToneMap(V2.captions).size).toBe(0);
    const m = captionToneMap(HS.captions);
    const idx = (txt: string) => HS.words.findIndex((w) => w.text.replace(/[.,:?!]/g, '') === txt);
    expect(m.get(idx('seconds'))).toBe('danger');
    expect(m.get(idx('TTL'))).toBe('term');
    expect(m.get(idx('Fixed'))).toBe('success');
  });

  it('tone colours are theme tokens (overridable), readable on the light surface and under white text', () => {
    expect(captionToneColor(theme, 'danger')).toBe(theme.colors.danger);
    expect(captionToneColor(theme, 'term')).toBe(theme.colors.warning);
    expect(captionToneColor(theme, 'brand')).toBe(theme.caption.highlight);
    expect(captionToneColor({...theme, caption: {...theme.caption, tones: {term: '#ffd166'}}}, 'term')).toBe('#ffd166');
    for (const tn of CAPTION_TONES as readonly CaptionTone[]) {
      expect(contrast(captionToneColorLight(theme, tn), theme.colors.light.surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(captionToneBlock(theme, tn), '#ffffff')).toBeGreaterThanOrEqual(3);
    }
  });

  it('speakers: labels, tones by declaration order, and a band that makes room for the tag', () => {
    expect(speakerOf(HS.captions, 'YOU')).toEqual({label: 'YOU', tone: 'brand'});
    expect(speakerOf(HS.captions, 'VISITOR').tone).toBe('info');
    expect(speakerOf({speakers: {A: {}, B: {}}}, 'B').tone).toBe('info');
    const base: CaptionBandCfg = {enabled: true, bottomFrac: 0.27, fontSize: 66};
    const tag = speakerTagMetrics(66).block;
    for (const style of ['word', 'pop', 'karaoke'] as const) {
      const a = captionBandTop('short', {...base, style});
      const b = captionBandTop('short', {...base, style, speakers: {MOM: {}}});
      expect(a - b).toBeCloseTo(tag, 6);
      expect(captionMetrics('short', {...base, style}).tagH).toBe(0);
    }
  });

  it('headline: the content column, two lines + tag, no bottom band', () => {
    const m = captionMetrics('short', {bottomFrac: 0.27, fontSize: 66, style: 'headline'});
    expect(m.x).toBe(HEADLINE_SIDE.short);
    expect(m.maxW).toBe(DIMENSIONS.short.width - 2 * HEADLINE_SIDE.short);
    expect(m.bandH).toBeCloseTo(m.fontSize * m.lineHeight * 2 + m.fontSize * 0.12, 6);
    expect(captionBandTop('short', {enabled: true, bottomFrac: 0.27, fontSize: 66, style: 'headline'})).toBeCloseTo(1920 * 0.8 - 90, 6);
  });
});
