/**
 * Pure geometry + timing of the `footage` block (a real, muted video clip in browser / laptop / phone chrome),
 * in design units relative to the block box. The renderer (blocks-footage.tsx) draws from these numbers and the
 * QA layout manifest (manifest.ts) reports them. No React / Remotion imports.
 *
 * - The clip viewport always has the clip's own aspect, so the video is never distorted (the box follows the clip).
 * - Clip time = startFrom + (t − appear) · playbackRate, clamped to the last frame (hold, never black).
 * - Zoom keyframes are clamped so the view never leaves the clip, and eased in (centre, log scale) space, which
 *   keeps every in-between view inside the clip too (see `zoomAt`).
 */
import {DEVICE_W, Rect, T, TextSpec, AspectEnv} from './geometry';
import {DUR, LEAD} from './motion/durations';
import {EASE} from './motion/easings';
import {fitFontSize, WEIGHT} from './motion/typography';
import {BlockV2, FootageFit, FootageRegion} from './types';

type B = Extract<BlockV2, {type: 'footage'}>;
export type FootageFrame = NonNullable<B['frame']>;
export type Zoom = {x: number; y: number; scale: number};
/** Normalised size (fraction of the clip) of the visible window at scale 1. Frame fit: the whole clip {1, 1}.
 *  `min`: the smallest zoom of this view (a 9:16 fill never goes below FOOTAGE.fillMinScale; default 1). */
export type Win = {w: number; h: number; min?: number};
const FULL: Win = {w: 1, h: 1};

export const FOOTAGE = {
  /** natural (maximum) design width per frame. Wider than the 940-unit Short column (which caps it there), so a
   *  recording can grow in a wide 16:9 column; the clip's height (maxH) still bounds it */
  naturalW: {browser: 1240, none: 1200, laptop: DEVICE_W.laptop, phone: DEVICE_W.phone, phoneWide: 900},
  /** maximum design height of the clip viewport per frame (a tall recording gets a narrower box) */
  maxH: {browser: 760, none: 760, laptop: 640, phone: 1000, phoneWide: 600},
  chromeH: 72,
  border: 2,
  bezel: 16,
  capGap: 12,
  capH: 46,
  /** largest zoom factor (a 1280-px recording at ×4 shows 320 source px) */
  zoomMax: 4,
  /** a zoom move takes DUR.slower (or less, when the next keyframe starts sooner), eased in-out */
  zoomMove: DUR.slower,
  /** the held last frame is requested this far before the clip's end */
  endEps: 0.001,
  /** clip times are requested this much later, so a time exactly on a frame boundary (k / clip fps, float noise
   *  either side) always resolves to frame k */
  seekBias: 0.0001,
  fallbackAspect: 16 / 9,
  /** fit 'fill': viewport aspect (w / h) in a Short (a tall column; the crop window shows the named region big) and
   *  the corner radius. A 16:9 fill keeps the clip's own aspect (no crop at scale 1, just no chrome) */
  fillAspectShort: 0.95,
  /** a 9:16 fill never shows the crop below this zoom (desktop UI recorded at ~1.4× UI zoom then reads at phone size;
   *  the column already shows only ~⅔ of a 16:10 recording's width at scale 1) */
  fillMinScale: 1.4,
  fillRadius: 28,
  /** a zoom with a `region` frames it with this margin (the element takes ≤ 1 / 1.2 of the window) */
  regionMargin: 1.2,
  /** callout ("zoom lens") panel: max size as a fraction of the viewport, inset from its edges, pop / fade times */
  callout: {maxW: 0.9, maxH: 0.46, inset: 0.04, pop: DUR.medium, out: DUR.fast, radius: 22, border: 4, minMag: 1.25},
} as const;

const clamp = (x: number, a: number, b: number) => Math.min(b, Math.max(a, x));
const finitePos = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x) && x > 0;

export const footageFrame = (b: B): FootageFrame => (b.frame && ['browser', 'laptop', 'phone', 'none'].includes(b.frame) ? b.frame : 'browser');
/** The clip's aspect: the block's `aspect` (Python, ffprobe), else the file header (props.assetAspects), else 16:9. */
export const footageAspect = (b: B, env: AspectEnv) => (finitePos(b.aspect) ? b.aspect : (env.asset(b.asset) ?? FOOTAGE.fallbackAspect));

/** Design width of the frame for a clip viewport of width `sw` (inverse of the per-frame screen width). */
const frameWForScreenW = (f: FootageFrame, sw: number) =>
  f === 'laptop' ? (sw + 40) / 0.89 : f === 'phone' ? sw + 2 * FOOTAGE.bezel : f === 'browser' ? sw + 2 * FOOTAGE.border : sw;

/** 'frame' or 'fill' for this format (`fit` may be per format: {short: 'fill'}). */
export const footageFit = (b: Pick<B, 'fit'>, format?: 'short' | 'landscape'): FootageFit => {
  const f = typeof b.fit === 'string' ? b.fit : b.fit && format ? b.fit[format] : undefined;
  return f === 'fill' ? 'fill' : 'frame';
};

export const footageNaturalW = (b: B, env: AspectEnv) => {
  const f = footageFrame(b);
  if (footageFit(b, env.format) === 'fill') return env.format === 'short' ? FOOTAGE.naturalW.browser : Math.min(FOOTAGE.naturalW.browser, FOOTAGE.maxH.browser * footageAspect(b, env));
  const a = footageAspect(b, env);
  const key = f === 'phone' && a >= 1 ? 'phoneWide' : f;
  return Math.min(FOOTAGE.naturalW[key], frameWForScreenW(f, FOOTAGE.maxH[key] * a));
};

export const geomFootage = (b: B, w: number, env: AspectEnv) => {
  const fit = footageFit(b, env.format);
  const f = footageFrame(b);
  const aspect = footageAspect(b, env);
  const texts: TextSpec[] = [];
  let screen: Rect;
  let body: Rect;
  let bottom: number;
  let radius: number;
  let title: TextSpec | undefined;
  if (fit === 'fill') {
    // no chrome: the viewport is the block, at the fill aspect (a crop of the clip; the clip itself is never distorted)
    const va = env.format === 'short' ? FOOTAGE.fillAspectShort : aspect;
    screen = {x: 0, y: 0, w, h: w / va};
    body = {...screen};
    bottom = screen.h;
    radius = FOOTAGE.fillRadius;
  } else if (f === 'browser') {
    const {chromeH, border} = FOOTAGE;
    const sw = w - 2 * border;
    screen = {x: border, y: chromeH, w: sw, h: sw / aspect};
    body = {x: 0, y: 0, w, h: chromeH + screen.h + border};
    bottom = body.h;
    radius = 0;
    if (b.title) {
      const tw = w - 2 * 150;
      title = T(b.title, 150, 12, tw, chromeH - 24, fitFontSize(b.title, 26, tw, {weight: WEIGHT.bold, minFs: 18}), WEIGHT.bold, 'center', 'title');
      texts.push(title);
    }
  } else if (f === 'laptop') {
    const lidW = Math.round(w * 0.89);
    const lidX = (w - lidW) / 2;
    const sw = lidW - 40;
    screen = {x: lidX + 20, y: 24, w: sw, h: sw / aspect};
    body = {x: lidX, y: 0, w: lidW, h: screen.h + 24 + 20};
    bottom = body.h + 34;
    radius = 10;
  } else if (f === 'phone') {
    const z = FOOTAGE.bezel;
    const sw = w - 2 * z;
    screen = {x: z, y: z, w: sw, h: sw / aspect};
    body = {x: 0, y: 0, w, h: screen.h + 2 * z};
    bottom = body.h;
    radius = Math.min(50, Math.min(screen.w, screen.h) * 0.12);
  } else {
    screen = {x: 0, y: 0, w, h: w / aspect};
    body = {...screen};
    bottom = screen.h;
    radius = 24;
  }
  let caption: TextSpec | undefined;
  if (b.caption) {
    caption = T(b.caption, 0, bottom + FOOTAGE.capGap, w, FOOTAGE.capH, fitFontSize(b.caption, 30, w, {weight: WEIGHT.semibold, minFs: 22}), WEIGHT.semibold, 'center', 'caption');
    texts.push(caption);
  }
  const h = Math.ceil(bottom + (b.caption ? FOOTAGE.capGap + FOOTAGE.capH : 0) - 1e-9);
  /** the visible window at scale 1 (fraction of the clip): the cover crop of the clip into the viewport */
  const win = fit === 'fill' ? {...baseWindow(aspect, screen.w / screen.h), ...(env.format === 'short' ? {min: FOOTAGE.fillMinScale} : {})} : FULL;
  return {frame: f, fit, aspect, screen, body, radius, h, title, caption, texts, win};
};

/** Cover crop of a clip of aspect `a` into a viewport of aspect `v`: the normalised window shown at scale 1. */
export const baseWindow = (a: number, v: number): Win => ({w: Math.min(1, v / a), h: Math.min(1, a / v)});

// ------------------------------------------------------------------------------------------------ time
/** Seconds into the clip shown at timeline time `t`: startFrom + (t − appear) · playbackRate; held at startFrom before
 *  the block appears and on the last frame once the clip has ended (when its duration is known). */
export const clipTime = (b: Pick<B, 'startFrom' | 'playbackRate' | 'duration'>, t: number, appear: number) => {
  const rate = finitePos(b.playbackRate) ? b.playbackRate : 1;
  const start = typeof b.startFrom === 'number' && Number.isFinite(b.startFrom) ? Math.max(0, b.startFrom) : 0;
  const ct = start + Math.max(0, t - appear) * rate;
  return finitePos(b.duration) ? Math.min(ct, Math.max(0, b.duration - FOOTAGE.endEps)) : ct;
};
/** The time actually requested from the decoder (clipTime + seekBias, still before the clip's end). */
export const seekTime = (b: Pick<B, 'startFrom' | 'playbackRate' | 'duration'>, t: number, appear: number) => {
  const ct = clipTime(b, t, appear) + FOOTAGE.seekBias;
  return finitePos(b.duration) ? Math.min(ct, Math.max(0, b.duration - FOOTAGE.endEps)) : ct;
};
/** True once the clip has reached its end and the last frame is being held. */
export const clipHeld = (b: Pick<B, 'startFrom' | 'playbackRate' | 'duration'>, t: number, appear: number) =>
  finitePos(b.duration) && clipTime(b, t, appear) >= b.duration - FOOTAGE.endEps - 1e-9;

// ------------------------------------------------------------------------------------------------ zoom
export const ZOOM_IDENTITY: Zoom = {x: 0.5, y: 0.5, scale: 1};
/** A focus keyframe clamped so its view lies inside the clip: scale ∈ [1, zoomMax], centre within half the visible
 *  window of the edges (½/scale for the whole-clip frame fit; per axis for a fill crop of window `win` at scale 1). */
export const clampZoom = (z: Zoom, win: Win = FULL): Zoom => {
  const scale = clamp(Number.isFinite(z.scale) ? z.scale : 1, Math.min(FOOTAGE.zoomMax, win.min ?? 1), FOOTAGE.zoomMax);
  const c = (v: number, half: number) => clamp(Number.isFinite(v) ? v : 0.5, half, 1 - half);
  return {x: c(z.x, win.w / (2 * scale)), y: c(z.y, win.h / (2 * scale)), scale};
};
const validRegion = (r: FootageRegion | undefined): r is FootageRegion =>
  !!r && [r.x, r.y, r.w, r.h].every(Number.isFinite) && r.w > 0 && r.h > 0;
/** The view that frames a named UI element: centred on it, as close as it still fits with FOOTAGE.regionMargin
 *  (stronger than a hand-set scale whenever the element is small), clamped to [1, zoomMax] and inside the clip. */
export const regionZoom = (r: FootageRegion, win: Win = FULL): Zoom => {
  const s = Math.min(win.w / (r.w * FOOTAGE.regionMargin), win.h / (r.h * FOOTAGE.regionMargin));
  return clampZoom({x: r.x + r.w / 2, y: r.y + r.h / 2, scale: s}, win);
};
/** The target view of a keyframe: its region's framing when it names one, else its own (clamped) centre + scale. */
export const zoomTarget = (z: Zoom & {region?: FootageRegion}, win: Win = FULL): Zoom => (validRegion(z.region) ? regionZoom(z.region, win) : clampZoom(z, win));
/** Eased interpolation in (centre, ln scale) space with one shared progress: between two clamped views every
 *  intermediate view stays inside the clip (½ − ½/s is concave in ln s), so a zoom never shows an empty edge. */
const lerpZoom = (a: Zoom, b: Zoom, p: number): Zoom => ({
  x: a.x + (b.x - a.x) * p,
  y: a.y + (b.y - a.y) * p,
  scale: Math.exp(Math.log(a.scale) + (Math.log(b.scale) - Math.log(a.scale)) * p),
});
/** The view at time t. Before the first keyframe: the whole clip. Each keyframe's move starts LEAD.block before its
 *  `at` (like every entrance) and eases (EASE.inOutCubic) over FOOTAGE.zoomMove, or less when the next keyframe starts
 *  sooner, so moves never overlap and each starts exactly where the previous one left the view. */
export const zoomAt = (zooms: B['zooms'], t: number, win: Win = FULL): Zoom => {
  const ks = [...(zooms ?? [])].filter((z) => Number.isFinite(z.at)).sort((a, b) => a.at - b.at);
  let prev = win.min && win.min > 1 ? clampZoom(ZOOM_IDENTITY, win) : ZOOM_IDENTITY;
  for (let i = 0; i < ks.length; i++) {
    const s = ks[i].at - LEAD.block;
    const next = i + 1 < ks.length ? ks[i + 1].at - LEAD.block : Infinity;
    const d = Math.min(FOOTAGE.zoomMove, next - s);
    const target = zoomTarget(ks[i], win);
    if (t < s) return prev;
    if (t < s + d) return lerpZoom(prev, target, EASE.inOutCubic((t - s) / d));
    prev = target;
  }
  return prev;
};
/** Where the (scaled) clip sits inside its viewport of size w × h for view z: the focus centre is moved to the middle,
 *  and the rect always covers the viewport (x ∈ [w − W, 0], y ∈ [h − H, 0]). `a` is the clip's aspect (default the
 *  viewport's, the frame fit); a different aspect is drawn as a cover crop at scale 1, never distorted. */
export const zoomRect = (z: Zoom, w: number, h: number, a: number = w / h): Rect => {
  const W = z.scale * Math.max(w, h * a);
  const H = W / a;
  return {x: clamp(w / 2 - z.x * W, w - W, 0), y: clamp(h / 2 - z.y * H, h - H, 0), w: W, h: H};
};
/** Times at which each zoom move has settled (for QA frame grabs): its start (at − LEAD) + its move length. */
export const zoomSettleTimes = (zooms: B['zooms']): number[] => {
  const ks = [...(zooms ?? [])].filter((z) => Number.isFinite(z.at)).sort((a, b) => a.at - b.at);
  return ks.map((k, i) => {
    const s = k.at - LEAD.block;
    const next = i + 1 < ks.length ? ks[i + 1].at - LEAD.block : Infinity;
    return s + Math.min(FOOTAGE.zoomMove, next - s);
  });
};

// ------------------------------------------------------------------------------------------------ callouts
type Callout = NonNullable<B['callouts']>[number];
/** Sorted valid callouts with their visible window: from at − LEAD.block until `at + hold`, the next beat's start (the
 *  next callout, or the next zoom keyframe after it: a new beat replaces the lens), or `end` (the block's end). */
export const calloutWindows = (cs: B['callouts'], end = Infinity, zooms?: B['zooms']) => {
  const ks = [...(cs ?? [])].filter((c) => Number.isFinite(c.at) && validRegion(c)).sort((a, b) => a.at - b.at);
  const zs = (zooms ?? []).map((z) => z.at).filter(Number.isFinite);
  return ks.map((c, i) => {
    const from = c.at - LEAD.block;
    const nz = Math.min(Infinity, ...zs.filter((a) => a > c.at + 1e-6));
    const next = Math.min(i + 1 < ks.length ? ks[i + 1].at : Infinity, nz) - LEAD.block;
    const hold = typeof c.hold === 'number' && c.hold > 0 ? c.at + c.hold : Infinity;
    return {c, from, to: Math.min(next, hold, end)};
  });
};
/** Callout progress at t: 0 → 1 over FOOTAGE.callout.pop after `from`, back to 0 over callout.out before `to`. */
export const calloutLife = (w: {from: number; to: number}, t: number) => {
  if (t < w.from || t >= w.to) return 0;
  const inP = clamp((t - w.from) / FOOTAGE.callout.pop, 0, 1);
  const outP = Number.isFinite(w.to) ? clamp((w.to - t) / FOOTAGE.callout.out, 0, 1) : 1;
  return Math.min(inP, outP);
};
/**
 * Callout geometry in viewport px (viewport w × h, clip aspect a, current view z): `src` is the region as drawn under
 * the view (possibly partly cropped), `panel` the magnified rounded panel (region aspect, ≤ maxW × maxH of the
 * viewport, inset from its edges) placed in the half away from the source so it never covers it, `mag` the panel's
 * magnification over the source as drawn, and the connector from the source's facing edge to the panel's.
 */
export const calloutRects = (c: FootageRegion, z: Zoom, w: number, h: number, a: number) => {
  const r = zoomRect(z, w, h, a);
  const src: Rect = {x: r.x + c.x * r.w, y: r.y + c.y * r.h, w: c.w * r.w, h: c.h * r.h};
  const {maxW, maxH, inset} = FOOTAGE.callout;
  const ra = (c.w / c.h) * a;
  const pw = Math.min(w * maxW, h * maxH * ra);
  const ph = pw / ra;
  const m = inset * Math.min(w, h);
  const scy = clamp(src.y + src.h / 2, 0, h);
  const below = scy < h / 2;
  const panel: Rect = {x: clamp(src.x + src.w / 2 - pw / 2, m, Math.max(m, w - m - pw)), y: below ? h - m - ph : m, w: pw, h: ph};
  const from = {x: clamp(src.x + src.w / 2, 0, w), y: clamp(below ? src.y + src.h : src.y, 0, h)};
  const to = {x: panel.x + pw / 2, y: below ? panel.y : panel.y + ph};
  return {src, panel, mag: pw / Math.max(1e-6, src.w), below, connector: {from, to}};
};
/** The callout's panel rect, settled (the view once its zoom move has ended): what QA and the manifest report. */
export const calloutSettled = (b: Pick<B, 'zooms'>, c: Callout, w: number, h: number, a: number, win: Win) =>
  calloutRects(c, zoomAt(b.zooms, c.at + FOOTAGE.zoomMove, win), w, h, a);
/** The callouts actually drawn: their windows, minus any whose settled panel would not magnify the source by at least
 *  callout.minMag (a lens no bigger than what the view already shows adds nothing). */
export const activeCallouts = (b: Pick<B, 'zooms' | 'callouts'>, w: number, h: number, a: number, win: Win, end = Infinity) =>
  calloutWindows(b.callouts, end, b.zooms)
    .map((wd) => ({...wd, rects: calloutSettled(b, wd.c, w, h, a, win)}))
    .filter((x) => x.rects.mag >= FOOTAGE.callout.minMag);
