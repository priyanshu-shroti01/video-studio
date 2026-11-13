import {continueRender, delayRender, cancelRender, staticFile} from 'remotion';
import {Theme, Tone} from './types';

/** Tone → colour from the theme (the only source of brand colour in the engine). */
export const toneColor = (theme: Theme, tone: Tone | undefined, fallback?: string): string => {
  const c = theme.colors;
  switch (tone) {
    case 'muted':
      return c.text2;
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
    case 'text':
      return c.text;
    default:
      return fallback ?? c.text;
  }
};

/** Solid fill for pills/badges of a tone. */
export const toneFill = (theme: Theme, tone: Tone): string => {
  const c = theme.colors;
  return {text: c.raised, muted: c.raised, brand: c.brand, danger: c.danger, success: c.success, warning: c.warning, info: c.info}[tone];
};

export const fontStack = (family: string, mono = false) =>
  mono ? `"${family}", ui-monospace, Menlo, monospace` : `"${family}", -apple-system, "Helvetica Neue", Arial, sans-serif`;

// Fonts are loaded once per browser tab, deduplicated by family+src.
const loaded = new Map<string, Promise<void>>();
const loadFace = (family: string, src: string, unicodeRange?: string, weight = '200 800') => {
  const key = `${family}|${src}`;
  let p = loaded.get(key);
  if (!p) {
    p = new FontFace(family, `url(${staticFile(src)}) format('woff2')`, unicodeRange ? {weight, unicodeRange} : {weight})
      .load()
      .then((f) => {
        document.fonts.add(f);
      });
    loaded.set(key, p);
  }
  return p;
};

export const loadThemeFonts = (theme: Theme) =>
  Promise.all(
    [theme.fonts.sans, theme.fonts.mono].flatMap((f) => f.files.map((file) => loadFace(f.family, file.src, file.unicodeRange, file.weight))),
  );

/** Blocks rendering until the theme fonts are ready (Remotion delayRender protocol). */
export const holdForFonts = (theme: Theme) => {
  const handle = delayRender(`Loading theme fonts (${theme.name})`);
  loadThemeFonts(theme)
    .then(() => continueRender(handle))
    .catch((e: unknown) => cancelRender(e instanceof Error ? e : new Error(String(e))));
};
