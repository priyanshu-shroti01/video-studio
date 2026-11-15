/**
 * v3 HUD: persistent overlay elements (header, term chips, series / chapter bar, stakes chip) that live across
 * scenes at the top of the frame. Pure (no React / Remotion): the renderer (hud-view.tsx), the scene planner
 * (plan.ts, which keeps content below the HUD) and the QA layout manifest all read this one plan.
 *
 * Time: Python resolves every event's `at` from an `@word:` anchor; a change starts HUD.lead before it, so the motion
 * peaks on the word. An element is hidden until its first event and after a `hide`.
 * Space: the HUD has fixed rows for the whole video (header + stakes, bar, chips), so nothing jumps when an element
 * appears; each scene reserves down to the lowest row visible during it (`hudBottomFor`).
 */
import {DIMENSIONS} from './contract';
import {formatNumber, Rect} from './geometry';
import {estimateTextWidth} from './motion/typography';
import {Format, Hud, HudElement, HudEvent, RenderProps, Tone} from './types';

/** Design px at the 1080-wide Short scale (× FORMAT_SPEC.k), seconds for times. */
export const HUD = {
  side: {short: 70, landscape: 140},
  top: {short: 130, landscape: 70},
  k: {short: 1, landscape: 0.85},
  rowGap: 16,
  /** space between the HUD's lowest visible row and the scene content */
  gapBelow: 30,
  /** below the brand bar when the bar is on screen while the HUD is */
  barGap: 20,
  header: {fs: 34, minFs: 24, h: 56, track: 0.14},
  stakes: {fs: 28, minFs: 20, h: 56, padX: 24, track: 0.02},
  progress: {fs: 26, h: 30, bar: 10, labelGap: 22, segGap: 8},
  chips: {fs: 26, minFs: 20, h: 50, padX: 20, gap: 12, dot: 10, dotGap: 12, maxRows: 2, track: 0.06},
  /** a change starts this long before its word */
  lead: 0.06,
  fadeOut: 0.3,
  swap: 0.42,
  fill: 0.8,
  count: 0.6,
  /** a chip just added stays highlighted this long, then settles over `settle` */
  fresh: 1.1,
  settle: 0.5,
} as const;

export const hudEnabled = (props: Pick<RenderProps, 'contractVersion' | 'hud'>) =>
  props.contractVersion >= 3 && !!props.hud && Array.isArray(props.hud.elements) && props.hud.elements.length > 0;

// ---------------------------------------------------------------------------------------------------------------
// State: a timeline of segments per element, folded from the sorted events.
// ---------------------------------------------------------------------------------------------------------------

export type HudChip = {text: string; tone?: Tone; at: number};
export type HudState =
  | {kind: 'header'; index: number}
  | {kind: 'progress'; value: number}
  | {kind: 'stakes'; values: (number | undefined)[]; tones: (Tone | undefined)[]}
  | {kind: 'chips'; chips: HudChip[]};
/** From `from` (an event's start = at − lead) until the next segment the element is in `state`. */
export type HudSegment = {from: number; to: number; visible: boolean; state: HudState};
export type HudTrack = {el: HudElement; segments: HudSegment[]; ranges: [number, number][]};

const initialState = (el: HudElement): HudState => {
  switch (el.kind) {
    case 'header':
      return {kind: 'header', index: 0};
    case 'progress':
      return {kind: 'progress', value: el.value ?? 0};
    case 'stakes':
      return {kind: 'stakes', values: el.parts.map((p) => p.value), tones: el.parts.map((p) => p.tone)};
    case 'chips':
      return {kind: 'chips', chips: []};
  }
};

const clampInt = (v: number, a: number, b: number) => Math.min(b, Math.max(a, Math.round(v)));

/** The state after `ev` (unknown ops / fields are ignored, never thrown: Python validated them). */
const apply = (el: HudElement, s: HudState, ev: HudEvent, t0: number): HudState => {
  if (ev.op === 'show' || ev.op === 'hide') return s;
  if (el.kind === 'header' && s.kind === 'header') {
    const n = el.steps.length;
    if (ev.op === 'advance') return {kind: 'header', index: Math.min(n - 1, s.index + 1)};
    if (ev.op === 'set' && ev.index !== undefined) return {kind: 'header', index: clampInt(ev.index, 0, n - 1)};
  }
  if (el.kind === 'progress' && s.kind === 'progress') {
    if (ev.op === 'advance') return {kind: 'progress', value: Math.min(el.total, s.value + 1)};
    if (ev.op === 'set' && ev.value !== undefined) return {kind: 'progress', value: Math.min(el.total, Math.max(0, ev.value))};
  }
  if (el.kind === 'stakes' && s.kind === 'stakes' && ev.op === 'set') {
    const i = ev.part ?? 0;
    if (i < 0 || i >= el.parts.length) return s;
    const values = [...s.values];
    const tones = [...s.tones];
    if (ev.value !== undefined) values[i] = ev.value;
    if (ev.tone !== undefined) tones[i] = ev.tone;
    return {kind: 'stakes', values, tones};
  }
  if (el.kind === 'chips' && s.kind === 'chips' && ev.op === 'add' && ev.text) {
    return {kind: 'chips', chips: [...s.chips, {text: ev.text, tone: ev.tone, at: t0}]};
  }
  return s;
};

/** Events sorted by time (stable: equal times keep their order). */
export const sortedEvents = (hud: Hud): HudEvent[] =>
  hud.events.map((e, i) => [e, i] as const).sort((a, b) => a[0].at - b[0].at || a[1] - b[1]).map(([e]) => e);

export const hudTracks = (hud: Hud, duration: number): HudTrack[] => {
  const evs = sortedEvents(hud);
  return hud.elements.map((el) => {
    let s = initialState(el);
    const segments: HudSegment[] = [{from: -Infinity, to: Infinity, visible: false, state: s}];
    for (const ev of evs) {
      if (ev.target !== el.id) continue;
      const t0 = ev.at - HUD.lead;
      s = apply(el, s, ev, t0);
      segments[segments.length - 1].to = t0;
      segments.push({from: t0, to: Infinity, visible: ev.op !== 'hide', state: s});
    }
    const ranges: [number, number][] = [];
    for (let i = 0; i < segments.length; i++) {
      const g = segments[i];
      if (!g.visible) continue;
      const last = ranges[ranges.length - 1];
      const end = g.to === Infinity ? duration : g.to;
      if (last && Math.abs(last[1] - g.from) < 1e-9) last[1] = end;
      else ranges.push([g.from, end]);
    }
    // a hide fades out: the element is still drawn for HUD.fadeOut after it
    for (const r of ranges) if (r[1] < duration) r[1] = Math.min(duration, r[1] + HUD.fadeOut);
    return {el, segments, ranges: ranges.map(([a, b]) => [r3(a), r3(b)] as [number, number])};
  });
};

const r3 = (x: number) => Math.round(x * 1000) / 1000;

/** The segment the element is in at t, and the one before it. */
export const segmentAt = (track: HudTrack, t: number): {seg: HudSegment; prev: HudSegment | undefined} => {
  let i = 0;
  while (i + 1 < track.segments.length && track.segments[i + 1].from <= t) i++;
  return {seg: track.segments[i], prev: i > 0 ? track.segments[i - 1] : undefined};
};

// ---------------------------------------------------------------------------------------------------------------
// Texts (shared by geometry, renderer and manifest)
// ---------------------------------------------------------------------------------------------------------------

export const headerParts = (el: Extract<HudElement, {kind: 'header'}>, index: number): {lead: string; name: string} => {
  const name = (el.steps[index] ?? '').toUpperCase();
  if (!el.prefix) return {lead: '', name};
  const lead = el.numbered === false ? el.prefix.toUpperCase() : `${el.prefix.toUpperCase()} ${index + 1}`;
  return {lead, name};
};
export const headerText = (el: Extract<HudElement, {kind: 'header'}>, index: number) => {
  const p = headerParts(el, index);
  return p.lead ? `${p.lead} · ${p.name}` : p.name;
};

const padNum = (v: number, n: number) => String(Math.round(Math.max(0, v))).padStart(n, '0');
export const progressPad = (el: Extract<HudElement, {kind: 'progress'}>) => el.pad ?? String(el.total).length;
export const progressText = (el: Extract<HudElement, {kind: 'progress'}>, value: number) => {
  const n = progressPad(el);
  const count = `${padNum(value, n)} / ${padNum(el.total, n)}`;
  return el.label ? `${el.label.toUpperCase()} ${count}` : count;
};

type StakesEl = Extract<HudElement, {kind: 'stakes'}>;
export const stakesValueText = (p: StakesEl['parts'][number], v: number | undefined) =>
  v === undefined ? '' : `${p.prefix ?? ''}${formatNumber(Math.round(v), 0, 'western')}${p.suffix ?? ''}`;
export const stakesPartText = (p: StakesEl['parts'][number], v: number | undefined) => {
  const n = stakesValueText(p, v);
  return n ? `${n} ${p.label}` : p.label;
};
export const STAKES_SEP = '  ·  ';
export const stakesText = (el: StakesEl, values: (number | undefined)[]) => el.parts.map((p, i) => stakesPartText(p, values[i])).join(STAKES_SEP);

// ---------------------------------------------------------------------------------------------------------------
// Geometry (output px)
// ---------------------------------------------------------------------------------------------------------------

export type HudHeaderBox = Rect & {kind: 'header'; fs: number; ls: number};
export type HudStakesBox = Rect & {kind: 'stakes'; fs: number; ls: number; padX: number};
export type HudProgressBox = Rect & {kind: 'progress'; fs: number; bar: Rect; label: Rect | null};
export type HudChipsBox = Rect & {kind: 'chips'; fs: number; ls: number; chipH: number; items: Rect[]; overflow: boolean};
export type HudBox = HudHeaderBox | HudStakesBox | HudProgressBox | HudChipsBox;

export type HudPlan = {
  format: Format;
  k: number;
  x0: number;
  w: number;
  y0: number;
  tracks: HudTrack[];
  boxes: Record<string, HudBox>;
  /** union of every element's visible ranges */
  ranges: [number, number][];
};

const HEADER_W = 800;
const CHIP_W = 700;

const headerWidth = (s: string, fs: number) => estimateTextWidth(s, fs, {weight: HEADER_W, letterSpacing: fs * HUD.header.track});
const stakesWidth = (s: string, fs: number) => estimateTextWidth(s, fs, {weight: 800, letterSpacing: fs * HUD.stakes.track});
const chipTextWidth = (s: string, fs: number) => estimateTextWidth(s.toUpperCase(), fs, {weight: CHIP_W, letterSpacing: fs * HUD.chips.track});
export const chipWidth = (s: string, fs: number, k: number) =>
  chipTextWidth(s, fs) + 2 * HUD.chips.padX * k + (HUD.chips.dot + HUD.chips.dotGap) * k;
export const progressLabelWidth = (s: string, fs: number) => estimateTextWidth(s, fs, {mono: true, letterSpacing: fs * 0.04});

/** Every value a stakes part takes over the video (for a width that never changes while it counts). */
const stakesValues = (track: HudTrack, i: number) => {
  const vs = new Set<number | undefined>();
  for (const g of track.segments) if (g.state.kind === 'stakes') vs.add(g.state.values[i]);
  return [...vs];
};

/** Widest stakes text over all states (each part at its widest value). */
export const stakesWidest = (el: StakesEl, track: HudTrack, fs: number) => {
  const widest = el.parts.map((p, i) => {
    let best = '';
    let bw = -1;
    for (const v of stakesValues(track, i)) {
      const s = stakesPartText(p, v);
      const w = stakesWidth(s, fs);
      if (w > bw) [best, bw] = [s, w];
    }
    return best;
  });
  return widest.join(STAKES_SEP);
};

const union = (xs: [number, number][]) => {
  const s = [...xs].sort((a, b) => a[0] - b[0]);
  const out: [number, number][] = [];
  for (const [a, b] of s) {
    const l = out[out.length - 1];
    if (l && a <= l[1]) l[1] = Math.max(l[1], b);
    else out.push([a, b]);
  }
  return out;
};
export const rangesOverlap = (ranges: [number, number][], a: number, b: number) => ranges.some(([x, y]) => x < b && y > a);

/** Lays chips out left to right in `w`, wrapping into rows; returns the boxes (relative to the area) and row count. */
export const flowChips = (texts: string[], fs: number, k: number, w: number) => {
  const h = HUD.chips.h * k * (fs / HUD.chips.fs);
  const gap = HUD.chips.gap * k;
  const items: Rect[] = [];
  let x = 0;
  let row = 0;
  for (const s of texts) {
    const cw = chipWidth(s, fs, k);
    if (x > 0 && x + cw > w) {
      row++;
      x = 0;
    }
    items.push({x, y: row * (h + gap), w: cw, h});
    x += cw + gap;
  }
  return {items, rows: texts.length ? row + 1 : 1, h, gap};
};

/**
 * The HUD plan: tracks, element boxes and their union visibility. `bar` = the brand bar rect (output px) and when it
 * shows; the HUD starts below it when both are on screen at some point (rows stay fixed for the whole video).
 */
export const planHud = (props: RenderProps, bar: (Rect & {from: number; to: number}) | null): HudPlan | null => {
  if (!hudEnabled(props)) return null;
  const hud = props.hud as Hud;
  const fmt = props.format;
  const {width} = DIMENSIONS[fmt];
  const k = HUD.k[fmt];
  const x0 = HUD.side[fmt];
  const w = width - 2 * x0;
  const duration = props.durationInFrames / props.fps;
  const tracks = hudTracks(hud, duration);
  const ranges = union(tracks.flatMap((tr) => tr.ranges));
  let y0: number = HUD.top[fmt];
  if (bar && rangesOverlap(ranges, bar.from, bar.to)) y0 = Math.max(y0, bar.y + bar.h + HUD.barGap * k);
  const byKind = (kind: HudElement['kind']) => tracks.find((tr) => tr.el.kind === kind);
  const header = byKind('header');
  const stakes = byKind('stakes');
  const progress = byKind('progress');
  const chips = byKind('chips');
  const boxes: Record<string, HudBox> = {};
  let y = y0;
  const gap = HUD.rowGap * k;

  // row 1: header (left) + stakes (right) when both fit; else the stakes chip gets its own centred row above
  let hFs = HUD.header.fs * k;
  let headerW = 0;
  if (header && header.el.kind === 'header') {
    const el = header.el;
    const widest = () => Math.max(0, ...el.steps.map((_, i) => headerWidth(headerText(el, i), hFs)));
    while (widest() > w && hFs > HUD.header.minFs * k) hFs = Math.max(HUD.header.minFs * k, hFs * 0.94);
    headerW = widest();
  }
  let sFs = HUD.stakes.fs * k;
  let stakesW = 0;
  const padX = HUD.stakes.padX * k;
  if (stakes && stakes.el.kind === 'stakes') {
    const el = stakes.el;
    const widest = () => stakesWidth(stakesWidest(el, stakes, sFs), sFs) + 2 * padX;
    while (widest() > w && sFs > HUD.stakes.minFs * k) sFs = Math.max(HUD.stakes.minFs * k, sFs * 0.94);
    stakesW = Math.min(w, widest());
  }
  const rowH = Math.max(header ? HUD.header.h * k : 0, stakes ? HUD.stakes.h * k : 0);
  const shareRow = !!header && !!stakes && headerW + 32 * k + stakesW <= w;
  if (stakes && !shareRow) {
    const h = HUD.stakes.h * k;
    boxes[stakes.el.id] = {kind: 'stakes', x: x0 + (w - stakesW) / 2, y, w: stakesW, h, fs: sFs, ls: sFs * HUD.stakes.track, padX};
    y += h + (header || progress || chips ? gap : 0);
  }
  if (header) {
    const h = shareRow ? rowH : HUD.header.h * k;
    boxes[header.el.id] = {kind: 'header', x: x0, y, w: shareRow ? w - stakesW - 32 * k : w, h, fs: hFs, ls: hFs * HUD.header.track};
    if (shareRow && stakes) {
      const sh = HUD.stakes.h * k;
      boxes[stakes.el.id] = {kind: 'stakes', x: x0 + w - stakesW, y: y + (h - sh) / 2, w: stakesW, h: sh, fs: sFs, ls: sFs * HUD.stakes.track, padX};
    }
    y += h + (progress || chips ? gap : 0);
  }
  if (progress && progress.el.kind === 'progress') {
    const el = progress.el;
    const h = HUD.progress.h * k;
    const fs = HUD.progress.fs * k;
    const show = el.showCount !== false;
    const lw = show ? progressLabelWidth(progressText(el, el.total), fs) : 0;
    const barW = show ? w - lw - HUD.progress.labelGap * k : w;
    const bh = HUD.progress.bar * k;
    boxes[el.id] = {
      kind: 'progress', x: x0, y, w, h, fs,
      bar: {x: x0, y: y + (h - bh) / 2, w: Math.max(40 * k, barW), h: bh},
      label: show ? {x: x0 + w - lw, y, w: lw, h} : null,
    };
    y += h + (chips ? gap : 0);
  }
  if (chips) {
    const texts = chips.segments.at(-1)?.state.kind === 'chips' ? (chips.segments.at(-1)!.state as Extract<HudState, {kind: 'chips'}>).chips.map((c) => c.text) : [];
    let fs = HUD.chips.fs * k;
    let f = flowChips(texts, fs, k, w);
    while (f.rows > HUD.chips.maxRows && fs > HUD.chips.minFs * k) {
      fs = Math.max(HUD.chips.minFs * k, fs * 0.94);
      f = flowChips(texts, fs, k, w);
    }
    const rows = Math.max(1, Math.min(f.rows, HUD.chips.maxRows));
    const h = rows * f.h + (rows - 1) * f.gap;
    const items = f.items.map((r) => ({x: x0 + r.x, y: y + r.y, w: r.w, h: r.h}));
    boxes[chips.el.id] = {kind: 'chips', x: x0, y, w, h, fs, ls: fs * HUD.chips.track, chipH: f.h, items, overflow: f.rows > HUD.chips.maxRows || items.some((r) => r.x + r.w > x0 + w + 0.5)};
    y += h;
  }
  return {format: fmt, k, x0, w, y0, tracks, boxes, ranges};
};

/** Bottom (output px) of the lowest HUD element visible at any time in [a, b] (undefined = none visible). */
export const hudBottomFor = (plan: HudPlan, a: number, b: number): number | undefined => {
  let out: number | undefined;
  for (const tr of plan.tracks) {
    const box = plan.boxes[tr.el.id];
    if (!box || !rangesOverlap(tr.ranges, a, b)) continue;
    out = Math.max(out ?? -Infinity, box.y + box.h);
  }
  return out;
};

/** Where scene content may start below the HUD (output px), or undefined when no HUD element shows in [a, b]. */
export const hudContentTop = (plan: HudPlan, a: number, b: number): number | undefined => {
  const bottom = hudBottomFor(plan, a, b);
  return bottom === undefined ? undefined : bottom + HUD.gapBelow * plan.k;
};

/** Text runs of each element with the window they are on screen (QA manifest; role 'label'). */
export type HudText = {text: string; x: number; y: number; w: number; h: number; fs: number; weight: number; est: number; from: number; to: number; mono?: boolean};

export const hudTexts = (plan: HudPlan, duration: number): Record<string, HudText[]> => {
  const out: Record<string, HudText[]> = {};
  for (const tr of plan.tracks) {
    const box = plan.boxes[tr.el.id];
    const list: HudText[] = (out[tr.el.id] = []);
    if (!box) continue;
    const segs = tr.segments.filter((g) => g.visible);
    const end = (g: HudSegment) => (g.to === Infinity ? duration : g.to);
    const el = tr.el;
    if (el.kind === 'header' && box.kind === 'header') {
      for (const g of segs) {
        if (g.state.kind !== 'header') continue;
        const s = headerText(el, g.state.index);
        const est = headerWidth(s, box.fs);
        const prevSame = list.at(-1);
        if (prevSame && prevSame.text === s && Math.abs(prevSame.to - g.from) < 1e-6) prevSame.to = r3(end(g));
        else list.push({text: s, x: box.x, y: box.y, w: box.w, h: box.h, fs: box.fs, weight: HEADER_W, est, from: r3(g.from), to: r3(end(g))});
      }
    } else if (el.kind === 'stakes' && box.kind === 'stakes') {
      for (const g of segs) {
        if (g.state.kind !== 'stakes') continue;
        const s = stakesText(el, g.state.values);
        const est = stakesWidth(s, box.fs);
        // a counted value is "shown" once it lands
        const landed = r3(Math.min(end(g), g.from + HUD.lead + HUD.count));
        const prevSame = list.at(-1);
        if (prevSame && prevSame.text === s) prevSame.to = r3(end(g));
        else list.push({text: s, x: box.x + box.padX, y: box.y, w: box.w - 2 * box.padX, h: box.h, fs: box.fs, weight: 800, est, from: list.length ? landed : r3(g.from), to: r3(end(g))});
      }
    } else if (el.kind === 'progress' && box.kind === 'progress' && box.label) {
      for (const g of segs) {
        if (g.state.kind !== 'progress') continue;
        const s = progressText(el, g.state.value);
        const prevSame = list.at(-1);
        if (prevSame && prevSame.text === s) prevSame.to = r3(end(g));
        else list.push({text: s, x: box.label.x, y: box.label.y, w: box.label.w, h: box.label.h, fs: box.fs, weight: 600, est: progressLabelWidth(s, box.fs), from: r3(g.from), to: r3(end(g)), mono: true});
      }
    } else if (el.kind === 'chips' && box.kind === 'chips') {
      const last = tr.segments.at(-1)?.state;
      const chips = last && last.kind === 'chips' ? last.chips : [];
      const vis = tr.ranges;
      chips.forEach((c, i) => {
        const r = box.items[i];
        if (!r) return;
        const to = vis.find(([a, b]) => c.at >= a - 1e-6 && c.at <= b)?.[1] ?? duration;
        const pad = HUD.chips.padX * plan.k + (HUD.chips.dot + HUD.chips.dotGap) * plan.k;
        const s = c.text.toUpperCase();
        list.push({text: s, x: r.x + pad, y: r.y, w: r.w - pad - HUD.chips.padX * plan.k, h: r.h, fs: box.fs, weight: CHIP_W, est: chipTextWidth(s, box.fs), from: r3(c.at), to: r3(to)});
      });
    }
  }
  return out;
};
