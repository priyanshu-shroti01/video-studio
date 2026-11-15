/**
 * v3 explainer blocks: gauge, countdown, chat-thread, notification, term-reveal, verdict, comment-cta, poll and
 * next-episode. Drawn exactly from geometry-explainer.ts (the numbers the QA manifest reports). Pure functions of t
 * built on the engine's motion tokens (DUR / LEAD / SPRING / EASE); every visible word comes from the block props.
 */
import React, {useId} from 'react';
import {easeInOut, lin, mix, spc} from './anim';
import {
  arcPath,
  chatTypingDur,
  commentTimes,
  countdownState,
  countdownText,
  gaugeRange,
  gaugeState,
  gaugeText,
  geomChat,
  geomComment,
  geomCountdown,
  geomGauge,
  geomNext,
  geomNotification,
  geomPoll,
  geomTerm,
  geomVerdict,
  NEXT,
  NOTE,
  noteShift,
  polar,
  POLL,
  subAtOf,
  TERM,
  termAtOf,
  typedChars,
  VERDICT,
  verdictMark,
  verdictTone,
  zoneTone,
} from './geometry-explainer';
import {ACCENT, DUR, LEAD} from './motion/durations';
import {EASE, SPRING} from './motion/easings';
import {reader, Txt} from './prim';
import {toneColor} from './theme';
import {Block, BlockV3, Theme, Tone} from './types';
import {alpha, Icon, inkTone, useEngine} from './ui';

type P<K extends BlockV3['type']> = {block: Extract<Block, {type: K}>; w: number; h: number; appear: number; boxY: number; scale: number; sceneStart?: number; sceneEnd?: number};

/** Stroke colour of a tone on the dark / light surface (brand → the brand fill, not the brand text tint). */
const toneStroke = (theme: Theme, tone: Tone | undefined) => (tone === undefined || tone === 'brand' ? theme.colors.brandHover : toneColor(theme, tone));

const hex = (s: string): [number, number, number] | undefined => {
  const m = /^#([0-9a-f]{6})$/i.exec(s);
  if (!m) return undefined;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
/** Linear mix of two #rrggbb colours (falls back to `b`). */
const mixColor = (a: string, b: string, p: number) => {
  const x = hex(a);
  const y = hex(b);
  if (!x || !y) return p < 0.5 ? a : b;
  const q = (i: number) => Math.round(x[i] + (y[i] - x[i]) * p);
  return `#${[q(0), q(1), q(2)].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
};

/** Ink for text / icons on a solid fill: white or the theme's dark background, whichever contrasts more (a light
 *  brand colour such as a teal gets dark ink; a deep purple gets white). */
const lum = (s: string) => {
  const c = hex(s);
  if (!c) return 0.2;
  const ch = c.map((v) => {
    const x = v / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
};
const contrast = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
export const inkOn = (theme: Theme, fill: string) => (contrast('#ffffff', fill) >= contrast(theme.colors.bg, fill) ? '#ffffff' : theme.colors.bg);

const card = (theme: Theme, extra: React.CSSProperties = {}): React.CSSProperties => ({
  position: 'absolute',
  inset: 0,
  background: `linear-gradient(180deg, ${theme.colors.raised} 0%, ${theme.colors.card} 100%)`,
  border: `2px solid ${theme.colors.border}`,
  borderRadius: theme.radius.card + 4,
  boxShadow: '0 34px 90px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06)',
  boxSizing: 'border-box',
  overflow: 'hidden',
  ...extra,
});

/** Zone colour of a gauge value, blended across each boundary (±3 % of the range) so the recolour is a short fade. */
const gaugeColor = (theme: Theme, block: Extract<BlockV3, {type: 'gauge'}>, v: number) => {
  const zones = block.zones?.length ? [...block.zones].sort((a, b) => a.to - b.to) : undefined;
  if (!zones) return toneStroke(theme, undefined);
  const {min, max} = gaugeRange(block);
  const band = (max - min) * 0.03;
  const here = toneStroke(theme, zoneTone(zones, v));
  for (const z of zones.slice(0, -1)) {
    if (Math.abs(v - z.to) < band) {
      const lo = toneStroke(theme, zoneTone(zones, z.to - band));
      const hi = toneStroke(theme, zoneTone(zones, z.to + band));
      return mixColor(lo, hi, EASE.inOutSine((v - (z.to - band)) / (2 * band)));
    }
  }
  return here;
};

// ------------------------------------------------------------------------------------------------ gauge
export const Gauge: React.FC<P<'gauge'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, ink, surface} = useEngine();
  const c = theme.colors;
  const g = geomGauge(block, w);
  const next = reader(g.texts);
  const label = block.label ? next() : undefined;
  const read = next();
  const cap = block.caption ? next() : undefined;
  const st = gaugeState(block, t);
  const col = gaugeColor(theme, block, st.readout);
  const keys = [...block.keys].sort((a, b) => a.at - b.at);
  const first = keys.length ? keys[0].at : Infinity;
  const draw = EASE.inOutCubic(lin(t, appear - LEAD.block, appear - LEAD.block + DUR.slower));
  const showRead = st.started ? lin(t, first, first + DUR.micro) : 0;
  // the readout lands with the counter's spring once each move has (nearly) settled
  const cur = st.active >= 0 ? keys[st.active] : undefined;
  const land = cur ? spc(t, cur.at + (cur.dur ?? DUR.slower) * 0.7, fps, SPRING.land) : 1;
  const track = surface === 'light' ? alpha(ink.text, 0.1) : alpha('#ffffff', 0.08);
  const dial = g.style === 'dial';
  const ang = g.start + g.sweep * st.frac;
  const zones = block.zones?.length ? [...block.zones].sort((a, b) => a.to - b.to) : [];
  const {min, max} = gaugeRange(block);
  const zr = g.R + g.sw * 0.95;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={{position: 'absolute', left: g.cx - g.R * 1.2, top: g.cy - g.R * 1.2, width: g.R * 2.4, height: g.R * 2.4, borderRadius: '50%', background: `radial-gradient(circle, ${alpha(col.startsWith('#') ? col : c.brand, 0.2 * draw)} 0%, rgba(0,0,0,0) 66%)`}} />
      {label ? <Txt s={label} color={ink.text2} /> : null}
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible'}}>
        <path d={arcPath(g.cx, g.cy, g.R, g.start, g.sweep)} fill="none" stroke={track} strokeWidth={g.sw} strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw} />
        {zones.map((z, i) => {
          const lo = i === 0 ? min : zones[i - 1].to;
          const hi = i === zones.length - 1 ? max : z.to;
          const a0 = g.start + (g.sweep * (Math.max(min, lo) - min)) / (max - min);
          const a1 = g.start + (g.sweep * (Math.min(max, hi) - min)) / (max - min);
          const gapDeg = 1.6;
          return <path key={i} d={arcPath(g.cx, g.cy, zr, a0 + (i ? gapDeg : 0), Math.max(0, a1 - a0 - (i ? gapDeg : 0)))} fill="none" stroke={toneStroke(theme, z.tone)} strokeOpacity={0.55 * draw} strokeWidth={Math.max(5, g.sw * 0.22)} strokeLinecap="butt" />;
        })}
        {g.ticks.map((tk, i) => (
          <line key={i} x1={tk.p0.x} y1={tk.p0.y} x2={tk.p1.x} y2={tk.p1.y} stroke={tk.major ? alpha(ink.text, 0.42) : alpha(ink.text, 0.2)} strokeWidth={tk.major ? 5 : 3} strokeLinecap="round" opacity={lin(t, appear + (i / g.ticks.length) * 0.4, appear + (i / g.ticks.length) * 0.4 + 0.2)} />
        ))}
        {st.frac > 0.001 ? (
          <path d={arcPath(g.cx, g.cy, g.R, g.start, g.sweep * st.frac)} fill="none" stroke={col} strokeWidth={g.sw} strokeLinecap="round" style={{filter: `drop-shadow(0 0 ${18}px ${alpha(col, 0.65)})`}} />
        ) : null}
        {!dial && st.frac > 0.001 ? (() => {
          const p = polar(g.cx, g.cy, g.R, ang);
          return <circle cx={p.x} cy={p.y} r={g.sw * 0.34} fill="#ffffff" />;
        })() : null}
        {dial ? (
          <g transform={`rotate(${ang.toFixed(3)} ${g.cx} ${g.cy})`} opacity={draw} style={{filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.45))'}}>
            <path d={`M ${g.cx - g.hub * 0.55} ${g.cy} L ${g.cx} ${g.cy - g.needleLen} L ${g.cx + g.hub * 0.55} ${g.cy} Z`} fill={surface === 'light' ? ink.text : '#ffffff'} />
            <circle cx={g.cx} cy={g.cy} r={g.hub} fill={c.raised} stroke={col} strokeWidth={5} />
          </g>
        ) : null}
      </svg>
      <Txt
        s={read}
        color={block.zones?.length ? (surface === 'light' ? ink.text : col) : ink.text}
        style={{opacity: showRead, fontVariantNumeric: 'tabular-nums', transform: `scale(${mix(1.05, 1, land)})`, textShadow: surface === 'light' ? undefined : `0 0 46px ${alpha(col, 0.45)}`}}
      >
        {gaugeText(block, st.readout)}
      </Txt>
      {cap ? <Txt s={cap} color={ink.muted} style={{opacity: lin(t, appear + 0.3, appear + 0.6)}} /> : null}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ countdown
export const Countdown: React.FC<P<'countdown'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, ink, surface} = useEngine();
  const g = geomCountdown(block, w);
  const next = reader(g.texts);
  const label = block.label ? next() : undefined;
  const read = next();
  const st = countdownState(block, t, appear);
  const col = toneStroke(theme, st.tone);
  const draw = EASE.inOutCubic(lin(t, appear - LEAD.block, appear - LEAD.block + DUR.slow));
  const track = surface === 'light' ? alpha(ink.text, 0.1) : alpha('#ffffff', 0.08);
  const end = appear + Math.max(0.05, (block.countEnd ?? appear + Math.abs(block.from - (block.to ?? 0))) - appear);
  const done = spc(t, end, fps, SPRING.badge);
  const pulse = st.done ? mix(1.06, 1, done) : 1;
  // one tick per twelfth of the ring; the ones the count has passed dim
  const ticks = Array.from({length: 12}, (_, i) => i);
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {label ? <Txt s={label} color={ink.text2} /> : null}
      <div style={{position: 'absolute', left: g.cx - g.R * 1.2, top: g.cy - g.R * 1.2, width: g.R * 2.4, height: g.R * 2.4, borderRadius: '50%', background: `radial-gradient(circle, ${alpha(col, 0.18 * draw)} 0%, rgba(0,0,0,0) 66%)`}} />
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible', transform: `scale(${pulse})`, transformOrigin: `${g.cx}px ${g.cy}px`}}>
        <circle cx={g.cx} cy={g.cy} r={g.R} fill="none" stroke={track} strokeWidth={g.sw} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw} />
        {ticks.map((i) => {
          const a = (360 * i) / 12;
          const p0 = polar(g.cx, g.cy, g.R + g.sw * 1.05, a);
          const p1 = polar(g.cx, g.cy, g.R + g.sw * 1.05 + 16, a);
          const passed = i / 12 > st.left - 1e-6 && i !== 0;
          return <line key={i} x1={p0.x} y1={p0.y} x2={p1.x} y2={p1.y} stroke={passed ? alpha(ink.text, 0.14) : alpha(ink.text, 0.45)} strokeWidth={4} strokeLinecap="round" opacity={draw} />;
        })}
        {st.left > 0.0005 && t >= appear - 0.05 ? (
          <path d={arcPath(g.cx, g.cy, g.R, 0, 360 * st.left * draw)} fill="none" stroke={col} strokeWidth={g.sw} strokeLinecap="round" style={{filter: `drop-shadow(0 0 16px ${alpha(col, 0.6)})`}} />
        ) : null}
        {st.left > 0.0005 && st.left < 0.9995 ? (() => {
          const p = polar(g.cx, g.cy, g.R, 360 * st.left);
          return <circle cx={p.x} cy={p.y} r={g.sw * 0.32} fill="#ffffff" />;
        })() : null}
      </svg>
      <Txt s={read} color={st.tone === 'brand' ? ink.text : toneColor(theme, st.tone)} style={{fontVariantNumeric: 'tabular-nums', opacity: lin(t, appear - 0.05, appear + 0.06), textShadow: surface === 'light' ? undefined : `0 0 40px ${alpha(col, 0.4)}`}}>
        {countdownText(block, st.value)}
      </Txt>
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ chat-thread
const TypingDots: React.FC<{t: number; color: string; size: number}> = ({t, color, size}) => (
  <>
    {[0, 1, 2].map((k) => {
      const ph = (t * 2.4 - k * 0.18) % 1;
      const bump = ph < 0.4 ? Math.sin((ph / 0.4) * Math.PI) : 0;
      return <div key={k} style={{width: size, height: size, borderRadius: size, background: color, opacity: 0.45 + 0.55 * bump, transform: `translateY(${-bump * size * 0.6}px)`}} />;
    })}
  </>
);

export const ChatThread: React.FC<P<'chat-thread'>> = ({block, w, h}) => {
  const {theme, t, fps} = useEngine();
  const c = theme.colors;
  const g = geomChat(block, w);
  const R = 34;
  const titleS = block.title ? g.texts[0] : undefined;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={card(theme)} />
      {titleS ? <Txt s={titleS} color={c.text} /> : null}
      {g.header ? <div style={{position: 'absolute', left: 34, right: 34, top: g.header.y, height: 2, background: c.border}} /> : null}
      {block.messages.map((m, i) => {
        const M = g.msgs[i];
        const typing = chatTypingDur(m);
        const t0 = m.at - typing;
        if (t < t0 - LEAD.row) return null;
        const tp = typing > 0 ? spc(t, t0 - LEAD.row, fps, SPRING.pop) : 0;
        const tOut = 1 - lin(t, m.at - 0.06, m.at + 0.06);
        const bp = spc(t, m.at - LEAD.row, fps, SPRING.pop);
        const left = M.left;
        const bub = M.bubble;
        const ink = left ? c.text : inkOn(theme, c.brand);
        const bg = left ? c.raised : `linear-gradient(135deg, ${c.brand}, ${c.brandHover})`;
        const corner = left ? `${R}px ${R}px ${R}px 10px` : `${R}px ${R}px 10px ${R}px`;
        const show = Math.min(1, bp * 1.3);
        return (
          <React.Fragment key={i}>
            {typing > 0 && tOut > 0 && tp > 0 ? (
              <div
                style={{
                  position: 'absolute',
                  left: M.typing.x,
                  top: M.typing.y,
                  width: M.typing.w,
                  height: M.typing.h,
                  borderRadius: corner,
                  background: left ? c.raised : alpha(c.brand, 0.85),
                  border: left ? `2px solid ${c.border}` : 'none',
                  boxSizing: 'border-box',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 12,
                  opacity: Math.min(1, tp * 1.4) * tOut,
                  transform: `scale(${mix(0.6, 1, tp)})`,
                  transformOrigin: left ? '0% 100%' : '100% 100%',
                }}
              >
                <TypingDots t={t} color={left ? c.text2 : inkOn(theme, c.brand)} size={16} />
              </div>
            ) : null}
            {M.name ? <Txt s={M.name} color={c.text2} style={{opacity: Math.max(Math.min(1, tp * 1.4), show)}} /> : null}
            {M.avatar ? (
              <div
                style={{
                  position: 'absolute',
                  left: M.avatar.x,
                  top: M.avatar.y,
                  width: M.avatar.s,
                  height: M.avatar.s,
                  borderRadius: '50%',
                  background: left ? `linear-gradient(135deg, ${c.surface}, ${c.raised})` : `linear-gradient(135deg, ${c.brandHover}, ${c.brand})`,
                  border: `2px solid ${left ? c.borderStrong : alpha(c.brandText, 0.5)}`,
                  boxSizing: 'border-box',
                  opacity: Math.max(Math.min(1, tp * 1.4), show),
                }}
              />
            ) : null}
            {M.avSpec ? <Txt s={M.avSpec} color={left ? c.text2 : inkOn(theme, c.brand)} style={{opacity: Math.max(Math.min(1, tp * 1.4), show)}} /> : null}
            {t >= m.at - LEAD.row ? (
              <div style={{position: 'absolute', left: 0, top: 0, width: w, height: h, opacity: show}}>
                <div
                  style={{
                    position: 'absolute',
                    left: bub.x,
                    top: bub.y,
                    width: bub.w,
                    height: bub.h,
                    borderRadius: corner,
                    background: bg,
                    border: left ? `2px solid ${c.border}` : 'none',
                    boxSizing: 'border-box',
                    boxShadow: left ? '0 10px 26px rgba(0,0,0,0.25)' : `0 12px 32px ${alpha(c.brand, 0.4)}`,
                    transform: `scale(${mix(0.82, 1, bp)})`,
                    transformOrigin: left ? '0% 100%' : '100% 100%',
                  }}
                />
                {M.lines.map((s, li) => (
                  <Txt key={li} s={s} color={ink} style={{transform: `scale(${mix(0.82, 1, bp)})`, transformOrigin: left ? `${bub.x - s.x}px ${bub.y + bub.h - s.y}px` : `${bub.x + bub.w - s.x}px ${bub.y + bub.h - s.y}px`}} />
                ))}
                {M.time ? <Txt s={M.time} color={c.muted} style={{opacity: lin(t, m.at + 0.15, m.at + 0.4)}} /> : null}
              </div>
            ) : null}
          </React.Fragment>
        );
      })}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ notification
export const Notification: React.FC<P<'notification'>> = ({block, w, h, boxY, scale}) => {
  const {theme, t, fps} = useEngine();
  const c = theme.colors;
  const g = geomNotification(block, w);
  const heights = g.banners.map((b) => b.h);
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {block.items.map((it, i) => {
        if (t < it.at - 0.3) return null;
        const bn = g.banners[i];
        const p = spc(t, it.at - LEAD.drop, fps, SPRING.drop);
        const y = noteShift(block, heights, i, t);
        // slides down from just above the frame's top edge (design px: the block's own top is boxY / scale)
        const fromTop = -(boxY / Math.max(1e-6, scale) + y + bn.h + 60);
        const dy = mix(fromTop, 0, p);
        const older = block.items.some((o, j) => j !== i && (o.at > it.at || (o.at === it.at && j > i)) && t >= o.at);
        return (
          <div key={i} style={{position: 'absolute', left: 0, top: y, width: w, height: bn.h, transform: `translateY(${dy}px)`, opacity: Math.min(1, p * 2) * (older ? 0.9 : 1)}}>
            <div
              style={{
                position: 'absolute',
                inset: 0,
                borderRadius: NOTE.radius,
                background: `linear-gradient(180deg, ${alpha(c.raised, 0.98)}, ${alpha(c.card, 0.98)})`,
                border: `2px solid ${c.borderStrong}`,
                boxShadow: '0 26px 60px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.08)',
                boxSizing: 'border-box',
              }}
            />
            <div
              style={{
                position: 'absolute',
                left: bn.tile.x,
                top: bn.tile.y,
                width: bn.tile.s,
                height: bn.tile.s,
                borderRadius: bn.tile.s * 0.26,
                background: `linear-gradient(135deg, ${c.brandHover}, ${c.brand})`,
                boxShadow: `0 8px 22px ${alpha(c.brand, 0.45)}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: inkOn(theme, c.brand),
                fontWeight: 800,
                fontSize: bn.tile.s * 0.46,
              }}
            >
              {it.icon ? <Icon name={it.icon} size={bn.tile.s * 0.52} color={inkOn(theme, c.brand)} stroke={2.4} /> : bn.letter}
            </div>
            {bn.specs.map((s, k) => (
              <Txt key={k} s={s} color={s.role === 'title' ? c.text : s.role === 'body' ? c.text2 : c.muted} />
            ))}
          </div>
        );
      })}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ term-reveal
export const TermReveal: React.FC<P<'term-reveal'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, motion: m, ink, surface} = useEngine();
  const c = theme.colors;
  const g = geomTerm(block, w);
  const termAt = termAtOf(block, appear);
  const subAt = subAtOf(block, appear);
  const kp = spc(t, appear - LEAD.word, fps, m.word.spring);
  const rule = easeInOut(t, appear + 0.08, appear + 0.08 + DUR.medium);
  const slam = spc(t, termAt - LEAD.drop, fps, SPRING.stamp);
  const on = lin(t, termAt - LEAD.drop, termAt - LEAD.drop + 0.06);
  const ghost = lin(t, termAt, termAt + 0.38);
  const bar = EASE.outCubic(lin(t, termAt + 0.12, termAt + 0.12 + DUR.medium));
  const sp = spc(t, subAt - LEAD.word, fps, m.word.spring);
  const col = block.tone ? inkTone(ink, theme, block.tone, ink.text) : ink.text;
  const top = g.termLines[0].y;
  const bottom = g.termLines[g.termLines.length - 1].y + g.lh;
  const origin = `${w / 2}px ${(top + bottom) / 2}px`;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {g.kicker ? (
        <div style={{position: 'absolute', left: 0, top: 0, width: w, height: g.kicker.h, opacity: Math.min(1, kp * 1.3), transform: `translateY(${(1 - kp) * 22}px)`}}>
          {g.kicker.rule > 0
            ? [-1, 1].map((sd) => {
                const K = g.kicker!;
                const len = K.rule * rule;
                // rules grow outward from the kicker's own edges
                const x = sd < 0 ? (w - K.kw) / 2 - 28 - len : (w + K.kw) / 2 + 28;
                return <div key={sd} style={{position: 'absolute', left: x, top: K.h / 2 - 2, width: len, height: 4, borderRadius: 2, background: surface === 'light' ? c.brand : alpha(c.brandHover, 0.85)}} />;
              })
            : null}
          <Txt s={{...g.kicker, y: 0}} color={ink.text2} />
        </div>
      ) : null}
      {t >= termAt - LEAD.drop - 0.02 ? (
        <>
          {ghost > 0 && ghost < 1 ? (
            <div style={{position: 'absolute', left: 0, top: 0, width: w, height: h, transform: `scale(${mix(1, 1.16, EASE.outCubic(ghost))})`, transformOrigin: origin, opacity: 0.32 * (1 - ghost)}}>
              {g.termLines.map((s, i) => (
                <Txt key={i} s={s} color="transparent" style={{WebkitTextStroke: `3px ${alpha(c.brandHover, 0.9)}`}} />
              ))}
            </div>
          ) : null}
          <div style={{position: 'absolute', left: 0, top: 0, width: w, height: h, transform: `scale(${mix(TERM.slam, 1, slam)})`, transformOrigin: origin, opacity: on}}>
            {g.termLines.map((s, i) => (
              <Txt key={i} s={s} color={col} style={{textShadow: surface === 'light' ? undefined : `0 0 60px ${alpha(c.brand, 0.55)}, 0 8px 30px rgba(0,0,0,0.4)`}} />
            ))}
          </div>
          <div style={{position: 'absolute', left: g.bar.x + (g.bar.w * (1 - bar)) / 2, top: g.bar.y, width: g.bar.w * bar, height: g.bar.h, borderRadius: g.bar.h / 2, background: `linear-gradient(90deg, ${c.brand}, ${c.brandHover}, ${c.brandText})`, boxShadow: `0 0 24px ${alpha(c.brand, 0.6)}`}} />
        </>
      ) : null}
      {g.subs.map((s, i) => (
        <Txt key={i} s={s} color={ink.text2} style={{opacity: Math.min(1, sp * 1.3), transform: `translateY(${(1 - sp) * 20}px)`}} />
      ))}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ verdict
export const Verdict: React.FC<P<'verdict'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, ink} = useEngine();
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const g = geomVerdict(block, w);
  const tone = verdictTone(block);
  const col = toneColor(theme, tone === 'brand' ? undefined : tone, theme.colors.brandHover);
  const mark = verdictMark(block);
  const at = appear;
  const slam = spc(t, at - LEAD.drop, fps, SPRING.stamp);
  const on = lin(t, at - LEAD.drop, at - LEAD.drop + 0.05);
  const ring = lin(t, at, at + 0.42);
  const subP = lin(t, at + 0.15, at + 0.15 + DUR.base);
  const S = g.stamp;
  const cx = S.x + S.w / 2;
  const cy = S.y + S.h / 2;
  const R = VERDICT.radius;
  const k = g.fs / VERDICT.fs;
  const M = g.mark;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <svg width={0} height={0} style={{position: 'absolute'}} aria-hidden>
        <defs>
          {/* worn-ink texture: a fixed noise field knocks small specks out of the stamp (seeded, deterministic) */}
          <filter id={`vd-${uid}`} x="-5%" y="-10%" width="110%" height="120%">
            <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves={2} seed={11} result="n" />
            <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 16 -11.4" result="holes" />
            <feComposite in="SourceGraphic" in2="holes" operator="out" />
          </filter>
        </defs>
      </svg>
      {ring > 0 && ring < 1 ? (
        <div
          style={{
            position: 'absolute',
            left: S.x,
            top: S.y,
            width: S.w,
            height: S.h,
            borderRadius: R,
            border: `${6 * k + 2}px solid ${alpha(col, 0.55 * (1 - ring))}`,
            boxSizing: 'border-box',
            transform: `rotate(${g.rot}deg) scale(${mix(1, 1.22, EASE.outCubic(ring))})`,
            transformOrigin: `${S.w / 2}px ${S.h / 2}px`,
          }}
        />
      ) : null}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: w,
          height: S.y + S.h + VERDICT.margin * 4,
          opacity: on,
          transform: `rotate(${g.rot}deg) scale(${mix(VERDICT.slam, 1, slam)})`,
          transformOrigin: `${cx}px ${cy}px`,
        }}
      >
        <div style={{position: 'absolute', inset: 0, filter: `url(#vd-${uid}) drop-shadow(0 10px 26px rgba(0,0,0,0.35))`}}>
          <div style={{position: 'absolute', left: S.x, top: S.y, width: S.w, height: S.h, borderRadius: R, border: `${VERDICT.border * k + 2}px solid ${col}`, background: alpha(col, 0.12), boxSizing: 'border-box'}} />
          <div style={{position: 'absolute', left: S.x + VERDICT.inset * k, top: S.y + VERDICT.inset * k, width: S.w - 2 * VERDICT.inset * k, height: S.h - 2 * VERDICT.inset * k, borderRadius: R * 0.6, border: `${Math.max(2, 3 * k)}px solid ${alpha(col, 0.85)}`, boxSizing: 'border-box'}} />
          {M ? (
            <svg width={M.s} height={M.s} viewBox="0 0 24 24" style={{position: 'absolute', left: M.x, top: M.y}}>
              <circle cx="12" cy="12" r="10.6" fill="none" stroke={col} strokeWidth={2.2} />
              {mark === 'cross' ? <path d="M8 8l8 8M16 8l-8 8" fill="none" stroke={col} strokeWidth={2.8} strokeLinecap="round" /> : <path d="M7 12.4l3.4 3.4L17.2 9" fill="none" stroke={col} strokeWidth={2.8} strokeLinecap="round" strokeLinejoin="round" />}
            </svg>
          ) : null}
          <Txt s={g.text} color={col} />
        </div>
      </div>
      {g.sub ? <Txt s={g.sub} color={ink.text2} style={{opacity: subP, transform: `translateY(${(1 - subP) * 14}px)`}} /> : null}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ comment-cta
export const CommentCta: React.FC<P<'comment-cta'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, motion: m, ink} = useEngine();
  const c = theme.colors;
  const g = geomComment(block, w);
  const T = commentTimes(block, appear);
  const n = typedChars(block, t, appear);
  const typed = [...block.keyword].slice(0, n).join('');
  const pp = spc(t, appear - LEAD.word, fps, m.word.spring);
  const box = spc(t, appear + 0.1 - LEAD.card, fps, m.card.spring);
  const focus = lin(t, T.start - 0.15, T.start + 0.1);
  const typing = t >= T.start && t < T.end;
  const caretOn = typing || (t >= T.start - 0.15 && (T.send === undefined || t < T.send) && Math.floor(t * ACCENT.caretHz) % 2 === 0);
  const sent = T.send !== undefined ? spc(t, T.send - LEAD.button, fps, SPRING.badge) : 0;
  const ring = T.send !== undefined ? lin(t, T.send, T.send + ACCENT.ring) : 0;
  const subAt = Math.max(appear + 0.4, T.end + 0.1);
  const sp = spc(t, subAt - LEAD.word, fps, m.word.spring);
  const B = g.box;
  const kw = g.keyword;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {g.prompt ? <Txt s={g.prompt} color={ink.text} style={{opacity: Math.min(1, pp * 1.3), transform: `translateY(${(1 - pp) * 26}px)`}} /> : null}
      <div style={{position: 'absolute', left: 0, top: 0, width: w, height: h, opacity: Math.min(1, box * 1.3), transform: `translateY(${(1 - box) * 30}px)`}}>
        <div
          style={{
            position: 'absolute',
            left: B.x,
            top: B.y,
            width: B.w,
            height: B.h,
            borderRadius: B.h / 2,
            background: `linear-gradient(180deg, ${c.raised}, ${c.card})`,
            border: `3px solid ${c.borderStrong}`,
            boxShadow: `0 24px 60px rgba(0,0,0,0.45), 0 0 ${40 * focus}px ${alpha(c.brand, 0.35 * focus)}`,
            boxSizing: 'border-box',
          }}
        />
        {focus > 0 ? <div style={{position: 'absolute', left: B.x, top: B.y, width: B.w, height: B.h, borderRadius: B.h / 2, border: `3px solid ${c.brandHover}`, boxSizing: 'border-box', opacity: focus}} /> : null}
        <div style={{position: 'absolute', left: g.avatar.x, top: g.avatar.y, width: g.avatar.s, height: g.avatar.s, borderRadius: '50%', background: `linear-gradient(135deg, ${c.surface}, ${c.raised})`, border: `2px solid ${c.borderStrong}`, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <Icon name="users" size={g.avatar.s * 0.5} color={c.text2} stroke={2} />
        </div>
        <Txt s={kw} color={c.text}>
          {typed}
          <span style={{display: 'inline-block', width: Math.max(4, kw.fs * 0.08), height: kw.fs * 0.95, marginLeft: 6, verticalAlign: 'middle', background: c.brandHover, opacity: caretOn ? 0.95 : 0, borderRadius: 2}} />
        </Txt>
        <div style={{position: 'absolute', left: g.send.x, top: g.send.y, width: g.send.s, height: g.send.s, transform: `scale(${1 + 0.12 * Math.sin(Math.PI * Math.min(1, sent))})`}}>
          {ring > 0 && ring < 1 ? <div style={{position: 'absolute', inset: -26 * ring, borderRadius: '50%', border: `4px solid ${alpha(c.brandHover, 0.7 * (1 - ring))}`}} /> : null}
          <div style={{position: 'absolute', inset: 0, borderRadius: '50%', background: sent > 0.02 ? `linear-gradient(135deg, ${c.brandHover}, ${c.brand})` : c.surface, border: `2px solid ${sent > 0.02 ? 'transparent' : c.borderStrong}`, boxSizing: 'border-box', boxShadow: sent > 0.02 ? `0 12px 30px ${alpha(c.brand, 0.55)}` : 'none', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <Icon name={sent > 0.5 ? 'check' : 'arrowUp'} size={g.send.s * 0.46} color={sent > 0.02 ? inkOn(theme, c.brand) : c.text2} stroke={2.8} />
          </div>
        </div>
      </div>
      {g.subs.map((s, i) => (
        <Txt key={i} s={s} color={ink.text2} style={{opacity: Math.min(1, sp * 1.3), transform: `translateY(${(1 - sp) * 18}px)`}} />
      ))}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ poll
export const Poll: React.FC<P<'poll'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, motion: m} = useEngine();
  const c = theme.colors;
  const g = geomPoll(block, w);
  const qp = spc(t, appear - LEAD.word, fps, m.word.spring);
  const pick = block.pick;
  const pickAt = block.pickAt;
  const fill = pick !== undefined && pickAt !== undefined ? easeInOut(t, pickAt, pickAt + POLL.fill) : 0;
  const bump = pick !== undefined && pickAt !== undefined ? spc(t, pickAt, fps, SPRING.badge) : 0;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={card(theme)} />
      {g.question.map((s, i) => (
        <Txt key={i} s={s} color={c.text} style={{opacity: Math.min(1, qp * 1.3), transform: `translateY(${(1 - qp) * 20}px)`}} />
      ))}
      {block.options.map((o, i) => {
        const O = g.options[i];
        const p = spc(t, o.at - LEAD.row, fps, m.row.spring);
        const chosen = pick === i;
        const dim = pick !== undefined && !chosen ? 1 - 0.45 * fill : 1;
        const r = O.rect;
        const textOn = chosen && fill * r.w > O.text.x - r.x + 20;
        const onFill = inkOn(theme, c.brand);
        return (
          <div key={i} style={{position: 'absolute', left: 0, top: 0, width: w, height: h, opacity: Math.min(1, p * 1.3) * dim, transform: `translateX(${(1 - p) * 48}px)`}}>
            <div style={{position: 'absolute', left: r.x, top: r.y, width: r.w, height: r.h, transform: chosen ? `scale(${1 + 0.025 * Math.sin(Math.PI * Math.min(1, bump))})` : undefined}}>
              <div style={{position: 'absolute', inset: 0, borderRadius: r.h / 2, background: c.surface, border: `2px solid ${chosen && fill > 0 ? c.brandHover : c.borderStrong}`, boxSizing: 'border-box', overflow: 'hidden'}}>
                {chosen && fill > 0 ? <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(fill * 100).toFixed(2)}%`, background: `linear-gradient(90deg, ${c.brand}, ${c.brandHover})`}} /> : null}
              </div>
            </div>
            <div style={{position: 'absolute', left: O.radio.x, top: O.radio.y, width: O.radio.s, height: O.radio.s, borderRadius: '50%', border: `4px solid ${chosen && fill > 0.3 ? onFill : c.text2}`, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
              {chosen && fill > 0.3 ? <div style={{width: O.radio.s * 0.45, height: O.radio.s * 0.45, borderRadius: '50%', background: onFill, transform: `scale(${Math.min(1, (fill - 0.3) / 0.4)})`}} /> : null}
            </div>
            <Txt s={O.text} color={textOn ? onFill : c.text} />
          </div>
        );
      })}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ next-episode
export const NextEpisode: React.FC<P<'next-episode'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, motion: m} = useEngine();
  const c = theme.colors;
  const g = geomNext(block, w);
  const next = reader(g.texts);
  const labelS = next();
  const pill = spc(t, appear + 0.15 - LEAD.button, fps, SPRING.badge);
  const play = spc(t, appear + 0.3 - LEAD.button, fps, SPRING.pop);
  const pulse = 1 + 0.03 * Math.sin(Math.max(0, t - appear - 0.8) * 4.2) * Math.min(1, Math.max(0, t - appear - 0.8) * 2);
  const fill = easeInOut(t, appear + 0.5, appear + 0.5 + NEXT.fill);
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={card(theme)}>
        <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 8, background: `linear-gradient(90deg, ${c.brand}, ${c.brandHover}, ${c.brandText})`}} />
        <div style={{position: 'absolute', right: -w * 0.15, top: -h * 0.5, width: w * 0.8, height: h * 1.2, background: `radial-gradient(ellipse, ${alpha(c.brand, 0.22)} 0%, rgba(0,0,0,0) 70%)`}} />
      </div>
      <div style={{position: 'absolute', left: 0, top: 0, opacity: Math.min(1, pill * 1.4), transform: `translateY(${(1 - pill) * 12}px)`}}>
        <div style={{position: 'absolute', left: g.pill.x, top: g.pill.y, width: g.pill.w, height: g.pill.h, borderRadius: 999, background: `linear-gradient(135deg, ${c.brandHover}, ${c.brand})`, boxShadow: `0 10px 30px ${alpha(c.brand, 0.5)}`}} />
        <Txt s={labelS} color={inkOn(theme, c.brand)} />
      </div>
      <div style={{position: 'absolute', left: g.play.x, top: g.play.y, width: g.play.s, height: g.play.s, transform: `scale(${play * pulse})`}}>
        <div style={{position: 'absolute', inset: 0, borderRadius: '50%', background: alpha(c.brand, 0.22), border: `3px solid ${alpha(c.brandText, 0.6)}`, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <Icon name="play" size={g.play.s * 0.44} color={c.brandText} stroke={2.6} />
        </div>
      </div>
      {g.title.map((s, i) => {
        const p = spc(t, appear + 0.25 + i * m.word.stagger * 2 - LEAD.word, fps, m.word.spring);
        return <Txt key={i} s={s} color={c.text} style={{opacity: Math.min(1, p * 1.3), transform: `translateY(${(1 - p) * 24}px)`}} />;
      })}
      {g.subs.map((s, i) => (
        <Txt key={i} s={s} color={c.text2} style={{opacity: lin(t, appear + 0.45, appear + 0.75)}} />
      ))}
      <div style={{position: 'absolute', left: g.bar.x, top: g.bar.y, width: g.bar.w, height: g.bar.h, borderRadius: g.bar.h / 2, background: alpha('#ffffff', 0.1), overflow: 'hidden'}}>
        <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(fill * 100).toFixed(2)}%`, borderRadius: g.bar.h / 2, background: `linear-gradient(90deg, ${c.brand}, ${c.brandHover})`, boxShadow: `0 0 16px ${alpha(c.brand, 0.6)}`}} />
      </div>
    </div>
  );
};

/** Dispatch for the v3 explainer blocks. */
export const BlockV3View: React.FC<{block: BlockV3; w: number; h: number; appear: number; boxY: number; scale: number; sceneStart?: number; sceneEnd?: number}> = (p) => {
  const b = p.block;
  switch (b.type) {
    case 'gauge':
      return <Gauge {...p} block={b} />;
    case 'countdown':
      return <Countdown {...p} block={b} />;
    case 'chat-thread':
      return <ChatThread {...p} block={b} />;
    case 'notification':
      return <Notification {...p} block={b} />;
    case 'term-reveal':
      return <TermReveal {...p} block={b} />;
    case 'verdict':
      return <Verdict {...p} block={b} />;
    case 'comment-cta':
      return <CommentCta {...p} block={b} />;
    case 'poll':
      return <Poll {...p} block={b} />;
    case 'next-episode':
      return <NextEpisode {...p} block={b} />;
  }
};
