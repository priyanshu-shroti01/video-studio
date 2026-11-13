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
import {BlockV2} from './types';

type B = Extract<BlockV2, {type: 'footage'}>;
export type FootageFrame = NonNullable<B['frame']>;
export type Zoom = {x: number; y: number; scale: number};

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
} as const;

const clamp = (x: number, a: number, b: number) => Math.min(b, Math.max(a, x));
const finitePos = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x) && x > 0;

export const footageFrame = (b: B): FootageFrame => (b.frame && ['browser', 'laptop', 'phone', 'none'].includes(b.frame) ? b.frame : 'browser');
/** The clip's aspect: the block's `aspect` (Python, ffprobe), else the file header (props.assetAspects), else 16:9. */
export const footageAspect = (b: B, env: AspectEnv) => (finitePos(b.aspect) ? b.aspect : (env.asset(b.asset) ?? FOOTAGE.fallbackAspect));

/** Design width of the frame for a clip viewport of width `sw` (inverse of the per-frame screen width). */
const frameWForScreenW = (f: FootageFrame, sw: number) =>
  f === 'laptop' ? (sw + 40) / 0.89 : f === 'phone' ? sw + 2 * FOOTAGE.bezel : f === 'browser' ? sw + 2 * FOOTAGE.border : sw;

export const footageNaturalW = (b: B, env: AspectEnv) => {
  const f = footageFrame(b);
  const a = footageAspect(b, env);
  const key = f === 'phone' && a >= 1 ? 'phoneWide' : f;
  return Math.min(FOOTAGE.naturalW[key], frameWForScreenW(f, FOOTAGE.maxH[key] * a));
};

export const geomFootage = (b: B, w: number, env: AspectEnv) => {
  const f = footageFrame(b);
  const aspect = footageAspect(b, env);
  const texts: TextSpec[] = [];
  let screen: Rect;
  let body: Rect;
  let bottom: number;
  let radius: number;
  let title: TextSpec | undefined;
  if (f === 'browser') {
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
  return {frame: f, aspect, screen, body, radius, h, title, caption, texts};
};

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
/** A focus keyframe clamped so its view lies inside the clip: scale ∈ [1, zoomMax], centre within ½/scale of the edges. */
export const clampZoom = (z: Zoom): Zoom => {
  const scale = clamp(Number.isFinite(z.scale) ? z.scale : 1, 1, FOOTAGE.zoomMax);
  const half = 0.5 / scale;
  const c = (v: number) => clamp(Number.isFinite(v) ? v : 0.5, half, 1 - half);
  return {x: c(z.x), y: c(z.y), scale};
};
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
export const zoomAt = (zooms: B['zooms'], t: number): Zoom => {
  const ks = [...(zooms ?? [])].filter((z) => Number.isFinite(z.at)).sort((a, b) => a.at - b.at);
  let prev = ZOOM_IDENTITY;
  for (let i = 0; i < ks.length; i++) {
    const s = ks[i].at - LEAD.block;
    const next = i + 1 < ks.length ? ks[i + 1].at - LEAD.block : Infinity;
    const d = Math.min(FOOTAGE.zoomMove, next - s);
    const target = clampZoom(ks[i]);
    if (t < s) return prev;
    if (t < s + d) return lerpZoom(prev, target, EASE.inOutCubic((t - s) / d));
    prev = target;
  }
  return prev;
};
/** Where the (scaled) clip sits inside its viewport of size w × h for view z: the focus centre is moved to the middle,
 *  and the rect always covers the viewport (x ∈ [w − W, 0], y ∈ [h − H, 0]). */
export const zoomRect = (z: Zoom, w: number, h: number): Rect => {
  const W = w * z.scale;
  const H = h * z.scale;
  return {x: clamp(w / 2 - z.x * W, w - W, 0), y: clamp(h / 2 - z.y * H, h - H, 0), w: W, h: H};
};
