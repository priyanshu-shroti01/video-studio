import {springAt} from './motion/entrances';
import {Word} from './types';

// Kept out of captions.ts: this uses Remotion's spring, and captions.ts is part of the pure layout manifest bundle
// (scripts/engine-layout.mjs refuses remotion/react imports there).

/** Per-word visual state of a kinetic look at time t.
 *  `active`: the page's most recently started word (it stays marked through a pause until the next word starts, so
 *  the highlight never flickers off between words); `fill`: karaoke progress 0..1 through the word; `pop`: spring
 *  0..1 since the word started (drives the scale-in); `spoken`: the word has started. */
export type WordLook = {active: boolean; spoken: boolean; fill: number; pop: number};
export const wordLook = (pageWords: Word[], k: number, t: number, fps: number): WordLook => {
  const w = pageWords[k];
  let cur = -1;
  pageWords.forEach((x, i) => {
    if (t >= x.start) cur = i;
  });
  const spoken = t >= w.start;
  const fill = w.end > w.start ? Math.min(1, Math.max(0, (t - w.start) / (w.end - w.start))) : spoken ? 1 : 0;
  const pop = spoken ? springAt(t, w.start, fps, {damping: 11, mass: 0.5}) : 0;
  return {active: cur === k, spoken, fill, pop};
};
