import {EXIT, LIFE} from './durations';
import {EASE} from './easings';

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lin = (t: number, a: number, b: number) => (b <= a ? (t >= b ? 1 : 0) : clamp01((t - a) / (b - a)));

/** Opacity multiplier for an optional block exit: 1 until exitAt-dur, exactly 0 at/after exitAt. */
export const exitFactor = (t: number, exitAt?: number, dur: number = EXIT.dur) =>
  exitAt === undefined ? 1 : 1 - Math.pow(lin(t, exitAt - dur, exitAt), EXIT.power);

/** Fade envelope: rises over `inDur` after `start`; reaches exactly 0 at `end` (exit complete before a cut). */
export const life = (t: number, start: number, end: number, inDur: number = LIFE.in, outDur: number = LIFE.out) =>
  Math.min(EASE.outCubic(lin(t, start, start + inDur)), 1 - Math.pow(lin(t, end - outDur, end), LIFE.outPower));
