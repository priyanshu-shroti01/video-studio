/**
 * Pure geometry of the `composition` block: a generated scene graphic made of primitives (text, shape, connector,
 * icon, number, logo, media) on a normalised canvas, in design units relative to the block box. The renderer
 * (blocks-composition.tsx) draws exactly these numbers and the QA layout manifest (texts.ts → manifest.ts) reports
 * them, so overflow / OCR checks see what is drawn. No React / Remotion imports.
 *
 * - The canvas has a fixed aspect per layout: `tall` (Shorts, narrow split columns) and `wide` (block ≥ wideMin design
 *   px, i.e. a 16:9 stack). Each element has a `box` (tall) and an optional `wide` box, as fractions of the canvas.
 * - Text is fitted deterministically: the largest font size (≤ the role's base size) at which the string wraps into at
 *   most `maxLines[role]` lines inside its box. When even the minimum size does not fit, the run is laid out on one line
 *   at that size and the manifest reports the overflow (the composer rejects such candidates).
 * - Circles, rings and arcs use the shorter side of their box (never distorted); connectors run between the edges of
 *   the elements they join.
 */
import {AspectEnv, containRect, formatNumber, LogoSpec, Rect, T, TextSpec, wrapByWidth} from './geometry';
import {estimateTextWidth, fitFontSize, WEIGHT} from './motion/typography';
import {BlockV2, CompositionElement, CompositionRole} from './types';

type B = Extract<BlockV2, {type: 'composition'}>;

export const COMPOSITION = {
  /** natural (maximum) design width: a 16:9 stack gets the wide layout, the 940-unit Short column the tall one */
  naturalW: 1500,
  /** blocks at least this wide (design px) use each element's `wide` box */
  wideMin: 1100,
  /** default canvas aspect (width / height) per layout, and the accepted range */
  aspect: {tall: 1, wide: 1.9},
  aspectMin: 0.4,
  aspectMax: 3,
  /** text: base / minimum font size, weight and maximum lines per role (design px) */
  fs: {title: 60, label: 42, body: 34, value: 46},
  minFs: {title: 30, label: 24, body: 22, value: 24},
  weight: {title: WEIGHT.heavy, label: WEIGHT.bold, body: WEIGHT.semibold, value: WEIGHT.heavy},
  maxLines: {title: 2, label: 2, body: 3, value: 1},
  line: 1.18,
  /** number: base / minimum font size and line box */
  numberFs: 200,
  numberMinFs: 48,
  numberLine: 1.12,
  /** default stroke width (design px) and corner radius of a roundrect (fraction of its shorter side, max 28 px) */
  strokeW: 4,
  round: 0.22,
  roundMax: 28,
  /** gap between a connector's end and the element it touches */
  connectorGap: 8,
  maxElements: 64,
} as const;

const ROLE_QA: Record<CompositionRole, TextSpec['role']> = {title: 'title', label: 'label', body: 'body', value: 'label'};
const CURRENCY = /[₹$€£¥]/;
const num = (x: unknown, d: number) => (typeof x === 'number' && Number.isFinite(x) ? x : d);
const clamp = (x: number, a: number, b: number) => Math.min(b, Math.max(a, x));

export type CompositionLayout = 'tall' | 'wide';
export const compositionLayout = (w: number): CompositionLayout => (w >= COMPOSITION.wideMin ? 'wide' : 'tall');
export const compositionAspect = (b: Pick<B, 'canvas'>, layout: CompositionLayout) =>
  clamp(num(b.canvas?.[layout], COMPOSITION.aspect[layout]), COMPOSITION.aspectMin, COMPOSITION.aspectMax);
export const compositionNaturalW = () => COMPOSITION.naturalW;
/** Design height of the block at width w (the canvas). */
export const compositionHeight = (b: Pick<B, 'canvas'>, w: number) => Math.round(w / compositionAspect(b, compositionLayout(w)));

/** The element's box (design px, block-relative) for a layout. */
export const elementRect = (e: CompositionElement, layout: CompositionLayout, W: number, H: number): Rect => {
  const bx = layout === 'wide' && Array.isArray(e.wide) && e.wide.length === 4 ? e.wide : e.box;
  const [x, y, w, h] = [0, 1, 2, 3].map((k) => num(bx?.[k], 0));
  return {x: x * W, y: y * H, w: Math.max(0, w * W), h: Math.max(0, h * H)};
};
const squareIn = (r: Rect): Rect => {
  const s = Math.min(r.w, r.h);
  return {x: r.x + (r.w - s) / 2, y: r.y + (r.h - s) / 2, w: s, h: s};
};
const ROUND_SHAPES = new Set(['circle', 'ring', 'arc']);

// ------------------------------------------------------------------------------------------------ text fitting
export type FittedText = {fs: number; lines: string[]; fits: boolean};

/** Largest font size (role base → role minimum) at which `text` wraps into ≤ maxLines lines inside bw × bh. */
export const fitTextBox = (text: string, role: CompositionRole, bw: number, bh: number): FittedText => {
  const C = COMPOSITION;
  const weight = C.weight[role];
  const base = C.fs[role];
  const min = C.minFs[role];
  const words = text.split(/\s+/).filter(Boolean);
  let best: FittedText | null = null;
  for (let n = 1; n <= C.maxLines[role]; n++) {
    let fs = Math.min(base, Math.floor(bh / (n * C.line)));
    for (; fs >= min; fs--) {
      if (best && fs <= best.fs) break;
      const widths = words.map((x) => estimateTextWidth(x, fs, {weight}));
      const lines = wrapByWidth(words, widths, fs * 0.26, bw).map((l) => l.map((i) => words[i]).join(' '));
      if (lines.length <= n && lines.every((l) => estimateTextWidth(l, fs, {weight}) <= bw)) {
        best = {fs, lines, fits: true};
        break;
      }
    }
  }
  if (best) return best;
  return {fs: min, lines: [words.join(' ')], fits: false};
};

const textRuns = (s: string, role: CompositionRole, align: 'left' | 'center' | 'right', r: Rect): TextSpec[] => {
  const f = fitTextBox(s, role, r.w, r.h);
  const lh = Math.round(f.fs * COMPOSITION.line);
  const y0 = r.y + (r.h - lh * f.lines.length) / 2;
  return f.lines.map((l, i) => T(l, r.x, y0 + i * lh, r.w, lh, f.fs, COMPOSITION.weight[role], align, ROLE_QA[role]));
};

export const numberText = (e: Pick<CompositionElement, 'prefix' | 'suffix' | 'decimals' | 'grouping'>, v: number) =>
  `${e.prefix ?? ''}${formatNumber(v, e.decimals ?? 0, e.grouping ?? 'none')}${e.suffix ?? ''}`;

// ------------------------------------------------------------------------------------------------ paths
const arcPath = (cx: number, cy: number, r: number, startDeg: number, sweepDeg: number) => {
  const sweep = clamp(sweepDeg, 0, 360);
  const pt = (deg: number) => {
    const a = (deg * Math.PI) / 180;
    return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  };
  if (sweep >= 359.999) {
    const [x0, y0] = pt(startDeg);
    const [x1, y1] = pt(startDeg + 180);
    return `M ${x0} ${y0} A ${r} ${r} 0 1 1 ${x1} ${y1} A ${r} ${r} 0 1 1 ${x0} ${y0}`;
  }
  const [x0, y0] = pt(startDeg);
  const [x1, y1] = pt(startDeg + sweep);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${sweep > 180 ? 1 : 0} 1 ${x1} ${y1}`;
};

/** Point where the ray from the centre of `r` towards (dx, dy) leaves the element (circle or rect), plus a gap. */
const edgePoint = (r: Rect, round: boolean, dx: number, dy: number, gap: number): [number, number] => {
  const cx = r.x + r.w / 2;
  const cy = r.y + r.h / 2;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  let d: number;
  if (round) d = Math.min(r.w, r.h) / 2;
  else {
    const tx = Math.abs(ux) > 1e-9 ? r.w / 2 / Math.abs(ux) : Infinity;
    const ty = Math.abs(uy) > 1e-9 ? r.h / 2 / Math.abs(uy) : Infinity;
    d = Math.min(tx, ty);
  }
  return [cx + ux * (d + gap), cy + uy * (d + gap)];
};

// ------------------------------------------------------------------------------------------------ geometry
export type CompositionPart = {
  index: number;
  el: CompositionElement;
  /** drawn rect, design px relative to the block (connectors: the path's bounding box) */
  rect: Rect;
  /** text lines (text) or the number's final run (number) */
  texts: TextSpec[];
  /** connector / arc / line path in block coordinates */
  path?: string;
  /** roundrect corner radius */
  radius?: number;
  strokeW?: number;
  logo?: LogoSpec;
};

export const geomComposition = (b: B, w: number, env: AspectEnv) => {
  const layout = compositionLayout(w);
  const aspect = compositionAspect(b, layout);
  const h = Math.round(w / aspect);
  const els = (b.elements ?? []).slice(0, COMPOSITION.maxElements);
  const rects = els.map((e) => elementRect(e, layout, w, h));
  const byId = new Map<string, number>();
  els.forEach((e, i) => {
    if (e.id) byId.set(e.id, i);
  });
  const parts: CompositionPart[] = [];
  const texts: TextSpec[] = [];
  const logos: LogoSpec[] = [];
  els.forEach((e, i) => {
    const r = rects[i];
    const sw = clamp(num(e.strokeW, COMPOSITION.strokeW), 1, 40);
    const part: CompositionPart = {index: i, el: e, rect: r, texts: []};
    switch (e.kind) {
      case 'text':
        if (e.text) part.texts = textRuns(e.text, e.role ?? 'label', e.align ?? 'center', r);
        break;
      case 'number': {
        const a = numberText(e, num(e.to, 0));
        const z = numberText(e, num(e.from, 0));
        const widest = a.length >= z.length ? a : z;
        const base = Math.min(COMPOSITION.numberFs, Math.floor(r.h / COMPOSITION.numberLine));
        const fs = fitFontSize(widest, Math.max(COMPOSITION.numberMinFs, base), r.w * 0.96, {weight: WEIGHT.heavy, minFs: COMPOSITION.numberMinFs});
        const lh = Math.round(fs * COMPOSITION.numberLine);
        const role = CURRENCY.test(e.prefix ?? '') || CURRENCY.test(e.suffix ?? '') ? 'price' : 'title';
        part.texts = [T(a, r.x, r.y + (r.h - lh) / 2, r.w, lh, fs, WEIGHT.heavy, 'center', role, {ls: -0.03 * fs})];
        break;
      }
      case 'shape': {
        const shape = e.shape ?? 'rect';
        part.strokeW = sw;
        if (ROUND_SHAPES.has(shape)) part.rect = squareIn(r);
        if (shape === 'roundrect') part.radius = Math.min(COMPOSITION.roundMax, Math.min(r.w, r.h) * COMPOSITION.round);
        if (shape === 'arc' || shape === 'ring') {
          const q = part.rect;
          part.path = arcPath(q.x + q.w / 2, q.y + q.h / 2, Math.max(0, q.w / 2 - sw / 2), num(e.start, 0), shape === 'ring' ? 360 : num(e.sweep, 360));
        }
        if (shape === 'line') {
          part.path = r.w >= r.h ? `M ${r.x} ${r.y + r.h / 2} L ${r.x + r.w} ${r.y + r.h / 2}` : `M ${r.x + r.w / 2} ${r.y} L ${r.x + r.w / 2} ${r.y + r.h}`;
        }
        break;
      }
      case 'connector': {
        const fi = e.fromId !== undefined ? byId.get(e.fromId) : undefined;
        const ti = e.toId !== undefined ? byId.get(e.toId) : undefined;
        part.strokeW = sw;
        if (fi === undefined || ti === undefined || fi === ti) break;
        const ra = rects[fi];
        const rb = rects[ti];
        const roundA = els[fi].kind === 'shape' && ROUND_SHAPES.has(els[fi].shape ?? '');
        const roundB = els[ti].kind === 'shape' && ROUND_SHAPES.has(els[ti].shape ?? '');
        const dx = rb.x + rb.w / 2 - (ra.x + ra.w / 2);
        const dy = rb.y + rb.h / 2 - (ra.y + ra.h / 2);
        const [x1, y1] = edgePoint(ra, roundA, dx, dy, COMPOSITION.connectorGap);
        const [x2, y2] = edgePoint(rb, roundB, -dx, -dy, COMPOSITION.connectorGap);
        const bend = clamp(num(e.curve, 0), -1, 1);
        const L = Math.hypot(x2 - x1, y2 - y1);
        if (Math.abs(bend) < 1e-6) {
          part.path = `M ${x1} ${y1} L ${x2} ${y2}`;
          part.rect = {x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1)};
        } else {
          const nx = L ? -(y2 - y1) / L : 0;
          const ny = L ? (x2 - x1) / L : 0;
          const cx = (x1 + x2) / 2 + nx * bend * L * 0.5;
          const cy = (y1 + y2) / 2 + ny * bend * L * 0.5;
          part.path = `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
          const xs = [x1, x2, cx];
          const ys = [y1, y2, cy];
          part.rect = {x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys)};
        }
        break;
      }
      case 'icon':
        part.rect = squareIn(r);
        break;
      case 'logo': {
        const v = e.variant ?? 'onDark';
        const expected = env.asset(env.logoPaths?.[v] ?? '') ?? env.logo[v];
        part.logo = {...containRect(r, expected), variant: v, expected};
        part.rect = {x: part.logo.x, y: part.logo.y, w: part.logo.w, h: part.logo.h};
        break;
      }
      case 'media': {
        const a = e.asset ? env.asset(e.asset) : undefined;
        if (a) part.rect = containRect(r, a);
        break;
      }
    }
    parts.push(part);
    texts.push(...part.texts);
    if (part.logo) logos.push(part.logo);
  });
  return {layout, aspect, h, parts, texts, logos};
};

/** Earliest element time (so an un-timed composition block never hides its own timed parts). */
export const compositionFirstTime = (b: Pick<B, 'elements'>): number | undefined => {
  const ts = (b.elements ?? []).map((e) => e.at).filter((x): x is number => typeof x === 'number' && Number.isFinite(x));
  return ts.length ? Math.min(...ts) - 0.1 : undefined;
};
