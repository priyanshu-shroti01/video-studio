/**
 * Pure geometry + state of the v3 explainer blocks (gauge, countdown, chat-thread, notification, term-reveal, verdict,
 * comment-cta, poll, next-episode), in design units relative to the block box. The renderer (blocks-explainer.tsx)
 * draws from these numbers and the QA manifest (texts.ts) reports them, like geometry.ts. Every block measures its own
 * height from its text, so layout.ts can fit it in both formats without overflow. No React / Remotion imports.
 */
import {formatNumber, Rect, T, TextSpec, wrapByWidth} from './geometry';
import {DUR} from './motion/durations';
import {EASE} from './motion/easings';
import {estimateTextWidth, fitFontSize, WEIGHT} from './motion/typography';
import {BlockV3, Tone} from './types';

type B<K extends BlockV3['type']> = Extract<BlockV3, {type: K}>;

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lin = (t: number, a: number, b: number) => (b <= a ? (t >= b ? 1 : 0) : clamp01((t - a) / (b - a)));
const est = (s: string, fs: number, weight: number = WEIGHT.heavy, ls = 0) => estimateTextWidth(s, fs, {weight, letterSpacing: ls});

/** Natural (maximum) design widths; `verdict` is sized by its own text (verdictNaturalW). */
export const EXPLAINER_NATURAL_W: Record<BlockV3['type'], number> = {
  gauge: 760,
  countdown: 620,
  'chat-thread': 900,
  notification: 920,
  'term-reveal': 1100,
  verdict: 0,
  'comment-cta': 900,
  poll: 880,
  'next-episode': 900,
};

/** Greedy wrap of `text` at `fs` into lines no wider than `maxW` (lines + their estimated widths). */
export const wrapLines = (text: string, fs: number, maxW: number, weight: number = WEIGHT.heavy, lsEm = 0) => {
  const words = text.split(/\s+/).filter(Boolean);
  const widths = words.map((x) => est(x, fs, weight, lsEm * fs));
  const gap = fs * 0.26;
  return wrapByWidth(words, widths, gap, maxW).map((ln) => ({text: ln.map((i) => words[i]).join(' '), w: ln.reduce((s, i) => s + widths[i], 0) + gap * (ln.length - 1)}));
};
/** Largest size ≤ fs at which the longest WORD of `text` fits `maxW` (wrapping handles the rest). */
const fitWords = (text: string, fs: number, maxW: number, weight: number, minFs: number, lsEm = 0) =>
  Math.min(fs, ...text.split(/\s+/).filter(Boolean).map((x) => fitFontSize(x, fs, maxW, {weight, minFs, letterSpacing: lsEm * fs})));

/** Points of an arc (degrees, 0 = top, clockwise) as an SVG path. A 360° sweep is drawn as two halves. */
export const polar = (cx: number, cy: number, r: number, deg: number) => {
  const a = (deg * Math.PI) / 180;
  return {x: cx + r * Math.sin(a), y: cy - r * Math.cos(a)};
};
const f2 = (x: number) => x.toFixed(2);
export const arcPath = (cx: number, cy: number, r: number, a0: number, sweep: number): string => {
  const s = Math.max(0, Math.min(360, sweep));
  if (s <= 0.001) return '';
  if (s >= 359.999) {
    const p0 = polar(cx, cy, r, a0);
    const pm = polar(cx, cy, r, a0 + 180);
    return `M ${f2(p0.x)} ${f2(p0.y)} A ${f2(r)} ${f2(r)} 0 0 1 ${f2(pm.x)} ${f2(pm.y)} A ${f2(r)} ${f2(r)} 0 0 1 ${f2(p0.x)} ${f2(p0.y)}`;
  }
  const p0 = polar(cx, cy, r, a0);
  const p1 = polar(cx, cy, r, a0 + s);
  return `M ${f2(p0.x)} ${f2(p0.y)} A ${f2(r)} ${f2(r)} 0 ${s > 180 ? 1 : 0} 1 ${f2(p1.x)} ${f2(p1.y)}`;
};

// ------------------------------------------------------------------------------------------------ gauge
export const GAUGE = {labelFs: 44, labelH: 64, captionFs: 34, captionH: 52, dur: DUR.slower, dial: {start: -120, sweep: 240}, ring: {start: 0, sweep: 360}, ticks: 11} as const;

export const gaugeRange = (b: B<'gauge'>) => {
  const min = b.min ?? 0;
  const max = b.max ?? Math.max(100, ...b.keys.map((k) => k.value));
  return {min, max: max > min ? max : min + 1};
};
export const gaugeText = (b: B<'gauge'>, v: number) => `${b.prefix ?? ''}${formatNumber(v, b.decimals ?? 0)}${b.suffix ?? ''}`;
const sortedKeys = <K extends {at: number}>(keys: K[]) => keys.map((k, i) => ({k, i})).sort((a, b) => a.k.at - b.k.at || a.i - b.i).map((x) => x.k);

/** Needle ease: a fast swing that overshoots ~4 % and settles exactly on 1 at q = 1 (a physical needle). */
export const needleEase = (q: number) => (q <= 0 ? 0 : q >= 1 ? 1 : 1 - (1 - q) ** 3 * Math.cos(1.2 * Math.PI * q));

/**
 * Value of the instrument at t. Key k moves from wherever the previous move left the value (the first from `min`) to
 * `k.value` over `k.dur` (default GAUGE.dur) starting exactly at `k.at`; a key that arrives early cuts the previous move
 * short, so the value is continuous. `started` is false before the first key (the readout is hidden then: no number
 * on screen before its word). `readout` never passes its target (ease-out); `needle` overshoots slightly.
 */
export const gaugeState = (b: B<'gauge'>, t: number) => {
  const {min, max} = gaugeRange(b);
  const keys = sortedKeys(b.keys);
  let readout = min;
  let needle = min;
  let started = false;
  let active = -1;
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    if (t < k.at) break;
    started = true;
    active = i;
    const nextAt = keys[i + 1]?.at ?? Infinity;
    const tt = Math.min(t, nextAt);
    const q = lin(tt, k.at, k.at + Math.max(0.05, k.dur ?? GAUGE.dur));
    const r0 = readout;
    const n0 = needle;
    readout = r0 + (k.value - r0) * EASE.outCubic(q);
    needle = n0 + (k.value - n0) * needleEase(q);
  }
  const k = 10 ** (b.decimals ?? 0);
  const shown = Math.round(readout * k) / k;
  return {started, active, readout: shown, needle: Math.min(max, Math.max(min, needle)), frac: (Math.min(max, Math.max(min, needle)) - min) / (max - min)};
};

/** Tone of the zone a value lies in (zones are ascending upper bounds; above the last bound = the last zone). */
export const zoneTone = (zones: {to: number; tone: Tone}[] | undefined, v: number): Tone | undefined => {
  if (!zones?.length) return undefined;
  const z = [...zones].sort((a, b) => a.to - b.to);
  return (z.find((x) => v <= x.to) ?? z[z.length - 1]).tone;
};

export const geomGauge = (b: B<'gauge'>, w: number) => {
  const style = b.style ?? 'dial';
  const G = GAUGE;
  const texts: TextSpec[] = [];
  let y = 0;
  if (b.label) {
    texts.push(T(b.label, 0, 0, w, G.labelH, fitFontSize(b.label, G.labelFs, w, {weight: WEIGHT.bold, minFs: 26}), WEIGHT.bold, 'center', 'label'));
    y = G.labelH + 14;
  }
  const dial = style === 'dial';
  const R = Math.round(w * (dial ? 0.4 : 0.36));
  const sw = Math.round(R * (dial ? 0.12 : 0.11));
  const cx = w / 2;
  const cy = y + 12 + sw / 2 + R;
  const {start, sweep} = dial ? G.dial : G.ring;
  const {min, max} = gaugeRange(b);
  const values = [min, max, ...b.keys.map((k) => k.value)];
  const widest = values.map((v) => gaugeText(b, v)).sort((p, q) => q.length - p.length)[0];
  const ls = -0.03;
  const readW = dial ? R * 1.15 : R * 1.32;
  const base = dial ? R * 0.5 : R * 0.6;
  const fs = Math.max(40, Math.floor(Math.min(base, (base * readW) / Math.max(1, est(widest, base, WEIGHT.heavy, ls * base)))));
  const readH = Math.round(fs * 1.1);
  const readY = dial ? cy + R * 0.5 - readH / 2 : cy - readH / 2;
  const last = sortedKeys(b.keys).at(-1);
  const readout = T(gaugeText(b, last ? last.value : min), cx - readW / 2, readY, readW, readH, fs, WEIGHT.heavy, 'center', /[₹$€£¥]/.test((b.prefix ?? '') + (b.suffix ?? '')) ? 'price' : 'title', {ls: ls * fs});
  texts.push(readout);
  let bottom = dial ? Math.max(cy + R * 0.5 + sw, readY + readH) : cy + R + sw / 2 + 12;
  if (b.caption) {
    bottom += 18;
    texts.push(T(b.caption, 0, bottom, w, G.captionH, fitFontSize(b.caption, G.captionFs, w, {weight: WEIGHT.semibold, minFs: 22}), WEIGHT.semibold, 'center', 'body'));
    bottom += G.captionH;
  }
  // ticks (dial): G.ticks marks inside the arc, the major ones (every 5th) longer
  const ticks = dial
    ? Array.from({length: (G.ticks - 1) * 2 + 1}, (_, i) => {
        const a = start + (sweep * i) / ((G.ticks - 1) * 2);
        const major = i % 2 === 0;
        const r0 = R - sw / 2 - 16;
        const r1 = r0 - (major ? 30 : 16);
        return {a, major, p0: polar(cx, cy, r0, a), p1: polar(cx, cy, r1, a)};
      })
    : [];
  return {style, R, sw, cx, cy, start, sweep, readout, ticks, needleLen: R * 0.78, hub: Math.max(14, R * 0.07), h: Math.ceil(bottom + 6), texts};
};

// ------------------------------------------------------------------------------------------------ countdown
export const COUNTDOWN = {labelFs: 42, labelH: 62, warn: 0.3, danger: 0.1} as const;
export const countdownText = (b: B<'countdown'>, v: number) => `${formatNumber(v, b.decimals ?? 0)}${b.suffix ?? ''}`;
/** End of the count: `countEnd`, else real time (|from − to| seconds after the start). */
export const countdownEnd = (b: B<'countdown'>, appear: number) => b.countEnd ?? appear + Math.abs(b.from - (b.to ?? 0));
/** Count value at t (rounded towards `from`, so 7.0 shows for the first tenth and 0.0 only at the end), the share of
 *  time left (1 → 0) and the urgency tone (warning ≤ 30 %, danger ≤ 10 % left) unless the block fixes a tone. */
export const countdownState = (b: B<'countdown'>, t: number, appear: number) => {
  const to = b.to ?? 0;
  const end = countdownEnd(b, appear);
  const p = lin(t, appear, end);
  const raw = b.from + (to - b.from) * p;
  const k = 10 ** (b.decimals ?? 0);
  const down = b.from >= to;
  const shown = p >= 1 ? to : (down ? Math.ceil(raw * k - 1e-9) : Math.floor(raw * k + 1e-9)) / k;
  const left = 1 - p;
  const tone: Tone = b.tone ?? (left <= COUNTDOWN.danger ? 'danger' : left <= COUNTDOWN.warn ? 'warning' : 'brand');
  return {value: shown, left, tone, done: p >= 1};
};
export const geomCountdown = (b: B<'countdown'>, w: number) => {
  const C = COUNTDOWN;
  const texts: TextSpec[] = [];
  let y = 0;
  if (b.label) {
    texts.push(T(b.label, 0, 0, w, C.labelH, fitFontSize(b.label, C.labelFs, w, {weight: WEIGHT.bold, minFs: 24}), WEIGHT.bold, 'center', 'label'));
    y = C.labelH + 14;
  }
  const R = Math.round(w * 0.4);
  const sw = Math.round(R * 0.1);
  const cx = w / 2;
  const cy = y + 14 + sw / 2 + R;
  const widest = [countdownText(b, b.from), countdownText(b, b.to ?? 0)].sort((p, q) => q.length - p.length)[0];
  const ls = -0.03;
  const base = R * 0.62;
  const readW = R * 1.36;
  const fs = Math.max(40, Math.floor(Math.min(base, (base * readW) / Math.max(1, est(widest, base, WEIGHT.heavy, ls * base)))));
  const readH = Math.round(fs * 1.1);
  const readout = T(countdownText(b, b.to ?? 0), cx - readW / 2, cy - readH / 2, readW, readH, fs, WEIGHT.heavy, 'center', 'title', {ls: ls * fs});
  texts.push(readout);
  return {R, sw, cx, cy, readout, ticks: 60, h: Math.ceil(cy + R + sw / 2 + 16), texts};
};

// ------------------------------------------------------------------------------------------------ chat-thread
export const CHAT = {pad: 36, headH: 100, avatar: 72, avGap: 18, fs: 46, lineH: 60, padX: 34, padY: 22, nameFs: 28, nameH: 42, timeFs: 26, timeH: 38, gap: 20, maxFrac: 0.8, typingW: 150, typingH: 92, typing: 0.6} as const;
export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((x) => [...x][0] ?? '')
    .join('')
    .toUpperCase();
export const chatTypingDur = (m: {typing?: number}) => Math.max(0, m.typing ?? CHAT.typing);

export const geomChat = (b: B<'chat-thread'>, w: number) => {
  const C = CHAT;
  const texts: TextSpec[] = [];
  const hasAv = b.messages.some((m) => m.name);
  const avSlot = hasAv ? C.avatar + C.avGap : 0;
  const innerW = w - 2 * C.pad;
  let y = C.pad;
  let header: {y: number; h: number} | undefined;
  if (b.title) {
    texts.push(T(b.title, C.pad + 8, y, innerW - 16, C.headH - 20, fitFontSize(b.title, 44, innerW - 16, {weight: WEIGHT.heavy, minFs: 24}), WEIGHT.heavy, 'center', 'title'));
    header = {y: y + C.headH - 20, h: 2};
    y += C.headH;
  }
  const maxBW = (innerW - avSlot) * C.maxFrac;
  const fs = Math.min(C.fs, ...b.messages.map((m) => fitWords(m.text, C.fs, maxBW - 2 * C.padX, WEIGHT.semibold, 24)));
  const lineH = Math.round(fs * (C.lineH / C.fs));
  const msgs = b.messages.map((m, i) => {
    const prev = b.messages[i - 1];
    const left = m.side !== 'right';
    let name: TextSpec | undefined;
    if (m.name && (!prev || prev.side !== m.side || prev.name !== m.name)) {
      const nx = left ? C.pad + avSlot + 8 : C.pad;
      name = T(m.name, nx, y, innerW - avSlot - 8, C.nameH, fitFontSize(m.name, C.nameFs, innerW - avSlot - 8, {weight: WEIGHT.bold, minFs: 20}), WEIGHT.bold, left ? 'left' : 'right', 'label');
      texts.push(name);
      y += C.nameH;
    }
    const lines = wrapLines(m.text, fs, maxBW - 2 * C.padX, WEIGHT.semibold);
    const bw = Math.max(fs * 2.2, ...lines.map((l) => l.w)) + 2 * C.padX;
    const bh = lines.length * lineH + 2 * C.padY;
    const bx = left ? C.pad + avSlot : w - C.pad - avSlot - bw;
    const bubble: Rect = {x: bx, y, w: bw, h: bh};
    const lineSpecs = lines.map((l, li) => T(l.text, bx + C.padX, y + C.padY + li * lineH, bw - 2 * C.padX + 1, lineH, fs, WEIGHT.semibold, 'left', 'body'));
    texts.push(...lineSpecs);
    const avatar = m.name ? {x: left ? C.pad : w - C.pad - C.avatar, y: y + bh - C.avatar, s: C.avatar, text: initials(m.name)} : undefined;
    let avSpec: TextSpec | undefined;
    if (avatar && avatar.text) {
      avSpec = T(avatar.text, avatar.x, avatar.y, avatar.s, avatar.s, fitFontSize(avatar.text, 30, avatar.s - 16, {weight: WEIGHT.heavy, minFs: 16}), WEIGHT.heavy, 'center', 'label');
      texts.push(avSpec);
    }
    const typing: Rect = {x: left ? bx : w - C.pad - avSlot - C.typingW, y, w: C.typingW, h: C.typingH};
    y += bh;
    let time: TextSpec | undefined;
    if (m.time) {
      time = T(m.time, bx, y + 4, bw, C.timeH - 4, C.timeFs, WEIGHT.semibold, left ? 'left' : 'right', 'label');
      texts.push(time);
      y += C.timeH;
    }
    y += C.gap;
    return {left, bubble, lines: lineSpecs, name, avatar, avSpec, time, typing};
  });
  const h = y - C.gap + C.pad;
  return {fs, lineH, header, msgs, h: Math.ceil(h), texts};
};

// ------------------------------------------------------------------------------------------------ notification
export const NOTE = {pad: 32, tile: 92, appFs: 30, appH: 44, titleFs: 44, titleH: 58, bodyFs: 36, bodyLH: 48, gap: 22, radius: 44, timeFs: 28, slide: 0.35} as const;
/** Item indices newest first (by `at`, then index): the final top-to-bottom order of the stack. */
export const noteOrder = (b: B<'notification'>) => b.items.map((it, i) => ({at: it.at, i})).sort((a, c) => c.at - a.at || c.i - a.i).map((x) => x.i);

export const geomNotification = (b: B<'notification'>, w: number) => {
  const N = NOTE;
  const textX = N.pad + N.tile + 24;
  const textW = w - textX - N.pad;
  const banners = b.items.map((it) => {
    const specs: TextSpec[] = [];
    const timeW = it.time ? est(it.time, N.timeFs, WEIGHT.semibold) : 0;
    specs.push(T(it.app, textX, N.pad, textW - (timeW ? timeW + 16 : 0), N.appH, fitFontSize(it.app, N.appFs, textW - (timeW ? timeW + 16 : 0), {weight: WEIGHT.bold, minFs: 20}), WEIGHT.bold, 'left', 'label'));
    if (it.time) specs.push(T(it.time, textX, N.pad, textW, N.appH, N.timeFs, WEIGHT.semibold, 'right', 'label'));
    let y = N.pad + N.appH + 2;
    specs.push(T(it.title, textX, y, textW, N.titleH, fitFontSize(it.title, N.titleFs, textW, {weight: WEIGHT.heavy, minFs: 26}), WEIGHT.heavy, 'left', 'title'));
    y += N.titleH;
    if (it.body) {
      const bfs = fitWords(it.body, N.bodyFs, textW, WEIGHT.semibold, 22);
      const lh = Math.round(bfs * (N.bodyLH / N.bodyFs));
      for (const l of wrapLines(it.body, bfs, textW, WEIGHT.semibold)) {
        specs.push(T(l.text, textX, y, textW, lh, bfs, WEIGHT.semibold, 'left', 'body'));
        y += lh;
      }
    }
    const h = Math.max(N.pad * 2 + N.tile, y + N.pad);
    return {h, tile: {x: N.pad, y: N.pad, s: N.tile}, specs, letter: initials(it.app).slice(0, 1)};
  });
  const order = noteOrder(b);
  const slotY: number[] = new Array(b.items.length).fill(0);
  let y = 0;
  for (const i of order) {
    slotY[i] = y;
    y += banners[i].h + N.gap;
  }
  const texts: TextSpec[] = [];
  for (const i of order) for (const s of banners[i].specs) texts.push({...s, y: s.y + slotY[i]});
  return {banners, order, slotY, h: Math.ceil(Math.max(1, y - N.gap)), texts};
};
/** Offset (design px) of item i at t: every newer item pushes it down by its own height + gap as it arrives. */
export const noteShift = (b: B<'notification'>, heights: number[], i: number, t: number) => {
  let dy = 0;
  b.items.forEach((it, j) => {
    const newer = it.at > b.items[i].at || (it.at === b.items[i].at && j > i);
    if (newer) dy += (heights[j] + NOTE.gap) * EASE.outCubic(lin(t, it.at - 0.05, it.at - 0.05 + NOTE.slide));
  });
  return dy;
};

// ------------------------------------------------------------------------------------------------ term-reveal
export const TERM = {kickerFs: 46, kickerH: 66, gap: 22, fs: 210, minFs: 84, lh: 1.02, ls: -0.025, subFs: 42, subLH: 56, bar: 12, slam: 1.38} as const;
export const termAtOf = (b: B<'term-reveal'>, appear: number) => b.termAt ?? appear + 0.6;
export const subAtOf = (b: B<'term-reveal'>, appear: number) => b.subAt ?? termAtOf(b, appear) + 0.45;

export const geomTerm = (b: B<'term-reveal'>, w: number) => {
  const M = TERM;
  const texts: TextSpec[] = [];
  let y = 0;
  let kicker: (TextSpec & {rule: number; kw: number}) | undefined;
  if (b.kicker) {
    const fs = fitFontSize(b.kicker, M.kickerFs, w * 0.8, {weight: WEIGHT.bold, minFs: 26});
    const kw = est(b.kicker, fs, WEIGHT.bold);
    const s = T(b.kicker, 0, 0, w, M.kickerH, fs, WEIGHT.bold, 'center', 'label');
    texts.push(s);
    kicker = {...s, rule: Math.max(0, Math.min(110, (w - kw) / 2 - 28)), kw};
    y = M.kickerH + M.gap;
  }
  const term = b.uppercase === false ? b.term : b.term.toUpperCase();
  const widthAt = (s: string, fs: number) => est(s, fs, WEIGHT.heavy, M.ls * fs);
  const words = term.split(/\s+/).filter(Boolean);
  const one = Math.floor(Math.min(M.fs, (M.fs * w) / Math.max(1, widthAt(term, M.fs))));
  let lines: string[] = [term];
  let fs = one;
  if (one < 130 && words.length > 1) {
    // two balanced lines: the split whose wider line is narrowest
    let best = {k: 1, mw: Infinity};
    for (let k = 1; k < words.length; k++) {
      const mw = Math.max(widthAt(words.slice(0, k).join(' '), M.fs), widthAt(words.slice(k).join(' '), M.fs));
      if (mw < best.mw) best = {k, mw};
    }
    const two = Math.floor(Math.min(M.fs, (M.fs * w) / best.mw));
    if (two > one) {
      lines = [words.slice(0, best.k).join(' '), words.slice(best.k).join(' ')];
      fs = two;
    }
  }
  fs = Math.max(M.minFs, fs);
  const lh = Math.round(fs * M.lh);
  const termLines = lines.map((l, i) => T(l, 0, y + i * lh, w, lh, fs, WEIGHT.heavy, 'center', 'title', {ls: M.ls * fs}));
  texts.push(...termLines);
  y += lines.length * lh;
  const widest = Math.max(...lines.map((l) => widthAt(l, fs)));
  const bar: Rect = {x: (w - Math.min(widest * 0.42, 380)) / 2, y: y + 14, w: Math.min(widest * 0.42, 380), h: M.bar};
  y = bar.y + bar.h;
  const subs: TextSpec[] = [];
  if (b.sub) {
    y += 26;
    const sfs = fitWords(b.sub, M.subFs, w * 0.92, WEIGHT.semibold, 24);
    for (const l of wrapLines(b.sub, sfs, w * 0.92, WEIGHT.semibold)) {
      const s = T(l.text, 0, y, w, M.subLH, sfs, WEIGHT.semibold, 'center', 'body');
      subs.push(s);
      texts.push(s);
      y += M.subLH;
    }
  }
  return {kicker, term, termLines, fs, lh, bar, subs, h: Math.ceil(y + 8), texts};
};

// ------------------------------------------------------------------------------------------------ verdict
export const VERDICT = {fs: 150, minFs: 28, padX: 54, padY: 24, border: 10, inset: 15, rot: -6, radius: 26, ls: 0.06, mark: 0.8, markGap: 0.28, subFs: 40, subH: 58, margin: 14, slam: 1.32} as const;
export const verdictMark = (b: B<'verdict'>) => b.mark ?? ((b.tone ?? 'danger') === 'success' ? 'check' : (b.tone ?? 'danger') === 'danger' ? 'cross' : 'none');
export const verdictTone = (b: B<'verdict'>): Tone => b.tone ?? 'danger';
const verdictSize = (b: B<'verdict'>, fs: number) => {
  const V = VERDICT;
  const text = b.text.toUpperCase();
  const tw = est(text, fs, WEIGHT.heavy, V.ls * fs);
  const m = verdictMark(b) !== 'none' ? fs * (V.mark + V.markGap) : 0;
  const sw = 2 * V.padX + m + tw;
  const sh = fs * 1.16 + 2 * V.padY;
  const a = (Math.abs(V.rot) * Math.PI) / 180;
  return {text, tw, m, sw, sh, bw: sw * Math.cos(a) + sh * Math.sin(a), bh: sw * Math.sin(a) + sh * Math.cos(a)};
};
/** Natural width: the rotated stamp at full size, plus a margin for the slam's settle. */
export const verdictNaturalW = (b: B<'verdict'>) => Math.ceil(verdictSize(b, VERDICT.fs).bw + 2 * VERDICT.margin);

export const geomVerdict = (b: B<'verdict'>, w: number) => {
  const V = VERDICT;
  let fs: number = V.fs;
  while (fs > V.minFs && verdictSize(b, fs).bw + 2 * V.margin > w) fs -= 2;
  const s = verdictSize(b, fs);
  const texts: TextSpec[] = [];
  const stamp: Rect = {x: (w - s.sw) / 2, y: V.margin + (s.bh - s.sh) / 2, w: s.sw, h: s.sh};
  const mark = s.m ? {x: stamp.x + V.padX, y: stamp.y + (s.sh - fs * V.mark) / 2, s: fs * V.mark} : undefined;
  const text = T(s.text, stamp.x + V.padX + s.m, stamp.y + V.padY, s.sw - 2 * V.padX - s.m, fs * 1.16, fs, WEIGHT.heavy, 'left', 'title', {ls: V.ls * fs});
  texts.push(text);
  let h = V.margin * 2 + s.bh;
  let sub: TextSpec | undefined;
  if (b.sub) {
    h += 10;
    sub = T(b.sub, 0, h, w, V.subH, fitFontSize(b.sub, V.subFs, w, {weight: WEIGHT.bold, minFs: 24}), WEIGHT.bold, 'center', 'body');
    texts.push(sub);
    h += V.subH;
  }
  return {fs, stamp, mark, text, sub, rot: V.rot, h: Math.ceil(h), texts};
};
/** Full-frame tint of a verdict (0..1): fast attack on the slam, then a ~0.5 s fade. 0 outside its window. */
export const VERDICT_TINT = {attack: 0.06, decay: 0.5, max: 1} as const;
export const verdictTintAt = (at: number, t: number) => {
  const tau = t - at;
  if (tau < 0 || tau >= VERDICT_TINT.attack + VERDICT_TINT.decay) return 0;
  if (tau < VERDICT_TINT.attack) return EASE.outQuad(tau / VERDICT_TINT.attack);
  const q = (tau - VERDICT_TINT.attack) / VERDICT_TINT.decay;
  return (1 - q) * (1 - q);
};

// ------------------------------------------------------------------------------------------------ comment-cta
export const COMMENT = {promptFs: 76, promptH: 100, boxH: 168, avatar: 104, send: 116, kwFs: 80, subFs: 42, subLH: 56, gap: 30, pad: 32, charDur: 0.09, maxType: 1.0} as const;
export const commentTimes = (b: B<'comment-cta'>, appear: number) => {
  const start = b.typeStart ?? appear + 0.35;
  const end = b.typeEnd ?? start + Math.min(COMMENT.maxType, COMMENT.charDur * Math.max(1, [...b.keyword].length));
  return {start, end: Math.max(end, start + 0.05), send: b.sendAt};
};
/** Characters of the keyword typed at t. */
export const typedChars = (b: B<'comment-cta'>, t: number, appear: number) => {
  const {start, end} = commentTimes(b, appear);
  return Math.floor([...b.keyword].length * lin(t, start, end) + 1e-9);
};
export const geomComment = (b: B<'comment-cta'>, w: number) => {
  const C = COMMENT;
  const texts: TextSpec[] = [];
  let y = 0;
  let prompt: TextSpec | undefined;
  if (b.prompt) {
    prompt = T(b.prompt, 0, 0, w, C.promptH, fitFontSize(b.prompt, C.promptFs, w, {weight: WEIGHT.heavy, minFs: 34, letterSpacing: -1}), WEIGHT.heavy, 'center', 'title', {ls: -1});
    texts.push(prompt);
    y = C.promptH + C.gap;
  }
  const box: Rect = {x: 0, y, w, h: C.boxH};
  const avatar = {x: C.pad, y: y + (C.boxH - C.avatar) / 2, s: C.avatar};
  const send = {x: w - C.pad - C.send, y: y + (C.boxH - C.send) / 2, s: C.send};
  const kx = C.pad + C.avatar + 28;
  const kw = send.x - 30 - 24 - kx;
  const keyword = T(b.keyword, kx, y, kw, C.boxH, fitFontSize(b.keyword, C.kwFs, kw, {weight: WEIGHT.heavy, minFs: 30}), WEIGHT.heavy, 'left', 'title');
  texts.push(keyword);
  y += C.boxH;
  const subs: TextSpec[] = [];
  if (b.sub) {
    y += 22;
    const sfs = fitWords(b.sub, C.subFs, w * 0.94, WEIGHT.semibold, 22);
    for (const l of wrapLines(b.sub, sfs, w * 0.94, WEIGHT.semibold)) {
      const s = T(l.text, 0, y, w, C.subLH, sfs, WEIGHT.semibold, 'center', 'body');
      subs.push(s);
      texts.push(s);
      y += C.subLH;
    }
  }
  return {prompt, box, avatar, send, keyword, subs, h: Math.ceil(y + 6), texts};
};

// ------------------------------------------------------------------------------------------------ poll
export const POLL = {pad: 48, qFs: 60, qLH: 74, optH: 128, optGap: 22, radio: 48, optFs: 48, fill: 0.5} as const;
export const geomPoll = (b: B<'poll'>, w: number) => {
  const P = POLL;
  const texts: TextSpec[] = [];
  const inner = w - 2 * P.pad;
  let y = P.pad;
  const qfs = fitWords(b.question, P.qFs, inner, WEIGHT.heavy, 28);
  const qlh = Math.round(qfs * (P.qLH / P.qFs));
  const question = wrapLines(b.question, qfs, inner).map((l, i) => T(l.text, P.pad, y + i * qlh, inner, qlh, qfs, WEIGHT.heavy, 'left', 'title'));
  texts.push(...question);
  y += question.length * qlh + 30;
  const tx = P.pad + 34 + P.radio + 24;
  const tw = w - P.pad - 34 - tx;
  const fs = Math.min(P.optFs, ...b.options.map((o) => fitFontSize(o.text, P.optFs, tw, {weight: WEIGHT.bold, minFs: 24})));
  const options = b.options.map((o, i) => {
    const r: Rect = {x: P.pad, y: y + i * (P.optH + P.optGap), w: inner, h: P.optH};
    const s = T(o.text, tx, r.y, tw, P.optH, fs, WEIGHT.bold, 'left', 'label');
    texts.push(s);
    return {rect: r, radio: {x: P.pad + 34, y: r.y + (P.optH - P.radio) / 2, s: P.radio}, text: s};
  });
  y += b.options.length * P.optH + Math.max(0, b.options.length - 1) * P.optGap + P.pad;
  return {question, options, h: Math.ceil(y), texts};
};

// ------------------------------------------------------------------------------------------------ next-episode
export const NEXT = {pad: 52, labelFs: 36, labelH: 70, play: 120, titleFs: 82, titleLH: 94, subFs: 44, subLH: 58, barH: 14, fill: 2.4} as const;
export const geomNext = (b: B<'next-episode'>, w: number) => {
  const X = NEXT;
  const texts: TextSpec[] = [];
  const inner = w - 2 * X.pad;
  const play = {x: w - X.pad - X.play, y: X.pad - 6, s: X.play};
  const label = b.label.toUpperCase();
  const lls = 2;
  const lfs = fitFontSize(label, X.labelFs, inner - X.play - 80, {weight: WEIGHT.heavy, minFs: 20, letterSpacing: lls});
  const lw = Math.min(inner - X.play - 24, est(label, lfs, WEIGHT.heavy, lls) + 56);
  const pill: Rect = {x: X.pad, y: X.pad + (X.play - 12 - X.labelH) / 2, w: lw, h: X.labelH};
  texts.push(T(label, pill.x + 28, pill.y, lw - 56, X.labelH, lfs, WEIGHT.heavy, 'center', 'label', {ls: lls}));
  let y = X.pad + X.play + 18;
  const tfs = fitWords(b.title, X.titleFs, inner, WEIGHT.heavy, 36, -0.02);
  const tlh = Math.round(tfs * (X.titleLH / X.titleFs));
  const title = wrapLines(b.title, tfs, inner, WEIGHT.heavy, -0.02).map((l, i) => T(l.text, X.pad, y + i * tlh, inner, tlh, tfs, WEIGHT.heavy, 'left', 'title', {ls: -0.02 * tfs}));
  texts.push(...title);
  y += title.length * tlh;
  const subs: TextSpec[] = [];
  if (b.sub) {
    y += 10;
    const sfs = fitWords(b.sub, X.subFs, inner, WEIGHT.semibold, 22);
    for (const l of wrapLines(b.sub, sfs, inner, WEIGHT.semibold)) {
      const s = T(l.text, X.pad, y, inner, X.subLH, sfs, WEIGHT.semibold, 'left', 'body');
      subs.push(s);
      texts.push(s);
      y += X.subLH;
    }
  }
  y += 34;
  const bar: Rect = {x: X.pad, y, w: inner, h: X.barH};
  y += X.barH + X.pad;
  return {play, pill, title, subs, bar, h: Math.ceil(y), texts};
};

// ------------------------------------------------------------------------------------------------ shared entry points
export const isExplainer = (b: {type: string}): b is BlockV3 => b.type in EXPLAINER_NATURAL_W;

export const explainerNaturalW = (b: BlockV3) => (b.type === 'verdict' ? verdictNaturalW(b) : EXPLAINER_NATURAL_W[b.type]);

/** Geometry (texts + height) of any explainer block at design width w. */
export const geomExplainer = (b: BlockV3, w: number): {h: number; texts: TextSpec[]} => {
  switch (b.type) {
    case 'gauge':
      return geomGauge(b, w);
    case 'countdown':
      return geomCountdown(b, w);
    case 'chat-thread':
      return geomChat(b, w);
    case 'notification':
      return geomNotification(b, w);
    case 'term-reveal':
      return geomTerm(b, w);
    case 'verdict':
      return geomVerdict(b, w);
    case 'comment-cta':
      return geomComment(b, w);
    case 'poll':
      return geomPoll(b, w);
    case 'next-episode':
      return geomNext(b, w);
  }
};

/** Earliest internal reveal of an un-timed explainer block (it is on screen before its first timed part). */
export const explainerFirstTime = (b: BlockV3): number | undefined => {
  const min = (xs: number[]) => (xs.length ? Math.min(...xs) : undefined);
  switch (b.type) {
    case 'gauge': {
      const m = min(b.keys.map((k) => k.at));
      return m === undefined ? undefined : m - 0.6;
    }
    case 'chat-thread': {
      const m = min(b.messages.map((x) => x.at - chatTypingDur(x)));
      return m === undefined ? undefined : m - 0.25;
    }
    case 'notification': {
      const m = min(b.items.map((x) => x.at));
      return m === undefined ? undefined : m - 0.2;
    }
    case 'poll': {
      const m = min(b.options.map((x) => x.at));
      return m === undefined ? undefined : m - 0.5;
    }
    case 'term-reveal':
      return b.termAt !== undefined ? b.termAt - 0.6 : undefined;
    case 'comment-cta':
      return b.typeStart !== undefined ? b.typeStart - 0.35 : undefined;
    default:
      return undefined;
  }
};
