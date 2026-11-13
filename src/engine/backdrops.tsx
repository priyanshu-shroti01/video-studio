/**
 * v2b scene backdrops. Every layer is a pure function of t and the theme colours (no randomness, no particles,
 * no CSS animation); each drifts slowly. Scenes with different backdrops crossfade (look.ts backdropWeights):
 * the heaviest layer is drawn opaque and the others on top at their weight, which is an exact 2-way crossfade
 * and continuous when the order flips at 50 %.
 */
import React, {useId} from 'react';
import {AbsoluteFill} from 'remotion';
import {backdropWeights, splitPanel} from './look';
import {BackdropKind, Format, Scene} from './types';
import {alpha, Backdrop, useEngine} from './ui';

/** Darken (f < 1) or lighten towards white (f > 1) a #rrggbb colour. */
export const shade = (hex: string, f: number) => {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const ch = (v: number) => Math.round(f <= 1 ? v * f : v + (255 - v) * (f - 1));
  const to = (v: number) => Math.max(0, Math.min(255, ch(v))).toString(16).padStart(2, '0');
  return `#${to((n >> 16) & 255)}${to((n >> 8) & 255)}${to(n & 255)}`;
};

type LayerProps = {width: number; height: number; format: Format; danger: number; brand: number};

const Radial: React.FC<{x: number; y: number; rx: number; ry: number; color: string; stop?: number}> = ({x, y, rx, ry, color, stop = 70}) => (
  <div style={{position: 'absolute', left: x - rx, top: y - ry, width: 2 * rx, height: 2 * ry, background: `radial-gradient(ellipse at center, ${color} 0%, rgba(0,0,0,0) ${stop}%)`}} />
);

/** Mood tint shared by the new backdrops (the 'glow' layer keeps its own v1/v2 tint). */
const Mood: React.FC<LayerProps & {light?: boolean}> = ({width, height, danger, brand, light}) => {
  const {theme} = useEngine();
  const c = theme.colors;
  const big = Math.max(width, height);
  return (
    <>
      {danger > 0 ? <Radial x={width / 2} y={height * 0.42} rx={big * 0.42} ry={big * 0.36} color={alpha(c.danger, (light ? 0.12 : 0.2) * danger)} /> : null}
      {brand > 0 ? <Radial x={width / 2} y={height * 0.42} rx={big * 0.38} ry={big * 0.32} color={alpha(c.brandHover, (light ? 0.1 : 0.28) * brand)} /> : null}
    </>
  );
};

const Vignette: React.FC<{strength: number}> = ({strength}) => (
  <AbsoluteFill style={{background: `radial-gradient(ellipse 75% 70% at 50% 45%, rgba(0,0,0,0) 55%, rgba(0,0,0,${strength}) 100%)`}} />
);

/** Centred soft light cone on near-black, a pool of brand light behind the content. No dot grid. */
const Spotlight: React.FC<LayerProps> = (p) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  const {width: W, height: H} = p;
  const sway = Math.sin(t * 0.23) * 1.6;
  const apexX = 50 + Math.sin(t * 0.17) * 1.2;
  const poolY = p.format === 'short' ? 0.42 : 0.5;
  const cone = `conic-gradient(from ${158 + sway}deg at ${apexX}% -12%, rgba(255,255,255,0) 0deg, rgba(255,255,255,0.075) 13deg, rgba(255,255,255,0.10) 22deg, rgba(255,255,255,0.075) 31deg, rgba(255,255,255,0) 44deg, rgba(255,255,255,0) 360deg)`;
  const fade = 'linear-gradient(180deg, black 0%, black 45%, transparent 92%)';
  return (
    <AbsoluteFill style={{background: shade(c.bg, 0.6)}}>
      <AbsoluteFill style={{background: cone, maskImage: fade, WebkitMaskImage: fade}} />
      <Radial x={W / 2} y={H * poolY} rx={Math.max(W, H) * 0.42} ry={Math.max(W, H) * 0.3} color={alpha(c.brand, 0.2 + 0.03 * Math.sin(t * 0.4))} />
      <Radial x={W / 2} y={H * poolY} rx={Math.max(W, H) * 0.22} ry={Math.max(W, H) * 0.14} color="rgba(255,255,255,0.05)" />
      <Vignette strength={0.55} />
      <Mood {...p} />
    </AbsoluteFill>
  );
};

/** Subtle perspective floor grid with a horizon glow (drawn in SVG from a pinhole projection; moves towards us). */
const Grid: React.FC<LayerProps> = (p) => {
  const {theme, t} = useEngine();
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const c = theme.colors;
  const {width: W, height: H} = p;
  const hY = H * (p.format === 'short' ? 0.6 : 0.62);
  const f = W * (p.format === 'short' ? 1.1 : 0.9); // focal length (px)
  const cam = 1.4; // camera height (world units)
  const cell = 1.6; // grid cell (world units)
  const drift = (t * 0.55) % cell;
  const rows: number[] = [];
  for (let k = 0; k < 40; k++) {
    const z = 1.2 + k * cell - drift;
    if (z <= 0.6) continue;
    const y = hY + (f * cam) / z;
    if (y > H + 4 || y - hY < 3) continue;
    rows.push(y);
  }
  const cols: number[] = [];
  for (let k = -22; k <= 22; k++) cols.push(k * cell + (Math.sin(t * 0.07) * cell) / 6);
  const zNear = 0.9;
  const line = alpha(c.brandText, 0.28);
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${shade(c.bg, 0.55)} 0%, ${c.bg} ${((hY / H) * 100 - 8).toFixed(1)}%, ${shade(c.bg, 0.7)} 100%)`}}>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
        <defs>
          <linearGradient id={`sb-fog-${uid}`} x1="0" y1={hY} x2="0" y2={H} gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#fff" stopOpacity="0" />
            <stop offset="0.35" stopColor="#fff" stopOpacity="0.55" />
            <stop offset="1" stopColor="#fff" stopOpacity="1" />
          </linearGradient>
          <mask id={`sb-fogm-${uid}`}>
            <rect x="0" y={hY} width={W} height={H - hY} fill={`url(#sb-fog-${uid})`} />
          </mask>
        </defs>
        <g mask={`url(#sb-fogm-${uid})`} stroke={line} strokeWidth={2} fill="none">
          {rows.map((y, i) => (
            <line key={`r${i}`} x1={0} y1={y} x2={W} y2={y} />
          ))}
          {cols.map((X, i) => (
            <line key={`c${i}`} x1={W / 2} y1={hY} x2={W / 2 + (f * X) / zNear} y2={hY + (f * cam) / zNear} />
          ))}
        </g>
      </svg>
      <Radial x={W / 2} y={hY} rx={W * 0.75} ry={H * 0.16} color={alpha(c.brand, 0.42 + 0.04 * Math.sin(t * 0.5))} />
      <Radial x={W / 2} y={hY} rx={W * 0.4} ry={H * 0.05} color={alpha(c.brandHover, 0.45)} />
      <div style={{position: 'absolute', left: 0, width: W, top: hY - 1, height: 2, background: `linear-gradient(90deg, rgba(0,0,0,0) 0%, ${alpha(c.brandText, 0.65)} 50%, rgba(0,0,0,0) 100%)`}} />
      <Radial x={W * 0.5} y={H * 0.1} rx={W * 0.7} ry={H * 0.28} color={alpha(c.info, 0.07)} />
      <Vignette strength={0.45} />
      <Mood {...p} />
    </AbsoluteFill>
  );
};

/** Brand-colour panel on one side (short: diagonal top band, landscape: diagonal left panel); content sits on the dark side. */
const Split: React.FC<LayerProps> = (p) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  const {width: W, height: H} = p;
  const sp = splitPanel(p.format, W, H);
  const poly = sp.polygon.map(([x, y]) => `${((x / W) * 100).toFixed(3)}% ${((y / H) * 100).toFixed(3)}%`).join(', ');
  const [e0, e1] = p.format === 'short' ? [sp.polygon[3], sp.polygon[2]] : [sp.polygon[1], sp.polygon[2]];
  const darkCx = p.format === 'short' ? W / 2 : (sp.contentLeft + W) / 2;
  const darkCy = p.format === 'short' ? (sp.contentTop + H) / 2.2 : H / 2;
  const hx = (p.format === 'short' ? 0.3 : 0.12) * W + Math.sin(t * 0.3) * W * 0.05;
  const hy = (p.format === 'short' ? 0.05 : 0.3) * H + Math.cos(t * 0.26) * H * 0.04;
  return (
    <AbsoluteFill style={{background: c.bg}}>
      <AbsoluteFill
        style={{
          backgroundImage: 'radial-gradient(rgba(255,255,255,0.06) 1.6px, transparent 1.8px)',
          backgroundSize: '40px 40px',
          backgroundPosition: `${(t * 5) % 40}px ${(t * 8) % 40}px`,
          maskImage: `radial-gradient(ellipse 60% 55% at ${((darkCx / W) * 100).toFixed(1)}% ${((darkCy / H) * 100).toFixed(1)}%, black 20%, transparent 85%)`,
          WebkitMaskImage: `radial-gradient(ellipse 60% 55% at ${((darkCx / W) * 100).toFixed(1)}% ${((darkCy / H) * 100).toFixed(1)}%, black 20%, transparent 85%)`,
        }}
      />
      <Radial x={darkCx} y={darkCy} rx={Math.max(W, H) * 0.38} ry={Math.max(W, H) * 0.3} color={alpha(c.brand, 0.16)} />
      {/* soft shadow the panel casts on the dark side */}
      <AbsoluteFill style={{clipPath: `polygon(${poly})`, background: 'rgba(0,0,0,0.6)', transform: p.format === 'short' ? 'translateY(26px)' : 'translateX(26px)', filter: 'blur(18px)'}} />
      <AbsoluteFill
        style={{
          clipPath: `polygon(${poly})`,
          background: `linear-gradient(${p.format === 'short' ? 160 : 150}deg, ${c.brandHover} 0%, ${c.brand} 45%, ${c.brandActive} 100%)`,
        }}
      >
        <AbsoluteFill style={{backgroundImage: 'repeating-linear-gradient(135deg, rgba(255,255,255,0.055) 0px, rgba(255,255,255,0.055) 2px, rgba(0,0,0,0) 2px, rgba(0,0,0,0) 26px)', backgroundPosition: `${(t * 6) % 37}px 0px`}} />
        <Radial x={hx} y={hy} rx={Math.max(W, H) * 0.32} ry={Math.max(W, H) * 0.24} color="rgba(255,255,255,0.22)" />
        <AbsoluteFill style={{background: 'linear-gradient(0deg, rgba(10,10,15,0.18), rgba(10,10,15,0) 60%)'}} />
      </AbsoluteFill>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
        <line x1={e0[0]} y1={e0[1]} x2={e1[0]} y2={e1[1]} stroke={alpha(c.brandText, 0.35)} strokeWidth={10} />
        <line x1={e0[0]} y1={e0[1]} x2={e1[0]} y2={e1[1]} stroke={alpha('#ffffff', 0.55)} strokeWidth={2.5} />
      </svg>
      <Mood {...p} />
    </AbsoluteFill>
  );
};

/** Light product surface (#f7f5fa) with soft highlights; for UI walkthroughs. */
const Light: React.FC<LayerProps> = (p) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  const L = c.light;
  const {width: W, height: H} = p;
  const big = Math.max(W, H);
  return (
    <AbsoluteFill style={{background: L.surface}}>
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(${alpha(L.text, 0.07)} 1.6px, transparent 1.8px)`,
          backgroundSize: '40px 40px',
          backgroundPosition: `${(t * 5) % 40}px ${(t * 8) % 40}px`,
          maskImage: 'radial-gradient(ellipse 80% 70% at 50% 45%, black 25%, transparent 85%)',
          WebkitMaskImage: 'radial-gradient(ellipse 80% 70% at 50% 45%, black 25%, transparent 85%)',
        }}
      />
      <Radial x={W * 0.18 + 60 * Math.sin(t * 0.3)} y={H * 0.12 + 50 * Math.cos(t * 0.27)} rx={big * 0.42} ry={big * 0.34} color={alpha(c.brand, 0.1)} />
      <Radial x={W * 0.85 + 50 * Math.cos(t * 0.25)} y={H * 0.8 + 60 * Math.sin(t * 0.31)} rx={big * 0.4} ry={big * 0.32} color={alpha(c.info, 0.08)} />
      <Radial x={W / 2} y={H * 0.42} rx={big * 0.36} ry={big * 0.26} color="rgba(255,255,255,0.85)" />
      <AbsoluteFill style={{background: `radial-gradient(ellipse 80% 75% at 50% 45%, rgba(0,0,0,0) 60%, ${alpha(L.text, 0.06)} 100%)`}} />
      <Mood {...p} light />
    </AbsoluteFill>
  );
};

/** Near-black with a faint vignette and a barely-there brand breath. Minimal. */
const Deep: React.FC<LayerProps> = (p) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  const {width: W, height: H} = p;
  const big = Math.max(W, H);
  return (
    <AbsoluteFill style={{background: shade(c.bg, 0.55)}}>
      <Radial x={W / 2} y={H * 0.44} rx={big * 0.5} ry={big * 0.36} color="rgba(255,255,255,0.03)" />
      <Radial x={W / 2 + Math.sin(t * 0.2) * W * 0.06} y={H * 0.95} rx={big * 0.5} ry={big * 0.22} color={alpha(c.brand, 0.1 + 0.02 * Math.sin(t * 0.35))} />
      <Vignette strength={0.6} />
      <Mood {...p} />
    </AbsoluteFill>
  );
};

const Layer: React.FC<LayerProps & {kind: BackdropKind}> = ({kind, ...p}) => {
  switch (kind) {
    case 'glow':
      return <Backdrop width={p.width} height={p.height} danger={p.danger} brand={p.brand} />;
    case 'spotlight':
      return <Spotlight {...p} />;
    case 'grid':
      return <Grid {...p} />;
    case 'split':
      return <Split {...p} />;
    case 'light':
      return <Light {...p} />;
    case 'deep':
      return <Deep {...p} />;
  }
};

/** All backdrops of the video, crossfaded by scene (v2b). */
export const BackdropStack: React.FC<{scenes: Scene[]; format: Format; width: number; height: number; danger: number; brand: number}> = ({scenes, format, width, height, danger, brand}) => {
  const {t} = useEngine();
  const w = backdropWeights(scenes, t);
  const kinds = (Object.keys(w) as BackdropKind[]).filter((k) => (w[k] ?? 0) > 0.001).sort((a, b) => (w[b] ?? 0) - (w[a] ?? 0));
  return (
    <>
      {kinds.map((k, i) => (
        <AbsoluteFill key={k} style={{opacity: i === 0 ? 1 : w[k]}}>
          <Layer kind={k} width={width} height={height} format={format} danger={danger} brand={brand} />
        </AbsoluteFill>
      ))}
    </>
  );
};
