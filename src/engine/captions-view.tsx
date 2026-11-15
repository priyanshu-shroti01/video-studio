import React, {useMemo} from 'react';
import {mix} from './anim';
import {
  captionEmphasis,
  captionMetrics,
  captionPageAt,
  CaptionMetrics,
  captionToneBlock,
  captionToneColor,
  captionToneColorLight,
  captionToneMap,
  keepTogether,
  lightCaptionPalette,
  mixColor,
  pageLayout,
  speakerColor,
  speakerOf,
  speakerTagMetrics,
} from './captions';
import {wordLook} from './captions-motion';
import {backdropWeights} from './look';
import {LEAD} from './motion/durations';
import {springAt} from './motion/entrances';
import {Env, sceneIndexAt, sceneTops} from './plan';
import {CaptionConfig, CaptionTone, RenderProps, Theme, Word} from './types';
import {alpha, useEngine} from './ui';

/**
 * The kinetic caption looks ('pop' | 'highlight' | 'karaoke' | 'minimal'); the classic boxed look stays in
 * Storyboard.tsx, untouched. Every look draws the Python-built pages (1–3 words for pop / highlight, ≤ 4 for karaoke)
 * inside the column and band captionMetrics() reserves, so it can never collide with scene content or platform UI.
 * Pure function of (props, t): no measuring, no state.
 */

/** Emphasised words (numbers, brand name, scene emphasis words) are this much larger in pop / highlight. */
export const EMPH_SCALE = 1.12;
const SETTLE_S = 0.12;

const hex = (s: string): [number, number, number] | null => {
  const m = /^#([0-9a-f]{6})$/i.exec(s);
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const mixHex = (a: string, b: string, p: number) => {
  const x = hex(a);
  const y = hex(b);
  if (!x || !y) return p < 0.5 ? a : b;
  const q = (i: number) => Math.round(x[i] + (y[i] - x[i]) * p);
  return `rgb(${q(0)},${q(1)},${q(2)})`;
};

/** Dark outline + a soft drop shadow: legible on dark, light and busy backdrops. The outline is a ring of hard
 *  text-shadows (round joins), not -webkit-text-stroke: a stroke draws miter spikes on letters like "G" and shows
 *  through translucent fills. `k` = outline thickness as a fraction of the font size (0 = shadow only). */
const outline = (fs: number, k: number, shadow = 0.55, lw = 0): React.CSSProperties => {
  // light surface: the outline and dark shadow fade out entirely (dark ink needs neither); a faint light halo only
  if (lw >= 0.999) return {textShadow: `0 ${(fs * 0.02).toFixed(1)}px ${(fs * 0.1).toFixed(1)}px rgba(255,255,255,0.45)`};
  const fade = 1 - Math.max(0, lw);
  const r = fs * k * 0.5;
  const ring = r > 0.2 ? Array.from({length: 16}, (_, i) => {
    const a = (i / 16) * 2 * Math.PI;
    return `${(Math.cos(a) * r).toFixed(2)}px ${(Math.sin(a) * r).toFixed(2)}px 0 rgba(6,7,12,${lw > 0 ? (0.95 * fade).toFixed(3) : '0.95'})`;
  }) : [];
  return {textShadow: [...ring, `0 ${(fs * 0.05).toFixed(1)}px ${(fs * 0.24).toFixed(1)}px rgba(0,0,0,${lw > 0 ? (shadow * fade).toFixed(3) : shadow})`].join(', ')};
};

/** Light-surface palette per theme (memoised: themes are props-stable). */
const lightCache = new WeakMap<Theme, ReturnType<typeof lightCaptionPalette>>();
const lightOf = (theme: Theme) => {
  let v = lightCache.get(theme);
  if (!v) lightCache.set(theme, (v = lightCaptionPalette(theme)));
  return v;
};

/** `lightW` 0..1: how much of a light surface (scene backdrop 'light') is under the captions now. At 0 every style is
 *  exactly the dark-backdrop one; at 1: dark ink, no outline, contrast-checked accent (lightCaptionPalette). */
type WordProps = {w: Word; k: number; pw: Word[]; t: number; fps: number; fs: number; emph: boolean; theme: Theme; lightW: number; tone?: CaptionTone};

/** v3: a toned word's colour at the current light-surface weight (undefined = no tone: the look's own colours). */
const toneInk = (theme: Theme, tone: CaptionTone | undefined, lightW: number) =>
  !tone ? undefined : lightW > 0 ? mixColor(captionToneColor(theme, tone), captionToneColorLight(theme, tone), lightW) : captionToneColor(theme, tone);

const PopWord: React.FC<WordProps> = ({w, k, pw, t, fps, fs, emph, theme, lightW, tone}) => {
  const s = wordLook(pw, k, t, fps);
  const next = pw[k + 1];
  const bump = emph ? 0.14 : 0.1;
  const peak = 1 + bump * s.pop;
  // active: springs from 0.9 to its peak; once the next word starts it settles back to 1 (no snap)
  const settle = !s.active && s.spoken && next ? Math.min(1, Math.max(0, (t - next.start) / SETTLE_S)) : 0;
  const scale = !s.spoken ? 1 : s.active ? mix(0.9, peak, Math.min(1, s.pop * 1.15)) : mix(1 + bump, 1, settle);
  const L = lightW > 0 ? lightOf(theme) : null;
  const accent = s.active || (emph && s.spoken);
  const base = !L ? (accent ? theme.caption.highlight : theme.caption.text) : mixColor(accent ? theme.caption.highlight : theme.caption.text, accent ? L.accent : L.ink, lightW);
  // a toned word takes its meaning colour as it is spoken and keeps it
  const tc = toneInk(theme, tone, lightW);
  const color = tc && (s.active || s.spoken) ? tc : base;
  return (
    <span style={{display: 'inline-block', fontSize: emph ? fs * EMPH_SCALE : fs, transform: `scale(${scale.toFixed(4)})`, transformOrigin: '50% 65%', color, ...outline(fs, 0.15, 0.55, lightW)}}>
      {w.text}
    </span>
  );
};

const HighlightWord: React.FC<WordProps> = ({w, k, pw, t, fps, fs, emph, theme, lightW, tone}) => {
  const s = wordLook(pw, k, t, fps);
  const next = pw[k + 1];
  // the block grows in from the left as the word starts and leaves to the right as the next one starts,
  // so it reads as one block travelling from word to word
  const leave = !s.active && s.spoken && next ? Math.min(1, Math.max(0, (t - next.start) / SETTLE_S)) : 0;
  const on = s.active ? Math.min(1, s.pop) : s.spoken && next ? 1 - leave : 0;
  // reaches full width at ~77 % of the spring (≈0.1 s), so a settled word is never partly uncovered
  const grow = s.active ? Math.min(1, 0.35 + 0.65 * Math.min(1, s.pop * 1.3)) : 1 - leave;
  const L = lightW > 0 ? lightOf(theme) : null;
  const dark = s.active ? '#ffffff' : emph ? theme.caption.highlight : theme.caption.text;
  const tc = toneInk(theme, tone, lightW);
  const color = tc && s.spoken && !s.active ? tc : !L || s.active ? dark : mixColor(dark, emph ? L.accent : L.ink, lightW);
  // a toned word's block is its tone, darkened until white reads on it
  const block = tone ? captionToneBlock(theme, tone) : null;
  return (
    <span style={{position: 'relative', display: 'inline-block', fontSize: emph ? fs * EMPH_SCALE : fs, padding: `0 ${(fs * 0.12).toFixed(1)}px`}}>
      {on > 0.001 ? (
        <span
          style={{
            position: 'absolute',
            left: -fs * 0.06,
            right: -fs * 0.08,
            top: fs * 0.02,
            bottom: -fs * 0.14,
            borderRadius: fs * 0.18,
            background: block ?? (L ? mixColor(theme.colors.brand, L.block, lightW) : theme.colors.brand),
            opacity: Math.min(1, on * 1.4),
            transform: `scaleX(${grow.toFixed(4)})`,
            transformOrigin: s.active ? 'left center' : 'right center',
            boxShadow: `0 ${(fs * 0.08).toFixed(1)}px ${(fs * 0.3).toFixed(1)}px rgba(0,0,0,${L ? (0.35 - 0.23 * lightW).toFixed(3) : '0.35'})`,
          }}
        />
      ) : null}
      <span style={{position: 'relative', color, ...outline(fs, s.active ? 0.0 : 0.1, s.active ? 0.25 : 0.55, s.active ? Math.min(lightW, 0.9) : lightW)}}>{w.text}</span>
    </span>
  );
};

const KaraokeWord: React.FC<WordProps> = ({w, k, pw, t, fps, fs, theme, lightW, tone}) => {
  const s = wordLook(pw, k, t, fps);
  const L = lightW > 0 ? lightOf(theme) : null;
  const filling = s.active && s.fill < 1;
  const darkFill = filling ? theme.caption.highlight : theme.caption.text;
  const fillColor = toneInk(theme, tone, lightW) ?? (L ? mixColor(darkFill, filling ? L.accent : L.ink, lightW) : darkFill);
  const darkMuted = mixHex(theme.caption.text, '#000000', 0.42);
  const muted = L ? mixColor(darkMuted, L.muted, lightW) : darkMuted;
  return (
    <span style={{position: 'relative', display: 'inline-block', fontSize: fs, transform: s.active ? `scale(${mix(1, 1.04, Math.min(1, s.pop)).toFixed(4)})` : undefined}}>
      <span style={{color: muted, ...outline(fs, 0.14, 0.55, lightW)}}>{w.text}</span>
      {s.fill > 0 ? (
        <span aria-hidden style={{position: 'absolute', left: 0, top: 0, color: fillColor, clipPath: `inset(-20% ${((1 - s.fill) * 100).toFixed(2)}% -20% -20%)`, ...outline(fs, 0.14, 0, lightW)}}>
          {w.text}
        </span>
      ) : null}
    </span>
  );
};

const MinimalWord: React.FC<WordProps> = ({w, k, pw, t, fps, fs, theme, lightW, tone}) => {
  const s = wordLook(pw, k, t, fps);
  const tc = toneInk(theme, tone, lightW);
  const ink = tc && s.spoken ? tc : mixHex(theme.caption.text, theme.colors.light.text, lightW);
  return (
    <span
      style={{
        display: 'inline-block',
        fontSize: fs,
        color: ink,
        opacity: s.spoken ? 1 : 0.62,
        textShadow: lightW > 0.99 ? 'none' : `0 2px ${(fs * 0.35).toFixed(1)}px rgba(0,0,0,${(0.65 * (1 - lightW)).toFixed(3)})`,
      }}
    >
      {w.text}
    </span>
  );
};

/** v3 'headline': words appear as they are spoken (the page's later words hold their place, invisible), so the
 *  sentence builds at the top of the content area; toned words in their colour, emphasis words in the highlight. */
const HeadlineWord: React.FC<WordProps> = ({w, t, fps, fs, emph, theme, lightW, tone}) => {
  const p = springAt(t, w.start - LEAD.word, fps, {damping: 16, mass: 0.55});
  const L = lightW > 0 ? lightOf(theme) : null;
  const base = emph ? theme.caption.highlight : theme.caption.text;
  const color = toneInk(theme, tone, lightW) ?? (L ? mixColor(base, emph ? L.accent : L.ink, lightW) : base);
  return (
    <span
      style={{
        display: 'inline-block',
        fontSize: fs,
        color,
        opacity: Math.min(1, p * 1.6),
        transform: `translateY(${((1 - p) * fs * 0.32).toFixed(2)}px)`,
        ...outline(fs, 0.1, 0.5, lightW),
      }}
    >
      {w.text}
    </span>
  );
};

const WORD = {pop: PopWord, highlight: HighlightWord, karaoke: KaraokeWord, minimal: MinimalWord, headline: HeadlineWord} as const;

/** v3 speaker tag ("● MOM") above a caption page. It pops in when the speaker changes (or returns after a pause)
 *  and holds across that speaker's pages. Colour: the speaker's tone (captions.ts speakerOf). */
export const SpeakerTag: React.FC<{cap: Pick<CaptionConfig, 'speakers' | 'pages' | 'fontSize'>; idx: number; words: Word[]; lightW: number; align?: 'center' | 'left'}> = ({cap, idx, words, lightW, align = 'center'}) => {
  const {t, fps, theme, sans} = useEngine();
  const page = cap.pages[idx];
  const m = speakerTagMetrics(cap.fontSize);
  if (!page?.speaker) return <div style={{height: m.block, flex: 'none'}} />;
  const prev = idx > 0 ? cap.pages[idx - 1] : undefined;
  const first = words[page.wordIdx[0]];
  const prevLast = prev ? words[prev.wordIdx[prev.wordIdx.length - 1]] : undefined;
  const fresh = !prev || prev.speaker !== page.speaker || (!!prevLast && !!first && first.start - prevLast.end > 0.6);
  const sp = speakerOf(cap, page.speaker);
  const col = speakerColor(theme, sp.tone);
  const light = lightW > 0.5;
  const p = fresh && first ? springAt(t, first.start - 0.05 - LEAD.word, fps, {damping: 14, mass: 0.5}) : 1;
  return (
    <div style={{display: 'flex', justifyContent: align === 'left' ? 'flex-start' : 'center', height: m.h, marginBottom: m.gap, flex: 'none'}}>
      <div
        style={{
          display: 'flex', alignItems: 'center', height: m.h, padding: `0 ${(m.fs * 0.75).toFixed(1)}px`, borderRadius: m.h / 2, boxSizing: 'border-box',
          background: light ? alpha(theme.colors.light.card, 0.96) : 'rgba(10,10,15,0.66)', border: `2px solid ${alpha(col, 0.75)}`,
          boxShadow: light ? '0 4px 14px rgba(21,17,28,0.10)' : `0 6px 20px rgba(0,0,0,0.35), 0 0 18px ${alpha(col, 0.2)}`,
          fontFamily: sans, fontWeight: 800, fontSize: m.fs, lineHeight: 1, letterSpacing: m.fs * 0.14, color: light ? theme.colors.light.text : col,
          whiteSpace: 'nowrap', textTransform: 'uppercase', opacity: Math.min(1, p * 1.5), transform: `scale(${mix(0.8, 1, p).toFixed(4)})`, transformOrigin: align === 'left' ? '0% 100%' : '50% 100%',
        }}
      >
        <span style={{width: m.fs * 0.5, height: m.fs * 0.5, borderRadius: '50%', background: col, marginRight: m.fs * 0.5, boxShadow: `0 0 ${(m.fs * 0.5).toFixed(1)}px ${alpha(col, 0.7)}`, flex: 'none'}} />
        {sp.label}
      </div>
    </div>
  );
};

/** Page entrance per look (spring from the page's first word, matching captionPageAt's 0.05 s lead). */
const enterStyle = (m: CaptionMetrics, t: number, start: number, fps: number): React.CSSProperties => {
  const p = springAt(t, start - 0.05, fps, {damping: 15, mass: 0.5});
  const o = Math.min(1, p * 1.6);
  if (m.look === 'pop') return {opacity: o, transform: `scale(${mix(0.82, 1, p).toFixed(4)})`};
  if (m.look === 'minimal') return {opacity: o};
  return {opacity: o, transform: `translateY(${((1 - p) * m.fontSize * 0.25).toFixed(2)}px)`};
};

export const KineticCaptions: React.FC<{props: RenderProps; env?: Env}> = ({props, env}) => {
  const {t, fps, theme, sans} = useEngine();
  const cap = props.captions;
  const emph = useMemo(() => (cap.emphasis === false ? new Set<number>() : captionEmphasis(props)), [props, cap.emphasis]);
  const keep = useMemo(() => keepTogether(props), [props]);
  const tones = useMemo(() => captionToneMap(cap), [cap]);
  const m = useMemo(() => captionMetrics(props.format, cap), [props.format, cap]);
  if (!cap.enabled) return null;
  const idx = captionPageAt(cap.pages, props.words, t);
  if (idx < 0) return null;
  const page = cap.pages[idx];
  const pw = page.wordIdx.map((i) => props.words[i]);
  const look = m.look === 'classic' ? 'pop' : m.look;
  const useEmph = look === 'pop' || look === 'highlight' || look === 'headline';
  // v3: a toned word is emphasised too in pop / highlight (scaled); headline colours emphasis words, never scales them
  const isEmph = (i: number) => useEmph && (emph.has(i) || (look !== 'headline' && tones.has(i)));
  const {fs, lines} = pageLayout(
    pw.map((w) => w.text),
    m,
    page.wordIdx.map((i) => (isEmph(i) ? EMPH_SCALE : 1)),
    page.wordIdx.map((i) => keep.has(i)),
  );
  // the same light-surface signal for every look (minimal switches ink; pop / highlight / karaoke drop the outline)
  const lightW = backdropWeights(props.scenes, t).light ?? 0;
  const W = WORD[look];
  if (look === 'headline') {
    // the band of the scene on screen at the page's first word (plan.ts sceneTops), below the HUD
    const s = props.scenes[sceneIndexAt(props.scenes, pw[0].start)];
    const band = env && s ? sceneTops(env, s).headline : undefined;
    if (!band) return null;
    return (
      // left-aligned: the sentence is written from the column's edge, under the HUD's own left edge
      <div style={{position: 'absolute', left: band.x, top: band.y, width: band.w, height: band.h, display: 'flex', flexDirection: 'column', alignItems: 'flex-start', fontFamily: sans, fontWeight: m.weight, lineHeight: m.lineHeight, letterSpacing: '-0.012em', textTransform: m.uppercase ? 'uppercase' : 'none'}}>
        {m.tagH ? <SpeakerTag cap={cap} idx={idx} words={props.words} lightW={lightW} align="left" /> : null}
        {lines.map((line) => (
          <div key={line[0]} style={{display: 'flex', flexWrap: 'nowrap', alignItems: 'baseline', columnGap: fs * 0.26, whiteSpace: 'nowrap'}}>
            {line.map((k) => (
              <W key={page.wordIdx[k]} w={pw[k]} k={k} pw={pw} t={t} fps={fps} fs={fs} emph={isEmph(page.wordIdx[k])} theme={theme} lightW={lightW} tone={tones.get(page.wordIdx[k])} />
            ))}
          </div>
        ))}
      </div>
    );
  }
  // the speaker tag sits above the page outside its entrance transform, so it holds while the speaker keeps talking
  const tag = m.tagH && page.speaker ? (
    <div style={{position: 'absolute', left: m.x, width: m.maxW, bottom: m.bottom + lines.length * fs * m.lineHeight}}>
      <SpeakerTag cap={cap} idx={idx} words={props.words} lightW={lightW} />
    </div>
  ) : null;
  return (
    <>
    {tag}
    <div
      style={{
        position: 'absolute',
        left: m.x,
        width: m.maxW,
        bottom: m.bottom,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        fontFamily: sans,
        fontWeight: m.weight,
        lineHeight: m.lineHeight,
        letterSpacing: look === 'pop' ? '-0.01em' : look === 'minimal' ? '0' : '-0.005em',
        textTransform: m.uppercase ? 'uppercase' : 'none',
        transformOrigin: '50% 100%',
        ...enterStyle(m, t, pw[0].start, fps),
      }}
    >
      {lines.map((line) => (
        <div key={line[0]} style={{display: 'flex', flexWrap: 'nowrap', alignItems: 'baseline', columnGap: fs * (look === 'highlight' ? 0.12 : look === 'pop' ? 0.34 : 0.26), whiteSpace: 'nowrap'}}>
          {line.map((k) => (
            <W key={page.wordIdx[k]} w={pw[k]} k={k} pw={pw} t={t} fps={fps} fs={fs} emph={isEmph(page.wordIdx[k])} theme={theme} lightW={lightW} tone={tones.get(page.wordIdx[k])} />
          ))}
        </div>
      ))}
    </div>
    </>
  );
};
