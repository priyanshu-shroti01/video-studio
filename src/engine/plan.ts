/**
 * Scene planning shared by the renderer (Storyboard.tsx) and the QA layout manifest (manifest.ts):
 * block boxes, appear/visible times, camera reserve, hook-tag ceiling, watermark. Pure.
 */
import {aspectEnv, brandBarRect, planWatermark, rectsIntersect, WatermarkPlan} from './branding';
import {DIMENSIONS, isV2} from './contract';
import {AspectEnv, Rect} from './geometry';
import {captionBandTop, FORMAT_SPEC, firstInternalTime, LayoutOpts, layoutScene, SceneLayout} from './layout';
import {backdropOf, isPolished, splitPanel} from './look';
import {appearTime} from './motion/durations';
import {cameraReserve} from './motion/transitions';
import {MotionPreset, presetFor} from './motion/presets';
import {BackdropKind, Block, RenderProps, Scene} from './types';

export const brandBarActiveFor = (bar: RenderProps['brandBar'], s: Pick<Scene, 'start' | 'end'>) => !!bar && bar.from < s.end && bar.to > s.start;

/** Blocks that carry branding (the watermark hides while any of them is visible). */
export const BRANDING_BLOCKS: ReadonlySet<Block['type']> = new Set(['logo', 'cta', 'logo-sting', 'outro']);
/** A branding block, or an image / device showing one of the theme's logo files. */
export const isBrandingBlock = (b: Block, logo: RenderProps['theme']['logo']) =>
  BRANDING_BLOCKS.has(b.type) || ((b.type === 'image' || b.type === 'device') && !!b.asset && [logo.onDark, logo.onLight, logo.mark].includes(b.asset));

export type Env = {
  props: RenderProps;
  v2: boolean;
  /** v2b look (look.ts isPolished): backdrops, hero scaling, polished blocks */
  polish: boolean;
  width: number;
  height: number;
  duration: number;
  aspects: AspectEnv;
  brandBar: (Rect & {from: number; to: number}) | null;
  watermark: WatermarkPlan | null;
};

export type ScenePlan = {
  layout: SceneLayout;
  bar: boolean;
  preset: MotionPreset;
  /** camera displacement reserve (output px) the layout insets by (v2) */
  reserve: {x: number; y: number};
  /** absolute y (px) a hook-tag string hangs from (0 = frame top) */
  ceilingY: number;
  appear: number[];
  visible: {from: number; to: number}[];
  /** content-area centre (camera origin) */
  cx: number;
  cy: number;
  /** v2b: the scene's backdrop ('glow' when unset) */
  backdrop: BackdropKind;
};

/** When each block appears: explicit `at`, else its first internal time, else the scene stagger. */
const blockAppear = (scene: Scene, preset: MotionPreset) =>
  scene.blocks.map((b, i) => b.at ?? firstInternalTime(b) ?? appearTime(scene.start, i, undefined, preset.blockStagger));
const blockVisible = (scene: Scene, appear: number[]) =>
  scene.blocks.map((b, i) => ({from: appear[i], to: Math.min(b.exitAt ?? scene.end, scene.end)}));

export const makeEnv = (props: RenderProps): Env => {
  const v2 = isV2(props);
  const polish = isPolished(props);
  const {width, height} = DIMENSIONS[props.format];
  const aspects = polish ? {...aspectEnv(props), polish: true} : aspectEnv(props);
  const bb = props.brandBar ? {...brandBarRect(props.format, aspects.logo.onDark), from: props.brandBar.from, to: props.brandBar.to} : null;
  const busy: [number, number][] = [];
  if (props.brandBar) busy.push([props.brandBar.from - 0.1, props.brandBar.to + 0.1]);
  for (const s of props.scenes) {
    const preset = presetFor(s.motion, props.motion);
    const ap = blockAppear(s, preset);
    const vis = blockVisible(s, ap);
    s.blocks.forEach((b, i) => {
      if (isBrandingBlock(b, props.theme.logo)) busy.push([Math.max(s.start - 0.15, vis[i].from - 0.1), vis[i].to + 0.05]);
    });
  }
  const watermark = v2 ? planWatermark(props, aspects, busy) : null;
  return {props, v2, polish, width, height, duration: props.durationInFrames / props.fps, aspects, brandBar: bb, watermark};
};

const overlaps = (ranges: [number, number][], a: number, b: number) => ranges.some(([x, y]) => x < b && y > a);

export const planScene = (env: Env, scene: Scene): ScenePlan => {
  const {props, v2, width} = env;
  const preset = presetFor(scene.motion, props.motion);
  const bar = brandBarActiveFor(props.brandBar, scene);
  const spec = FORMAT_SPEC[props.format];
  let reserve = {x: 0, y: 0};
  let ceilingY = 0;
  let layout: SceneLayout;
  if (!v2) {
    layout = layoutScene(scene, props.format, props.captions, bar, env.aspects);
  } else {
    const top0 = bar ? spec.topWithBar : spec.topNoBar;
    const bottom0 = captionBandTop(props.format, props.captions);
    reserve = cameraReserve(scene.camera, width - 2 * spec.side, bottom0 - top0, width, preset.camera);
    const opts: LayoutOpts = {reserveX: reserve.x, reserveY: reserve.y};
    if (env.polish) {
      opts.hero = true;
      if (backdropOf(scene) === 'split') {
        // content lives on the dark side of the brand panel
        const sp = splitPanel(props.format, width, env.height);
        if (props.format === 'short') opts.topMin = sp.contentTop;
        else opts.leftMin = sp.contentLeft;
      }
    }
    layout = layoutScene(scene, props.format, props.captions, bar, env.aspects, opts);
    const wm = env.watermark;
    if (wm && overlaps(wm.visibleRanges, scene.start, scene.end) && wm.position.startsWith('top')) {
      // the watermark never sits on content: push the stack below it when a box would touch it
      const hit = layout.boxes.some((b) => rectsIntersect(b, wm.rect, 16 + reserve.y));
      if (hit) layout = layoutScene(scene, props.format, props.captions, bar, env.aspects, {...opts, topMin: Math.max(opts.topMin ?? 0, wm.rect.y + wm.rect.h + 24)});
      if (wm.position === 'top-center') ceilingY = wm.rect.y + wm.rect.h + 14;
    }
    if (bar && env.brandBar) ceilingY = Math.max(ceilingY, env.brandBar.y + env.brandBar.h + 14);
  }
  const appear = blockAppear(scene, preset);
  return {
    layout,
    bar,
    preset,
    reserve,
    ceilingY,
    appear,
    visible: blockVisible(scene, appear),
    cx: width / 2,
    cy: (layout.top + layout.bottom) / 2,
    backdrop: backdropOf(scene),
  };
};
