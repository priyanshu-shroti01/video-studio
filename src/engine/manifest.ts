/**
 * Deterministic LAYOUT MANIFEST for QA (OCR / logo / brand checks). Built from the same pure planning
 * code the renderer uses (plan.ts → layout.ts → geometry.ts), never from a browser.
 *
 * Coordinates: output pixels at the final frame size, at each block's settled (post-entrance) position,
 * before the scene camera move (see docs/MOTION.md → "Camera" for the maximum displacement QA must tolerate).
 * Times: seconds on the final timeline.
 *
 * Entry point for scripts/engine-layout.mjs (bundled with esbuild). Keep this import graph free of
 * React / Remotion.
 */
import {DIMENSIONS} from './contract';
import {LogoSpec, Rect, specWidth, TextSpec} from './geometry';
import {activeCallouts, geomFootage, zoomSettleTimes} from './geometry-footage';
import {captionLook, captionMetrics} from './captions';
import {hudTexts} from './hud';
import {captionBandTop, FORMAT_SPEC} from './layout';
import {makeEnv, planScene, sceneTops} from './plan';
import {blockContent} from './texts';
import {RenderProps} from './types';

export {collectAssetPaths, intrinsicAspect} from './assets';

const r2 = (x: number) => Math.round(x * 100) / 100;
const r3 = (x: number) => Math.round(x * 1000) / 1000;
const rect = (r: Rect) => ({x: r2(r.x), y: r2(r.y), w: r2(r.w), h: r2(r.h)});

export type ManifestText = {
  text: string;
  bbox: Rect;
  fontSize: number;
  fontWeight: number;
  estWidth: number;
  maxWidth: number;
  overflow: boolean;
  role: TextSpec['role'];
};
export type ManifestLogo = {variant: LogoSpec['variant']; bbox: Rect; aspect: number; expectedAspect: number};
/** A video viewport (footage block): the drawn clip rect (output px, settled, before the camera; zooms happen inside
 *  it), its aspect and the clip's intrinsic aspect (equal: the clip is never distorted). */
export type ManifestMedia = {
  role: 'media';
  kind: 'video';
  asset: string;
  frame: string;
  bbox: Rect;
  aspect: number;
  /** frame fit: the clip's aspect; fill fit: the viewport's own (a cover crop of the clip, never distorted) */
  expectedAspect: number;
  fit?: 'frame' | 'fill';
  clipAspect?: number;
  /** times at which each zoom move has settled (visual QA samples the footage there) */
  settle?: number[];
  /** callout panels (output px, settled) and when each is up */
  callouts?: {bbox: Rect; from: number; to: number; mag: number}[];
};
export type ManifestBlock = {
  index: number;
  type: string;
  bbox: Rect;
  visible: {from: number; to: number};
  texts: ManifestText[];
  logos: ManifestLogo[];
  /** only on blocks that show a video (footage) */
  media?: ManifestMedia[];
};
/** v3: a HUD element (output px, fixed for the whole video) with the windows it is on screen and its text runs
 *  (each with the window it shows; a counted stakes value from when it lands). */
export type ManifestHudElement = {
  id: string;
  kind: string;
  bbox: Rect;
  visibleRanges: [number, number][];
  texts: (ManifestText & {from: number; to: number})[];
};
export type LayoutManifest = {
  contractVersion: number;
  format: RenderProps['format'];
  width: number;
  height: number;
  fps: number;
  safeArea: Rect;
  captionBand: Rect;
  /** v3: `hudBottom` = y below which this scene's content starts because of the HUD; `captionBand` = this scene's own
   *  caption band when the style is 'headline' (top of the content area) */
  scenes: {id: string; start: number; end: number; blocks: ManifestBlock[]; hudBottom?: number; captionBand?: Rect}[];
  watermark: {policy: string; bbox: Rect; variant: string; opacity: number; visibleRanges: [number, number][]} | null;
  brandBar: {bbox: Rect; from: number; to: number} | null;
  /** v3: the persistent HUD (only present when the props have one) */
  hud?: {elements: ManifestHudElement[]};
};

/** Overflow tolerance (design px) so float noise never flips the flag. */
const EPS = 0.5;

export const buildManifest = (props: RenderProps): LayoutManifest => {
  const env = makeEnv(props);
  const {width, height} = DIMENSIONS[props.format];
  const spec = FORMAT_SPEC[props.format];
  const bandTop = captionBandTop(props.format, props.captions);
  const capM = captionMetrics(props.format, props.captions);       // classic: H·bottomFrac and W·maxWidthFrac, as before
  const capBottom = height - capM.bottom;
  const capW = capM.maxW;
  const headline = props.captions.enabled && captionLook(props.captions.style) === 'headline';
  const firstTops = headline && props.scenes.length ? sceneTops(env, props.scenes[0]) : undefined;
  const captionBand = headline && firstTops?.headline
    ? firstTops.headline   // the top band of the first scene; every scene carries its own (scenes[].captionBand)
    : props.captions.enabled
      ? {x: (width - capW) / 2, y: bandTop, w: capW, h: capBottom - bandTop}
      : {x: 0, y: bandTop, w: width, h: height - bandTop};
  const topSafe = spec.topNoBar;
  const scenes = props.scenes.map((s) => {
    const P = planScene(env, s);
    const blocks: ManifestBlock[] = s.blocks.map((b, i) => {
      const box = P.layout.boxes[i];
      const k = box.scale;
      const {texts, logos} = blockContent(b, box.designW, box.designH, env.aspects);
      const out: ManifestBlock = {
        index: i,
        type: b.type,
        bbox: rect(box),
        visible: {from: r3(P.visible[i].from), to: r3(P.visible[i].to)},
        texts: texts.map((t) => {
          const est = specWidth(t);
          const bx = t.align === 'left' ? t.x : t.align === 'right' ? t.x + t.w - est : t.x + (t.w - est) / 2;
          return {
            text: t.text,
            bbox: rect({x: box.x + bx * k, y: box.y + t.y * k, w: est * k, h: t.h * k}),
            fontSize: r2(t.fs * k),
            fontWeight: t.weight,
            estWidth: r2(est * k),
            maxWidth: r2(t.w * k),
            overflow: est > t.w + EPS,
            role: t.role,
          };
        }),
        logos: logos.map((l) => ({
          variant: l.variant,
          bbox: rect({x: box.x + l.x * k, y: box.y + l.y * k, w: l.w * k, h: l.h * k}),
          aspect: r3(b.type === 'logo' ? box.w / box.h : l.w / l.h),
          expectedAspect: r3(l.expected),
        })),
      };
      if (b.type === 'footage') {
        const g = geomFootage(b, box.designW, env.aspects);
        const sr = g.screen;
        const fill = g.fit === 'fill';
        const md: ManifestMedia = {role: 'media', kind: 'video', asset: b.asset, frame: fill ? 'fill' : g.frame, bbox: rect({x: box.x + sr.x * k, y: box.y + sr.y * k, w: sr.w * k, h: sr.h * k}), aspect: r3(sr.w / sr.h), expectedAspect: r3(fill ? sr.w / sr.h : g.aspect)};
        if (fill) Object.assign(md, {fit: 'fill' as const, clipAspect: r3(g.aspect)});
        if (b.zooms?.length) md.settle = zoomSettleTimes(b.zooms).map(r3);
        if (b.callouts?.length) {
          md.callouts = activeCallouts(b, sr.w, sr.h, g.aspect, g.win, P.visible[i].to).map((wd) => {
            const c = wd.rects;
            const pr = c.panel;
            return {bbox: rect({x: box.x + (sr.x + pr.x) * k, y: box.y + (sr.y + pr.y) * k, w: pr.w * k, h: pr.h * k}), from: r3(wd.from), to: r3(wd.to), mag: r3(c.mag)};
          });
        }
        out.media = [md];
      }
      return out;
    });
    const sc: LayoutManifest['scenes'][number] = {id: s.id, start: s.start, end: s.end, blocks};
    if (P.tops.hud !== undefined) sc.hudBottom = r2(P.tops.hud);
    if (P.tops.headline) sc.captionBand = rect(P.tops.headline);
    return sc;
  });
  let hud: LayoutManifest['hud'];
  if (env.hud) {
    const runs = hudTexts(env.hud, env.duration);
    hud = {
      elements: env.hud.tracks.map((tr) => {
        const b = env.hud!.boxes[tr.el.id];
        return {
          id: tr.el.id,
          kind: tr.el.kind,
          bbox: rect(b ?? {x: 0, y: 0, w: 0, h: 0}),
          visibleRanges: tr.ranges,
          texts: (runs[tr.el.id] ?? []).map((x) => {
            const bx = tr.el.kind === 'stakes' ? x.x + (x.w - x.est) / 2 : tr.el.kind === 'progress' ? x.x + x.w - x.est : x.x;
            return {text: x.text, bbox: rect({x: bx, y: x.y, w: x.est, h: x.h}), fontSize: r2(x.fs), fontWeight: x.weight, estWidth: r2(x.est), maxWidth: r2(x.w),
              overflow: x.est > x.w + EPS || (tr.el.kind === 'chips' && b?.kind === 'chips' && b.overflow), role: 'label' as const, from: x.from, to: x.to};
          }),
        };
      }),
    };
  }
  const wm = env.watermark;
  return {
    contractVersion: props.contractVersion,
    format: props.format,
    width,
    height,
    fps: props.fps,
    safeArea: rect({x: spec.side, y: topSafe, w: width - 2 * spec.side, h: bandTop - topSafe}),
    captionBand: rect(captionBand),
    scenes,
    watermark: wm ? {policy: wm.policy, bbox: rect(wm.rect), variant: wm.variant, opacity: wm.opacity, visibleRanges: wm.visibleRanges} : null,
    brandBar: env.brandBar ? {bbox: rect(env.brandBar), from: env.brandBar.from, to: env.brandBar.to} : null,
    ...(hud ? {hud} : {}),
  };
};

/** Fills props.assetAspects from a byte reader (v1 too: QA's expectedAspect is then the file's true aspect); used by the manifest script (fs) — the renderer uses fetch. */
export const withAssetAspects = (
  props: RenderProps,
  read: (publicPath: string) => Uint8Array | undefined,
  collect: (p: RenderProps) => string[],
  aspectOf: (bytes: Uint8Array, path: string) => number | undefined,
): RenderProps => {
  if (props.assetAspects) return props;
  const out: Record<string, number> = {};
  for (const p of collect(props)) {
    const bytes = read(p);
    const a = bytes ? aspectOf(bytes, p) : undefined;
    if (a) out[p] = a;
  }
  return {...props, assetAspects: out};
};
