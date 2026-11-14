import {describe, expect, it} from 'vitest';
import {
  CAPTION_SAFE,
  captionBoxHeight,
  captionEmphasis,
  captionLook,
  captionMetrics,
  keepTogether,
  pageLayout,
  contrast,
  lightCaptionPalette,
  mixColor,
} from '../captions';
import {readdirSync, existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {wordLook} from '../captions-motion';
import {DIMENSIONS} from '../contract';
import {captionBandTop, layoutScene} from '../layout';
import {buildManifest} from '../manifest';
import {estimateTextWidth} from '../motion/typography';
import {CaptionConfig, Format, RenderProps, Scene, Word} from '../types';
import sampleShort from '../fixtures/sample-v2-short.json';
import sampleLandscape from '../fixtures/sample-v2-landscape.json';

const SHORT = sampleShort as unknown as RenderProps;
const LAND = sampleLandscape as unknown as RenderProps;
const KINETIC = ['pop', 'highlight', 'karaoke', 'minimal'] as const;
const man = (p: RenderProps) => buildManifest({...p, assetAspects: p.assetAspects ?? {}});
const withStyle = (p: RenderProps, style: CaptionConfig['style'] | undefined): RenderProps =>
  ({...p, captions: {...p.captions, style}}) as RenderProps;

describe('caption styles: classic is unchanged', () => {
  it('maps the original values (and a missing style) to the classic look', () => {
    expect(captionLook('word')).toBe('classic');
    expect(captionLook('phrase')).toBe('classic');
    expect(captionLook('classic')).toBe('classic');
    expect(captionLook(undefined)).toBe('classic');
    for (const s of KINETIC) expect(captionLook(s)).toBe(s);
  });

  it('keeps the exact original band, box and column numbers for classic props (both formats)', () => {
    for (const p of [SHORT, LAND]) {
      const {width, height} = DIMENSIONS[p.format];
      const c = p.captions;
      const legacyBand = height - height * c.bottomFrac - captionBoxHeight(c.fontSize, 2) - 24;
      for (const style of ['word', 'phrase', 'classic', undefined] as const) {
        const q = withStyle(p, style);
        expect(captionBandTop(q.format, q.captions)).toBe(legacyBand);
        const m = captionMetrics(q.format, q.captions);
        expect(m.bottom).toBe(height * c.bottomFrac);
        expect(m.maxW).toBe(width * c.maxWidthFrac);
        expect(m.fontSize).toBe(c.fontSize);
      }
    }
  });

  it('builds a byte-identical layout manifest for classic props whatever the classic spelling', () => {
    for (const p of [SHORT, LAND]) {
      const ref = JSON.stringify(man(p));
      for (const style of ['phrase', 'classic'] as const) expect(JSON.stringify(man(withStyle(p, style)))).toBe(ref);
    }
  });
});

describe('caption styles: placement', () => {
  const formats: [Format, RenderProps][] = [
    ['short', SHORT],
    ['landscape', LAND],
  ];
  it('keeps every new look out of the platform UI zones (bottom 20 % and side rail on 9:16)', () => {
    for (const [fmt, p] of formats) {
      const {width, height} = DIMENSIONS[fmt];
      for (const style of KINETIC) {
        const m = captionMetrics(fmt, {...p.captions, style});
        expect(m.bottom).toBeGreaterThanOrEqual(height * CAPTION_SAFE[fmt].bottomFrac - 1e-9);
        expect(m.x).toBeGreaterThanOrEqual(CAPTION_SAFE[fmt].sidePx - 1e-9);
        expect(m.x + m.maxW).toBeLessThanOrEqual(width - CAPTION_SAFE[fmt].sidePx + 1e-9);
        if (fmt === 'short') expect(m.x + m.maxW).toBeLessThanOrEqual(width * 0.9);
      }
    }
    // even a project that asks for a lower box is lifted out of the Shorts overlay
    expect(captionMetrics('short', {bottomFrac: 0.05, fontSize: 66, style: 'pop'}).bottom).toBe(1920 * 0.2);
  });

  it('reserves a band tall enough for two lines of the larger kinetic type, and lays content out above it', () => {
    for (const [fmt, p] of formats) {
      for (const style of KINETIC) {
        const cap = {...p.captions, style};
        const m = captionMetrics(fmt, cap);
        const top = captionBandTop(fmt, cap);
        expect(DIMENSIONS[fmt].height - m.bottom - top).toBeGreaterThanOrEqual(m.fontSize * m.lineHeight * 2 + 24);
        for (const s of p.scenes) {
          const L = layoutScene(s, fmt, cap, false, p.theme.logo.aspect);
          for (const b of L.boxes) expect(b.y + b.h).toBeLessThanOrEqual(top + 1e-6);
        }
        // the manifest's caption band is exactly what the engine draws into
        const band = man({...p, captions: cap} as RenderProps).captionBand;
        expect(band.y + band.h).toBeCloseTo(DIMENSIONS[fmt].height - m.bottom, 0);
        expect(band.x).toBeCloseTo(m.x, 0);
      }
    }
  });

  it('places minimal lower than classic on 16:9 and pop larger than classic', () => {
    const c = LAND.captions;
    expect(captionMetrics('landscape', {...c, style: 'minimal'}).bottom).toBeLessThan(captionMetrics('landscape', c).bottom);
    expect(captionMetrics('short', {...SHORT.captions, style: 'pop'}).fontSize).toBeGreaterThan(SHORT.captions.fontSize);
  });
});

describe('caption styles: page layout', () => {
  const m = captionMetrics('short', {bottomFrac: 0.27, fontSize: 66, maxWidthFrac: 0.8, style: 'pop'});
  const width = (texts: string[], fs: number, line: number[]) =>
    line.reduce((w, k, i) => w + estimateTextWidth(texts[k].toUpperCase(), fs, {weight: m.weight}) + (i ? fs * 0.34 : 0), 0);

  it('uses one line when it fits, else a balanced 2-line split that never breaks a name', () => {
    expect(pageLayout(['Meet', 'Kokoro.'], m).lines).toEqual([[0, 1]]);
    const t = ['Meet', 'Video', 'Studio.'];
    const r = pageLayout(t, m, [1, 1.12, 1.12], [false, true, false]);
    expect(r.lines).toEqual([[0], [1, 2]]);
    for (const line of r.lines) expect(width(t, r.fs, line)).toBeLessThanOrEqual(m.maxW + 1e-6);
  });

  it('shrinks only as much as needed, never below 60 %, never wider than the column', () => {
    const t = ['Internationalisation', 'considerations'];
    const r = pageLayout(t, m);
    expect(r.fs).toBeLessThan(m.fontSize);
    expect(r.fs).toBeGreaterThanOrEqual(Math.round(m.fontSize * 0.6));
    expect(r.lines.length).toBeLessThanOrEqual(2);
  });
});

describe('caption styles: emphasis and word state', () => {
  const words: Word[] = [
    {text: 'Meet', start: 0.1, end: 0.4},
    {text: 'Video', start: 0.45, end: 0.7},
    {text: 'Studio.', start: 0.72, end: 1.1},
    {text: 'Only', start: 1.5, end: 1.7},
    {text: '₹49', start: 1.75, end: 2.2},
    {text: 'fast.', start: 2.3, end: 2.6},
    {text: 'fast', start: 5.2, end: 5.5},
  ];
  const scene = (id: string, start: number, end: number, blocks: Scene['blocks']): Scene =>
    ({id, purpose: 'x', start, end, transition: 'fade', layout: 'stack', mood: 'neutral', blocks}) as Scene;
  const props = {
    words,
    theme: {...SHORT.theme, name: 'Video Studio'},
    scenes: [
      scene('a', 0, 3, [{type: 'kinetic-text', size: 'l', words: [{text: 'Fast.', emphasis: true}, {text: 'only'}]} as Scene['blocks'][number]]),
      scene('b', 3, 6, []),
    ],
  };

  it('emphasises numbers, the brand name and the scene’s own emphasis words (only inside that scene)', () => {
    const e = captionEmphasis(props);
    expect([...e].sort((a, b) => a - b)).toEqual([1, 2, 4, 5]);
    expect(e.has(6)).toBe(false); // "fast" again, but in a scene that does not emphasise it
    expect(e.has(3)).toBe(false); // not marked emphasis in the block
    expect([...keepTogether(props)]).toEqual([1]); // "Video" stays on the line of "Studio."
  });

  it('marks the latest started word active (also through a pause), fills karaoke progress, springs the pop', () => {
    const pw = words.slice(0, 3);
    expect(wordLook(pw, 0, 0.05, 30)).toEqual({active: false, spoken: false, fill: 0, pop: 0});
    expect(wordLook(pw, 0, 0.2, 30).active).toBe(true);
    expect(wordLook(pw, 0, 0.43, 30).active).toBe(true); // the gap between "Meet" and "Video"
    expect(wordLook(pw, 0, 0.5, 30).active).toBe(false);
    expect(wordLook(pw, 1, 0.5, 30).active).toBe(true);
    expect(wordLook(pw, 2, 0.91, 30).fill).toBeCloseTo(0.5, 2);
    expect(wordLook(pw, 2, 2.0, 30).fill).toBe(1);
    const early = wordLook(pw, 1, 0.47, 30).pop;
    const later = wordLook(pw, 1, 0.65, 30).pop;
    expect(early).toBeGreaterThan(0);
    expect(later).toBeGreaterThan(early);
  });
});

describe('caption styles: light surfaces', () => {
  const brandsDir = join(__dirname, '../../../brands');
  const themes = [SHORT.theme, ...readdirSync(brandsDir)
    .map((d) => join(brandsDir, d, 'theme.json'))
    .filter((f) => existsSync(f))
    .map((f) => JSON.parse(readFileSync(f, 'utf8')))];

  it('uses dark ink and a contrast-checked accent on the light surface for every brand theme', () => {
    for (const th of themes) {
      const L = lightCaptionPalette(th);
      const bg = th.colors.light.surface;
      expect(contrast(L.ink, bg)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(L.accent, bg)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(L.muted, bg)).toBeGreaterThanOrEqual(3);
      expect(contrast('#ffffff', L.block)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('leaves dark-backdrop colours untouched (mix weight 0 returns the input string)', () => {
    expect(mixColor('#9aa6ff', '#000000', 0)).toBe('#9aa6ff');
    expect(mixColor('rgb(1,2,3)', '#ffffff', 0)).toBe('rgb(1,2,3)');
    expect(mixColor('#000000', '#ffffff', 1)).toBe('#ffffff');
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 5);
  });
});
