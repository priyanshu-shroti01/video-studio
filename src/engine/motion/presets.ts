import {MotionPresetName} from '../types';
import {STAGGER} from './durations';
import {SPRING, SpringCfg} from './easings';

/**
 * Motion presets change the *shape* of entrances (springs, travel, stagger, blur), never cue times:
 * every entrance still starts at its Python-resolved `at` (minus the same LEAD in every preset).
 * 'standard' is bit-identical to the v1 engine.
 */
export type MotionPreset = {
  name: MotionPresetName;
  /** block entrance: spring, vertical travel (design px), opacity gain (opacity = min(1, p * gain)) */
  entrance: {spring: SpringCfg; offsetY: number; opacityGain: number; scaleFrom: number};
  /** per-word reveal (headline, cta, kinetic-text): spring, default stagger (s), rise (fraction of font size) */
  word: {spring: SpringCfg; stagger: number; ctaStagger: number; rise: number};
  /** list rows / table rows / cards */
  row: {spring: SpringCfg; travel: number};
  card: {spring: SpringCfg; travel: number};
  /** fallback stagger of un-timed blocks (Python normally sets every block's `at`) */
  blockStagger: number;
  /** subtle directional motion blur on fast translations (px/frame threshold; 0 = off) */
  motionBlur: number;
  /** focus pull on block entrance (px of blur at p=0; 0 = off) */
  focusPull: number;
  /** camera amplitude multiplier */
  camera: number;
};

const standard: MotionPreset = {
  name: 'standard',
  entrance: {spring: SPRING.entrance, offsetY: 40, opacityGain: 1.4, scaleFrom: 1},
  word: {spring: SPRING.word, stagger: 0.08, ctaStagger: 0.12, rise: 0.33},
  row: {spring: SPRING.row, travel: 120},
  card: {spring: SPRING.card, travel: 60},
  blockStagger: STAGGER.block,
  motionBlur: 0,
  focusPull: 0,
  camera: 1,
};

export const MOTION_PRESETS: Record<MotionPresetName, MotionPreset> = {
  standard,
  calm: {
    name: 'calm',
    entrance: {spring: {damping: 22, mass: 1}, offsetY: 26, opacityGain: 1.2, scaleFrom: 1},
    word: {spring: {damping: 20, mass: 0.9}, stagger: 0.1, ctaStagger: 0.15, rise: 0.22},
    row: {spring: {damping: 20, mass: 0.9}, travel: 70},
    card: {spring: {damping: 22, mass: 1}, travel: 40},
    blockStagger: 0.16,
    motionBlur: 0,
    focusPull: 0,
    camera: 0.6,
  },
  energetic: {
    name: 'energetic',
    entrance: {spring: {damping: 12, mass: 0.55}, offsetY: 64, opacityGain: 1.8, scaleFrom: 0.96},
    word: {spring: {damping: 11, mass: 0.5}, stagger: 0.06, ctaStagger: 0.09, rise: 0.42},
    row: {spring: {damping: 12, mass: 0.55}, travel: 160},
    card: {spring: {damping: 12, mass: 0.6}, travel: 80},
    blockStagger: 0.09,
    motionBlur: 7,
    focusPull: 0,
    camera: 1.25,
  },
  cinematic: {
    name: 'cinematic',
    entrance: {spring: {damping: 24, mass: 1.25}, offsetY: 30, opacityGain: 1.1, scaleFrom: 0.97},
    word: {spring: {damping: 22, mass: 1.1}, stagger: 0.11, ctaStagger: 0.16, rise: 0.2},
    row: {spring: {damping: 22, mass: 1.1}, travel: 60},
    card: {spring: {damping: 24, mass: 1.2}, travel: 36},
    blockStagger: 0.18,
    motionBlur: 9,
    focusPull: 6,
    camera: 1,
  },
};


export const presetFor = (sceneMotion?: MotionPresetName, globalMotion?: MotionPresetName): MotionPreset =>
  MOTION_PRESETS[sceneMotion ?? globalMotion ?? 'standard'] ?? standard;
