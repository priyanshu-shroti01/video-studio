/**
 * v3 explainer blocks (geometry-explainer.ts): keyframe interpolation, timing, geometry in both formats, manifest texts,
 * the numbers rule, the cross annotation and the verdict-tint photosensitivity budget.
 */
import {existsSync, readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {describe, expect, it} from 'vitest';
import {collectAssetPaths, intrinsicAspect} from '../assets';
import {DIMENSIONS} from '../contract';
import {hasVerdictTint, usesFx} from '../effects';
import {
  arcPath,
  commentTimes,
  countdownEnd,
  countdownState,
  EXPLAINER_NATURAL_W,
  explainerFirstTime,
  GAUGE,
  gaugeState,
  geomChat,
  geomExplainer,
  geomGauge,
  geomNotification,
  geomTerm,
  geomVerdict,
  initials,
  needleEase,
  noteOrder,
  noteShift,
  NOTE,
  typedChars,
  VERDICT,
  verdictMark,
  verdictNaturalW,
  verdictTintAt,
  zoneTone,
} from '../geometry-explainer';
import {captionBandTop, firstInternalTime, layoutScene, measureBlock, naturalWidth} from '../layout';
import {buildManifest, withAssetAspects} from '../manifest';
import {allowedFlashes, annotationPath, crossDraw, flashEvents, maxFlashesPerWindow} from '../motion/effects';
import {makeEnv, planScene} from '../plan';
import {Block, BlockV3, CONTRACT_VERSION, RenderProps, SUPPORTED_CONTRACT_VERSIONS, V3_BLOCK_TYPES} from '../types';
import xShort from '../fixtures/sample-explainer-short.json';
import xLand from '../fixtures/sample-explainer-landscape.json';

const ROOT = resolve(__dirname, '../../..');
const readPublic = (p: string) => {
  const f = join(ROOT, 'public', p);
  return existsSync(f) ? new Uint8Array(readFileSync(f)) : undefined;
};
const withAspects = (p: RenderProps) => withAssetAspects(p, readPublic, collectAssetPaths, intrinsicAspect);
const XS = withAspects(xShort as unknown as RenderProps);
const XL = withAspects(xLand as unknown as RenderProps);
type G = Extract<BlockV3, {type: 'gauge'}>;
const gauge = (extra: Partial<G> = {}): G => ({type: 'gauge', keys: [{at: 2, value: 41}, {at: 5, value: 89}], ...extra});

describe('contract v3', () => {
  it('bumps the contract and still draws v1 / v2 props', () => {
    expect(CONTRACT_VERSION).toBe(3);
    expect(SUPPORTED_CONTRACT_VERSIONS).toEqual([1, 2, 3]);
    expect(XS.contractVersion).toBe(3);
    const py = readFileSync(join(ROOT, 'pipeline/contract.py'), 'utf8');
    expect(/CONTRACT_VERSION = (\d+)/.exec(py)?.[1]).toBe('3');
    for (const t of V3_BLOCK_TYPES) expect(py).toContain(`"${t}"`);
    for (const k of ['termAt', 'subAt', 'typeStart', 'sendAt', 'pickAt']) expect(py).toContain(`"${k}"`);
  });
  it('the fixtures use every v3 block type in both formats', () => {
    for (const p of [XS, XL]) {
      const types = new Set(p.scenes.flatMap((s) => s.blocks.map((b) => b.type)));
      for (const t of V3_BLOCK_TYPES) expect(types.has(t)).toBe(true);
      expect(p.scenes.some((s) => (s.effects ?? []).some((e) => e.type === 'annotate' && e.kind === 'cross'))).toBe(true);
    }
    expect(XS.format).toBe('short');
    expect(XL.format).toBe('landscape');
  });
});

describe('gauge keyframes', () => {
  it('hides the readout until the first key, then lands exactly on each key value', () => {
    const b = gauge();
    expect(gaugeState(b, 1.99).started).toBe(false);
    expect(gaugeState(b, 1.99).readout).toBe(0);
    expect(gaugeState(b, 2).started).toBe(true);
    expect(gaugeState(b, 2 + GAUGE.dur).readout).toBe(41);
    expect(gaugeState(b, 4.99).readout).toBe(41);
    expect(gaugeState(b, 5 + GAUGE.dur).readout).toBe(89);
    expect(gaugeState(b, 30).readout).toBe(89);
  });
  it('the readout never passes its target (no unspoken number); the needle overshoots a little and settles', () => {
    const b = gauge();
    let prev = -1;
    let maxNeedle = 0;
    for (let t = 2; t <= 2 + GAUGE.dur; t += 1 / 60) {
      const s = gaugeState(b, t);
      expect(s.readout).toBeGreaterThanOrEqual(prev);
      expect(s.readout).toBeLessThanOrEqual(41);
      prev = s.readout;
      maxNeedle = Math.max(maxNeedle, s.needle);
    }
    expect(maxNeedle).toBeGreaterThan(41);
    expect(maxNeedle).toBeLessThan(41 * 1.08);
    expect(needleEase(0)).toBe(0);
    expect(needleEase(1)).toBe(1);
  });
  it('an early key cuts the previous move short and continues from where it was (continuous value)', () => {
    const b = gauge({keys: [{at: 1, value: 80, dur: 2}, {at: 1.5, value: 20}]});
    const before = gaugeState(b, 1.5 - 1e-6).readout;
    const after = gaugeState(b, 1.5 + 1e-6).readout;
    expect(Math.abs(after - before)).toBeLessThan(1);
    expect(gaugeState(b, 10).readout).toBe(20);
  });
  it('keys are taken in time order whatever their array order; decimals round the readout', () => {
    const b = gauge({keys: [{at: 5, value: 9.25}, {at: 2, value: 4.5}], max: 10, decimals: 1});
    expect(gaugeState(b, 3).readout).toBe(4.5);
    expect(gaugeState(b, 9).readout).toBe(9.3);
  });
  it('zones pick the tone of the value (ascending upper bounds; above the last = the last)', () => {
    const z = [{to: 49, tone: 'danger' as const}, {to: 89, tone: 'warning' as const}, {to: 100, tone: 'success' as const}];
    expect(zoneTone(z, 10)).toBe('danger');
    expect(zoneTone(z, 49)).toBe('danger');
    expect(zoneTone(z, 50)).toBe('warning');
    expect(zoneTone(z, 95)).toBe('success');
    expect(zoneTone([...z].reverse(), 95)).toBe('success');
    expect(zoneTone(undefined, 50)).toBeUndefined();
  });
  it('dial and ring geometry: arc inside the box, readout centred, 360° arc closes', () => {
    for (const style of ['dial', 'ring'] as const) {
      for (const w of [600, 760, 940]) {
        const g = geomGauge(gauge({style, label: 'Score', caption: 'Mobile'}), w);
        expect(g.cx - g.R - g.sw / 2).toBeGreaterThanOrEqual(0);
        expect(g.cx + g.R + g.sw / 2).toBeLessThanOrEqual(w);
        expect(g.cy - g.R - g.sw / 2).toBeGreaterThanOrEqual(64);
        expect(g.h).toBeGreaterThan(g.cy);
        expect(g.readout.x + g.readout.w / 2).toBeCloseTo(w / 2, 6);
      }
    }
    expect(arcPath(100, 100, 50, 0, 360).match(/A /g)?.length).toBe(2);
    expect(arcPath(100, 100, 50, 0, 0)).toBe('');
  });
});

describe('countdown, typing and other timing', () => {
  it('counts from → to in real time by default and shows the start value for the first tick', () => {
    const b = {type: 'countdown' as const, from: 7, decimals: 1};
    expect(countdownEnd(b, 10)).toBe(17);
    expect(countdownState(b, 10, 10).value).toBe(7);
    expect(countdownState(b, 10.05, 10).value).toBe(7);
    expect(countdownState(b, 10.5, 10).value).toBe(6.5);
    expect(countdownState(b, 17, 10).value).toBe(0);
    expect(countdownState(b, 17, 10).done).toBe(true);
    expect(countdownState(b, 10, 10).tone).toBe('brand');
    expect(countdownState(b, 15.2, 10).tone).toBe('warning');
    expect(countdownState(b, 16.5, 10).tone).toBe('danger');
    expect(countdownState({...b, tone: 'info'}, 16.5, 10).tone).toBe('info');
    expect(countdownState({...b, countEnd: 12}, 11, 10).value).toBe(3.5);
  });
  it('comment keyword types between typeStart and typeEnd', () => {
    const b = {type: 'comment-cta' as const, keyword: 'SPEED', typeStart: 3};
    const T = commentTimes(b, 1);
    expect(T.start).toBe(3);
    expect(T.end).toBeCloseTo(3 + 5 * 0.09, 6);
    expect(typedChars(b, 2.99, 1)).toBe(0);
    expect(typedChars(b, T.end, 1)).toBe(5);
    expect(typedChars({type: 'comment-cta', keyword: 'GO'}, 1.35, 1)).toBe(0);
  });
  it('un-timed blocks appear before their first timed part', () => {
    expect(explainerFirstTime(gauge())).toBeCloseTo(1.4, 6);
    expect(explainerFirstTime({type: 'chat-thread', messages: [{side: 'left', text: 'Hi', at: 3, typing: 1}]})).toBeCloseTo(1.75, 6);
    expect(explainerFirstTime({type: 'poll', question: 'Q?', options: [{text: 'A', at: 4}, {text: 'B', at: 5}]})).toBeCloseTo(3.5, 6);
    expect(firstInternalTime({type: 'notification', items: [{app: 'A', title: 'T', at: 2}]} as Block)).toBeCloseTo(1.8, 6);
    expect(explainerFirstTime({type: 'verdict', text: 'No'})).toBeUndefined();
  });
  it('the verdict tint rises fast and is gone ~0.56 s later', () => {
    expect(verdictTintAt(5, 4.99)).toBe(0);
    expect(verdictTintAt(5, 5.06)).toBeCloseTo(1, 6);
    expect(verdictTintAt(5, 5.3)).toBeGreaterThan(0);
    expect(verdictTintAt(5, 5.57)).toBe(0);
  });
});

describe('geometry: measured, fitted, no overflow', () => {
  const blocks: BlockV3[] = [
    gauge({label: 'Page speed score', caption: 'Mobile, home page'}),
    gauge({style: 'ring', suffix: '%', label: 'Uptime'}),
    {type: 'countdown', from: 7, decimals: 1, suffix: 's', label: 'Until they leave'},
    {type: 'chat-thread', title: 'Maya', messages: [{side: 'left', name: 'Maya Rao', text: 'Is my site down again? It has been slow since this morning and customers are writing in.', at: 1, time: '9:41'}, {side: 'right', text: 'On it.', at: 2}]},
    {type: 'notification', items: [{app: 'Uptime', title: 'Checkout page is down', body: 'Second outage this week. Customers cannot pay.', time: 'now', at: 1}, {app: 'Reviews', title: 'New review', at: 2}]},
    {type: 'term-reveal', kicker: 'This is called', term: 'Time to first byte', sub: 'How long the server takes to answer'},
    {type: 'term-reveal', term: 'Supercalifragilistic'},
    {type: 'verdict', text: 'Rejected', sub: 'Too slow'},
    {type: 'verdict', text: 'Approved by the team', tone: 'success'},
    {type: 'comment-cta', prompt: 'Want the checklist?', keyword: 'CHECKLIST', sub: 'One word is enough'},
    {type: 'poll', question: 'Which matters more for a small online shop today?', options: [{text: 'Speed', at: 1}, {text: 'A design that looks premium', at: 2}, {text: 'Price', at: 3}, {text: 'Support', at: 4}], pick: 1, pickAt: 5},
    {type: 'next-episode', label: 'Day 4', title: 'Fixing images without losing quality', sub: 'Tomorrow, same time'},
  ];
  it('every text fits its run at Short, split-column and landscape widths', () => {
    for (const b of blocks) {
      for (const col of [940, 700, 1929]) {
        const w = Math.min(naturalWidth(b as Block, col), col);
        const g = geomExplainer(b, w);
        expect(g.h).toBeGreaterThan(0);
        expect(measureBlock(b as Block, w, 5)).toBe(g.h);
        for (const s of g.texts) {
          expect(s.x).toBeGreaterThanOrEqual(-1e-6);
          expect(s.x + s.w).toBeLessThanOrEqual(w + 1e-6);
          expect(s.y + s.h).toBeLessThanOrEqual(g.h + 1e-6);
        }
      }
    }
  });
  it('natural widths: fixed per type, verdict sized by its own rotated stamp', () => {
    expect(EXPLAINER_NATURAL_W.gauge).toBe(760);
    const v = {type: 'verdict' as const, text: 'Rejected'};
    expect(verdictNaturalW(v)).toBeGreaterThan(600);
    const g = geomVerdict(v, verdictNaturalW(v));
    expect(g.fs).toBe(VERDICT.fs);
    const narrow = geomVerdict(v, 520);
    expect(narrow.fs).toBeLessThan(VERDICT.fs);
    const a = (Math.abs(VERDICT.rot) * Math.PI) / 180;
    expect(narrow.stamp.w * Math.cos(a) + narrow.stamp.h * Math.sin(a)).toBeLessThanOrEqual(520);
    expect(verdictMark(v)).toBe('cross');
    expect(verdictMark({type: 'verdict', text: 'OK', tone: 'success'})).toBe('check');
    expect(verdictMark({type: 'verdict', text: 'Hmm', tone: 'warning'})).toBe('none');
  });
  it('chat bubbles sit on their side, wrap long text and stack in order', () => {
    const b = blocks[3] as Extract<BlockV3, {type: 'chat-thread'}>;
    const g = geomChat(b, 900);
    expect(g.msgs[0].left).toBe(true);
    expect(g.msgs[1].bubble.x + g.msgs[1].bubble.w).toBeCloseTo(900 - 36 - (72 + 18), 6);
    expect(g.msgs[0].lines.length).toBeGreaterThan(1);
    expect(g.msgs[1].bubble.y).toBeGreaterThan(g.msgs[0].bubble.y + g.msgs[0].bubble.h);
    expect(g.msgs[0].avSpec?.text).toBe('MR');
    expect(initials('maya')).toBe('M');
  });
  it('term-reveal: one big line when it fits, two balanced lines otherwise', () => {
    expect(geomTerm({type: 'term-reveal', term: 'TTFB'}, 940).termLines.length).toBe(1);
    const two = geomTerm({type: 'term-reveal', term: 'Time to first byte'}, 940);
    expect(two.termLines.length).toBe(2);
    expect(two.fs).toBeGreaterThan(130);
    expect(geomTerm({type: 'term-reveal', term: 'Bounce rate', uppercase: false}, 940).term).toBe('Bounce rate');
  });
  it('notifications: newest on top; older ones are pushed down as each new one arrives', () => {
    const b = {type: 'notification' as const, items: [{app: 'A', title: 'First', at: 1}, {app: 'B', title: 'Second', at: 2}, {app: 'C', title: 'Third', at: 3}]};
    const g = geomNotification(b, 920);
    expect(noteOrder(b)).toEqual([2, 1, 0]);
    expect(g.slotY[2]).toBe(0);
    const hs = g.banners.map((x) => x.h);
    expect(noteShift(b, hs, 0, 1.5)).toBe(0);
    expect(noteShift(b, hs, 0, 10)).toBeCloseTo(g.slotY[0], 6);
    expect(noteShift(b, hs, 1, 10)).toBeCloseTo(g.slotY[1], 6);
    expect(noteShift(b, hs, 0, 2 + NOTE.slide)).toBeCloseTo(hs[1] + NOTE.gap, 6);
  });
});

describe('fixtures in both formats', () => {
  it('every block stays inside the safe area and above the caption band', () => {
    for (const p of [XS, XL]) {
      const env = makeEnv(p);
      const {width} = DIMENSIONS[p.format];
      const band = captionBandTop(p.format, p.captions);
      for (const s of p.scenes) {
        const P = planScene(env, s);
        for (const b of P.layout.boxes) {
          expect(b.y + b.h + P.reserve.y).toBeLessThanOrEqual(band + 1e-6);
          expect(b.x - P.reserve.x).toBeGreaterThanOrEqual(0);
          expect(b.x + b.w + P.reserve.x).toBeLessThanOrEqual(width + 1e-6);
        }
      }
    }
  });
  it('the manifest lists the texts of every v3 block, none overflowing', () => {
    for (const p of [XS, XL]) {
      const m = buildManifest(p);
      for (const s of m.scenes) {
        for (const b of s.blocks) {
          if (!(V3_BLOCK_TYPES as readonly string[]).includes(b.type)) continue;
          expect(b.texts.length).toBeGreaterThan(0);
          for (const t of b.texts) expect(t.overflow).toBe(false);
        }
      }
      const all = m.scenes.flatMap((s) => s.blocks.flatMap((b) => b.texts.map((t) => t.text)));
      for (const want of ['92', 'BOUNCE', 'REJECTED', 'SPEED', 'Hosting', 'PART 2', 'Checkout page is down', 'Is my site down again?'])
        expect(all.some((x) => x.includes(want))).toBe(true);
    }
  });
  it('split layouts work in 16:9 and fall back to a stack in 9:16', () => {
    const sc = XL.scenes.find((s) => s.id === 'score')!;
    const L = layoutScene(sc, 'landscape', XL.captions, false, makeEnv(XL).aspects);
    expect(L.split).toBe(true);
    expect(L.boxes[1].x).toBeGreaterThan(L.boxes[0].x + L.boxes[0].w);
    const Ls = layoutScene(XS.scenes.find((s) => s.id === 'score')!, 'short', XS.captions, false, makeEnv(XS).aspects);
    expect(Ls.split).toBe(false);
  });
  it('numbers rule: the gauge and countdown never show a value before its word', () => {
    for (const p of [XS, XL]) {
      for (const s of p.scenes) {
        for (const b of s.blocks) {
          if (b.type === 'gauge') {
            for (const k of b.keys) {
              const spoken = p.words.find((w) => w.start >= s.start - 1e-3 && w.text.replace(/[^\d]/g, '') === String(k.value));
              expect(spoken).toBeDefined();
              expect(k.at).toBeGreaterThanOrEqual(spoken!.start - 0.3);
              // nothing of this key is shown before its at
              expect(gaugeState(b, k.at - 0.01).readout).not.toBe(k.value);
            }
            expect(gaugeState(b, Math.min(...b.keys.map((k) => k.at)) - 0.01).started).toBe(false);
          }
          if (b.type === 'countdown') {
            const spoken = p.words.find((w) => w.start >= s.start - 1e-3 && w.text.replace(/[^\d]/g, '') === String(b.from));
            expect(b.at!).toBeGreaterThanOrEqual(spoken!.start - 0.3);
          }
        }
      }
    }
  });
});

describe('effects: cross annotation and verdict tints', () => {
  it('a cross is two strokes over the target, the second drawn after the first', () => {
    const a = annotationPath('cross', {x: 100, y: 100, w: 400, h: 100}, 7);
    expect(a.d.startsWith('M ')).toBe(true);
    expect(a.head).toBeDefined();
    expect(a.d).not.toBe(a.head);
    expect(crossDraw(0)).toEqual({first: 0, second: 0});
    expect(crossDraw(0.45).second).toBe(0);
    expect(crossDraw(0.55).first).toBe(1);
    expect(crossDraw(1)).toEqual({first: 1, second: 1});
  });
  it('verdict tints count as flashes: at most 3 in any second, and they mount the effect layer', () => {
    const vb = (at: number, tint?: boolean) => ({type: 'verdict' as const, text: 'No', at, tint});
    const scenes = [{id: 'a', start: 0, end: 2, transition: 'fade' as const, effects: [{type: 'flash' as const, at: 0.2}, {type: 'flash' as const, at: 0.3}], blocks: [vb(0.4), vb(0.5), vb(0.6, false)]}];
    const ev = flashEvents(scenes);
    expect(ev.map((e) => e.key)).toEqual(['a#0', 'a#1', 'a#verdict0', 'a#verdict1']);
    const ok = allowedFlashes(scenes);
    expect(ok.has('a#verdict0')).toBe(true);
    expect(ok.has('a#verdict1')).toBe(false);
    expect(maxFlashesPerWindow(ev.filter((e) => ok.has(e.key)).map((e) => e.t))).toBeLessThanOrEqual(3);
    expect(hasVerdictTint({blocks: [vb(1) as Block]})).toBe(true);
    expect(hasVerdictTint({blocks: [vb(1, false) as Block]})).toBe(false);
    expect(usesFx(XS)).toBe(true);
  });
});
