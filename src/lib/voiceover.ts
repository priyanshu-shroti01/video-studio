import {staticFile} from 'remotion';

/** Shape of public/voiceover/<name>.json written by scripts/legacy/voiceover.py */
export type Word = {text: string; start: number; end: number};
export type VoiceoverTiming = {
  text: string;
  voice: string;
  audio: string; // path relative to public/, e.g. "voiceover/test.mp3"
  duration: number; // exact decoded duration in seconds
  speechEnd: number; // end of the last spoken word
  fps: number;
  durationInFrames: number;
  words: Word[];
};

/** Fetches a timing JSON from public/. Returns null if it doesn't exist yet. */
export const loadVoiceover = async (path: string | null): Promise<VoiceoverTiming | null> => {
  if (!path) return null;
  try {
    const res = await fetch(staticFile(path));
    if (!res.ok) return null;
    return (await res.json()) as VoiceoverTiming;
  } catch {
    return null;
  }
};

/** Groups words into caption "pages" of at most `maxWords`, breaking early on sentence punctuation. */
export const pageWords = (words: Word[], maxWords: number): Word[][] => {
  const pages: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length >= maxWords || /[.!?,;:]$/.test(w.text)) {
      pages.push(cur);
      cur = [];
    }
  }
  if (cur.length) pages.push(cur);
  return pages;
};

/** Seconds at which the narration first says `needle` (case-insensitive), or null. */
export const cueAt = (timing: VoiceoverTiming | null, needle: string): number | null => {
  const n = needle.toLowerCase();
  const w = timing?.words.find((x) => x.text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '').includes(n));
  return w ? w.start : null;
};
