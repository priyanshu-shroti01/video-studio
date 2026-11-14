/**
 * Scene planning shared by the renderer (Storyboard.tsx) and the QA layout manifest (manifest.ts):
 * block boxes, appear/visible times, camera reserve, hook-tag ceiling, watermark. Pure.
 */
import {aspectEnv, brandBarRect, planWatermark, rectsIntersect, WatermarkPlan} from './branding';
import {DIMENSIONS, isV2} from './contract';
import {AspectEnv, Rect} from './geometry';
import {Box, captionBandTop, FORMAT_SPEC, firstInternalTime, LayoutOpts, layoutScene, SceneLayout} from './layout';
import {backdropOf, isPolished, splitPanel} from './look';
import {appearTime, DUR, LEAD} from './motion/durations';
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
  /** staged entrance: the blocks that appear first are shown alone (centred, as large as the area allows), then move
   *  to their final place during [t0, t1], just before the later blocks enter. Undefined when not staged. */
  stage?: StagePlan;
};

/** Per early block: where it starts (absolute px) and how much larger than its final box it is. */
export type StagePlan = {t0: number; t1: number; from: Record<number, {x: number; y: number; scale: number}>};

/** Staging rules (seconds / ratios). */
export const STAGE = {
  /** the early blocks must be on screen alone at least this long */
  minSolo: 1.0,
  /** blocks appearing within this of the first one belong to the early group */
  group: 0.35,
  /** move duration (shortened when the solo time is short) */
  move: DUR.slower,
  /** a solo layout this close to the final one (scale ratio and centre distance) is not worth a move */
  minScale: 1.06,
  minShift: 40,
} as const;

/** Where the early group sits when it is alone, mapped onto the FINAL design boxes (content keeps its geometry: the
 *  block is drawn at its final design size and only translated + scaled). */
export const stagePlan = (layout: SceneLayout, solo: SceneLayout, idx: number[], appear: number[], t2: number): StagePlan | undefined => {
  const first = Math.min(...idx.map((i) => appear[i]));
  const t1 = t2 - LEAD.card;
  const t0 = Math.max(first + STAGE.minSolo * 0.6, t1 - STAGE.move);
  if (t1 - t0 < 0.25) return undefined;
  const from: StagePlan['from'] = {};
  let worthIt = false;
  idx.forEach((i, k) => {
    const f: Box = layout.boxes[i];
    const s: Box = solo.boxes[k];
    // fit the final design box inside the solo box (keeps aspect even if the solo column was a different width)
    const scale = Math.min(s.w / f.designW, s.h / f.designH);
    const w = f.designW * scale;
    const h = f.designH * scale;
    const x = s.x + (s.w - w) / 2;
    const y = s.y + (s.h - h) / 2;
    const shift = Math.hypot(x + w / 2 - (f.x + f.w / 2), y + h / 2 - (f.y + f.h / 2));
    if (scale / f.scale >= STAGE.minScale || shift >= STAGE.minShift) worthIt = true;
    from[i] = {x, y, scale};
  });
  return worthIt ? {t0, t1, from} : undefined;
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
  const aspects = polish ? {...aspectEnv(props), polish: true, format: props.format} : {...aspectEnv(props), format: props.format};
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
  let stage: StagePlan | undefined;
  if (v2 && env.polish && scene.blocks.length > 1) {
    const first = Math.min(...appear);
    const idx = scene.blocks.map((_, i) => i).filter((i) => appear[i] <= first + STAGE.group);
    const later = scene.blocks.map((_, i) => i).filter((i) => !idx.includes(i));
    const t2 = later.length ? Math.min(...later.map((i) => appear[i])) : Infinity;
    if (later.length && t2 - first >= STAGE.minSolo) {
      const opts: LayoutOpts = {reserveX: reserve.x, reserveY: reserve.y, hero: true};
      if (backdropOf(scene) === 'split') {
        const sp = splitPanel(props.format, width, env.height);
        if (props.format === 'short') opts.topMin = sp.contentTop;
        else opts.leftMin = sp.contentLeft;
      }
      const solo = layoutScene({...scene, layout: 'stack', blocks: idx.map((i) => scene.blocks[i])}, props.format, props.captions, bar, env.aspects, opts);
      stage = stagePlan(layout, solo, idx, appear, t2);
    }
  }
  return {
    stage,
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
