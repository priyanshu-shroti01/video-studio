/**
 * Branding geometry (pure): logo aspects, the brand bar, and the v2 watermark (policy → asset, corner
 * placement per format, duplicate-branding suppression). Shared by the renderer and the QA manifest.
 */
import {captionBandTop, legacyLogoAspects} from './layout';
import {DIMENSIONS} from './contract';
import {AspectEnv, Rect} from './geometry';
import {BRANDBAR_DUR, WATERMARK_DUR} from './motion/durations';
import {LogoVariant, RenderProps, Watermark, WatermarkPosition} from './types';

const clamp = (x: number, a: number, b: number) => Math.min(b, Math.max(a, x));

/**
 * Logo + asset aspects. v1 props keep the v1 numbers (theme.logo.aspect, mark 1.7) so they render
 * exactly as before; v2 uses theme.logo.aspects, else each file's intrinsic aspect (SVG viewBox / PNG
 * header, resolved into props.assetAspects by calculateMetadata or the manifest script).
 */
export const aspectEnv = (props: Pick<RenderProps, 'contractVersion' | 'theme' | 'assetAspects'>): AspectEnv => {
  const L = props.theme.logo;
  const logoPaths = {onDark: L.onDark, onLight: L.onLight, mark: L.mark};
  if (props.contractVersion < 2) return {logo: legacyLogoAspects(L.aspect), asset: (p) => props.assetAspects?.[p], logoPaths};
  const legacy = legacyLogoAspects(L.aspect);
  const pick = (v: LogoVariant) => L.aspects?.[v] ?? props.assetAspects?.[logoPaths[v]] ?? legacy[v];
  return {logo: {onDark: pick('onDark'), onLight: pick('onLight'), mark: pick('mark')}, asset: (p) => props.assetAspects?.[p], logoPaths};
};

/** The persistent top-centre brand bar logo (v1 geometry). */
export const BRAND_BAR = {short: {w: 380, cy: 160}, landscape: {w: 300, cy: 72}} as const;
export const brandBarRect = (format: RenderProps['format'], onDarkAspect: number): Rect => {
  const {width} = DIMENSIONS[format];
  const s = BRAND_BAR[format];
  const h = s.w / onDarkAspect;
  return {x: (width - s.w) / 2, y: s.cy - h / 2, w: s.w, h};
};
export const brandBarVisible = (bar: RenderProps['brandBar'], t: number) => !!bar && t >= bar.from - BRANDBAR_DUR.pad && t <= bar.to + BRANDBAR_DUR.pad;

/** Per-format watermark defaults (fractions of the frame width). */
export const WATERMARK_DEFAULTS = {
  short: {markWidthFrac: 0.085, logoWidthFrac: 0.26, marginFrac: 0.045, topInset: 120, overlayFrac: 0.2, platform: 'top-left' as WatermarkPosition},
  landscape: {markWidthFrac: 0.042, logoWidthFrac: 0.13, marginFrac: 0.028, topInset: 0, overlayFrac: 0, platform: 'top-right' as WatermarkPosition},
  opacity: 0.9,
} as const;

export type WatermarkPlan = {
  policy: Exclude<Watermark['policy'], 'none'>;
  src: string;
  variant: LogoVariant | 'custom';
  opacity: number;
  position: WatermarkPosition;
  rect: Rect;
  aspect: number;
  /** intervals (s) where other branding is visible → watermark fully hidden */
  busy: [number, number][];
  /** intervals (s) where the watermark is drawn (opacity > 0) */
  visibleRanges: [number, number][];
};

const mergeIntervals = (xs: [number, number][], gap = 0) => {
  const s = [...xs].filter(([a, b]) => b > a).sort((p, q) => p[0] - q[0]);
  const out: [number, number][] = [];
  for (const [a, b] of s) {
    const last = out[out.length - 1];
    if (last && a <= last[1] + gap) last[1] = Math.max(last[1], b);
    else out.push([a, b]);
  }
  return out;
};
const r3 = (x: number) => Math.round(x * 1000) / 1000;

/**
 * Resolves the watermark: asset + aspect, rect (output px) and visibility. `busy` = intervals where a
 * logo / cta / logo-sting / outro block or the brand bar is visible (computed by plan.ts).
 */
export const planWatermark = (props: RenderProps, env: AspectEnv, busyRaw: [number, number][]): WatermarkPlan | null => {
  const wm = props.watermark;
  if (props.contractVersion < 2 || !wm || wm.policy === 'none') return null;
  const {width: W, height: H} = DIMENSIONS[props.format];
  const D = WATERMARK_DEFAULTS[props.format];
  let src: string;
  let variant: LogoVariant | 'custom';
  if (wm.policy === 'custom') {
    if (!wm.asset) throw new Error('watermark policy "custom" requires `asset` (a path relative to public/)');
    src = wm.asset;
    variant = 'custom';
  } else {
    variant = wm.variant ?? (wm.policy === 'platform' ? 'mark' : 'onDark');
    src = props.theme.logo[variant];
  }
  const aspect = (variant === 'custom' ? env.asset(src) : env.logo[variant]) ?? 1;
  const isMark = variant === 'mark' || aspect < 2;
  const widthFrac = clamp(wm.widthFrac ?? (isMark ? D.markWidthFrac : D.logoWidthFrac), 0.02, 0.4);
  const m = clamp(wm.marginFrac ?? D.marginFrac, 0, 0.15) * W;
  let w = widthFrac * W;
  let h = w / aspect;
  if (h > 0.1 * H) {
    h = 0.1 * H;
    w = h * aspect;
  }
  const position: WatermarkPosition = wm.policy === 'platform' ? D.platform : (wm.position ?? D.platform);
  const x = position.endsWith('left') ? m : position.endsWith('right') ? W - m - w : (W - w) / 2;
  let y: number;
  if (position.startsWith('top')) y = Math.max(m, D.topInset);
  else {
    const cap = props.captions;
    const capBottom = cap.enabled ? H - H * cap.bottomFrac : H;
    if (props.format === 'short') {
      // Shorts: between the caption box and the platform overlay (bottom ~20% is covered by the player UI)
      y = Math.max(H * (1 - D.overlayFrac) - h - m * 0.5, capBottom + 12);
    } else {
      y = H - m - h;
      const colX0 = (W * (1 - cap.maxWidthFrac)) / 2;
      const colX1 = W - colX0;
      const overlapsCol = x < colX1 && x + w > colX0;
      if (cap.enabled && overlapsCol && y < capBottom && y + h > captionBandTop(props.format, cap)) y = capBottom + 8;
    }
    y = Math.min(y, H - h - 4);
  }
  const duration = props.durationInFrames / props.fps;
  // gaps shorter than a fade in + out (incl. at the very start / end) would only flicker: hide through them
  const gap = 2 * WATERMARK_DUR.fade;
  const busy = mergeIntervals(
    busyRaw.map(([a, b]) => [a < gap ? 0 : a, duration - b < gap ? duration : b] as [number, number]).map(([a, b]) => [Math.max(0, a), Math.min(duration, b)] as [number, number]),
    gap,
  );
  const visibleRanges: [number, number][] = [];
  let cur = 0;
  for (const [a, b] of busy) {
    if (a > cur) visibleRanges.push([r3(cur), r3(a)]);
    cur = Math.max(cur, b);
  }
  if (cur < duration) visibleRanges.push([r3(cur), r3(duration)]);
  return {
    policy: wm.policy,
    src,
    variant,
    opacity: clamp(wm.opacity ?? WATERMARK_DEFAULTS.opacity, 0.05, 1),
    position,
    rect: {x, y, w, h},
    aspect,
    busy: busy.map(([a, b]) => [r3(a), r3(b)]),
    visibleRanges,
  };
};

/** 0..1 visibility at t: 0 inside any busy interval, fades over WATERMARK_DUR.fade around them and at t=0. */
export const watermarkFactor = (plan: Pick<WatermarkPlan, 'busy'>, t: number) => {
  const f = WATERMARK_DUR.fade;
  let v = Math.min(1, Math.max(0, t / f));
  for (const [a, b] of plan.busy) {
    if (t >= a && t <= b) return 0;
    const d = t < a ? a - t : t - b;
    v = Math.min(v, Math.min(1, d / f));
  }
  return v;
};

export const rectsIntersect = (a: Rect, b: Rect, pad = 0) =>
  a.x < b.x + b.w + pad && a.x + a.w + pad > b.x && a.y < b.y + b.h + pad && a.y + a.h + pad > b.y;
