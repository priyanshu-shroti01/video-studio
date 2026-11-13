/**
 * Typography tokens (design units = the 1080-wide Short scale; the scene scales boxes per format).
 * Also the single text-width estimator shared by the layout (wrapping, auto-fit) and the QA layout
 * manifest (`estWidth` / `overflow`), so what QA flags is exactly what the layout assumed.
 * Pure module.
 */
export const HEADLINE_FS = {xl: 150, l: 120, m: 92} as const;
export const TEXT_FS = {l: 64, m: 48, s: 36} as const;
export const CTA_FS = 92;
export const KINETIC_FS = {xl: 150, l: 120, m: 92} as const;
export const COUNTER_FS = {l: 220, m: 160} as const;

/** Type scale used by the v2 blocks (cards, tables, UI mocks). */
export const TYPE = {
  display: 64,
  title: 46,
  cardTitle: 38,
  body: 40,
  cell: 44,
  label: 32,
  small: 28,
  micro: 24,
  mono: 32,
} as const;

export const WEIGHT = {regular: 500, semibold: 600, bold: 700, heavy: 800} as const;
export const LINE = {tight: 1.08, snug: 1.15, normal: 1.25} as const;
/** Letter spacing as a fraction of the font size. */
export const TRACK = {headline: -0.025, display: -0.02, none: 0, caps: 0.12} as const;

/** v1 wrap constants (kept for bit-identical v1 layout). */
export const CHAR_W = 0.6;
export const CHAR_W_TEXT = 0.56;
export const MONO_ADVANCE = 0.6; // Geist Mono advance width, em

// Per-character advance classes (em) for a bold geometric sans (Plus Jakarta Sans ExtraBold-like),
// deliberately on the generous side so the estimate errs towards "overflow".
const CLASS_W: [RegExp, number][] = [
  [/\s/, 0.26],
  [/[il|!.,:;'’`]/, 0.28],
  [/[fjtrI()[\]{}/\\-]/, 0.4],
  [/[mw]/, 0.88],
  [/[MW@%]/, 0.96],
  [/[A-Z]/, 0.72],
  [/[0-9]/, 0.62],
  [/[a-z]/, 0.6],
];
const charW = (ch: string) => {
  for (const [re, w] of CLASS_W) if (re.test(ch)) return w;
  return 0.66; // symbols (₹, ✓, …) and non-Latin
};
const WEIGHT_FACTOR = (w: number) => (w >= 800 ? 1 : w >= 700 ? 0.97 : w >= 600 ? 0.95 : 0.93);
const SAFETY = 1.03;

/** Estimated rendered width (px at `fontSize`) of a single-line string. */
export const estimateTextWidth = (text: string, fontSize: number, opts: {weight?: number; mono?: boolean; letterSpacing?: number} = {}) => {
  const ls = (opts.letterSpacing ?? 0) * Math.max(0, [...text].length);
  if (opts.mono) return [...text].length * fontSize * MONO_ADVANCE + ls;
  let em = 0;
  for (const ch of text) em += charW(ch);
  return em * fontSize * WEIGHT_FACTOR(opts.weight ?? WEIGHT.heavy) * SAFETY + ls;
};

/** Largest font size ≤ `fs` at which `text` fits `maxWidth` (never below `minFs`). */
export const fitFontSize = (text: string, fs: number, maxWidth: number, opts: {weight?: number; mono?: boolean; minFs?: number; letterSpacing?: number} = {}) => {
  const w = estimateTextWidth(text, fs, opts);
  if (w <= maxWidth) return fs;
  return Math.max(opts.minFs ?? 1, Math.floor((fs * maxWidth) / w));
};
