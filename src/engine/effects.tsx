/**
 * Drawing of the effect transitions and emphasis effects (state: motion/effects.ts, motion/fx-transitions.ts).
 * Everything here is gated: props without `scene.effects`, effect transitions or `theme.grain` never mount any of it,
 * and Storyboard.tsx keeps its classic code path for them (same DOM, same pixels).
 */
import React from 'react';
import {DIMENSIONS} from './contract';
import {specWidth} from './geometry';
import {clampZoom, geomFootage, zoomAt, zoomRect} from './geometry-footage';
import {
  allowedFlashes,
  annotationPath,
  burstParticles,
  cursorState,
  drawProgress,
  effectSeed,
  flashIntensity,
  FX,
  grainOpacity,
  grainSeed,
  hasEffects,
  R,
  tiltAt,
} from './motion/effects';
import {EASE} from './motion/easings';
import {estimateTextWidth} from './motion/typography';
import {FxTransitionState, isFxTransition, lightLeakAt, TR_FX} from './motion/fx-transitions';
import {blockContent} from './texts';
import {toneColor} from './theme';
import {Block, RenderProps, Scene, SceneEffect} from './types';
import {alpha, useEngine} from './ui';

export const fxBlurId = (axis: 'x' | 'y', level: number) => `sb-fxblur-${axis}-${level}`;
export const glitchId = (level: number) => `sb-glitch-${level}`;

/** True when the props use any effect (the renderer mounts the effect layers only then). */
export const usesFx = (props: Pick<RenderProps, 'scenes' | 'theme'>) =>
  !!props.theme.grain || props.scenes.some((s) => hasEffects(s) || isFxTransition(s.transition));

const flashCache = new WeakMap<Scene[], Set<string>>();
/** Photosensitivity guard: the flashes the engine may draw (≤ 3 in any second), computed once per props. */
export const flashBudget = (scenes: Scene[]) => {
  let s = flashCache.get(scenes);
  if (!s) {
    s = allowedFlashes(scenes);
    flashCache.set(scenes, s);
  }
  return s;
};

/** SVG filters of the effect transitions (directional blur per axis + RGB split), defined once. */
export const FxDefs: React.FC = () => (
  <svg width={0} height={0} style={{position: 'absolute'}} aria-hidden>
    <defs>
      {(['x', 'y'] as const).flatMap((axis) =>
        TR_FX.blur.sigma.map((sd, level) =>
          level === 0 ? null : (
            <filter key={`${axis}${level}`} id={fxBlurId(axis, level)} x={axis === 'x' ? '-20%' : '-5%'} y={axis === 'y' ? '-20%' : '-5%'} width={axis === 'x' ? '140%' : '110%'} height={axis === 'y' ? '140%' : '110%'}>
              <feGaussianBlur stdDeviation={axis === 'x' ? `${sd} 0` : `0 ${sd}`} />
            </filter>
          ),
        ),
      )}
      {TR_FX.glitch.split.map((dx, level) =>
        level === 0 ? null : (
          <filter key={`g${level}`} id={glitchId(level)} x="-5%" y="0%" width="110%" height="100%" colorInterpolationFilters="sRGB">
            <feColorMatrix in="SourceGraphic" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r" />
            <feOffset in="r" dx={dx} dy={0} result="ro" />
            <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g" />
            <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b" />
            <feOffset in="b" dx={-dx} dy={0} result="bo" />
            <feBlend in="ro" in2="g" mode="screen" result="rg" />
            <feBlend in="rg" in2="bo" mode="screen" />
          </filter>
        ),
      )}
    </defs>
  </svg>
);

/** Extra transform of the scene layer (effect transition offset/scale, punch-zoom, shake); '' at identity. */
export const fxLayerTransform = (tr: FxTransitionState | undefined, cam: {scale: number; dx: number; dy: number} | undefined) => {
  const dx = (tr?.dx ?? 0) + (cam?.dx ?? 0) + (tr?.glitchDx ?? 0);
  const dy = cam?.dy ?? 0; // tr.dy is already in the base transform
  const sc = (tr?.scale ?? 1) * (cam?.scale ?? 1);
  if (dx === 0 && dy === 0 && sc === 1) return '';
  return ` translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px) scale(${sc.toFixed(5)})`;
};
/** Filter of the scene layer during an effect transition (undefined otherwise). */
export const fxLayerFilter = (tr: FxTransitionState | undefined) => {
  if (!tr) return undefined;
  const f = [
    tr.blurLevel > 0 ? `url(#${fxBlurId(tr.blurAxis, tr.blurLevel)})` : '',
    tr.glitch > 0 ? `url(#${glitchId(tr.glitch)})` : '',
    tr.blur > 0.05 ? `blur(${tr.blur.toFixed(2)}px)` : '',
  ].filter(Boolean);
  return f.length ? f.join(' ') : undefined;
};

/** Tilt / parallax entrance transform of block `index` ('' when no tilt is active). Applied after the block's own
 *  transform, around the block's centre, so the block settles exactly at its laid-out box. */
export const blockTiltTransform = (effects: SceneEffect[] | undefined, index: number, t: number, appear: number, w: number, h: number) => {
  for (const e of effects ?? []) {
    if (e.type !== 'tilt' || e.target !== index) continue;
    const s = tiltAt(e, t, appear);
    if (!s.active) return '';
    return ` translate(${(w / 2 + s.dx).toFixed(2)}px, ${(h / 2).toFixed(2)}px) perspective(${FX.tilt.perspective}px) rotateX(${s.rx.toFixed(3)}deg) rotateY(${s.ry.toFixed(3)}deg) translate(${(-w / 2).toFixed(2)}px, ${(-h / 2).toFixed(2)}px)`;
  }
  return '';
};

const normText = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}₹$%.]+/gu, ' ').trim();

/** Rect (design px, block-relative) of `text` inside a block, else of the whole block. */
export const annotationRect = (b: Block, w: number, h: number, aspects: Parameters<typeof blockContent>[3], text?: string): R => {
  const texts = blockContent(b, w, h, aspects).texts;
  const want = text ? normText(text) : '';
  if (want) {
    for (const s of texts) {
      const hay = s.text.toLowerCase();
      const i = hay.indexOf(want) >= 0 ? hay.indexOf(want) : normText(s.text) === want ? 0 : -1;
      if (i < 0) continue;
      const est = specWidth(s);
      const bx = s.align === 'left' ? s.x : s.align === 'right' ? s.x + s.w - est : s.x + (s.w - est) / 2;
      const ew = (x: string) => estimateTextWidth(x, s.fs, {weight: s.weight, letterSpacing: s.ls ?? 0, mono: s.mono});
      const sub = s.text.slice(i, i + want.length);
      const scale = est / Math.max(1, ew(s.text));
      return {x: bx + ew(s.text.slice(0, i)) * scale, y: s.y + s.h * 0.08, w: Math.max(8, ew(sub) * scale), h: s.h * 0.84};
    }
  }
  // no text match: the largest text run (the title / value), else the block box
  const big = [...texts].sort((a, b2) => b2.fs - a.fs)[0];
  if (big && !text) {
    const est = specWidth(big);
    const bx = big.align === 'left' ? big.x : big.align === 'right' ? big.x + big.w - est : big.x + (big.w - est) / 2;
    return {x: bx, y: big.y + big.h * 0.08, w: est, h: big.h * 0.84};
  }
  return {x: w * 0.04, y: h * 0.04, w: w * 0.92, h: h * 0.92};
};

const particleColors = (c: RenderProps['theme']['colors']) => [c.brand, c.brandHover, c.success, c.warning];

const Particles: React.FC<{e: Extract<SceneEffect, {type: 'burst'}>; seed: number; ox: number; oy: number; k: number; r0?: number}> = ({e, seed, ox, oy, k, r0 = 0}) => {
  const {t, theme} = useEngine();
  const ps = burstParticles(e, t, seed, r0);
  if (!ps.length) return null;
  const cols = particleColors(theme.colors);
  return (
    <>
      {ps.map((p, i) =>
        p.opacity <= 0.01 ? null : p.shape === 'dot' ? (
          <circle key={i} cx={ox + p.x * k} cy={oy + p.y * k} r={(p.size * k) / 2.4} fill={cols[p.color]} opacity={p.opacity} />
        ) : (
          <rect
            key={i}
            x={-(p.size * k) / 2}
            y={-(p.size * k) / 4}
            width={p.size * k}
            height={(p.size * k) / 2}
            rx={1.5 * k}
            fill={cols[p.color]}
            opacity={p.opacity}
            transform={`translate(${(ox + p.x * k).toFixed(2)} ${(oy + p.y * k).toFixed(2)}) rotate(${p.rot.toFixed(1)})`}
          />
        ),
      )}
    </>
  );
};

const CURSOR_PATH = 'M 0 0 L 0 30 L 7.5 23 L 12.5 34.5 L 17.5 32.5 L 12.8 21.2 L 23 21 Z';

/** Effects drawn inside block `index` (design px; they follow its entrance, staging and tilt). */
export const BlockFx: React.FC<{scene: Scene; index: number; block: Block; w: number; h: number}> = ({scene, index, block, w, h}) => {
  const {t, theme, aspects} = useEngine();
  const c = theme.colors;
  const items: React.ReactNode[] = [];
  (scene.effects ?? []).forEach((e, i) => {
    if (!('target' in e) || e.target !== index) return;
    const seed = effectSeed(scene.id, i);
    if (e.type === 'annotate') {
      const p = drawProgress(e, t);
      if (p <= 0) return;
      const r = annotationRect(block, w, h, aspects, e.text);
      const a = annotationPath(e.kind, r, seed, w);
      const col = e.tone ? toneColor(theme, e.tone) : c.brandHover;
      const shaft = e.kind === 'arrow' ? Math.min(1, p / 0.75) : p;
      const head = e.kind === 'arrow' ? Math.max(0, (p - 0.75) / 0.25) : 0;
      items.push(
        <g key={i} style={{filter: `drop-shadow(0 4px 14px ${alpha(c.brand, 0.45)})`}}>
          <path d={a.d} pathLength={1} fill="none" stroke={col} strokeWidth={a.stroke} strokeLinecap="round" strokeLinejoin="round" strokeDasharray="1 1" strokeDashoffset={1 - shaft} />
          {a.head && head > 0 ? <path d={a.head} pathLength={1} fill="none" stroke={col} strokeWidth={a.stroke} strokeLinecap="round" strokeLinejoin="round" strokeDasharray="1 1" strokeDashoffset={1 - head} /> : null}
        </g>,
      );
    } else if (e.type === 'burst') {
      const r = annotationRect(block, w, h, aspects);
      items.push(<Particles key={i} e={e} seed={seed} ox={r.x + r.w / 2} oy={r.y + r.h / 2} k={1} r0={Math.max(r.w, r.h) * 0.6} />);
    } else if (e.type === 'cursor') {
      let px: number;
      let py: number;
      let unit = 1;
      let target = {x: e.x ?? 0.5, y: e.y ?? 0.5};
      if (block.type === 'footage') {
        const g = geomFootage(block, w, aspects);
        if (e.x === undefined || e.y === undefined) {
          const ks = (block.zooms ?? []).filter((z) => z.at <= e.at + 0.05).sort((a2, b2) => b2.at - a2.at);
          if (ks.length) {
            const z = clampZoom(ks[0]);
            target = {x: e.x ?? z.x, y: e.y ?? z.y};
          }
        }
        const st = cursorState(e, target, t);
        if (!st) return;
        const zr = zoomRect(zoomAt(block.zooms, t), g.screen.w, g.screen.h);
        px = g.screen.x + zr.x + st.x * zr.w;
        py = g.screen.y + zr.y + st.y * zr.h;
        unit = Math.max(0.8, Math.min(1.6, g.screen.w / 900));
        items.push(<CursorView key={i} x={px} y={py} st={st} unit={unit} brand={c.brandHover} />);
      } else {
        const st = cursorState(e, target, t);
        if (!st) return;
        px = st.x * w;
        py = st.y * h;
        items.push(<CursorView key={i} x={px} y={py} st={st} unit={unit} brand={c.brandHover} />);
      }
    }
  });
  if (!items.length) return null;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', pointerEvents: 'none'}}>
      {items}
    </svg>
  );
};

const CursorView: React.FC<{x: number; y: number; st: NonNullable<ReturnType<typeof cursorState>>; unit: number; brand: string}> = ({x, y, st, unit, brand}) => {
  const s = 1.25 * unit * (1 - 0.16 * st.press);
  return (
    <g opacity={st.opacity}>
      {st.ripple ? (
        <>
          <circle cx={x} cy={y} r={(14 + 62 * st.ripple.r) * unit} fill={alpha(brand, 0.18 * st.ripple.opacity)} stroke={brand} strokeOpacity={0.9 * st.ripple.opacity} strokeWidth={4 * unit} />
        </>
      ) : null}
      <g transform={`translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${s.toFixed(4)})`} style={{filter: 'drop-shadow(0 3px 6px rgba(0,0,0,0.45))'}}>
        <path d={CURSOR_PATH} fill="#ffffff" stroke="#15111c" strokeWidth={2} strokeLinejoin="round" />
      </g>
    </g>
  );
};

/** Scene-level effects without a target block (a burst from the content centre), output px. */
export const SceneFx: React.FC<{scene: Scene; cx: number; cy: number; width: number; height: number}> = ({scene, cx, cy, width, height}) => {
  const bursts = (scene.effects ?? []).map((e, i) => [e, i] as const).filter(([e]) => e.type === 'burst' && e.target === undefined);
  if (!bursts.length) return null;
  return (
    <svg width={width} height={height} style={{position: 'absolute', left: 0, top: 0, pointerEvents: 'none'}}>
      {bursts.map(([e, i]) => (e.type === 'burst' ? <Particles key={i} e={e} seed={effectSeed(scene.id, i)} ox={cx} oy={cy} k={width / 1080} /> : null))}
    </svg>
  );
};

/** Full-frame light layers (below the brand bar, watermark and captions): flash pulses, light leaks, film grain. */
export const FxOverlay: React.FC<{props: RenderProps; frame: number}> = ({props, frame}) => {
  const {t, fps, theme} = useEngine();
  const {width, height} = DIMENSIONS[props.format];
  const allowed = flashBudget(props.scenes);
  let flash = 0;
  for (const s of props.scenes) {
    if (!hasEffects(s) || t < s.start - 0.2 || t > s.end + 0.6) continue;
    s.effects!.forEach((e, i) => {
      if (e.type === 'flash' && allowed.has(`${s.id}#${i}`)) flash = Math.max(flash, flashIntensity(e, t));
    });
  }
  const leak = lightLeakAt(props.scenes, t, allowed);
  const grain = grainOpacity(theme.grain);
  const c = theme.colors;
  return (
    <>
      {leak ? <LightLeak width={width} height={height} p={leak.p} intensity={leak.intensity} seed={leak.seed} brand={c.brandHover} /> : null}
      {flash > 0.002 ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            pointerEvents: 'none',
            mixBlendMode: 'screen',
            background: `radial-gradient(ellipse 85% 70% at 50% 42%, rgba(255,255,255,${(flash * 0.95).toFixed(4)}) 0%, ${alpha(c.brandHover, flash * 0.55)} 55%, ${alpha(c.brand, flash * 0.25)} 100%)`,
          }}
        />
      ) : null}
      {grain > 0 ? <Grain width={width} height={height} opacity={grain} seed={grainSeed(frame, fps)} /> : null}
    </>
  );
};

const LightLeak: React.FC<{width: number; height: number; p: number; intensity: number; seed: number; brand: string}> = ({width, height, p, intensity, seed, brand}) => {
  // a warm flare sweeping in from one edge (alternating per cut) plus a brand haze trailing it: light spilling across
  // the lens, never a centred blob
  const tall = height > width;
  const left = seed % 2 === 1;
  const x0 = -18 + 60 * EASE.inOutSine(p);
  const x = left ? x0 : 100 - x0;
  const y = tall ? 22 + 16 * p : 30 + 12 * p;
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        mixBlendMode: 'screen',
        opacity: intensity,
        background: [
          `radial-gradient(ellipse ${tall ? '48% 70%' : '30% 95%'} at ${x.toFixed(2)}% ${y.toFixed(2)}%, rgba(255,226,190,0.95) 0%, rgba(255,168,96,0.7) 22%, rgba(255,110,60,0.28) 48%, rgba(0,0,0,0) 72%)`,
          `linear-gradient(${left ? 105 : 255}deg, rgba(0,0,0,0) ${(x0 - 10).toFixed(2)}%, rgba(255,150,90,0.22) ${(x0 + 8).toFixed(2)}%, ${alpha(brand, 0.3)} ${(x0 + 26).toFixed(2)}%, rgba(0,0,0,0) ${(x0 + 52).toFixed(2)}%)`,
        ].join(', '),
      }}
    />
  );
};

const Grain: React.FC<{width: number; height: number; opacity: number; seed: number}> = ({width, height, opacity, seed}) => {
  // noise is generated at half resolution and scaled up (cheaper, and grain reads slightly soft, like film)
  const w = Math.round(width / 2);
  const h = Math.round(height / 2);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{position: 'absolute', left: 0, top: 0, width, height, opacity, mixBlendMode: 'overlay', pointerEvents: 'none'}}>
      <filter id="sb-grain">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={1} seed={seed} stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width={w} height={h} filter="url(#sb-grain)" />
    </svg>
  );
};
