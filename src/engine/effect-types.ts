/**
 * Scene emphasis effects (render contract, additive, same CONTRACT_VERSION; Python mirror: pipeline/effects.py).
 * See docs/MOTION.md#effects and motion/effects.ts. Re-exported by types.ts.
 */
import type {Tone} from './types';

/** Emphasis effects (additive, same contract version; motion/effects.ts, docs/MOTION.md#effects). `at` is absolute seconds
 *  (Python resolves `@word:` anchors). `target` = index of a block in the scene. All are deterministic and end at identity. */
export type SceneEffect =
  | {type: 'punch-zoom'; at: number; scale?: number; dur?: number}
  | {type: 'shake'; at: number; amp?: number; dur?: number}
  | {type: 'flash'; at: number; intensity?: number}
  | {type: 'burst'; at: number; target?: number; count?: number; spread?: 'radial' | 'up'}
  | {type: 'annotate'; at: number; kind: 'underline' | 'circle' | 'arrow' | 'cross'; target?: number; text?: string; tone?: Tone; dur?: number}
  | {type: 'cursor'; at: number; target: number; x?: number; y?: number}
  | {type: 'tilt'; at?: number; target: number; rx?: number; ry?: number; dur?: number};
export type SceneEffectType = SceneEffect['type'];
