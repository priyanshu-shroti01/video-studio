// Interface glyphs: Lucide (ISC licence, @iconify-json/lucide 1.2.100, fetched with the taste-skill icons resolver).
// Inlined here so the Studio needs no network and its CSP stays strict. Credits: docs/LICENSING.md.
import React from 'react';

const PATHS: Record<string, string> = {
  'activity': "<path d=\"M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2\"/>",
  'arrow-left': "<path d=\"m12 19l-7-7l7-7m7 7H5\"/>",
  'arrow-right': "<path d=\"M5 12h14m-7-7l7 7l-7 7\"/>",
  'check': "<path d=\"M20 6L9 17l-5-5\"/>",
  'circle-check': "<g><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m9 12l2 2l4-4\"/></g>",
  'circle-help': "<g><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3m.08 4h.01\"/></g>",
  'clapperboard': "<path d=\"m12.296 3.464l3.02 3.956M20.2 6L3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3zM3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zm3.18-5.724l3.1 3.899\"/>",
  'download': "<g><path d=\"M12 15V3m9 12v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/><path d=\"m7 10l5 5l5-5\"/></g>",
  'file-pen-line': "<g><path d=\"M14.364 13.634a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506l4.013-4.009a1 1 0 0 0-3.004-3.004zm.123-5.776A1 1 0 0 1 14 7V2\"/><path d=\"M20 19.645V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l2.516 2.516M8 18h1\"/></g>",
  'globe': "<g><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 2a14.5 14.5 0 0 0 0 20a14.5 14.5 0 0 0 0-20M2 12h20\"/></g>",
  'house': "<g><path d=\"M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8\"/><path d=\"M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z\"/></g>",
  'images': "<g><path d=\"m22 11l-1.296-1.296a2.4 2.4 0 0 0-3.408 0L11 16\"/><path d=\"M4 8a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2\"/><circle cx=\"13\" cy=\"7\" r=\"1\" fill=\"currentColor\"/><rect width=\"14\" height=\"14\" x=\"8\" y=\"2\" rx=\"2\"/></g>",
  'layout-dashboard': "<g><rect width=\"7\" height=\"9\" x=\"3\" y=\"3\" rx=\"1\"/><rect width=\"7\" height=\"5\" x=\"14\" y=\"3\" rx=\"1\"/><rect width=\"7\" height=\"9\" x=\"14\" y=\"12\" rx=\"1\"/><rect width=\"7\" height=\"5\" x=\"3\" y=\"16\" rx=\"1\"/></g>",
  'list-video': "<path d=\"M21 5H3m7 7H3m7 7H3m12-6.997a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718l-4.997 2.997a1 1 0 0 1-1.517-.86z\"/>",
  'play': "<path d=\"M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z\"/>",
  'plus': "<path d=\"M5 12h14m-7-7v14\"/>",
  'send': "<path d=\"M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11zm7.318-19.539l-10.94 10.939\"/>",
  'settings': "<g><path d=\"M9.671 4.136a2.34 2.34 0 0 1 4.659 0a2.34 2.34 0 0 0 3.319 1.915a2.34 2.34 0 0 1 2.33 4.033a2.34 2.34 0 0 0 0 3.831a2.34 2.34 0 0 1-2.33 4.033a2.34 2.34 0 0 0-3.319 1.915a2.34 2.34 0 0 1-4.659 0a2.34 2.34 0 0 0-3.32-1.915a2.34 2.34 0 0 1-2.33-4.033a2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/></g>",
  'x': "<path d=\"M18 6L6 18M6 6l12 12\"/>",
};

export type IconName = keyof typeof PATHS;

/** A 1.75px line glyph that takes the text colour. Decorative unless `label` is given. */
export const Icon: React.FC<{name: string; size?: number; label?: string; className?: string}> = ({name, size = 18, label, className = ''}) => (
  <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
    strokeLinecap="round" strokeLinejoin="round" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}
    dangerouslySetInnerHTML={{__html: PATHS[name] ?? ''}} />
);

/** A platform's own logo in its colours (CC0 drawings from gilbarbara/logos; trademarks of their owners), on a white tile. */
const LOGOS = ['linkedin', 'youtube', 'instagram', 'facebook', 'tiktok', 'x'];
export const PlatformLogo: React.FC<{platform: string; size?: number}> = ({platform, size = 20}) => (LOGOS.includes(platform)
  ? <span className="plogo" style={{width: size + 8, height: size + 8}}><img src={`/files/public/shared/logos/platform-${platform}.svg`} alt="" width={size} height={size} /></span>
  : null);
