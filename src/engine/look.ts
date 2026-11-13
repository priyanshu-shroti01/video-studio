/**
 * v2b "look": scene backdrops, their crossfades, the split-panel geometry and the polish gate. Pure (no React /
 * Remotion), shared by the renderer (backdrops.tsx, Storyboard.tsx) and the planner / QA manifest (plan.ts).
 *
 * Polish gate: props opt into the v2b look by using it — any scene `backdrop` or any v2b block type. Props
 * without either (every v1 and pre-v2b v2 storyboard) render bit-identically to the v2 engine.
 */
import {isV2} from './contract';
import {EASE} from './motion/easings';
import {BackdropKind, Format, RenderProps, Scene} from './types';

export const BACKDROPS: readonly BackdropKind[] = ['glow', 'spotlight', 'grid', 'split', 'light', 'deep'];
export const V2B_BLOCKS: ReadonlySet<string> = new Set(['plan-card', 'install-flow', 'server-stack']);

export const isPolished = (props: Pick<RenderProps, 'contractVersion' | 'scenes'>) =>
  isV2(props) && props.scenes.some((s) => s.backdrop !== undefined || s.blocks.some((b) => V2B_BLOCKS.has(b.type)));

export const backdropOf = (s: Pick<Scene, 'backdrop'>): BackdropKind => (s.backdrop && BACKDROPS.includes(s.backdrop) ? s.backdrop : 'glow');
export const isLightScene = (s: Pick<Scene, 'backdrop'>) => backdropOf(s) === 'light';

/** Half-width (s) of the backdrop crossfade centred on each scene boundary; shorter between a light and a dark
 *  backdrop (a long 50/50 mix of the two reads as a muddy grey). */
export const BACKDROP_XFADE = 0.3;
export const BACKDROP_XFADE_LUMA = 0.14;
const xfade = (a: Pick<Scene, 'backdrop'> | undefined, b: Pick<Scene, 'backdrop'> | undefined) =>
  a && b && isLightScene(a) !== isLightScene(b) ? BACKDROP_XFADE_LUMA : BACKDROP_XFADE;

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lin = (t: number, a: number, b: number) => (b <= a ? (t >= b ? 1 : 0) : clamp01((t - a) / (b - a)));

/**
 * Weight (0..1, summing to 1) of every backdrop kind at t. Each scene owns its backdrop from start to end with
 * an eased crossfade of ±BACKDROP_XFADE around each boundary (the first scene owns t < start, the last t > end),
 * so two adjacent scenes with different backdrops blend smoothly and equal ones never dip.
 */
export const backdropWeights = (scenes: Pick<Scene, 'start' | 'end' | 'backdrop'>[], t: number): Partial<Record<BackdropKind, number>> => {
  const w: Partial<Record<BackdropKind, number>> = {};
  if (!scenes.length) return {glow: 1};
  const sorted = [...scenes].sort((a, b) => a.start - b.start);
  let sum = 0;
  sorted.forEach((s, i) => {
    const xi = xfade(sorted[i - 1], s);
    const xo = xfade(s, sorted[i + 1]);
    const rise = i === 0 ? 1 : EASE.inOutSine(lin(t, s.start - xi, s.start + xi));
    const fall = i === sorted.length - 1 ? 1 : 1 - EASE.inOutSine(lin(t, s.end - xo, s.end + xo));
    const v = rise * fall;
    if (v <= 0) return;
    const k = backdropOf(s);
    w[k] = (w[k] ?? 0) + v;
    sum += v;
  });
  if (sum <= 0) {
    // inside a gap between scenes: the nearest scene's backdrop
    const near = sorted.reduce((best, s) => (Math.min(Math.abs(t - s.start), Math.abs(t - s.end)) < Math.min(Math.abs(t - best.start), Math.abs(t - best.end)) ? s : best));
    return {[backdropOf(near)]: 1};
  }
  for (const k of Object.keys(w) as BackdropKind[]) w[k] = (w[k] ?? 0) / sum;
  return w;
};

/**
 * The 'split' brand panel (output px). Short: a top band whose lower edge runs diagonally from yLeft to yRight;
 * landscape: a left panel whose right edge runs diagonally from xTop to xBottom. `contentTop` / `contentLeft`
 * is where the layout's content area starts (clear of the panel at its widest point, plus a gap).
 */
export const SPLIT = {
  short: {yLeft: 0.135, yRight: 0.085, gap: 40},
  landscape: {xTop: 0.3, xBottom: 0.22, gap: 64},
} as const;
export const splitPanel = (format: Format, width: number, height: number) => {
  if (format === 'short') {
    const a = SPLIT.short.yLeft * height;
    const b = SPLIT.short.yRight * height;
    return {polygon: [[0, 0], [width, 0], [width, b], [0, a]] as [number, number][], contentTop: Math.max(a, b) + SPLIT.short.gap, contentLeft: 0};
  }
  const a = SPLIT.landscape.xTop * width;
  const b = SPLIT.landscape.xBottom * width;
  return {polygon: [[0, 0], [a, 0], [b, height], [0, height]] as [number, number][], contentTop: 0, contentLeft: Math.max(a, b) + SPLIT.landscape.gap};
};
