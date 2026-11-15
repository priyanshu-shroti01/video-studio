import {DIMENSIONS} from './contract';
import {estimateTextWidth} from './motion/typography';
import {CaptionConfig, CaptionTone, Format, RenderProps, Theme, Tone, Word} from './types';

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

// ---------------------------------------------------------------------------------------------------------------
// Caption styles (contract-additive). 'word' / 'phrase' / 'classic' keep the original boxed look above, untouched.
// The kinetic looks follow 2025–26 short-form practice (docs/MOTION.md#captions): 1–3 words per page, big heavy
// type with a dark stroke + soft shadow instead of a box, the spoken word marked in the brand colour.
// ---------------------------------------------------------------------------------------------------------------

export type CaptionLook = 'classic' | 'pop' | 'highlight' | 'karaoke' | 'minimal' | 'headline';
export const captionLook = (style: string | undefined): CaptionLook =>
  style === 'pop' || style === 'highlight' || style === 'karaoke' || style === 'minimal' || style === 'headline' ? style : 'classic';
/** v3 'headline': the page sits at the top of the content area (below the HUD), not in a bottom band. */
export const isTopCaption = (style: string | undefined) => captionLook(style) === 'headline';
/** Side margin of the headline column (= layout.ts FORMAT_SPEC.side; kept here to avoid an import cycle). */
export const HEADLINE_SIDE: Record<Format, number> = {short: 70, landscape: 140};

/** Platform UI zones the new looks stay out of. Shorts/Reels/TikTok: the bottom ~20 % (title, description, music)
 *  and the right-hand action rail (~120–160 px of 1080). Landscape players only overlay a thin bottom strip. */
export const CAPTION_SAFE: Record<Format, {bottomFrac: number; sidePx: number}> = {
  short: {bottomFrac: 0.2, sidePx: 140},
  landscape: {bottomFrac: 0.035, sidePx: 0},
};

/** Per-look type scale (× the configured `fontSize`, which stays the classic size), line height, weight. */
const LOOK = {
  pop: {scale: 1.3, line: 1.06, weight: 800, upper: true},
  highlight: {scale: 1.18, line: 1.22, weight: 800, upper: false},
  karaoke: {scale: 1.15, line: 1.12, weight: 800, upper: false},
  minimal: {scale: 0.8, line: 1.2, weight: 600, upper: false},
  headline: {scale: 0.95, line: 1.14, weight: 800, upper: false},
} as const;

/** v3 speaker tag ("● MOM") above a caption page: size relative to the configured caption `fontSize`. */
export const SPEAKER_TAG = {scale: 0.42, minFs: 22, h: 1.9, gap: 0.45, track: 0.14} as const;
export const speakerTagMetrics = (fontSize: number) => {
  const fs = Math.max(SPEAKER_TAG.minFs, Math.round(fontSize * SPEAKER_TAG.scale));
  const h = Math.round(fs * SPEAKER_TAG.h);
  const gap = Math.round(fs * SPEAKER_TAG.gap);
  return {fs, h, gap, block: h + gap};
};
export const hasSpeakers = (cap: Partial<Pick<CaptionConfig, 'speakers'>>) => !!cap.speakers && Object.keys(cap.speakers).length > 0;

export type CaptionMetrics = {
  look: CaptionLook;
  fontSize: number;
  lineHeight: number;
  weight: number;
  uppercase: boolean;
  /** distance of the caption block's bottom edge from the frame bottom (px) */
  bottom: number;
  /** caption column (centred) */
  x: number;
  maxW: number;
  /** height the layout reserves for 2 lines (+ stroke / pop headroom, + the speaker tag when speakers are set) */
  bandH: number;
  /** v3: room reserved above the text for the speaker tag (0 without speakers) */
  tagH: number;
};

type CapLike = Pick<CaptionConfig, 'bottomFrac' | 'fontSize'> & Partial<Pick<CaptionConfig, 'style' | 'maxWidthFrac' | 'uppercase' | 'speakers'>>;

export const captionMetrics = (format: Format, cap: CapLike): CaptionMetrics => {
  const {width, height} = DIMENSIONS[format];
  const look = captionLook(cap.style);
  const frac = cap.maxWidthFrac ?? 0.8;
  const tagH = hasSpeakers(cap) ? speakerTagMetrics(cap.fontSize).block : 0;
  if (look === 'classic') {
    const maxW = width * frac;
    return {look, fontSize: cap.fontSize, lineHeight: 1.15, weight: 800, uppercase: false, bottom: height * cap.bottomFrac,
      x: (width - maxW) / 2, maxW, bandH: tagH ? captionBoxHeight(cap.fontSize, 2) + tagH : captionBoxHeight(cap.fontSize, 2), tagH};
  }
  const L = LOOK[look];
  if (look === 'headline') {
    // the content column itself (under the HUD); `bottom` is unused (the band's y comes from the scene plan)
    const fs = Math.round(cap.fontSize * L.scale);
    const maxW = width - 2 * HEADLINE_SIDE[format];
    return {look, fontSize: fs, lineHeight: L.line, weight: L.weight, uppercase: cap.uppercase ?? L.upper, bottom: 0,
      x: HEADLINE_SIDE[format], maxW, bandH: fs * L.line * 2 + fs * 0.12 + tagH, tagH};
  }
  const safe = CAPTION_SAFE[format];
  const fs = Math.round(cap.fontSize * L.scale);
  // minimal sits lower on 16:9 (a thin line above the player's progress bar); never inside a platform zone
  const frac0 = look === 'minimal' && format === 'landscape' ? Math.min(cap.bottomFrac, 0.05) : cap.bottomFrac;
  const bottom = height * Math.max(frac0, safe.bottomFrac);
  const maxW = Math.min(width * frac, width - 2 * safe.sidePx);
  const headroom = look === 'pop' ? fs * 0.36 : look === 'highlight' ? fs * 0.2 : fs * 0.16; // spring scale / stroke / block
  return {look, fontSize: fs, lineHeight: L.line, weight: L.weight, uppercase: cap.uppercase ?? L.upper, bottom,
    x: (width - maxW) / 2, maxW, bandH: fs * L.line * 2 + headroom + tagH, tagH};
};

// ---------------------------------------------------------------------------------------------------------------
// v3 caption tones and speakers. Absent (every v2 caption config) = no change to any look.
// ---------------------------------------------------------------------------------------------------------------

/** Tone of each word index that carries one (from the pages' parallel `tones` arrays). */
export const captionToneMap = (cap: Pick<CaptionConfig, 'pages'>): Map<number, CaptionTone> => {
  const out = new Map<number, CaptionTone>();
  for (const pg of cap.pages) {
    if (!pg.tones) continue;
    pg.wordIdx.forEach((wi, k) => {
      const tn = pg.tones?.[k];
      if (tn) out.set(wi, tn);
    });
  }
  return out;
};

/** Colour of a caption tone on a dark surface (theme.caption.tones overrides; theme tokens only). */
export const captionToneColor = (theme: Theme, tone: CaptionTone): string => {
  const o = theme.caption.tones?.[tone];
  if (o) return o;
  const c = theme.colors;
  switch (tone) {
    case 'danger':
      return c.danger;
    case 'success':
      return c.success;
    case 'term':
    case 'warning':
      return c.warning;
    case 'info':
      return c.info;
    case 'brand':
      return theme.caption.highlight;
  }
};

/** The same tone on the light surface: darkened until it reads (≥ 4.8:1 on light.surface, like the accent). */
export const captionToneColorLight = (theme: Theme, tone: CaptionTone) => darkenFor(captionToneColor(theme, tone), theme.colors.light.surface, 4.8);

/** A block colour under white text (highlight look): darkened until white reads on it (≥ 3:1, large bold type). */
export const captionToneBlock = (theme: Theme, tone: CaptionTone) => darkenFor(captionToneColor(theme, tone), '#ffffff', 3);

const SPEAKER_TONES: Tone[] = ['brand', 'info', 'warning', 'success', 'danger'];
/** Display label + tone of a speaker (default tones cycle by order of `captions.speakers`). */
export const speakerOf = (cap: Pick<CaptionConfig, 'speakers'>, name: string): {label: string; tone: Tone} => {
  const keys = Object.keys(cap.speakers ?? {});
  const sp = cap.speakers?.[name];
  const i = Math.max(0, keys.indexOf(name));
  return {label: (sp?.label ?? name).toUpperCase(), tone: sp?.tone ?? SPEAKER_TONES[i % SPEAKER_TONES.length]};
};
export const speakerColor = (theme: Theme, tone: Tone): string => {
  const c = theme.colors;
  switch (tone) {
    case 'brand':
      return c.brandText;
    case 'danger':
      return c.danger;
    case 'success':
      return c.success;
    case 'warning':
      return c.warning;
    case 'info':
      return c.info;
    case 'muted':
      return c.text2;
    default:
      return c.text;
  }
};

/** Lines + font size for one page: the look's size if the page fits one line, else the best-balanced 2-line split
 *  (never between `keepWithNext` pairs, e.g. "Video | Studio"), shrinking (never below 60 %) only when neither fits.
 *  Widths come from the conservative layout estimator, so the real text is never wider than the column. */
export const pageLayout = (
  texts: string[],
  m: Pick<CaptionMetrics, 'fontSize' | 'maxW' | 'weight' | 'uppercase'>,
  scales: number[] = [],
  keepWithNext: boolean[] = [],
): {fs: number; lines: number[][]} => {
  const shown = texts.map((s) => (m.uppercase ? s.toUpperCase() : s));
  const n = shown.length;
  const lineW = (a: number, b: number, fs: number) => {
    let w = 0;
    for (let i = a; i < b; i++) w += estimateTextWidth(shown[i], fs * (scales[i] ?? 1), {weight: m.weight}) + (i > a ? fs * 0.34 : 0);
    return w;
  };
  const all = Array.from({length: n}, (_, i) => i);
  const minFs = m.fontSize * 0.6;
  for (let fs = m.fontSize; ; fs *= 0.94) {
    const last = fs * 0.94 < minFs;
    if (lineW(0, n, fs) <= m.maxW) return {fs: Math.round(fs), lines: [all]};
    let best = -1;
    let bestW = Infinity;
    for (let j = 1; j < n; j++) {
      if (keepWithNext[j - 1]) continue;
      const w = Math.max(lineW(0, j, fs), lineW(j, n, fs));
      if (w < bestW) [best, bestW] = [j, w];
    }
    if (best > 0 && (bestW <= m.maxW || last)) return {fs: Math.round(fs), lines: [all.slice(0, best), all.slice(best)]};
    if (last) return {fs: Math.round(fs), lines: [all]};
  }
};

/** Back-compat helper: the font size pageLayout() picks. */
export const pageFontSize = (texts: string[], m: Pick<CaptionMetrics, 'fontSize' | 'maxW' | 'weight' | 'uppercase'>, emphScale = 1): number =>
  pageLayout(texts, m, texts.map(() => emphScale)).fs;

const bare = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}₹$€%]+/gu, '');

const brandTokens = (props: Pick<RenderProps, 'theme'>) => (props.theme.name ?? '').split(/\s+/).map(bare).filter(Boolean);
const brandLen = (props: Pick<RenderProps, 'theme'>) => brandTokens(props).length;
/** Indices where the brand name (theme.name, e.g. "Video Studio") starts in the spoken words. */
export const brandRunStarts = (props: Pick<RenderProps, 'words' | 'theme'>): number[] => {
  const toks = brandTokens(props);
  const words = props.words.map((w) => bare(w.text));
  const out: number[] = [];
  if (toks.length) for (let i = 0; i + toks.length <= words.length; i++) if (toks.every((b, k) => words[i + k] === b)) out.push(i);
  return out;
};
/** Word indices that must stay on the same line as the next word (inside the brand name). */
export const keepTogether = (props: Pick<RenderProps, 'words' | 'theme'>): Set<number> => {
  const out = new Set<number>();
  for (const i of brandRunStarts(props)) for (let k = 0; k < brandLen(props) - 1; k++) out.add(i + k);
  return out;
};

/** Word indices that get extra emphasis: numbers (digits, prices), the brand name (theme.name, matched as a run of
 *  words) and the words a scene itself emphasises (kinetic-text `emphasis`, headline words with a colour tone),
 *  matched only while that scene is on screen. */
export const captionEmphasis = (props: Pick<RenderProps, 'words' | 'scenes' | 'theme'>): Set<number> => {
  const out = new Set<number>();
  const words = props.words.map((w) => bare(w.text));
  props.words.forEach((w, i) => {
    if (/\d/.test(w.text)) out.add(i);
  });
  for (const i of brandRunStarts(props)) for (let k = 0; k < brandLen(props); k++) out.add(i + k);
  for (const s of props.scenes) {
    const keys = new Set<string>();
    for (const b of s.blocks) {
      if (b.type === 'kinetic-text') b.words.forEach((w) => w.emphasis && keys.add(bare(w.text)));
      if (b.type === 'headline') b.words.forEach((w) => w.tone && w.tone !== 'text' && w.tone !== 'muted' && keys.add(bare(w.text)));
    }
    keys.delete('');
    if (!keys.size) continue;
    props.words.forEach((w, i) => {
      if (w.start >= s.start && w.start <= s.end && keys.has(words[i])) out.add(i);
    });
  }
  return out;
};

// ---------------------------------------------------------------------------------------------------------------
// Light surfaces (scene backdrop 'light'): the kinetic looks drop the dark outline and switch to dark ink, with the
// accent darkened until it meets WCAG contrast on the light surface (text ≥ 4.5:1, karaoke's muted words ≥ 3:1).
// ---------------------------------------------------------------------------------------------------------------

export const parseRgb = (s: string): [number, number, number] | null => {
  const h = /^#([0-9a-f]{6})$/i.exec(s.trim());
  if (h) {
    const n = parseInt(h[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const m = /^rgba?\(([^)]+)\)$/i.exec(s.trim());
  if (!m) return null;
  const v = m[1].split(',').map((x) => parseFloat(x));
  return v.length >= 3 && v.slice(0, 3).every((x) => Number.isFinite(x)) ? [v[0], v[1], v[2]] : null;
};
const toHex = (c: number[]) => '#' + c.map((x) => Math.round(Math.min(255, Math.max(0, x))).toString(16).padStart(2, '0')).join('');

/** `a` → `b` by p. p ≤ 0 returns `a` itself (so dark-backdrop styles stay exactly as they were). */
export const mixColor = (a: string, b: string, p: number): string => {
  if (p <= 0) return a;
  if (p >= 1) return b;
  const x = parseRgb(a);
  const y = parseRgb(b);
  if (!x || !y) return p < 0.5 ? a : b;
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * p)).join(',')})`;
};

const lum = (c: [number, number, number]) => {
  const f = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
};
/** WCAG 2 contrast ratio of two colours (1..21). */
export const contrast = (a: string, b: string): number => {
  const x = parseRgb(a);
  const y = parseRgb(b);
  if (!x || !y) return 1;
  const [l1, l2] = [lum(x), lum(y)].sort((p, q) => q - p);
  return (l1 + 0.05) / (l2 + 0.05);
};
/** `color` darkened toward black in small steps (hue kept) until it reaches `min` contrast on `bg`. */
export const darkenFor = (color: string, bg: string, min: number): string => {
  const c = parseRgb(color);
  if (!c) return color;
  for (let k = 0; k <= 40; k++) {
    const d = toHex(c.map((v) => v * (1 - k * 0.025)));
    if (contrast(d, bg) >= min) return d;
  }
  return '#000000';
};

/** Colours of the kinetic looks over a light surface (min contrasts carry a small margin over 4.5 / 3 because the
 *  light backdrop has soft highlights slightly darker than `light.surface`). */
export const lightCaptionPalette = (theme: Theme) => {
  const bg = theme.colors.light.surface;
  return {
    ink: theme.colors.light.text,
    accent: darkenFor(theme.colors.brand, bg, 4.8),
    muted: darkenFor(theme.colors.light.muted, bg, 3.2),
    block: darkenFor(theme.colors.brand, '#ffffff', 4.8), // highlight block under white text
  };
};
