import {describe, expect, it} from 'vitest';
import {appearTime, countValue, exitFactor, life} from '../anim';
import {captionBoxHeight, captionPageAt, wordState} from '../captions';
import {assertContract, DIMENSIONS} from '../contract';
import {captionBandTop, FORMAT_SPEC, layoutScene, measureBlock, wrapWords} from '../layout';
import {Block, CaptionConfig, CONTRACT_VERSION, Format, RenderProps, Word} from '../types';
import sampleShort from '../fixtures/sample-short.json';
import sampleLandscape from '../fixtures/sample-landscape.json';

const SHORT = sampleShort as unknown as RenderProps;
const LAND = sampleLandscape as unknown as RenderProps;
const CAP_SHORT = {enabled: true, bottomFrac: 0.27, fontSize: 66};
const CAP_LAND = {enabled: true, bottomFrac: 0.07, fontSize: 50};

const tall: Block[] = [
  {type: 'logo', variant: 'onDark', width: 760},
  {type: 'pill', text: 'Fast NVMe hosting', tone: 'brand'},
  {type: 'price', currency: '₹', amount: 49, period: '/mo', label: 'Launch plan', note: 'excl. taxes'},
  {type: 'compare-rows', rows: [{label: 'Today', value: '₹49', at: 1}, {label: 'Renewal', value: '₹49', at: 2}]},
  {type: 'checklist', items: [{text: 'A', at: 1}, {text: 'B', at: 2}, {text: 'C', at: 3}]},
];

const noOverlap = (boxes: {y: number; h: number; col: number}[]) => {
  for (const col of [0, 1]) {
    const c = boxes.filter((b) => b.col === col).sort((a, b) => a.y - b.y);
    for (let i = 1; i < c.length; i++) expect(c[i].y).toBeGreaterThanOrEqual(c[i - 1].y + c[i - 1].h - 1e-6);
  }
};

describe('layout', () => {
  it('keeps every block above the caption band and below the top margin (both formats, fixtures)', () => {
    for (const props of [SHORT, LAND]) {
      const band = captionBandTop(props.format, props.captions);
      for (const s of props.scenes) {
        const bar = !!props.brandBar && props.brandBar.from < s.end && props.brandBar.to > s.start;
        const L = layoutScene(s, props.format, props.captions, bar, props.theme.logo.aspect);
        for (const b of L.boxes) {
          expect(b.y).toBeGreaterThanOrEqual(L.top - 1e-6);
          expect(b.y + b.h).toBeLessThanOrEqual(band + 1e-6);
          expect(b.x).toBeGreaterThanOrEqual(0);
          expect(b.x + b.w).toBeLessThanOrEqual(DIMENSIONS[props.format].width + 1e-6);
        }
        noOverlap(L.boxes);
      }
    }
  });

  it('shrinks an over-tall stack to fit instead of entering the caption band', () => {
    const L = layoutScene({layout: 'stack', blocks: tall}, 'short', CAP_SHORT, true, 5);
    expect(L.fit).toBeLessThan(1);
    const last = L.boxes[L.boxes.length - 1];
    expect(last.y + last.h).toBeLessThanOrEqual(captionBandTop('short', CAP_SHORT) + 1e-6);
    noOverlap(L.boxes);
  });

  it('reserves room for a 2-line caption plus 24px above the caption bottom', () => {
    const band = captionBandTop('short', CAP_SHORT);
    expect(band).toBeCloseTo(1920 - 1920 * 0.27 - captionBoxHeight(66, 2) - 24, 6);
    expect(captionBandTop('short', {...CAP_SHORT, enabled: false})).toBeGreaterThan(band);
  });

  it('uses two columns for landscape split and falls back to a stack in short format', () => {
    const scene = {layout: 'split' as const, splitAt: 2, blocks: tall.slice(0, 4)};
    const land = layoutScene(scene, 'landscape', CAP_LAND, false, 5);
    expect(land.split).toBe(true);
    expect(land.boxes.slice(0, 2).every((b) => b.col === 0)).toBe(true);
    expect(land.boxes.slice(2).every((b) => b.col === 1)).toBe(true);
    expect(land.boxes[2].x).toBeGreaterThan(land.boxes[0].x);
    const short = layoutScene(scene, 'short', CAP_SHORT, false, 5);
    expect(short.split).toBe(false);
    expect(short.boxes.every((b) => b.col === 0)).toBe(true);
  });

  it('uses the higher top margin while the brand bar is visible', () => {
    const a = layoutScene({layout: 'stack', blocks: tall.slice(0, 1)}, 'short', CAP_SHORT, true, 5);
    const b = layoutScene({layout: 'stack', blocks: tall.slice(0, 1)}, 'short', CAP_SHORT, false, 5);
    expect(a.top).toBe(FORMAT_SPEC.short.topWithBar);
    expect(b.top).toBe(FORMAT_SPEC.short.topNoBar);
  });

  it('measures deterministically and wraps headlines to the box width', () => {
    const h: Block = {type: 'headline', size: 'xl', words: 'Building a website in India?'.split(' ').map((text) => ({text}))};
    expect(measureBlock(h, 940, 5)).toBe(measureBlock(h, 940, 5));
    const lines = wrapWords('Building a website in India?'.split(' '), 150, 940);
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.flat()).toEqual([0, 1, 2, 3, 4]);
    expect(measureBlock(h, 400, 5)).toBeGreaterThan(measureBlock(h, 940, 5));
  });
});

describe('timing', () => {
  it('staggers un-timed blocks after the scene start and honours explicit at', () => {
    expect(appearTime(10, 0)).toBeCloseTo(10.1);
    expect(appearTime(10, 2)).toBeCloseTo(10.34);
    expect(appearTime(10, 2, 11.5)).toBe(11.5);
  });

  it('scene life reaches exactly 0 at the end and 1 mid-scene', () => {
    expect(life(5, 0, 5)).toBe(0);
    expect(life(2.5, 0, 5)).toBe(1);
    expect(life(6, 0, 5)).toBe(0);
  });

  it('block exit is complete at exitAt', () => {
    expect(exitFactor(3, undefined)).toBe(1);
    expect(exitFactor(3, 3)).toBe(0);
    expect(exitFactor(2.5, 3)).toBe(1);
  });

  it('counts up from countFrom to amount between at and countEnd', () => {
    expect(countValue(0.9, 1, 1.5, 0, 49)).toBe(0);
    expect(countValue(1.5, 1, 1.5, 0, 49)).toBe(49);
    const mid = countValue(1.25, 1, 1.5, 0, 49);
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(49);
    expect(Number.isInteger(mid)).toBe(true);
  });
});

describe('captions', () => {
  const words: Word[] = [
    {text: 'Meet', start: 0.1, end: 0.4},
    {text: 'Shroti', start: 0.45, end: 0.8},
    {text: 'Host.', start: 0.82, end: 1.2},
    {text: 'Fast', start: 1.6, end: 1.9},
  ];
  const pages: CaptionConfig['pages'] = [
    {start: 0.1, end: 1.2, wordIdx: [0, 1, 2]},
    {start: 1.6, end: 1.9, wordIdx: [3]},
  ];
  it('finds the visible page, holds through pauses and clears after the last word', () => {
    expect(captionPageAt(pages, words, 0)).toBe(-1);
    expect(captionPageAt(pages, words, 0.06)).toBe(0);
    expect(captionPageAt(pages, words, 1.4)).toBe(0);
    expect(captionPageAt(pages, words, 1.6)).toBe(1);
    expect(captionPageAt(pages, words, 2.4)).toBe(1);
    expect(captionPageAt(pages, words, 2.6)).toBe(-1);
    expect(captionPageAt([], words, 1)).toBe(-1);
  });
  it('classifies words for karaoke highlighting', () => {
    expect(wordState(words[1], 0.5)).toBe('current');
    expect(wordState(words[1], 0.9)).toBe('spoken');
    expect(wordState(words[1], 0.2)).toBe('upcoming');
  });
  it('fixture captions never outlast the voiceover', () => {
    for (const p of [SHORT, LAND]) {
      const last = p.words[p.words.length - 1];
      expect(captionPageAt(p.captions.pages, p.words, last.end + 0.61)).toBe(-1);
      expect(last.end + 0.6).toBeLessThanOrEqual(p.durationInFrames / p.fps + 1e-6);
    }
  });
});

describe('contract', () => {
  it('accepts the fixtures and rejects a version mismatch with a clear message', () => {
    expect(() => assertContract(SHORT)).not.toThrow();
    expect(() => assertContract(LAND)).not.toThrow();
    expect(() => assertContract({...SHORT, contractVersion: CONTRACT_VERSION + 1})).toThrow(/contractVersion/);
    expect(() => assertContract({...SHORT, format: 'square' as Format})).toThrow(/Unknown format/);
    expect(() => assertContract({...SHORT, durationInFrames: 0})).toThrow(/positive/);
  });
  it('fixtures exercise every block type', () => {
    const all = new Set([SHORT, LAND].flatMap((p) => p.scenes.flatMap((s) => s.blocks.map((b) => b.type))));
    const expected: Block['type'][] = ['logo', 'headline', 'text', 'pill', 'price', 'checklist', 'bars', 'compare-rows', 'plans', 'domain-input', 'browser', 'hook-tag', 'flat-line', 'cta'];
    for (const t of expected) expect(all.has(t)).toBe(true);
  });
});
