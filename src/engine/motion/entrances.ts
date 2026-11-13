import {spring} from 'remotion';
import {LEAD} from './durations';
import {SpringCfg} from './easings';
import {MotionPreset} from './presets';

/** Spring progress from second `at` (0 before). Deterministic: a pure function of t. */
export const springAt = (t: number, at: number, fps: number, cfg: SpringCfg) =>
  t < at ? 0 : spring({frame: (t - at) * fps, fps, config: {damping: cfg.damping, mass: cfg.mass}});

export type Entrance = {p: number; opacity: number; dy: number; scale: number; blur: number; blurY: number};

/**
 * Block entrance (scene layer): spring from `appear - LEAD.block`. Travel/opacity/scale per preset.
 * `blurY` = directional motion-blur level (0–3) when the translation is fast (preset.motionBlur px/frame
 * threshold, measured in output px), `blur` = focus-pull px. Both 0 for 'standard'.
 */
export const blockEntrance = (t: number, appear: number, fps: number, m: MotionPreset, outScale = 1): Entrance => {
  const at = appear - LEAD.block;
  const p = springAt(t, at, fps, m.entrance.spring);
  const opacity = Math.min(1, p * m.entrance.opacityGain);
  const dy = (1 - p) * m.entrance.offsetY;
  const scale = m.entrance.scaleFrom === 1 ? 1 : m.entrance.scaleFrom + (1 - m.entrance.scaleFrom) * p;
  return {p, opacity, dy, scale, blur: m.focusPull > 0 ? m.focusPull * Math.max(0, 1 - p) : 0, blurY: motionBlurLevel(t, at, fps, m, m.entrance.offsetY * outScale)};
};

/** Velocity-gated directional blur level 0..3 for a spring translation of `travel` output px. */
export const motionBlurLevel = (t: number, at: number, fps: number, m: MotionPreset, travel: number) => {
  if (m.motionBlur <= 0 || t < at) return 0;
  const p1 = springAt(t, at, fps, m.entrance.spring);
  const p0 = springAt(t - 1 / fps, at, fps, m.entrance.spring);
  const v = Math.abs(p1 - p0) * travel; // px per frame
  if (v < m.motionBlur) return 0;
  return Math.min(3, 1 + Math.floor((v - m.motionBlur) / m.motionBlur));
};

/** Per-word reveal: spring from `at - LEAD.word`. */
export const wordEntrance = (t: number, at: number, fps: number, m: MotionPreset) => springAt(t, at - LEAD.word, fps, m.word.spring);

/** SVG filter id for a motion-blur level (filters are defined once by the Storyboard). */
export const MOTION_BLUR_LEVELS = [0, 1.5, 3, 4.5] as const;
export const motionBlurFilterId = (level: number) => `sb-mblur-${level}`;
