import {CaptionConfig, Word} from './types';

/**
 * Index of the caption page visible at `t`, or -1.
 * A page shows from its first word's start (−0.05 s lead) and holds until the next page starts;
 * the last page clears 0.6 s after the final word ends. Nothing shows before the first word.
 */
export const captionPageAt = (pages: CaptionConfig['pages'], words: Word[], t: number): number => {
  if (pages.length === 0 || words.length === 0) return -1;
  let idx = -1;
  for (let i = 0; i < pages.length; i++) {
    const first = words[pages[i].wordIdx[0]];
    if (first && t >= first.start - 0.05) idx = i;
  }
  if (idx < 0) return -1;
  const lastWord = words[words.length - 1];
  if (t > lastWord.end + 0.6) return -1;
  return idx;
};

/** 'current' | 'spoken' | 'upcoming' for karaoke highlighting. */
export const wordState = (w: Word, t: number): 'current' | 'spoken' | 'upcoming' =>
  t >= w.start && t <= w.end ? 'current' : t > w.end ? 'spoken' : 'upcoming';

/** Height of the caption box for `lines` lines (used by the layout to keep content out of the band). */
export const captionBoxHeight = (fontSize: number, lines = 2) => fontSize * 1.15 * lines + fontSize * 0.5;
