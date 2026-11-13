import {captionBoxHeight} from './captions';
import {Block, CaptionConfig, Format, Scene} from './types';
import {DIMENSIONS} from './contract';
import {
  AspectEnv,
  DEVICE_W,
  geomChart,
  geomCounter,
  geomDashboard,
  geomDevice,
  geomFeatureCompare,
  geomImage,
  geomKinetic,
  geomLogoSting,
  geomOutro,
  geomPriceCompare,
  geomProgress,
  geomScrollDemo,
  geomTerminal,
  imageNaturalW,
  LogoAspects,
  NATURAL_W,
  pillMinW,
} from './geometry';
import {compositionFirstTime, compositionHeight, compositionNaturalW} from './geometry-composition';
import {footageNaturalW, geomFootage} from './geometry-footage';
import {geomInstallFlow, geomPlanCard, geomServerStack} from './geometry-v2b';
import {CHAR_W, CTA_FS, HEADLINE_FS, TEXT_FS} from './motion/typography';

export {CTA_FS, HEADLINE_FS, TEXT_FS};

/**
 * Deterministic layout. Blocks are designed in "design units" (the 1080-wide Short scale) with fixed
 * heights per type/size; each block box is then scaled by k (format scale) × fit (shrink-to-fit).
 * Text wrapping is computed here too and the renderer draws exactly these lines, so what we measure
 * is what we draw — the layout is testable without a DOM.
 */
export const FORMAT_SPEC: Record<Format, {k: number; side: number; gap: number; topWithBar: number; topNoBar: number; colGap: number}> = {
  short: {k: 1, side: 70, gap: 40, topWithBar: 250, topNoBar: 130, colGap: 0},
  landscape: {k: 0.85, side: 140, gap: 34, topWithBar: 150, topNoBar: 70, colGap: 90},
};

/** Greedy word wrap by estimated advance width. Returns word-index lines. (v1 estimator: chars × em.) */
export const wrapWords = (words: string[], fontSize: number, maxWidth: number, charW = CHAR_W): number[][] => {
  const lines: number[][] = [];
  let cur: number[] = [];
  let width = 0;
  const space = fontSize * 0.3;
  words.forEach((w, i) => {
    const ww = w.length * fontSize * charW;
    const next = cur.length ? width + space + ww : ww;
    if (cur.length && next > maxWidth) {
      lines.push(cur);
      cur = [i];
      width = ww;
    } else {
      cur.push(i);
      width = next;
    }
  });
  if (cur.length) lines.push(cur);
  return lines;
};

export const splitText = (s: string) => s.split(/\s+/).filter(Boolean);

/** v1 aspect of the mark (kept for contractVersion 1 only; v2 uses the SVG's own viewBox). */
export const MARK_ASPECT = 1.7;

/** Normalises the v1 `logoAspect: number` argument into an AspectEnv. */
export const toAspectEnv = (a: number | AspectEnv): AspectEnv =>
  typeof a === 'number' ? {logo: {onDark: a, onLight: a, mark: MARK_ASPECT}, asset: () => undefined} : a;
export const legacyLogoAspects = (aspect: number): LogoAspects => ({onDark: aspect, onLight: aspect, mark: MARK_ASPECT});

/** Narrowest design width a block can take without overflowing: wrapping text needs no minimum; a pill needs its
 *  single line; fixed-size blocks need their natural width. Used to keep a narrow 'split' column usable. */
export const minContentW = (b: Block, colDesignW: number, env: number | AspectEnv = 5): number => {
  switch (b.type) {
    case 'headline':
    case 'text':
    case 'kinetic-text':
      return 0;
    case 'pill':
      return pillMinW(b);
    default:
      return naturalWidth(b, colDesignW, env);
  }
};

/** Natural (maximum) design width of a block. */
export const naturalWidth = (b: Block, colDesignW: number, env: number | AspectEnv = 5): number => {
  switch (b.type) {
    case 'logo':
      return b.width ?? (b.variant === 'mark' ? 260 : 760);
    case 'headline':
    case 'text':
    case 'pill':
    case 'kinetic-text':
      return colDesignW;
    case 'price':
      return 900;
    case 'checklist':
      return 840;
    case 'bars':
      return 880;
    case 'compare-rows':
      return 860;
    case 'plans':
      return 960;
    case 'domain-input':
      return 900;
    case 'browser':
      return 880;
    case 'hook-tag':
      return 520;
    case 'flat-line':
      return 900;
    case 'cta':
      return 980;
    case 'device':
      return DEVICE_W[b.frame];
    case 'image':
      return imageNaturalW(b, toAspectEnv(env));
    case 'footage':
      return footageNaturalW(b, toAspectEnv(env));
    case 'composition':
      return compositionNaturalW();
    default:
      return NATURAL_W[b.type];
  }
};

/** Design height of a block at design width `w`. */
export const measureBlock = (b: Block, w: number, logoAspect: number | AspectEnv): number => {
  const env = toAspectEnv(logoAspect);
  switch (b.type) {
    case 'logo':
      return Math.round(w / env.logo[b.variant]);
    case 'headline': {
      const fs = HEADLINE_FS[b.size];
      return Math.round(wrapWords(b.words.map((x) => x.text), fs, w).length * fs * 1.08 + 12);
    }
    case 'text': {
      const fs = TEXT_FS[b.size];
      return Math.round(wrapWords(splitText(b.text), fs, w, 0.56).length * fs * 1.25);
    }
    case 'pill':
      return b.stamp ? 116 : 84;
    case 'price':
      return (b.label ? 62 : 0) + 300 + (b.note ? 44 : 0);
    case 'checklist':
      return b.items.length * 108 + Math.max(0, b.items.length - 1) * 22;
    case 'bars':
      return 500;
    case 'compare-rows':
      return 50 + 40 + b.rows.length * 110 + Math.max(0, b.rows.length - 1) * 2;
    case 'plans':
      return 36 + 450;
    case 'domain-input':
      return 490;
    case 'browser':
      return 470;
    case 'hook-tag':
      return 330;
    case 'flat-line':
      return 330;
    case 'cta':
      return Math.round(wrapWords(splitText(b.text), CTA_FS, w).length * CTA_FS * 1.1 + 30 + 150 + (b.sub ? 70 : 0));
    case 'kinetic-text':
      return geomKinetic(b, w).h;
    case 'counter':
      return geomCounter(b, w).h;
    case 'price-compare':
      return geomPriceCompare(b, w, env.polish).h;
    case 'terminal':
      return geomTerminal(b, w).h;
    case 'dashboard':
      return geomDashboard(b, w, env).h;
    case 'device':
      return geomDevice(b, w, env).h;
    case 'image':
      return geomImage(b, w, env).h;
    case 'progress':
      return geomProgress(b, w).h;
    case 'scroll-demo':
      return geomScrollDemo(b, w).h;
    case 'chart':
      return geomChart(b, w, env.polish).h;
    case 'feature-compare':
      return geomFeatureCompare(b, w, env.polish).h;
    case 'logo-sting':
      return geomLogoSting(b, w, env).h;
    case 'outro':
      return geomOutro(b, w, env).h;
    case 'plan-card':
      return geomPlanCard(b, w).h;
    case 'install-flow':
      return geomInstallFlow(b, w).h;
    case 'server-stack':
      return geomServerStack(b, w).h;
    case 'footage':
      return geomFootage(b, w, env).h;
    case 'composition':
      return compositionHeight(b, w);
  }
};

/** Earliest internal reveal time of a block (so an un-timed block never hides its own timed parts). */
export const firstInternalTime = (b: Block): number | undefined => {
  const min = (xs: (number | undefined)[]) => {
    const ts = xs.filter((x): x is number => x !== undefined);
    return ts.length ? Math.min(...ts) : undefined;
  };
  switch (b.type) {
    case 'headline':
    case 'kinetic-text':
      return min(b.words.map((w) => w.at));
    case 'checklist':
      return b.items.length ? Math.min(...b.items.map((i) => i.at)) : undefined;
    case 'bars':
      return b.bars.length ? Math.min(...b.bars.map((x) => x.at)) : undefined;
    case 'compare-rows':
    case 'price-compare':
    case 'feature-compare':
      return b.rows.length ? Math.min(...b.rows.map((r) => r.at)) : undefined;
    case 'domain-input':
      return b.keyTimes.length ? b.keyTimes[0] - 0.3 : undefined;
    case 'terminal':
      return b.lines.length ? Math.min(...b.lines.map((l) => l.at)) - 0.3 : undefined;
    case 'progress':
      return b.steps.length ? Math.min(...b.steps.map((s) => s.at)) - 0.2 : undefined;
    case 'install-flow':
      return b.steps.length ? Math.min(...b.steps.map((s) => s.at)) - 0.3 : undefined;
    case 'server-stack':
      return b.nodes.length ? Math.min(...b.nodes.map((s) => s.at)) - 0.3 : undefined;
    case 'composition':
      return compositionFirstTime(b);
    default:
      return undefined;
  }
};

export type Box = {x: number; y: number; w: number; h: number; scale: number; designW: number; designH: number; col: 0 | 1};
export type SceneLayout = {top: number; bottom: number; fit: number; scale: number; boxes: Box[]; split: boolean; side: number};

/** Top of the caption band (content must end above this line). */
export const captionBandTop = (format: Format, captions: Pick<CaptionConfig, 'enabled' | 'bottomFrac' | 'fontSize'>) => {
  const {height} = DIMENSIONS[format];
  if (!captions.enabled) return height - 90 * FORMAT_SPEC[format].k;
  return height - height * captions.bottomFrac - captionBoxHeight(captions.fontSize, 2) - 24;
};

/** v2 layout options: insets reserved for the camera move and a raised top (e.g. under a watermark).
 *  v2b: `leftMin` (content area starts right of this x, e.g. the 'split' brand panel) and `hero` (scale a sparse
 *  scene up to fill the content area, see HERO). */
export type LayoutOpts = {reserveX?: number; reserveY?: number; topMin?: number; leftMin?: number; hero?: boolean};

/** v2b hero scaling: a scene whose blocks use little of the content area grows (width- and height-limited) up to
 *  `single` (one block) / `multi` (several), filling at most `fill` of the area's height. */
export const HERO = {single: 1.5, multi: 1.18, fill: 0.9} as const;

export const layoutScene = (
  scene: Pick<Scene, 'layout' | 'splitAt' | 'splitRatio' | 'blocks'>,
  format: Format,
  captions: Pick<CaptionConfig, 'enabled' | 'bottomFrac' | 'fontSize'>,
  brandBarActive: boolean,
  logoAspect: number | AspectEnv,
  opts: LayoutOpts = {},
): SceneLayout => {
  const {width} = DIMENSIONS[format];
  const spec = FORMAT_SPEC[format];
  const rx = opts.reserveX ?? 0;
  const ry = opts.reserveY ?? 0;
  const top = Math.max(brandBarActive ? spec.topWithBar : spec.topNoBar, opts.topMin ?? 0) + ry;
  const bottom = captionBandTop(format, captions) - ry;
  const side = spec.side + rx;
  const left = Math.max(side, opts.leftMin !== undefined ? opts.leftMin + rx : 0);
  const avail = Math.max(1, bottom - top);
  const split = format === 'landscape' && scene.layout === 'split' && scene.blocks.length > 1;
  const splitAt = split ? Math.min(Math.max(1, scene.splitAt ?? Math.ceil(scene.blocks.length / 2)), scene.blocks.length - 1) : scene.blocks.length;
  // (kept as `width - 2 * side` without a leftMin: float-identical to the v1/v2 layout)
  const areaW = opts.leftMin === undefined ? width - 2 * side : width - side - left;
  const ratio = split ? Math.min(0.7, Math.max(0.3, scene.splitRatio ?? 0.5)) : 1;
  const colWs = split ? [(areaW - spec.colGap) * ratio, (areaW - spec.colGap) * (1 - ratio)] : [areaW];
  if (split && ratio !== 0.5) {
    // splitRatio is a preference: the narrower column still gets its content's natural width (up to half)
    const total = areaW - spec.colGap;
    const narrow = ratio > 0.5 ? 1 : 0;
    const idx = narrow ? scene.blocks.slice(splitAt).map((_, i) => i + splitAt) : scene.blocks.slice(0, splitAt).map((_, i) => i);
    const need = Math.max(0, ...idx.map((i) => minContentW(scene.blocks[i], total / spec.k, logoAspect) * spec.k));
    colWs[narrow] = Math.max(colWs[narrow], Math.min(need, total / 2));
    colWs[1 - narrow] = total - colWs[narrow];
  }
  const columns: {idx: number[]; x: number; w: number}[] = split
    ? [
        {idx: scene.blocks.slice(0, splitAt).map((_, i) => i), x: left, w: colWs[0]},
        {idx: scene.blocks.slice(splitAt).map((_, i) => i + splitAt), x: left + colWs[0] + spec.colGap, w: colWs[1]},
      ]
    : [{idx: scene.blocks.map((_, i) => i), x: left, w: areaW}];
  const colOf = (i: number) => (split && i >= splitAt ? 1 : 0);

  const designW = scene.blocks.map((b, i) => {
    const cw = colWs[colOf(i)];
    return Math.min(naturalWidth(b, cw / spec.k, logoAspect), cw / spec.k);
  });
  const designH = scene.blocks.map((b, i) => measureBlock(b, designW[i], logoAspect));
  const colTotal = (idx: number[]) => idx.reduce((s, i) => s + designH[i] * spec.k, 0) + spec.gap * Math.max(0, idx.length - 1);
  let fit = Math.min(1, ...columns.map((c) => avail / Math.max(1, colTotal(c.idx))));
  if (opts.hero && fit >= 1 && scene.blocks.length) {
    // sparse scene: grow towards a hero, limited by the column width and HERO.fill of the height
    const cap = scene.blocks.length === 1 ? HERO.single : HERO.multi;
    const wLimit = Math.min(...designW.map((dw, i) => colWs[colOf(i)] / (dw * spec.k)));
    const hLimit = Math.min(...columns.map((c) => (avail * HERO.fill) / Math.max(1, colTotal(c.idx))));
    fit = Math.max(1, Math.min(cap, wLimit, hLimit));
  }
  const scale = spec.k * fit;

  const boxes: Box[] = new Array(scene.blocks.length);
  columns.forEach((c, ci) => {
    const total = colTotal(c.idx) * fit;
    let y = top + (avail - total) / 2;
    for (const i of c.idx) {
      const w = designW[i] * scale;
      const h = designH[i] * scale;
      boxes[i] = {x: c.x + (c.w - w) / 2, y, w, h, scale, designW: designW[i], designH: designH[i], col: ci as 0 | 1};
      y += h + spec.gap * fit;
    }
  });
  return {top, bottom, fit, scale, boxes, split, side};
};
