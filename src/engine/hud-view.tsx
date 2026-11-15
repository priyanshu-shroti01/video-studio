import React from 'react';
import {lin, mix} from './anim';
import {mixColor} from './captions';
import {
  HUD,
  HudBox,
  HudChip,
  HudPlan,
  HudSegment,
  HudTrack,
  headerParts,
  progressPad,
  stakesValueText,
  STAKES_SEP,
} from './hud';
import {backdropWeights} from './look';
import {EASE} from './motion/easings';
import {springAt} from './motion/entrances';
import {toneColor} from './theme';
import {HudElement, Scene, Theme, Tone} from './types';
import {alpha, useEngine} from './ui';

/**
 * v3 HUD renderer: draws the plan from hud.ts outside the scene layer (scene cameras and transitions never move it),
 * above the scenes and below the brand bar, watermark and captions. Every motion is a pure function of t.
 */

const ENTER = {damping: 18, mass: 0.7};
const POP = {damping: 13, mass: 0.55};

/** Start of the visible run the segment at t belongs to (so a change right after a show doesn't cut the entrance). */
const runStart = (tr: HudTrack, i: number) => {
  let j = i;
  while (j > 0 && tr.segments[j - 1].visible) j--;
  return tr.segments[j].from;
};
const segIndexAt = (tr: HudTrack, t: number) => {
  let i = 0;
  while (i + 1 < tr.segments.length && tr.segments[i + 1].from <= t) i++;
  return i;
};

type Vis = {o: number; dy: number};
const visibility = (tr: HudTrack, i: number, t: number, fps: number, k: number): Vis => {
  const seg = tr.segments[i];
  const prev = i > 0 ? tr.segments[i - 1] : undefined;
  if (seg.visible) {
    const p = springAt(t, runStart(tr, i), fps, ENTER);
    return {o: Math.min(1, p * 1.4), dy: (1 - p) * -16 * k};
  }
  if (prev?.visible) {
    const q = 1 - EASE.outCubic(lin(t, seg.from, seg.from + HUD.fadeOut));
    return {o: q, dy: (1 - q) * -10 * k};
  }
  return {o: 0, dy: 0};
};

/** Light-surface blend of the HUD palette (scene backdrop 'light' under it). */
type Pal = {text: string; text2: string; muted: string; accent: string; card: string; border: string; track: string; shadow: string};
const palette = (theme: Theme, lw: number): Pal => {
  const c = theme.colors;
  const L = c.light;
  return {
    text: mixColor(c.text, L.text, lw),
    text2: mixColor(c.text2, L.text2, lw),
    muted: mixColor(c.muted, L.muted, lw),
    accent: mixColor(c.brandText, c.brand, lw),
    card: lw > 0.5 ? alpha(L.card, 0.92) : alpha(c.card, 0.82),
    border: lw > 0.5 ? L.border : c.borderStrong,
    track: lw > 0.5 ? alpha(L.text, 0.1) : 'rgba(255,255,255,0.13)',
    shadow: lw > 0.5 ? '0 6px 22px rgba(21,17,28,0.10)' : '0 8px 26px rgba(0,0,0,0.38)',
  };
};
const textShadow = (lw: number) => (lw > 0.5 ? 'none' : '0 2px 14px rgba(0,0,0,0.55)');
const tone = (theme: Theme, t: Tone | undefined, fallback: string) => (t ? toneColor(theme, t, fallback) : fallback);

const Header: React.FC<{el: Extract<HudElement, {kind: 'header'}>; box: Extract<HudBox, {kind: 'header'}>; tr: HudTrack; i: number; pal: Pal; lw: number}> = ({el, box, tr, i, pal, lw}) => {
  const {t, sans} = useEngine();
  const seg = tr.segments[i];
  const prev = i > 0 ? tr.segments[i - 1] : undefined;
  const idx = seg.state.kind === 'header' ? seg.state.index : 0;
  const prevIdx = prev?.visible && prev.state.kind === 'header' ? prev.state.index : idx;
  const p = idx !== prevIdx ? EASE.outCubic(lin(t, seg.from, seg.from + HUD.swap)) : 1;
  const line = (index: number, o: number, dy: number) => {
    const parts = headerParts(el, index);
    return (
      <div style={{position: 'absolute', left: 0, top: 0, height: box.h, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap', opacity: o, transform: `translateY(${dy.toFixed(2)}px)`}}>
        {parts.lead ? (
          <>
            <span style={{color: pal.accent}}>{parts.lead}</span>
            <span style={{color: pal.muted, whiteSpace: 'pre'}}>{' · '}</span>
          </>
        ) : null}
        <span style={{color: pal.text}}>{parts.name}</span>
      </div>
    );
  };
  const travel = box.h * 0.55;
  return (
    <div style={{position: 'absolute', left: box.x, top: box.y, width: box.w, height: box.h, overflow: 'hidden', fontFamily: sans, fontWeight: 800, fontSize: box.fs, letterSpacing: box.ls, textShadow: textShadow(lw)}}>
      {p < 1 ? line(prevIdx, 1 - p, -travel * p) : null}
      {line(idx, p, travel * (1 - p))}
    </div>
  );
};

const Stakes: React.FC<{el: Extract<HudElement, {kind: 'stakes'}>; box: Extract<HudBox, {kind: 'stakes'}>; tr: HudTrack; i: number; pal: Pal}> = ({el, box, tr, i, pal}) => {
  const {t, sans, theme} = useEngine();
  const seg = tr.segments[i];
  const prev = i > 0 ? tr.segments[i - 1] : undefined;
  const st = seg.state.kind === 'stakes' ? seg.state : null;
  const pst = prev?.state.kind === 'stakes' && prev.visible ? prev.state : null;
  return (
    <div
      style={{
        position: 'absolute', left: box.x, top: box.y, width: box.w, height: box.h, borderRadius: box.h / 2, background: pal.card,
        border: `${Math.max(1.5, 2 * (box.h / HUD.stakes.h))}px solid ${pal.border}`, boxShadow: pal.shadow, boxSizing: 'border-box',
        display: 'flex', alignItems: 'center', justifyContent: 'center', whiteSpace: 'nowrap', fontFamily: sans, fontSize: box.fs, letterSpacing: box.ls,
      }}
    >
      {el.parts.map((part, k) => {
        const v = st?.values[k];
        const from = pst?.values[k];
        const changed = pst && from !== undefined && v !== undefined && from !== v;
        const q = changed ? EASE.outQuad(lin(t, seg.from + HUD.lead, seg.from + HUD.lead + HUD.count)) : 1;
        const shown = changed ? Math.round(mix(from as number, v as number, q)) : v;
        // the number bumps once as the count lands (0.4 s, ≤ 8 %)
        const land = seg.from + HUD.lead + HUD.count;
        const sc = changed ? 1 + 0.08 * Math.sin(Math.PI * lin(t, land - 0.08, land + 0.32)) : 1;
        const num = stakesValueText(part, shown);
        // a tone change (e.g. danger → success) blends with the count, so the colour lands with the number
        const color = changed || pst?.tones[k] !== st?.tones[k] ? mixColor(tone(theme, pst?.tones[k], pal.text), tone(theme, st?.tones[k], pal.text), changed ? q : 1) : tone(theme, st?.tones[k], pal.text);
        return (
          <React.Fragment key={k}>
            {k > 0 ? <span style={{color: pal.muted, fontWeight: 600, whiteSpace: 'pre'}}>{STAKES_SEP}</span> : null}
            {num ? (
              <span style={{display: 'inline-block', color, fontWeight: 800, fontVariantNumeric: 'tabular-nums', transform: `scale(${sc.toFixed(4)})`}}>{num}</span>
            ) : null}
            <span style={{color: pal.text2, fontWeight: 600, whiteSpace: 'pre'}}>{num ? ` ${part.label}` : part.label}</span>
          </React.Fragment>
        );
      })}
    </div>
  );
};

const Progress: React.FC<{el: Extract<HudElement, {kind: 'progress'}>; box: Extract<HudBox, {kind: 'progress'}>; tr: HudTrack; i: number; pal: Pal; lw: number}> = ({el, box, tr, i, pal, lw}) => {
  const {t, mono, theme} = useEngine();
  const c = theme.colors;
  const seg = tr.segments[i];
  const prev = i > 0 ? tr.segments[i - 1] : undefined;
  const v = seg.state.kind === 'progress' ? seg.state.value : 0;
  const pv = prev?.visible && prev.state.kind === 'progress' ? prev.state.value : v;
  const q = pv !== v ? EASE.inOutCubic(lin(t, seg.from, seg.from + HUD.fill)) : 1;
  const value = mix(pv, v, q);
  const total = Math.max(1, el.total);
  const b = box.bar;
  const fill = `linear-gradient(90deg, ${c.brand} 0%, ${c.brandHover} 100%)`;
  const glow = lw > 0.5 ? 'none' : `0 0 ${(b.h * 1.4).toFixed(1)}px ${alpha(c.brand, 0.55)}`;
  const shownValue = q < 0.5 ? pv : v;
  const n = progressPad(el);
  return (
    <>
      {el.style === 'segments' ? (
        <div style={{position: 'absolute', left: b.x, top: b.y, width: b.w, height: b.h, display: 'flex', gap: HUD.progress.segGap * (b.h / HUD.progress.bar)}}>
          {Array.from({length: total}, (_, s) => {
            const f = Math.min(1, Math.max(0, value - s));
            return (
              <div key={s} style={{position: 'relative', flex: 1, height: b.h, borderRadius: b.h / 2, background: pal.track, overflow: 'hidden'}}>
                {f > 0.001 ? <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(f * 100).toFixed(2)}%`, background: fill, borderRadius: b.h / 2, boxShadow: glow}} /> : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{position: 'absolute', left: b.x, top: b.y, width: b.w, height: b.h, borderRadius: b.h / 2, background: pal.track}}>
          <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${((value / total) * 100).toFixed(3)}%`, minWidth: value > 0 ? b.h : 0, background: fill, borderRadius: b.h / 2, boxShadow: glow}} />
        </div>
      )}
      {box.label ? (
        <div style={{position: 'absolute', left: box.label.x, top: box.label.y, width: box.label.w, height: box.label.h, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', whiteSpace: 'pre', fontFamily: mono, fontSize: box.fs, letterSpacing: box.fs * 0.04, fontWeight: 600, textShadow: textShadow(lw)}}>
          {el.label ? <span style={{color: pal.text2}}>{`${el.label.toUpperCase()} `}</span> : null}
          <span style={{color: pal.text, fontWeight: 700}}>{String(Math.round(shownValue)).padStart(n, '0')}</span>
          <span style={{color: pal.muted}}>{` / ${String(el.total).padStart(n, '0')}`}</span>
        </div>
      ) : null}
    </>
  );
};

const Chip: React.FC<{chip: HudChip; r: {x: number; y: number; w: number; h: number}; fs: number; ls: number; k: number; pal: Pal; lw: number}> = ({chip, r, fs, ls, k, pal, lw}) => {
  const {t, fps, sans, theme} = useEngine();
  if (t < chip.at) return null;
  const col = tone(theme, chip.tone ?? 'brand', theme.colors.brandText);
  const p = springAt(t, chip.at, fps, POP);
  // fresh: tinted in its tone, then settles to the quiet chip (the dot keeps the tone)
  const fresh = 1 - EASE.inOutCubic(lin(t, chip.at + HUD.fresh, chip.at + HUD.fresh + HUD.settle));
  const bg = fresh > 0.001 ? mixColor(lw > 0.5 ? '#ffffff' : theme.colors.card, col, 0.24 * fresh) : lw > 0.5 ? '#ffffff' : theme.colors.card;
  const sc = r.h / HUD.chips.h / k;
  return (
    <div
      style={{
        position: 'absolute', left: r.x, top: r.y, width: r.w, height: r.h, borderRadius: r.h / 2, boxSizing: 'border-box',
        background: bg, border: `${(2 * k * sc).toFixed(2)}px solid ${fresh > 0.001 ? mixColor(lw > 0.5 ? theme.colors.light.border : '#3a3a46', col, fresh) : pal.border}`,
        boxShadow: fresh > 0.001 ? `0 0 ${(18 * k * fresh).toFixed(1)}px ${alpha(theme.colors.brand, 0.35 * fresh)}, ${pal.shadow}` : pal.shadow,
        display: 'flex', alignItems: 'center', justifyContent: 'center', whiteSpace: 'nowrap',
        opacity: Math.min(1, p * 1.5), transform: `scale(${mix(0.72, 1, p).toFixed(4)})`, transformOrigin: '20% 50%',
        fontFamily: sans, fontWeight: 700, fontSize: fs, letterSpacing: ls, textTransform: 'uppercase',
      }}
    >
      <span style={{width: HUD.chips.dot * k * sc, height: HUD.chips.dot * k * sc, borderRadius: '50%', background: col, marginRight: HUD.chips.dotGap * k * sc, flex: 'none', boxShadow: lw > 0.5 ? 'none' : `0 0 ${(8 * k).toFixed(1)}px ${alpha(theme.colors.brand, 0.5)}`}} />
      <span style={{color: fresh > 0.5 ? pal.text : mixColor(pal.text2, pal.text, fresh)}}>{chip.text}</span>
    </div>
  );
};

const Chips: React.FC<{box: Extract<HudBox, {kind: 'chips'}>; seg: HudSegment; k: number; pal: Pal; lw: number}> = ({box, seg, k, pal, lw}) => {
  const chips = seg.state.kind === 'chips' ? seg.state.chips : [];
  return (
    <>
      {chips.map((c, n) => (box.items[n] ? <Chip key={n} chip={c} r={box.items[n]} fs={box.fs} ls={box.ls} k={k} pal={pal} lw={lw} /> : null))}
    </>
  );
};

export const HudView: React.FC<{plan: HudPlan; scenes: Scene[]; polish: boolean}> = ({plan, scenes, polish}) => {
  const {t, fps, theme} = useEngine();
  const lw = polish ? (backdropWeights(scenes, t).light ?? 0) : 0;
  const pal = palette(theme, lw);
  return (
    <>
      {plan.tracks.map((tr) => {
        const box = plan.boxes[tr.el.id];
        if (!box) return null;
        const i = segIndexAt(tr, t);
        const v = visibility(tr, i, t, fps, plan.k);
        if (v.o <= 0.001) return null;
        // a hidden element fades out with its last visible state
        const j = tr.segments[i].visible ? i : Math.max(0, i - 1);
        const el = tr.el;
        let body: React.ReactNode = null;
        if (el.kind === 'header' && box.kind === 'header') body = <Header el={el} box={box} tr={tr} i={j} pal={pal} lw={lw} />;
        else if (el.kind === 'stakes' && box.kind === 'stakes') body = <Stakes el={el} box={box} tr={tr} i={j} pal={pal} />;
        else if (el.kind === 'progress' && box.kind === 'progress') body = <Progress el={el} box={box} tr={tr} i={j} pal={pal} lw={lw} />;
        else if (el.kind === 'chips' && box.kind === 'chips') body = <Chips box={box} seg={tr.segments[j]} k={plan.k} pal={pal} lw={lw} />;
        return (
          <div key={el.id} style={{position: 'absolute', inset: 0, opacity: v.o, transform: `translateY(${v.dy.toFixed(2)}px)`, pointerEvents: 'none'}}>
            {body}
          </div>
        );
      })}
    </>
  );
};
