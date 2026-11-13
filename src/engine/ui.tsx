import React, {createContext, useContext} from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {clamp01, lin, spc} from './anim';
import {AspectEnv} from './geometry';
import {legacyLogoAspects} from './layout';
import {ACCENT} from './motion/durations';
import {SPRING} from './motion/easings';
import {MOTION_PRESETS, MotionPreset} from './motion/presets';
import {fontStack} from './theme';
import {IconName, LogoVariant, Theme} from './types';

/** Colours for text drawn straight on the backdrop (headlines, kinetic text, counters, pills…). On a 'light'
 *  backdrop they come from the theme's light tokens; everywhere else they are exactly the dark-theme colours. */
export type Ink = {text: string; text2: string; muted: string; accent: string; success: string};
export const darkInk = (theme: Theme): Ink => ({text: theme.colors.text, text2: theme.colors.text2, muted: theme.colors.muted, accent: theme.colors.brandText, success: theme.colors.success});
export const lightInk = (theme: Theme): Ink => ({text: theme.colors.light.text, text2: theme.colors.light.text2, muted: theme.colors.light.muted, accent: theme.colors.brand, success: theme.colors.light.success});

/** Tone → colour for text on the backdrop: like toneColor, but text / muted / brand / success follow the ink. */
export const inkTone = (ink: Ink, theme: Theme, tone: string | undefined, fallback: string) => {
  switch (tone) {
    case 'text':
      return ink.text;
    case 'muted':
      return ink.text2;
    case 'brand':
      return ink.accent;
    case 'success':
      return ink.success;
    case 'danger':
      return theme.colors.danger;
    case 'warning':
      return theme.colors.warning;
    case 'info':
      return theme.colors.info;
    default:
      return fallback;
  }
};

/** Per-frame engine context: theme + clock + the scene's motion preset. Blocks are pure functions of these.
 *  v2b: `polish` (the v2b look is on), `surface` (the scene's backdrop is light or dark) and its `ink`. */
export type Ctx = {
  theme: Theme;
  t: number;
  fps: number;
  sans: string;
  mono: string;
  motion: MotionPreset;
  aspects: AspectEnv;
  v2: boolean;
  polish: boolean;
  surface: 'dark' | 'light';
  ink: Ink;
};
export const EngineCtx = createContext<Ctx | null>(null);
export const useEngine = (): Ctx => {
  const c = useContext(EngineCtx);
  if (!c) throw new Error('Engine components must be rendered inside <EngineCtx.Provider>');
  return c;
};
export const makeCtx = (theme: Theme, t: number, fps: number, extra: Partial<Pick<Ctx, 'motion' | 'aspects' | 'v2' | 'polish'>> = {}): Ctx => ({
  theme,
  t,
  fps,
  sans: fontStack(theme.fonts.sans.family),
  mono: fontStack(theme.fonts.mono.family, true),
  motion: extra.motion ?? MOTION_PRESETS.standard,
  aspects: extra.aspects ?? {logo: legacyLogoAspects(theme.logo.aspect), asset: () => undefined},
  v2: extra.v2 ?? false,
  polish: extra.polish ?? false,
  surface: 'dark',
  ink: darkInk(theme),
});

const Glow: React.FC<{x: number; y: number; size: number; color: string}> = ({x, y, size, color}) => (
  <div
    style={{
      position: 'absolute',
      left: x - size / 2,
      top: y - size / 2,
      width: size,
      height: size,
      borderRadius: '50%',
      background: `radial-gradient(circle, ${color} 0%, rgba(0,0,0,0) 65%)`,
    }}
  />
);

/** Hex (#rrggbb) → rgba() with alpha. Falls back to the input for non-hex colours. */
export const alpha = (hex: string, a: number) => {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

/** Theme backdrop: drifting dot grid + two soft glows; `danger`/`brand` 0..1 tint the scene mood. */
export const Backdrop: React.FC<{width: number; height: number; danger: number; brand: number}> = ({width, height, danger, brand}) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  if (theme.background.style === 'plain') return <AbsoluteFill style={{background: c.bg}} />;
  const big = Math.max(width, height);
  return (
    <AbsoluteFill style={{background: c.bg}}>
      <AbsoluteFill
        style={{
          backgroundImage: 'radial-gradient(rgba(255,255,255,0.075) 1.6px, transparent 1.8px)',
          backgroundSize: '40px 40px',
          backgroundPosition: `${(t * 6) % 40}px ${(t * 10) % 40}px`,
          maskImage: 'radial-gradient(ellipse 80% 70% at 50% 45%, black 30%, transparent 85%)',
          WebkitMaskImage: 'radial-gradient(ellipse 80% 70% at 50% 45%, black 30%, transparent 85%)',
        }}
      />
      <Glow x={width * 0.23 + 70 * Math.sin(t * 0.35)} y={height * 0.22 + 60 * Math.cos(t * 0.3)} size={big * 0.58} color={alpha(theme.background.glowA, 0.3 * (1 - danger))} />
      <Glow x={width * 0.8 + 60 * Math.cos(t * 0.28)} y={height * 0.73 + 70 * Math.sin(t * 0.33)} size={big * 0.52} color={alpha(theme.background.glowB, 0.16 * (1 - danger))} />
      {danger > 0 ? <Glow x={width / 2} y={height * 0.4} size={big * 0.68} color={alpha(c.danger, 0.22 * danger)} /> : null}
      {brand > 0 ? <Glow x={width / 2} y={height * 0.42} size={big * 0.6} color={alpha(c.brandHover, 0.35 * brand)} /> : null}
    </AbsoluteFill>
  );
};

export const Card: React.FC<{light?: boolean; style?: React.CSSProperties; children: React.ReactNode}> = ({light, style, children}) => {
  const {theme, sans} = useEngine();
  const c = theme.colors;
  return (
    <div
      style={{
        background: light ? c.light.card : c.card,
        border: `2px solid ${light ? c.light.border : c.border}`,
        borderRadius: theme.radius.card,
        boxShadow: light ? '0 30px 80px rgba(0,0,0,0.45)' : '0 30px 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06)',
        fontFamily: sans,
        boxSizing: 'border-box',
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Pill: React.FC<{bg: string; color: string; style?: React.CSSProperties; children: React.ReactNode}> = ({bg, color, style, children}) => {
  const {theme, sans} = useEngine();
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 14,
        padding: '12px 28px',
        borderRadius: theme.radius.pill,
        background: bg,
        color,
        fontFamily: sans,
        fontWeight: 800,
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/** Check mark that pops and strokes itself in from `at`. */
export const Check: React.FC<{at: number; size?: number; color?: string}> = ({at, size = 64, color}) => {
  const {theme, t, fps} = useEngine();
  const s = spc(t, at, fps, SPRING.pop);
  const draw = clamp01(lin(t, at + ACCENT.checkDrawFrom, at + ACCENT.checkDrawTo));
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{transform: `scale(${s})`, flexShrink: 0}}>
      <circle cx="12" cy="12" r="11" fill={color ?? theme.colors.success} />
      <path d="M6.5 12.5l3.6 3.6 7.4-7.6" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="20" strokeDashoffset={20 * (1 - draw)} />
    </svg>
  );
};

// Icon paths simplified from Lucide (ISC licence).
const ICONS: Record<IconName, React.ReactNode> = {
  zap: <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />,
  lock: (
    <>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </>
  ),
  server: (
    <>
      <rect x="3" y="3" width="18" height="7" rx="2" />
      <rect x="3" y="14" width="18" height="7" rx="2" />
      <path d="M7 6.5h.01M7 17.5h.01" />
    </>
  ),
  cloud: (
    <>
      <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
      <path d="M12 12v6M9.5 14.5 12 12l2.5 2.5" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </>
  ),
  arrowUp: <path d="M12 19V5M5 12l7-7 7 7" />,
  arrowRight: <path d="M5 12h14M12 5l7 7-7 7" />,
  check: <path d="M20 6 9 17l-5-5" />,
  shield: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
  rocket: (
    <>
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z" />
      <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" />
      <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 5v14a9 3 0 0 0 18 0V5M3 12a9 3 0 0 0 18 0" />
    </>
  ),
  mail: (
    <>
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m22 7-10 6L2 7" />
    </>
  ),
  users: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  chart: <path d="M3 3v18h18M7 16v-4M12 16V8M17 16v-7" />,
  star: <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />,
  // v2b
  app: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  cpu: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
      <path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2" />
    </>
  ),
  memory: (
    <>
      <path d="M6 19v-3M10 19v-3M14 19v-3M18 19v-3M8 11V9M16 11V9M12 11V9M2 15h20" />
      <path d="M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v1.1a2 2 0 0 0 0 3.84V17a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-5.1a2 2 0 0 0 0-3.84Z" />
    </>
  ),
  disk: (
    <>
      <path d="M22 12H2" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
      <path d="M6 16h.01M10 16h.01" />
    </>
  ),
  refresh: (
    <>
      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
      <path d="M8 16H3v5" />
    </>
  ),
  plug: <path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z" />,
  palette: (
    <>
      <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.93 0 1.65-.75 1.65-1.69 0-.44-.18-.84-.44-1.13-.29-.29-.44-.65-.44-1.13a1.64 1.64 0 0 1 1.67-1.67h2c3.05 0 5.55-2.5 5.55-5.55C21.97 6.01 17.46 2 12 2z" />
      <path d="M13.5 6.5h.01M17.5 10.5h.01M8.5 7.5h.01M6.5 12.5h.01" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </>
  ),
  download: <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />,
  gauge: <path d="m12 14 4-4M3.34 19a10 10 0 1 1 17.32 0" />,
  play: <path d="M7 4.5v15a1 1 0 0 0 1.5.87l12-7.5a1 1 0 0 0 0-1.74l-12-7.5A1 1 0 0 0 7 4.5Z" />,
};
export const Icon: React.FC<{name: IconName; size?: number; color?: string; stroke?: number}> = ({name, size = 48, color = 'currentColor', stroke = 2.2}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{flexShrink: 0}}>
    {ICONS[name]}
  </svg>
);

/** Pointer that dips on click and ripples from the tip. Coordinates are local to the parent. */
export const Cursor: React.FC<{x: number; y: number; clickAt: number; opacity?: number}> = ({x, y, clickAt, opacity = 1}) => {
  const {t} = useEngine();
  const press = t >= clickAt && t < clickAt + 0.12 ? 1 : 0;
  const ring = lin(t, clickAt, clickAt + 0.45);
  return (
    <div style={{position: 'absolute', left: x, top: y, opacity, pointerEvents: 'none', zIndex: 5}}>
      {ring > 0 && ring < 1 ? (
        <div
          style={{
            position: 'absolute',
            left: -50 * ring,
            top: -50 * ring,
            width: 100 * ring,
            height: 100 * ring,
            borderRadius: '50%',
            border: `4px solid rgba(255,255,255,${0.7 * (1 - ring)})`,
          }}
        />
      ) : null}
      <svg width="64" height="64" viewBox="0 0 24 24" style={{transform: `scale(${1 - 0.15 * press})`, transformOrigin: '0 0', filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.5))'}}>
        <path d="M3 2l15 10.5-6.6 1.2 3.9 7.3-2.9 1.5-3.9-7.4L3 20z" fill="#fff" stroke="#000" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    </div>
  );
};

/** Theme logo (or an explicit public/ `src`), always object-fit: contain inside its box — never distorted. */
export const Logo: React.FC<{variant: LogoVariant; width: number; height: number; src?: string; style?: React.CSSProperties}> = ({variant, width, height, src, style}) => {
  const {theme} = useEngine();
  return <Img src={staticFile(src ?? theme.logo[variant])} style={{width, height, display: 'block', objectFit: 'contain', ...style}} />;
};
