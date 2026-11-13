import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {clamp01, lin, sp} from './anim';
import {B, SANS} from './brand';

/** Dark backdrop: drifting dot grid + two soft glows (brand purple / blue; tinted red during the problem act). */
export const Backdrop: React.FC<{t: number; danger: number; bloom: number}> = ({t, danger, bloom}) => {
  const glowA = danger > 0 ? `rgba(240,87,107,${0.22 * danger + 0.0})` : 'transparent';
  return (
    <AbsoluteFill style={{background: B.bg}}>
      <AbsoluteFill
        style={{
          backgroundImage: 'radial-gradient(rgba(255,255,255,0.075) 1.6px, transparent 1.8px)',
          backgroundSize: '40px 40px',
          backgroundPosition: `${(t * 6) % 40}px ${(t * 10) % 40}px`,
          maskImage: 'radial-gradient(ellipse 80% 70% at 50% 45%, black 30%, transparent 85%)',
          WebkitMaskImage: 'radial-gradient(ellipse 80% 70% at 50% 45%, black 30%, transparent 85%)',
        }}
      />
      <Glow x={250 + 70 * Math.sin(t * 0.35)} y={420 + 60 * Math.cos(t * 0.3)} size={1100} color={`rgba(168,16,199,${0.3 * (1 - danger)})`} />
      <Glow x={860 + 60 * Math.cos(t * 0.28)} y={1400 + 70 * Math.sin(t * 0.33)} size={1000} color={`rgba(63,167,255,${0.16 * (1 - danger)})`} />
      <Glow x={540} y={760} size={1300} color={glowA} />
      <Glow x={540} y={820} size={900 + 500 * bloom} color={`rgba(200,23,234,${0.42 * bloom})`} />
    </AbsoluteFill>
  );
};

export const Glow: React.FC<{x: number; y: number; size: number; color: string}> = ({x, y, size, color}) => (
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

/** Absolute-positioned box centred on x. */
export const At: React.FC<{x?: number; y: number; w: number; style?: React.CSSProperties; children: React.ReactNode}> = ({
  x = 540,
  y,
  w,
  style,
  children,
}) => <div style={{position: 'absolute', left: x - w / 2, top: y, width: w, ...style}}>{children}</div>;

export const Card: React.FC<{light?: boolean; style?: React.CSSProperties; children: React.ReactNode}> = ({light, style, children}) => (
  <div
    style={{
      background: light ? B.light.card : B.card,
      border: `2px solid ${light ? B.light.border : B.border}`,
      borderRadius: 32,
      boxShadow: light ? '0 30px 80px rgba(0,0,0,0.45)' : '0 30px 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06)',
      fontFamily: SANS,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Pill: React.FC<{bg: string; color: string; style?: React.CSSProperties; children: React.ReactNode}> = ({bg, color, style, children}) => (
  <div
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 14,
      padding: '12px 28px',
      borderRadius: 999,
      background: bg,
      color,
      fontFamily: SANS,
      fontWeight: 800,
      ...style,
    }}
  >
    {children}
  </div>
);

/** Green check that draws itself: circle pops, tick strokes in. */
export const Check: React.FC<{t: number; at: number; size?: number; color?: string}> = ({t, at, size = 64, color = B.success}) => {
  const s = sp(t, at, 12, 0.6);
  const draw = clamp01(lin(t, at + 0.08, at + 0.35));
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{transform: `scale(${s})`, flexShrink: 0}}>
      <circle cx="12" cy="12" r="11" fill={color} />
      <path d="M6.5 12.5l3.6 3.6 7.4-7.6" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="20" strokeDashoffset={20 * (1 - draw)} />
    </svg>
  );
};

// Icon paths: simplified from Lucide (ISC licence), the icon set shrotihost.in itself uses.
const ICONS: Record<string, React.ReactNode> = {
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
};
export const Icon: React.FC<{name: keyof typeof ICONS; size?: number; color?: string; stroke?: number}> = ({name, size = 48, color = 'currentColor', stroke = 2.2}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{flexShrink: 0}}>
    {ICONS[name]}
  </svg>
);

/** macOS-style pointer. `press` 0..1 dips it on click; a ring ripples from the tip after `clickAt`. */
export const Cursor: React.FC<{x: number; y: number; t: number; clickAt: number; opacity?: number}> = ({x, y, t, clickAt, opacity = 1}) => {
  const press = t >= clickAt && t < clickAt + 0.12 ? 1 : 0;
  const ring = lin(t, clickAt, clickAt + 0.45);
  return (
    <div style={{position: 'absolute', left: x, top: y, opacity, pointerEvents: 'none'}}>
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

export const Logo: React.FC<{width: number; style?: React.CSSProperties}> = ({width, style}) => (
  <Img src={staticFile('brand/logo-on-dark.svg')} style={{width, height: width / 5, display: 'block', ...style}} />
);
