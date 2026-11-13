/**
 * `composition` block: a generated scene graphic (pipeline/creative/composer.py). Drawn exactly from
 * geometry-composition.ts (the numbers the QA manifest reports). Every element is a pure function of t: it enters at
 * its own `at` with its motion preset (fade-up, fade, scale-in, draw-on, pop, none), numbers count up like `counter`,
 * and `pulseAt` adds a short brand highlight. Colours come only from theme tokens.
 */
import React from 'react';
import {Img, staticFile} from 'remotion';
import {countValueDec, lin, mix, spc} from './anim';
import {CompositionPart, geomComposition, numberText} from './geometry-composition';
import {DUR, LEAD} from './motion/durations';
import {EASE, SPRING} from './motion/easings';
import {Txt} from './prim';
import {Block, CompositionColor, CompositionElement} from './types';
import {alpha, Icon, Logo, useEngine} from './ui';
import type {Ctx} from './ui';

type P = {block: Extract<Block, {type: 'composition'}>; w: number; h: number; appear: number};

/** Theme token → colour. Surfaces follow a light backdrop (light tokens); text follows the scene's ink. */
export const paint = (tok: CompositionColor | undefined, fallback: CompositionColor, ctx: Pick<Ctx, 'theme' | 'surface' | 'ink'>): string => {
  const c = ctx.theme.colors;
  const L = c.light;
  const light = ctx.surface === 'light';
  switch (tok ?? fallback) {
    case 'brand':
      return c.brand;
    case 'brandText':
      return light ? c.brand : c.brandText;
    case 'surface':
      return light ? L.surface : c.surface;
    case 'card':
      return light ? L.card : c.card;
    case 'raised':
      return light ? L.surface : c.raised;
    case 'border':
      return light ? L.border : c.border;
    case 'bg':
      return c.bg;
    case 'text':
      return ctx.ink.text;
    case 'muted':
      return ctx.ink.text2;
    case 'success':
      return ctx.ink.success;
    case 'danger':
      return c.danger;
    case 'warning':
      return c.warning;
    case 'info':
      return c.info;
  }
  return ctx.ink.text;
};

const DRAWN = new Set(['ring', 'arc', 'line']);
const defaultMotion = (e: CompositionElement) =>
  e.motion ?? (e.kind === 'connector' || (e.kind === 'shape' && DRAWN.has(e.shape ?? '')) ? 'draw-on' : e.kind === 'icon' ? 'pop' : e.kind === 'shape' ? 'scale-in' : 'fade-up');

type State = {opacity: number; dy: number; scale: number; draw: number; pulse: number};

/** Entrance + highlight state of one element at time t (pure). */
export const elementState = (e: CompositionElement, t: number, appear: number, fps: number, row: {damping: number; mass: number}): State => {
  const a = (typeof e.at === 'number' ? e.at : appear) - LEAD.block;
  const m = defaultMotion(e);
  let s: State = {opacity: 1, dy: 0, scale: 1, draw: 1, pulse: 0};
  if (m === 'fade-up') {
    const p = spc(t, a, fps, row);
    s = {...s, opacity: Math.min(1, p * 1.4), dy: (1 - p) * 28};
  } else if (m === 'fade') s = {...s, opacity: EASE.outCubic(lin(t, a, a + DUR.base))};
  else if (m === 'scale-in') {
    const p = spc(t, a, fps, row);
    s = {...s, opacity: Math.min(1, p * 1.6), scale: mix(0.6, 1, p)};
  } else if (m === 'pop') {
    const p = spc(t, a, fps, SPRING.pop);
    s = {...s, opacity: Math.min(1, p * 2), scale: p};
  } else if (m === 'draw-on') {
    const d = EASE.outCubic(lin(t, a, a + DUR.slow));
    s = {...s, opacity: t >= a ? 1 : 0, draw: d};
  } else s = {...s, opacity: t >= a ? 1 : 0};
  if (typeof e.pulseAt === 'number' && t >= e.pulseAt) {
    const k = t - e.pulseAt;
    s.pulse = k < 0.9 ? Math.sin((Math.PI * k) / 0.9) : 0;
  }
  return s;
};

const Part: React.FC<{p: CompositionPart; w: number; h: number; appear: number}> = ({p, w, h, appear}) => {
  const ctx = useEngine();
  const {t, fps, theme, motion} = ctx;
  const e = p.el;
  const st = elementState(e, t, appear, fps, motion.row.spring);
  if (st.opacity <= 0) return null;
  const r = p.rect;
  const op = st.opacity * (typeof e.opacity === 'number' ? Math.min(1, Math.max(0, e.opacity)) : 1);
  const scale = st.scale * (1 + 0.06 * st.pulse);
  const box: React.CSSProperties = {position: 'absolute', left: r.x, top: r.y + st.dy, width: r.w, height: r.h, opacity: op, transform: scale !== 1 ? `scale(${scale})` : undefined, transformOrigin: '50% 50%'};
  const glow = st.pulse > 0 ? `0 0 ${40 * st.pulse}px ${alpha(theme.colors.brand, 0.65 * st.pulse)}` : undefined;
  switch (e.kind) {
    case 'text': {
      const col = paint(e.color, e.role === 'body' ? 'muted' : 'text', ctx);
      return (
        <>
          {p.texts.map((s, i) => (
            <Txt key={i} s={s} color={col} style={{opacity: op, transform: `translateY(${st.dy}px) scale(${scale})`, transformOrigin: '50% 50%', textShadow: glow}} />
          ))}
        </>
      );
    }
    case 'number': {
      const s = p.texts[0];
      if (!s) return null;
      const at = typeof e.at === 'number' ? e.at : appear;
      const end = typeof e.countEnd === 'number' ? e.countEnd : at + DUR.slower;
      const v = countValueDec(t, at, end, e.from ?? 0, e.to ?? 0, e.decimals ?? 0);
      const land = spc(t, end, fps, SPRING.land);
      return (
        <Txt
          s={s}
          color={paint(e.color, 'text', ctx)}
          style={{opacity: op, fontVariantNumeric: 'tabular-nums', transform: `translateY(${st.dy}px) scale(${mix(1.06, 1, land) * (1 + 0.06 * st.pulse)})`, textShadow: `0 0 50px ${alpha(theme.colors.brand, 0.5)}`}}
        >
          {numberText(e, v)}
        </Txt>
      );
    }
    case 'icon': {
      if (!e.icon) return null;
      return (
        <div style={{...box, display: 'flex', alignItems: 'center', justifyContent: 'center', filter: glow ? `drop-shadow(${glow})` : undefined}}>
          <Icon name={e.icon} size={r.w} color={paint(e.color, 'brandText', ctx)} stroke={2.2} />
        </div>
      );
    }
    case 'logo':
      return p.logo ? <div style={box}><Logo variant={p.logo.variant === 'custom' ? 'onDark' : p.logo.variant} width={r.w} height={r.h} /></div> : null;
    case 'media':
      return e.asset ? <Img src={staticFile(e.asset)} style={{...box, objectFit: 'contain', display: 'block'}} /> : null;
    case 'connector': {
      if (!p.path || st.draw <= 0.001) return null; // (a round cap would show a dot before the line starts drawing)
      return (
        <svg width={w} height={h} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', opacity: op}}>
          <path d={p.path} pathLength={1} fill="none" stroke={paint(e.stroke, 'brand', ctx)} strokeWidth={p.strokeW} strokeLinecap="round" strokeDasharray="1" strokeDashoffset={1 - st.draw} />
        </svg>
      );
    }
    case 'shape': {
      const shape = e.shape ?? 'rect';
      const fill = paint(e.fill, 'card', ctx);
      const stroke = e.stroke ? paint(e.stroke, 'border', ctx) : undefined;
      if (p.path) {
        if (st.draw <= 0.001) return null;
        return (
          <svg width={w} height={h} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', opacity: op, filter: glow ? `drop-shadow(${glow})` : undefined}}>
            <path d={p.path} pathLength={1} fill="none" stroke={paint(e.stroke, shape === 'line' ? 'border' : 'brand', ctx)} strokeWidth={p.strokeW} strokeLinecap="round" strokeDasharray="1" strokeDashoffset={1 - st.draw} />
          </svg>
        );
      }
      const radius = shape === 'circle' ? '50%' : shape === 'roundrect' ? p.radius : 0;
      return <div style={{...box, borderRadius: radius, background: fill, border: stroke ? `${p.strokeW}px solid ${stroke}` : undefined, boxSizing: 'border-box', boxShadow: glow}} />;
    }
  }
  return null;
};

export const Composition: React.FC<P> = ({block, w, h, appear}) => {
  const {aspects} = useEngine();
  const g = geomComposition(block, w, aspects);
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {g.parts.map((p) => (
        <Part key={p.index} p={p} w={w} h={g.h} appear={appear} />
      ))}
    </div>
  );
};
