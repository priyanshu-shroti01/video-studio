/**
 * Pure geometry of the v2 blocks, in design units relative to the block box (0,0 = box top-left).
 * The renderer (blocks-v2.tsx) positions every text / logo / shape from these numbers, and the QA layout
 * manifest (manifest.ts) reports the same numbers — so the manifest is the renderer's layout, not a copy.
 * No React / Remotion imports.
 */
import {COUNTER_FS, estimateTextWidth, fitFontSize, KINETIC_FS, TYPE, WEIGHT} from './motion/typography';
import {BlockV2, LogoVariant} from './types';

export type Role = 'title' | 'body' | 'price' | 'url' | 'caption' | 'label';
export type Align = 'left' | 'center' | 'right';
/** A single-line text run: box (x, y, w = max width, h = line box), font, alignment, QA role. */
export type TextSpec = {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  fs: number;
  weight: number;
  align: Align;
  role: Role;
  mono?: boolean;
  /** letter spacing, px */
  ls?: number;
  /** estimated width when the run is not a plain string at `fs` (e.g. kinetic lines with emphasis words) */
  est?: number;
  /** true when the run sits in a viewport that may clip it (scroll-demo) */
  clipped?: boolean;
};
export type Rect = {x: number; y: number; w: number; h: number};
export type LogoSpec = Rect & {variant: LogoVariant | 'custom'; expected: number};

export type LogoAspects = Record<LogoVariant, number>;
/** What geometry needs from the world: logo aspects and asset aspects (public/ path → w/h). */
export type AspectEnv = {logo: LogoAspects; asset: (path: string) => number | undefined; logoPaths?: Partial<Record<LogoVariant, string>>; polish?: boolean};

export const T = (text: string, x: number, y: number, w: number, h: number, fs: number, weight: number, align: Align, role: Role, extra: Partial<TextSpec> = {}): TextSpec => ({
  text,
  x,
  y,
  w,
  h,
  fs,
  weight,
  align,
  role,
  ...extra,
});

/** Estimated width of a TextSpec (the one estimator the layout and QA share). */
/** Pill metrics (shared by the text geometry and the layout): font size, horizontal padding, icon slot, height. */
export const pillMetrics = (b: {stamp?: boolean; icon?: unknown}) => {
  const stamp = !!b.stamp;
  return {fs: stamp ? 76 : 46, padX: stamp ? 44 : 36, iconW: b.icon ? (stamp ? 70 : 46) + 14 : 0, h: stamp ? 116 : 84, ls: stamp ? 6 : 0};
};
/** Narrowest design width at which a pill's single line still fits. */
export const pillMinW = (b: {text: string; stamp?: boolean; icon?: unknown}) => {
  const m = pillMetrics(b);
  return estimateTextWidth(b.text, m.fs, {weight: WEIGHT.heavy, letterSpacing: m.ls || undefined}) + 2 * m.padX + m.iconW;
};

export const specWidth = (s: TextSpec) => s.est ?? estimateTextWidth(s.text, s.fs, {weight: s.weight, mono: s.mono, letterSpacing: s.ls});

/** Greedy wrap by estimated width. Returns lines of word indices. */
export const wrapByWidth = (words: string[], widths: number[], gap: number, maxW: number): number[][] => {
  const lines: number[][] = [];
  let cur: number[] = [];
  let width = 0;
  words.forEach((_, i) => {
    const next = cur.length ? width + gap + widths[i] : widths[i];
    if (cur.length && next > maxW) {
      lines.push(cur);
      cur = [i];
      width = widths[i];
    } else {
      cur.push(i);
      width = next;
    }
  });
  if (cur.length) lines.push(cur);
  return lines;
};
const wrapText = (text: string, fs: number, maxW: number, weight: number = WEIGHT.heavy) => {
  const words = text.split(/\s+/).filter(Boolean);
  const widths = words.map((x) => estimateTextWidth(x, fs, {weight}));
  return wrapByWidth(words, widths, fs * 0.26, maxW).map((l) => l.map((i) => words[i]).join(' '));
};

export const NATURAL_W: Record<BlockV2['type'], number> = {
  'kinetic-text': 0, // full column
  counter: 900,
  'price-compare': 920,
  terminal: 900,
  dashboard: 940,
  device: 0, // by frame
  image: 900,
  progress: 900,
  'scroll-demo': 880,
  chart: 900,
  'feature-compare': 900,
  'logo-sting': 760,
  outro: 900,
  // v2b (wide layouts; geometry-v2b.ts switches to the tall layout in a narrower column)
  'plan-card': 1400,
  'install-flow': 1560,
  'server-stack': 1440,
  footage: 0, // by frame + clip aspect (geometry-footage.ts)
  composition: 1500, // geometry-composition.ts COMPOSITION.naturalW (tall layout below wideMin)
};
export const DEVICE_W = {phone: 400, laptop: 900} as const;
export const IMAGE_MAX_H = 760;

/** Formats a number with fixed decimals and optional grouping (deterministic, no Intl). */
export const formatNumber = (v: number, decimals = 0, grouping: 'none' | 'western' | 'indian' = 'none') => {
  const neg = v < 0;
  const [int, frac] = Math.abs(v).toFixed(decimals).split('.');
  let g = int;
  if (grouping === 'western') g = int.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  if (grouping === 'indian' && int.length > 3) g = int.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + int.slice(-3);
  return (neg ? '-' : '') + g + (frac ? '.' + frac : '');
};

const CURRENCY = /[₹$€£¥]/;

// ------------------------------------------------------------------------------------------------
type B<K extends BlockV2['type']> = Extract<BlockV2, {type: K}>;

export const geomKinetic = (b: B<'kinetic-text'>, w: number) => {
  const base: number = KINETIC_FS[b.size ?? 'l'];
  const EMPH = 1.12;
  const measure = (fs: number) => b.words.map((x) => estimateTextWidth(x.text, fs * (x.emphasis ? EMPH : 1), {weight: WEIGHT.heavy, letterSpacing: -0.02 * fs * (x.emphasis ? EMPH : 1)}));
  // auto-fit: the longest single word must fit the box (kinetic text never overflows by design)
  let fs = base;
  const widest = Math.max(1, ...measure(base));
  if (widest > w) fs = Math.floor((base * w) / widest);
  const widths = measure(fs);
  const gap = fs * 0.28;
  const lineH = Math.round(fs * 1.18);
  const lines = wrapByWidth(b.words.map((x) => x.text), widths, gap, w);
  const align = b.align ?? 'center';
  const words: {i: number; x: number; y: number; w: number; fs: number; line: number}[] = [];
  const texts: TextSpec[] = [];
  lines.forEach((ln, li) => {
    const lw = ln.reduce((s, i) => s + widths[i], 0) + gap * (ln.length - 1);
    let x = align === 'center' ? (w - lw) / 2 : 0;
    for (const i of ln) {
      words.push({i, x, y: li * lineH, w: widths[i], fs: fs * (b.words[i].emphasis ? EMPH : 1), line: li});
      x += widths[i] + gap;
    }
    texts.push(T(ln.map((i) => b.words[i].text).join(' '), 0, li * lineH, w, lineH, fs, WEIGHT.heavy, align, 'title', {est: lw}));
  });
  return {h: lines.length * lineH + Math.round(fs * 0.12), fs, lineH, words, texts};
};

export const counterText = (b: B<'counter'>, v: number) => `${b.prefix ?? ''}${formatNumber(v, b.decimals ?? 0, b.grouping ?? 'none')}${b.suffix ?? ''}`;
export const geomCounter = (b: B<'counter'>, w: number) => {
  const base: number = COUNTER_FS[b.size ?? 'l'];
  const a = counterText(b, b.to);
  const z = counterText(b, b.from ?? 0);
  const widest = a.length >= z.length ? a : z;
  const ls = -0.03;
  const fs = fitFontSize(widest, base, w * 0.96, {weight: WEIGHT.heavy, minFs: 60});
  const labelH = b.label ? 64 : 0;
  const numH = Math.round(fs * 1.12);
  const texts: TextSpec[] = [];
  if (b.label) texts.push(T(b.label, 0, 0, w, labelH, 44, WEIGHT.bold, 'center', 'label'));
  texts.push(T(a, 0, labelH, w, numH, fs, WEIGHT.heavy, 'center', CURRENCY.test(b.prefix ?? '') || CURRENCY.test(b.suffix ?? '') ? 'price' : 'title', {ls: ls * fs}));
  return {h: labelH + numH + 16, fs, ls: ls * fs, labelH, numH, texts};
};

/** Shared table geometry (price-compare, feature-compare). */
const tableGeom = (w: number, nCols: number, nRows: number, opts: {title?: string; badge: boolean; rowH: number}) => {
  const pad = 36;
  const titleH = opts.title ? 64 : 0;
  const badgeH = opts.badge ? 50 : 0;
  const headH = 80;
  const innerW = w - 2 * pad;
  const labelW = Math.round(innerW * (nCols >= 3 ? 0.3 : 0.36));
  const colW = (innerW - labelW) / Math.max(1, nCols);
  const y0 = pad + titleH + badgeH;
  const rowsY = y0 + headH;
  const h = rowsY + nRows * opts.rowH + pad - 6;
  const colX = (c: number) => pad + labelW + c * colW;
  return {pad, titleH, badgeH, headH, innerW, labelW, colW, y0, rowsY, h, colX, rowH: opts.rowH};
};

/** v2b: in a portrait column (Shorts) the cards get taller proportions so a scene doesn't end in empty space. */
export const portraitPolish = (w: number, polish?: boolean) => !!polish && w < 1000;

export const geomPriceCompare = (b: B<'price-compare'>, w: number, polish?: boolean) => {
  const n = b.columns.length;
  const g = tableGeom(w, n, b.rows.length, {title: b.title, badge: b.winner !== undefined, rowH: portraitPolish(w, polish) ? 120 : 100});
  const texts: TextSpec[] = [];
  if (b.title) texts.push(T(b.title, g.pad, g.pad, g.innerW, 50, TYPE.cardTitle, WEIGHT.bold, 'left', 'title'));
  const headFs = Math.min(...b.columns.map((c) => fitFontSize(c, 32, g.colW - 16, {minFs: 24})));
  b.columns.forEach((c, ci) => texts.push(T(c, g.colX(ci) + 8, g.y0, g.colW - 16, g.headH, headFs, WEIGHT.heavy, 'center', 'label')));
  const labelFs = Math.min(36, ...b.rows.map((r) => fitFontSize(r.label, 36, g.labelW - 12, {weight: WEIGHT.bold, minFs: 26})));
  const hikeW = 42;
  const valFs = Math.min(
    TYPE.cell,
    ...b.rows.flatMap((r) => r.values.map((v, ci) => fitFontSize(v, TYPE.cell, g.colW - 24 - (r.hike?.includes(ci) ? hikeW : 0), {minFs: 28}))),
  );
  const cells: {row: number; col: number; x: number; y: number; w: number; h: number}[] = [];
  b.rows.forEach((r, ri) => {
    const y = g.rowsY + ri * g.rowH;
    texts.push(T(r.label, g.pad, y, g.labelW - 12, g.rowH, labelFs, WEIGHT.bold, 'left', 'label'));
    r.values.forEach((v, ci) => {
      const hike = r.hike?.includes(ci) ? hikeW : 0;
      cells.push({row: ri, col: ci, x: g.colX(ci), y, w: g.colW, h: g.rowH});
      texts.push(T(v, g.colX(ci) + 12, y, g.colW - 24 - hike, g.rowH, valFs, WEIGHT.heavy, 'center', 'price'));
    });
  });
  const badgeText = b.winnerLabel ?? 'Best value';
  const badgeFs = 24;
  const badge = b.winner !== undefined ? {x: g.colX(b.winner) + 6, y: g.pad + g.titleH, w: g.colW - 12, h: 40} : undefined;
  if (badge) texts.push(T(badgeText.toUpperCase(), badge.x, badge.y, badge.w, badge.h, fitFontSize(badgeText.toUpperCase(), badgeFs, badge.w - 16, {minFs: 18, letterSpacing: 2}), WEIGHT.heavy, 'center', 'label', {ls: 2}));
  return {...g, headFs, labelFs, valFs, hikeW, cells, badge, badgeText: badgeText.toUpperCase(), texts};
};

export const geomFeatureCompare = (b: B<'feature-compare'>, w: number, polish?: boolean) => {
  const n = b.columns.length;
  const g = tableGeom(w, n, b.rows.length, {title: b.title, badge: false, rowH: portraitPolish(w, polish) ? 112 : 92});
  const texts: TextSpec[] = [];
  if (b.title) texts.push(T(b.title, g.pad, g.pad, g.innerW, 50, TYPE.cardTitle, WEIGHT.bold, 'left', 'title'));
  const headFs = Math.min(...b.columns.map((c) => fitFontSize(c, 32, g.colW - 16, {minFs: 24})));
  b.columns.forEach((c, ci) => texts.push(T(c, g.colX(ci) + 8, g.y0, g.colW - 16, g.headH, headFs, WEIGHT.heavy, 'center', 'label')));
  const labelFs = Math.min(36, ...b.rows.map((r) => fitFontSize(r.label, 36, g.labelW - 12, {weight: WEIGHT.bold, minFs: 26})));
  const strFs = Math.min(34, ...b.rows.flatMap((r) => r.values.filter((v): v is string => typeof v === 'string').map((v) => fitFontSize(v, 34, g.colW - 20, {minFs: 24}))));
  b.rows.forEach((r, ri) => {
    const y = g.rowsY + ri * g.rowH;
    texts.push(T(r.label, g.pad, y, g.labelW - 12, g.rowH, labelFs, WEIGHT.bold, 'left', 'label'));
    r.values.forEach((v, ci) => {
      if (typeof v === 'string') texts.push(T(v, g.colX(ci) + 10, y, g.colW - 20, g.rowH, strFs, WEIGHT.heavy, 'center', 'body'));
    });
  });
  return {...g, headFs, labelFs, strFs, icon: 52, texts};
};

export const TERMINAL = {chromeH: 72, pad: 32, fs: TYPE.mono, lineH: 50} as const;
export const terminalLineText = (b: B<'terminal'>, i: number) => {
  const l = b.lines[i];
  const kind = l.kind ?? 'out';
  if (kind === 'cmd') return `${b.prompt ?? '$'} ${l.text}`;
  if (kind === 'ok') return `✓ ${l.text}`;
  if (kind === 'err') return `✗ ${l.text}`;
  return l.text;
};
export const terminalTypeEnd = (l: B<'terminal'>['lines'][number]) => l.typeEnd ?? l.at + Math.min(1.2, 0.04 * l.text.length);
export const geomTerminal = (b: B<'terminal'>, w: number) => {
  const {chromeH, pad, fs, lineH} = TERMINAL;
  const texts: TextSpec[] = [];
  if (b.title) texts.push(T(b.title, 140, 0, w - 280, chromeH, 26, WEIGHT.bold, 'center', 'label'));
  const lines = b.lines.map((_, i) => ({x: pad, y: chromeH + pad + i * lineH, w: w - 2 * pad, h: lineH}));
  lines.forEach((r, i) => texts.push(T(terminalLineText(b, i), r.x, r.y, r.w, r.h, fs, WEIGHT.regular, 'left', 'body', {mono: true})));
  return {chromeH, pad, fs, lineH, lines, h: chromeH + pad * 2 + b.lines.length * lineH - 10, texts};
};

export const geomDashboard = (b: B<'dashboard'>, w: number, env: AspectEnv) => {
  const h = portraitPolish(w, env.polish) ? 820 : 620;
  const sideW = 210;
  const pad = 28;
  const x0 = sideW + pad;
  const mainW = w - x0 - pad;
  const texts: TextSpec[] = [];
  const markH = 48;
  const mark = {x: 26, y: 30, w: markH * env.logo.mark, h: markH};
  const nav = (b.nav ?? []).slice(0, 6).map((label, i) => ({label, x: 16, y: 112 + i * 64, w: sideW - 32, h: 52}));
  nav.forEach((n) => texts.push(T(n.label, n.x + 18, n.y, n.w - 26, n.h, fitFontSize(n.label, 28, n.w - 26, {weight: WEIGHT.bold, minFs: 22}), WEIGHT.bold, 'left', 'label')));
  if (b.title) texts.push(T(b.title, x0, pad, mainW, 56, 36, WEIGHT.heavy, 'left', 'title'));
  const stats = b.stats.slice(0, 4);
  const ns = Math.max(1, stats.length);
  const tileW = (mainW - (ns - 1) * 16) / ns;
  const tileY = 104;
  const tileH = 156;
  const valFs = Math.min(48, ...stats.map((s) => fitFontSize(s.value, 48, tileW - 40, {minFs: 28})));
  const tiles = stats.map((s, i) => {
    const x = x0 + i * (tileW + 16);
    texts.push(T(s.label, x + 20, tileY + 16, tileW - 40, 36, fitFontSize(s.label, 26, tileW - 40, {weight: WEIGHT.bold, minFs: 20}), WEIGHT.bold, 'left', 'label'));
    texts.push(T(s.value, x + 20, tileY + 56, tileW - 40, 60, valFs, WEIGHT.heavy, 'left', CURRENCY.test(s.value) ? 'price' : 'title'));
    if (s.delta) texts.push(T(s.delta, x + 20, tileY + 116, tileW - 40, 30, fitFontSize(s.delta, 26, tileW - 40, {weight: WEIGHT.bold, minFs: 22}), WEIGHT.bold, 'left', 'label'));
    return {x, y: tileY, w: tileW, h: tileH};
  });
  const chartY = tileY + tileH + 22;
  const chartH = h - chartY - pad;
  const chart = {x: x0, y: chartY, w: mainW, h: chartH};
  const bars = b.chart?.bars ?? [];
  const m = Math.max(1, bars.length);
  const plotTop = chartY + (b.chart?.title ? 64 : 28);
  const plotBottom = chartY + chartH - 52;
  const slot = (mainW - 40) / m;
  const barW = Math.min(64, slot * 0.56);
  const maxV = Math.max(1e-9, ...bars.map((x) => x.value));
  if (b.chart?.title) texts.push(T(b.chart.title, x0 + 24, chartY + 16, mainW - 48, 40, 28, WEIGHT.bold, 'left', 'label'));
  const labelFs = Math.min(26, ...bars.map((x) => fitFontSize(x.label, 26, slot - 6, {weight: WEIGHT.bold, minFs: 18})));
  const barRects = bars.map((x, i) => {
    const bx = x0 + 20 + slot * i + (slot - barW) / 2;
    const bh = (x.value / maxV) * (plotBottom - plotTop);
    texts.push(T(x.label, x0 + 20 + slot * i + 3, plotBottom + 10, slot - 6, 36, labelFs, WEIGHT.bold, 'center', 'label'));
    return {x: bx, y: plotBottom - bh, w: barW, h: bh};
  });
  return {h, sideW, pad, x0, mainW, mark, nav, tiles, valFs, chart, plotTop, plotBottom, barRects, texts, logos: [{...mark, variant: 'mark' as const, expected: env.logo.mark}]};
};

/** Device frames + the simple built-in screen UI. */
export const geomDevice = (b: B<'device'>, w: number, env: AspectEnv) => {
  const phone = b.frame === 'phone';
  const texts: TextSpec[] = [];
  let screen: Rect;
  let h: number;
  let body: Rect;
  if (phone) {
    const bezel = 16;
    const sw = w - 2 * bezel;
    const sh = Math.round(sw * 2.08);
    screen = {x: bezel, y: bezel, w: sw, h: sh};
    h = sh + 2 * bezel;
    body = {x: 0, y: 0, w, h};
  } else {
    const lidW = Math.round(w * 0.89);
    const lidX = (w - lidW) / 2;
    const sw = lidW - 40;
    const sh = Math.round(sw / 1.6);
    screen = {x: lidX + 20, y: 24, w: sw, h: sh};
    body = {x: lidX, y: 0, w: lidW, h: sh + 24 + 20};
    h = body.h + 34;
  }
  const ui = !b.asset && b.screen ? deviceUi(b.screen, screen, phone, texts, env) : undefined;
  const logos: LogoSpec[] = ui?.mark ? [{...ui.mark, variant: 'mark', expected: env.logo.mark}] : [];
  if (b.asset) {
    const a = env.asset(b.asset);
    const variant = assetLogoVariant(b.asset, env);
    if (variant && a) logos.push({...containRect(screen, a), variant, expected: a});
  }
  return {phone, screen, body, h, ui, texts, logos};
};
const deviceUi = (s: NonNullable<B<'device'>['screen']>, r: Rect, phone: boolean, texts: TextSpec[], env: AspectEnv) => {
  const u = phone ? 1 : 0.9;
  const pad = Math.round(28 * u);
  const statusH = phone ? 56 : 0;
  const headY = r.y + statusH + (phone ? 4 : 16);
  const headH = Math.round(70 * u);
  const markH = Math.round(40 * u);
  const mark = {x: r.x + pad, y: headY + (headH - markH) / 2, w: markH * env.logo.mark, h: markH};
  const titleX = mark.x + mark.w + 16;
  const innerW = r.w - 2 * pad;
  texts.push(T(s.title, titleX, headY, r.x + r.w - pad - titleX, headH, fitFontSize(s.title, Math.round(32 * u), r.x + r.w - pad - titleX, {minFs: 22}), WEIGHT.heavy, 'left', 'title'));
  let y = headY + headH + Math.round(18 * u);
  let subLines = 0;
  if (s.subtitle) {
    const sfs = Math.round(28 * u);
    const lines = wrapText(s.subtitle, sfs, innerW, WEIGHT.semibold).slice(0, 2);
    lines.forEach((l, i) => texts.push(T(l, r.x + pad, y + i * sfs * 1.3, innerW, sfs * 1.3, sfs, WEIGHT.semibold, 'left', 'body')));
    y += lines.length * sfs * 1.3 + Math.round(18 * u);
    subLines = lines.length;
  }
  const rowH = Math.round(80 * u);
  const rows = (s.rows ?? []).slice(0, phone ? 6 : 4).map((text, i) => {
    const ry = y + i * (rowH + 14);
    const icon = Math.round(40 * u);
    const tx = r.x + pad + 20 + icon + 16;
    const tw = r.x + r.w - pad - 20 - tx;
    texts.push(T(text, tx, ry, tw, rowH, fitFontSize(text, Math.round(28 * u), tw, {weight: WEIGHT.bold, minFs: 20}), WEIGHT.bold, 'left', 'body'));
    return {x: r.x + pad, y: ry, w: innerW, h: rowH, icon};
  });
  const btnH = Math.round(84 * u);
  const button = s.button ? {x: r.x + pad, y: r.y + r.h - pad - btnH, w: innerW, h: btnH} : undefined;
  if (button && s.button) texts.push(T(s.button, button.x, button.y, button.w, button.h, fitFontSize(s.button, Math.round(30 * u), button.w - 30, {minFs: 20}), WEIGHT.heavy, 'center', 'label'));
  return {statusH, headY, headH, mark, rows, button, pad, subLines};
};

export const containRect = (box: Rect, aspect: number): Rect => {
  const bw = box.w;
  const bh = box.h;
  if (bw / bh > aspect) {
    const w = bh * aspect;
    return {x: box.x + (bw - w) / 2, y: box.y, w, h: bh};
  }
  const h = bw / aspect;
  return {x: box.x, y: box.y + (bh - h) / 2, w: bw, h};
};
const assetLogoVariant = (path: string, env: AspectEnv): LogoVariant | undefined =>
  (['onDark', 'onLight', 'mark'] as LogoVariant[]).find((v) => env.logoPaths?.[v] === path);

export const imageAspect = (b: B<'image'>, env: AspectEnv) => env.asset(b.asset) ?? 16 / 9;
export const imageNaturalW = (b: B<'image'>, env: AspectEnv) => Math.min(NATURAL_W.image, (b.maxHeight ?? IMAGE_MAX_H) * imageAspect(b, env));
export const geomImage = (b: B<'image'>, w: number, env: AspectEnv) => {
  const a = imageAspect(b, env);
  const img = {x: 0, y: 0, w, h: w / a};
  const capH = b.caption ? 58 : 0;
  const texts: TextSpec[] = b.caption ? [T(b.caption, 0, img.h + 12, w, 46, 30, WEIGHT.semibold, 'center', 'caption')] : [];
  const variant = assetLogoVariant(b.asset, env);
  const logos: LogoSpec[] = variant ? [{...img, variant, expected: a}] : [];
  return {aspect: a, img, h: Math.round(img.h + capH), texts, logos};
};

export const geomProgress = (b: B<'progress'>, w: number) => {
  const titleH = b.title ? 64 : 0;
  const n = Math.max(1, b.steps.length);
  const slot = w / n;
  const d = 72;
  const cy = titleH + 8 + d / 2;
  const texts: TextSpec[] = [];
  if (b.title) texts.push(T(b.title, 0, 0, w, 50, TYPE.cardTitle, WEIGHT.bold, 'center', 'title'));
  const labelFs = Math.min(32, ...b.steps.map((s) => fitFontSize(s.label, 32, slot - 16, {weight: WEIGHT.bold, minFs: 22})));
  const steps = b.steps.map((s, i) => {
    const cx = slot * (i + 0.5);
    texts.push(T(String(i + 1), cx - d / 2, cy - d / 2, d, d, 30, WEIGHT.heavy, 'center', 'label'));
    texts.push(T(s.label, slot * i + 8, titleH + d + 24, slot - 16, 44, labelFs, WEIGHT.bold, 'center', 'label'));
    return {cx, cy};
  });
  return {h: titleH + d + 24 + 44 + 8, d, cy, slot, steps, labelFs, texts};
};

export const SCROLL = {chromeH: 88, viewportH: 640, pad: 44} as const;
const SECTION_H = {hero: 460, features: 380, pricing: 400, cta: 320, plain: 300} as const;
export const geomScrollDemo = (b: B<'scroll-demo'>, w: number) => {
  const {chromeH, viewportH, pad} = SCROLL;
  const innerW = w - 2 * pad;
  const texts: TextSpec[] = [T(b.url, 150, 18, w - 190, 52, 28, WEIGHT.regular, 'left', 'url', {mono: true})];
  let y = 0;
  const inner: TextSpec[] = [];
  const sections = b.sections.map((s) => {
    const kind = s.kind ?? 'plain';
    const sh = SECTION_H[kind];
    const top = y;
    const items = (s.text ?? '').split('|').map((x) => x.trim()).filter(Boolean);
    const add = (t: TextSpec) => inner.push(t);
    if (kind === 'hero') {
      const lines = wrapText(s.title, 60, innerW).slice(0, 2);
      lines.forEach((l, i) => add(T(l, pad, top + 64 + i * 70, innerW, 70, 60, WEIGHT.heavy, 'left', 'title')));
      const ty = top + 64 + lines.length * 70 + 18;
      if (s.text) wrapText(s.text, 30, innerW, WEIGHT.semibold).slice(0, 2).forEach((l, i) => add(T(l, pad, ty + i * 40, innerW, 40, 30, WEIGHT.semibold, 'left', 'body')));
    } else if (kind === 'cta') {
      add(T(s.title, pad, top + 90, innerW, 64, fitFontSize(s.title, 48, innerW - 40, {minFs: 30}), WEIGHT.heavy, 'center', 'title'));
      if (s.text) add(T(s.text, pad, top + 170, innerW, 44, fitFontSize(s.text, 30, innerW - 40, {weight: WEIGHT.semibold, minFs: 22}), WEIGHT.semibold, 'center', 'body'));
    } else {
      add(T(s.title, pad, top + 44, innerW, 56, fitFontSize(s.title, 44, innerW, {minFs: 28}), WEIGHT.heavy, 'left', 'title'));
      if (kind === 'features' || kind === 'pricing') {
        const k = Math.max(1, Math.min(3, items.length || 3));
        const tw = (innerW - (k - 1) * 20) / k;
        items.slice(0, 3).forEach((it, i) =>
          add(T(it, pad + i * (tw + 20) + 14, top + 130 + (kind === 'pricing' ? 70 : 110), tw - 28, 56, fitFontSize(it, kind === 'pricing' ? 44 : 30, tw - 28, {minFs: 20}), WEIGHT.heavy, 'center', kind === 'pricing' ? 'price' : 'label')),
        );
      } else if (s.text) {
        wrapText(s.text, 30, innerW, WEIGHT.semibold).slice(0, 3).forEach((l, i) => add(T(l, pad, top + 118 + i * 42, innerW, 42, 30, WEIGHT.semibold, 'left', 'body')));
      }
    }
    y += sh;
    return {kind, top, h: sh, items};
  });
  const contentH = y;
  // stop on a section boundary (never ends with a heading clipped under the browser chrome)
  const bottom = Math.max(0, contentH - viewportH);
  const scrollMax = bottom === 0 ? 0 : Math.max(0, ...sections.map((x) => x.top).filter((top) => top <= bottom));
  // manifest: the texts visible in the viewport before scrolling (frame-relative)
  for (const t of inner) if (t.y < viewportH) texts.push({...t, y: chromeH + t.y, clipped: t.y + t.h > viewportH});
  return {chromeH, viewportH, pad, innerW, sections, inner, contentH, scrollMax, h: chromeH + viewportH, texts};
};

export const chartValueText = (b: B<'chart'>, v: number) => `${b.valuePrefix ?? ''}${formatNumber(v, b.decimals ?? 0)}${b.valueSuffix ?? ''}`;
export const geomChart = (b: B<'chart'>, w: number, polish?: boolean) => {
  const h = portraitPolish(w, polish) ? 740 : 560;
  const pad = 40;
  const titleH = b.title ? 60 : 0;
  const plotTop = pad + titleH + 60;
  const plotBottom = h - pad - 52;
  const plotH = plotBottom - plotTop;
  const n = Math.max(1, b.data.length);
  const slot = (w - 2 * pad) / n;
  const barW = Math.min(120, slot * 0.58);
  // line charts keep 20% headroom so a flat series doesn't hug the title
  const maxV = Math.max(1e-9, ...b.data.map((d) => d.value)) * (b.kind === 'line' ? 1.2 : 1);
  const texts: TextSpec[] = [];
  if (b.title) texts.push(T(b.title, pad, pad, w - 2 * pad, 50, TYPE.cardTitle, WEIGHT.bold, 'left', 'title'));
  const valFs = Math.min(34, ...b.data.map((d) => fitFontSize(chartValueText(b, d.value), 34, slot - 6, {minFs: 20})));
  const labelFs = Math.min(28, ...b.data.map((d) => fitFontSize(d.label, 28, slot - 6, {weight: WEIGHT.bold, minFs: 18})));
  const role: Role = CURRENCY.test(b.valuePrefix ?? '') ? 'price' : 'label';
  const points = b.data.map((d, i) => {
    const cx = pad + slot * (i + 0.5);
    const vh = (d.value / maxV) * plotH;
    const top = plotBottom - vh;
    texts.push(T(chartValueText(b, d.value), pad + slot * i + 3, top - 50, slot - 6, 44, valFs, WEIGHT.heavy, 'center', role));
    texts.push(T(d.label, pad + slot * i + 3, plotBottom + 12, slot - 6, 38, labelFs, WEIGHT.bold, 'center', 'label'));
    return {cx, top, vh, bar: {x: cx - barW / 2, y: top, w: barW, h: vh}};
  });
  return {h, pad, plotTop, plotBottom, plotH, slot, barW, points, valFs, labelFs, texts};
};

export const geomLogoSting = (b: B<'logo-sting'>, w: number, env: AspectEnv) => {
  const variant = b.variant ?? 'onDark';
  const a = env.logo[variant];
  const lw = w * 0.86;
  const lh = lw / a;
  const logo = {x: (w - lw) / 2, y: 30, w: lw, h: lh};
  const texts: TextSpec[] = [];
  const tagY = logo.y + lh + 34;
  if (b.tagline) texts.push(T(b.tagline, 0, tagY, w, 56, fitFontSize(b.tagline, 40, w, {weight: WEIGHT.bold, minFs: 26}), WEIGHT.bold, 'center', 'body'));
  return {variant, logo, h: Math.round(tagY + (b.tagline ? 56 : 0) + (b.tagline ? 24 : -4)), texts, logos: [{...logo, variant, expected: a} as LogoSpec]};
};

export const geomOutro = (b: B<'outro'>, w: number, env: AspectEnv) => {
  const a = env.logo.onDark;
  const lw = Math.min(w, 620);
  const logo = {x: (w - lw) / 2, y: 0, w: lw, h: lw / a};
  const texts: TextSpec[] = [];
  let y = logo.h + 26;
  if (b.tagline) {
    texts.push(T(b.tagline, 0, y, w, 54, fitFontSize(b.tagline, 40, w, {weight: WEIGHT.bold, minFs: 26}), WEIGHT.bold, 'center', 'body'));
    y += 54 + 34;
  } else y += 20;
  const ctaLines = b.cta ? wrapText(b.cta, 72, w).slice(0, 2) : [];
  ctaLines.forEach((l, i) => texts.push(T(l, 0, y + i * 82, w, 82, 72, WEIGHT.heavy, 'center', 'title', {ls: -2})));
  y += ctaLines.length * 82 + (ctaLines.length ? 34 : 0);
  const arrow = 60;
  const urlFs = fitFontSize(b.url, 60, w - 2 * 48 - arrow - 20, {minFs: 32});
  const urlW = estimateTextWidth(b.url, urlFs, {weight: WEIGHT.heavy});
  const btnW = Math.min(w, urlW + 2 * 48 + arrow + 20);
  const button = {x: (w - btnW) / 2, y, w: btnW, h: 128};
  texts.push(T(b.url, button.x + 48, y, btnW - 2 * 48 - arrow - 20, 128, urlFs, WEIGHT.heavy, 'left', 'url', {est: urlW}));
  return {logo, button, urlFs, arrow, ctaLines, h: Math.round(y + 128 + 16), texts, logos: [{...logo, variant: 'onDark', expected: a} as LogoSpec]};
};
