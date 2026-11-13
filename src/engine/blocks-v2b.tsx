/**
 * v2b product blocks: plan-card, install-flow, server-stack. Drawn exactly from geometry-v2b.ts (the numbers the
 * QA manifest reports). Pure functions of t; every visible word comes from the block props.
 */
import React, {useId} from 'react';
import {Img, staticFile} from 'remotion';
import {countValueDec, lin, mix, spc} from './anim';
import {TextSpec} from './geometry';
import {geomInstallFlow, geomPlanCard, geomServerStack, INSTALL, planPriceText, quadAt} from './geometry-v2b';
import {ACCENT, DUR, LEAD} from './motion/durations';
import {EASE, SPRING} from './motion/easings';
import {reader, Txt} from './prim';
import {toneColor} from './theme';
import {Block, BlockV2, IconName} from './types';
import {alpha, Check, Icon, useEngine} from './ui';

type P<K extends BlockV2['type']> = {block: Extract<Block, {type: K}>; w: number; h: number; appear: number; boxY: number; scale: number; sceneStart?: number; sceneEnd?: number};

/** A soft diagonal light sweep across a rounded rect (0 < p < 1 while sweeping). */
const Sheen: React.FC<{p: number; radius: number; strength?: number}> = ({p, radius, strength = 0.28}) =>
  p > 0 && p < 1 ? (
    <div style={{position: 'absolute', inset: 0, borderRadius: radius, overflow: 'hidden', pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          top: '-30%',
          bottom: '-30%',
          width: '38%',
          left: `${mix(-45, 110, EASE.inOutSine(p))}%`,
          background: `linear-gradient(100deg, rgba(255,255,255,0) 0%, rgba(255,255,255,${strength}) 50%, rgba(255,255,255,0) 100%)`,
          transform: 'skewX(-16deg)',
        }}
      />
    </div>
  ) : null;

/** Rotating arc spinner (deterministic). */
const Spinner: React.FC<{size: number; color: string; track: string; t: number}> = ({size, color, track, t}) => (
  <svg width={size} height={size} viewBox="0 0 48 48" style={{transform: `rotate(${(t * 420) % 360}deg)`}}>
    <circle cx="24" cy="24" r="19" fill="none" stroke={track} strokeWidth="5" />
    <path d="M24 5a19 19 0 0 1 19 19" fill="none" stroke={color} strokeWidth="5" strokeLinecap="round" />
  </svg>
);

// ------------------------------------------------------------------------------------------------ plan-card
export const PlanCard: React.FC<P<'plan-card'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, surface, motion: m} = useEngine();
  const c = theme.colors;
  const L = c.light;
  const light = (block.variant ?? (surface === 'light' ? 'light' : 'dark')) === 'light';
  const g = geomPlanCard(block, w);
  const next = reader(g.texts);
  const nameS = next();
  const badgeS = g.badge ? next() : undefined;
  next(); // the price run (drawn below as currency + counting amount)
  const perS = next();
  const billS = block.billing ? next() : undefined;
  const featS = block.features.map(() => next());
  const ctaS = g.cta && block.ctaLabel ? next() : undefined;
  const ink = light
    ? {text: L.text, text2: L.text2, muted: L.muted, line: L.border, check: L.success, icon: c.brand}
    : {text: c.text, text2: c.text2, muted: c.muted, line: c.border, check: c.success, icon: c.brandText};
  const R = theme.radius.card + 4;
  const countEnd = block.countEnd ?? appear + DUR.slower;
  const v = countValueDec(t, appear + 0.1, countEnd, block.countFrom ?? 0, block.price, Number.isInteger(block.price) ? 0 : 2);
  const land = spc(t, countEnd, fps, SPRING.land);
  const counting = t < countEnd;
  const pr = g.price;
  const badgeP = spc(t, appear + 0.3, fps, SPRING.badge);
  const hl = block.highlightAt;
  const ctaIn = spc(t, appear + 0.35 - LEAD.button, fps, SPRING.button);
  const hlP = hl !== undefined ? spc(t, hl, fps, SPRING.badge) : 0;
  const ring = hl !== undefined ? lin(t, hl, hl + ACCENT.ring) : 0;
  const pulse = hl !== undefined && t > hl ? 1 + 0.022 * Math.sin((t - hl) * 5.2) * Math.min(1, (t - hl) * 2) : 1;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {/* halo */}
      <div style={{position: 'absolute', inset: -70, borderRadius: R + 70, background: `radial-gradient(ellipse at 50% 40%, ${alpha(c.brand, light ? 0.16 : 0.32)} 0%, rgba(0,0,0,0) 68%)`}} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: R,
          background: light ? L.card : `linear-gradient(180deg, ${c.raised} 0%, ${c.card} 55%, ${c.surface} 100%)`,
          border: `2px solid ${light ? L.border : alpha(c.brandText, 0.32)}`,
          boxShadow: light
            ? `0 40px 90px ${alpha(L.text, 0.16)}, 0 8px 24px ${alpha(L.text, 0.08)}`
            : `0 40px 100px rgba(0,0,0,0.55), 0 0 0 1px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08)`,
          overflow: 'hidden',
          boxSizing: 'border-box',
        }}
      >
        <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 8, background: `linear-gradient(90deg, ${c.brand}, ${c.brandHover}, ${c.brandText})`}} />
        <div style={{position: 'absolute', left: -w * 0.2, top: -h * 0.35, width: w * 0.9, height: h * 0.7, background: `radial-gradient(ellipse, ${alpha(c.brand, light ? 0.07 : 0.18)} 0%, rgba(0,0,0,0) 70%)`}} />
      </div>
      <Txt s={nameS} color={ink.text} />
      {g.badge && badgeS ? (
        <div style={{position: 'absolute', left: 0, top: 0, opacity: Math.min(1, badgeP * 1.4), transform: `translateY(${(1 - badgeP) * 10}px)`}}>
          <div style={{position: 'absolute', left: g.badge.x, top: g.badge.y, width: g.badge.w, height: g.badge.h, borderRadius: 999, background: light ? alpha(c.brand, 0.1) : alpha(c.brand, 0.24), border: `2px solid ${alpha(light ? c.brand : c.brandText, 0.55)}`, boxSizing: 'border-box'}} />
          <Txt s={badgeS} color={light ? c.brand : c.brandText} />
        </div>
      ) : null}
      {/* price: raised currency · counting amount · period */}
      <div style={{position: 'absolute', left: 0, top: 0, transform: `scale(${mix(1.06, 1, land)})`, transformOrigin: `${pr.amtX}px ${pr.baseline}px`}}>
        <div style={{position: 'absolute', left: pr.curX, top: pr.curY, height: pr.curH, lineHeight: `${pr.curH}px`, fontSize: pr.curFs, fontWeight: 700, color: ink.text2, whiteSpace: 'nowrap'}}>{block.currency ?? '₹'}</div>
        <div
          style={{
            position: 'absolute',
            left: pr.amtX,
            top: pr.y,
            height: pr.h,
            lineHeight: `${pr.h}px`,
            fontSize: pr.fs,
            fontWeight: 800,
            letterSpacing: -0.04 * pr.fs,
            color: ink.text,
            whiteSpace: 'nowrap',
            fontVariantNumeric: 'tabular-nums',
            textShadow: light ? undefined : `0 0 60px ${alpha(c.brand, 0.45)}`,
          }}
        >
          {planPriceText(block, v)}
        </div>
      </div>
      <Txt s={perS} color={ink.muted} style={{opacity: counting ? 0.5 : 1}} />
      {billS ? <Txt s={billS} color={ink.muted} style={{opacity: lin(t, countEnd, countEnd + 0.3)}} /> : null}
      <div style={{position: 'absolute', left: g.divider.x, top: g.divider.y, width: g.divider.w, height: g.divider.h, background: ink.line}} />
      {block.features.map((f, i) => {
        const r = g.rows[i];
        const p = spc(t, f.at - LEAD.row, fps, m.row.spring);
        return (
          <div key={i} style={{position: 'absolute', left: 0, top: 0, opacity: Math.min(1, p * 1.3), transform: `translateX(${(1 - p) * -30}px)`}}>
            <div style={{position: 'absolute', left: r.check.x, top: r.check.y}}>
              <Check at={f.at + 0.04} size={r.check.s} color={ink.check} />
            </div>
            {r.icon && f.icon ? (
              <div style={{position: 'absolute', left: r.icon.x, top: r.icon.y}}>
                <Icon name={f.icon} size={r.icon.s} color={ink.icon} stroke={2.2} />
              </div>
            ) : null}
            <Txt s={featS[i]} color={ink.text} />
          </div>
        );
      })}
      {g.cta && ctaS ? (
        <div style={{position: 'absolute', left: g.cta.x, top: g.cta.y, width: g.cta.w, height: g.cta.h, opacity: ctaIn, transform: `translateY(${(1 - ctaIn) * 20}px) scale(${pulse * mix(1, 1.03, hlP * (1 - lin(t, (hl ?? 0) + 0.25, (hl ?? 0) + 0.6)))})`}}>
          {ring > 0 && ring < 1 ? <div style={{position: 'absolute', inset: -26 * ring, borderRadius: 24 + 26 * ring, border: `4px solid ${alpha(c.brandText, 0.7 * (1 - ring))}`}} /> : null}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              borderRadius: 24,
              background: `linear-gradient(135deg, ${c.brand}, ${c.brandHover})`,
              boxShadow: `0 ${14 + 10 * hlP}px ${40 + 30 * hlP}px ${alpha(c.brand, 0.4 + 0.25 * hlP)}, inset 0 1px 0 rgba(255,255,255,0.25)`,
            }}
          />
          <Sheen p={hl !== undefined ? lin(t, hl + 0.05, hl + 0.75) : 0} radius={24} />
          <Txt s={{...ctaS, x: ctaS.x - g.cta.x, y: 0}} color="#fff" />
          <div style={{position: 'absolute', right: 34, top: (g.cta.h - 44) / 2, transform: `translateX(${hlP * 6 * Math.max(0, Math.sin((t - (hl ?? 0)) * 4))}px)`}}>
            <Icon name="arrowRight" size={44} color="#fff" stroke={3} />
          </div>
        </div>
      ) : null}
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ install-flow
/** Progress 0..1 of the installer at t (step i fills its 1/n share between its `at` and the next step / doneAt). */
export const installProgress = (b: Extract<BlockV2, {type: 'install-flow'}>, t: number) => {
  const n = b.steps.length;
  if (!n) return t >= b.doneAt ? 1 : 0;
  let p = 0;
  b.steps.forEach((s, i) => {
    const end = b.steps[i + 1]?.at ?? b.doneAt;
    p += EASE.inOutSine(lin(t, s.at, end)) / n;
  });
  return t >= b.doneAt ? 1 : Math.min(0.99, p);
};

export const InstallFlow: React.FC<P<'install-flow'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, sans} = useEngine();
  const c = theme.colors;
  const L = c.light;
  const g = geomInstallFlow(block, w);
  const next = reader(g.texts);
  const titleS = block.title ? next() : undefined;
  const appS = next();
  const pctS = next();
  const stepS = block.steps.map(() => next());
  const doneS = next();
  const urlS = g.preview ? next() : undefined;
  const done = t >= block.doneAt;
  const doneP = spc(t, block.doneAt, fps, SPRING.sticker);
  const prog = installProgress(block, t);
  // before doneAt the window sits centred in the box; it makes room as the site preview slides in
  const slide = g.preview ? EASE.inOutCubic(lin(t, block.doneAt + 0.1, block.doneAt + 0.7)) : 1;
  const offX = g.preview && g.wide ? ((w - g.winW) / 2) * (1 - slide) : 0;
  const offY = g.preview && !g.wide ? ((h - g.win.h) / 2) * (1 - slide) : 0;
  const prevP = g.preview ? spc(t, block.doneAt + 0.25, fps, SPRING.card) : 0;
  const R = 30;
  const initial = (block.app.trim()[0] ?? '•').toUpperCase();
  const tileGlow = done ? 0.5 + 0.2 * Math.sin((t - block.doneAt) * 4) : 0.28;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={{position: 'absolute', left: offX, top: offY, width: g.win.w, height: g.win.h}}>
        <div style={{position: 'absolute', inset: 0, borderRadius: R, background: L.card, border: `2px solid ${L.border}`, boxShadow: `0 40px 90px rgba(0,0,0,0.38), 0 10px 30px ${alpha(L.text, 0.12)}`, overflow: 'hidden', boxSizing: 'border-box'}}>
          <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: INSTALL.chromeH, background: L.surface, borderBottom: `2px solid ${L.border}`}} />
        </div>
        {[c.danger, c.warning, c.success].map((col, i) => (
          <div key={col} style={{position: 'absolute', left: 30 + i * 34, top: INSTALL.chromeH / 2 - 10, width: 20, height: 20, borderRadius: 10, background: col, opacity: 0.9}} />
        ))}
        {titleS ? <Txt s={titleS} color={L.muted} /> : null}
        {/* app header */}
        <div
          style={{
            position: 'absolute',
            left: g.tile.x,
            top: g.tile.y,
            width: g.tile.s,
            height: g.tile.s,
            borderRadius: 28,
            background: block.appIcon?.bg
              ? `linear-gradient(140deg, ${alpha('#ffffff', 0.18)}, transparent 60%), ${block.appIcon.bg}`
              : `linear-gradient(140deg, ${c.brandHover}, ${c.brand} 55%, ${c.brandActive})`,
            boxShadow: `0 14px 34px ${alpha(block.appIcon?.bg ?? c.brand, tileGlow)}, inset 0 1px 0 rgba(255,255,255,0.3)`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontFamily: sans,
            fontWeight: 800,
            fontSize: g.tile.s * 0.52,
            letterSpacing: -2,
          }}
        >
          {block.appIcon ? (
            <Img src={staticFile(block.appIcon.asset)} style={{width: g.tile.s * 0.66, height: g.tile.s * 0.66, display: 'block'}} />
          ) : initial}
          {done ? (
            <div style={{position: 'absolute', right: -10, bottom: -10, transform: `scale(${doneP})`}}>
              <svg width={44} height={44} viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="11" fill={c.success} stroke="#fff" strokeWidth="2" />
                <path d="M6.8 12.4l3.4 3.4 7-7.2" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          ) : null}
        </div>
        <Txt s={appS} color={L.text} />
        <Txt s={pctS} color={done ? L.success : c.brand} style={{fontVariantNumeric: 'tabular-nums', opacity: lin(t, appear, appear + 0.3)}}>
          {`${Math.round(prog * 100)}%`}
        </Txt>
        {/* progress bar */}
        <div style={{position: 'absolute', left: g.bar.x, top: g.bar.y, width: g.bar.w, height: g.bar.h, borderRadius: g.bar.h / 2, background: alpha(L.text, 0.07), overflow: 'hidden'}}>
          <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${prog * 100}%`, borderRadius: g.bar.h / 2, background: done ? `linear-gradient(90deg, ${c.success}, ${L.success})` : `linear-gradient(90deg, ${c.brand}, ${c.brandHover})`}} />
          {!done && prog > 0 ? (
            <div style={{position: 'absolute', top: 0, bottom: 0, width: 120, left: `calc(${prog * 100}% - 120px)`, background: `linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,${0.35 + 0.25 * Math.sin(t * 8)}))`}} />
          ) : null}
        </div>
        {/* steps */}
        {block.steps.map((s, i) => {
          const r = g.rows[i];
          const end = block.steps[i + 1]?.at ?? block.doneAt;
          const active = t >= s.at && t < end;
          const isDone = t >= end;
          const inP = spc(t, Math.min(s.at, appear + 0.15 + i * 0.08) - LEAD.row, fps, SPRING.row);
          const hi = active ? Math.min(1, (t - s.at) / 0.15) : isDone ? Math.max(0, 1 - (t - end) / 0.25) : 0;
          return (
            <div key={i} style={{position: 'absolute', left: 0, top: 0, opacity: Math.min(1, inP * 1.3), transform: `translateY(${(1 - inP) * 14}px)`}}>
              {hi > 0 ? <div style={{position: 'absolute', left: g.pad - 16, top: r.y + 6, width: g.inner + 32, height: INSTALL.rowH - 12, borderRadius: 18, background: alpha(c.brand, 0.07 * hi)}} /> : null}
              <div style={{position: 'absolute', left: r.icon.x, top: r.icon.y, width: r.icon.s, height: r.icon.s}}>
                {isDone ? (
                  <Check at={end} size={r.icon.s} color={L.success} />
                ) : active ? (
                  <Spinner size={r.icon.s} color={c.brand} track={alpha(c.brand, 0.15)} t={t} />
                ) : (
                  <div style={{width: r.icon.s, height: r.icon.s, borderRadius: r.icon.s / 2, border: `4px solid ${L.border}`, boxSizing: 'border-box'}} />
                )}
              </div>
              <Txt s={stepS[i]} color={isDone ? L.text2 : active ? L.text : L.muted} />
            </div>
          );
        })}
        {/* success row */}
        {done ? (
          <div style={{position: 'absolute', left: 0, top: 0, opacity: Math.min(1, doneP * 1.4), transform: `translateY(${(1 - doneP) * 16}px)`}}>
            <div style={{position: 'absolute', left: g.done.x, top: g.done.y, width: g.done.w, height: g.done.h, borderRadius: 22, background: alpha(c.success, 0.12), border: `2px solid ${alpha(c.success, 0.45)}`, boxSizing: 'border-box', boxShadow: `0 0 ${36 * doneP}px ${alpha(c.success, 0.25)}`}} />
            <div style={{position: 'absolute', left: g.done.x + 28, top: g.done.y + (g.done.h - 56) / 2}}>
              <Check at={block.doneAt} size={56} color={L.success} />
            </div>
            <Txt s={doneS} color={L.success} />
          </div>
        ) : null}
      </div>
      {/* the new site, sliding in */}
      {g.preview && urlS && prevP > 0 ? (
        <SitePreview r={g.preview} urlS={urlS} p={prevP} wide={g.wide} t={t} at={block.doneAt + 0.25} />
      ) : null}
    </div>
  );
};

const SitePreview: React.FC<{r: {x: number; y: number; w: number; h: number}; urlS: TextSpec; p: number; wide: boolean; t: number; at: number}> = ({r, urlS, p, wide, t, at}) => {
  const {theme} = useEngine();
  const c = theme.colors;
  const L = c.light;
  const ch = INSTALL.prevChrome;
  const bw = r.w - 40;
  const item = (k: number) => EASE.outCubic(lin(t, at + 0.15 + k * 0.08, at + 0.5 + k * 0.08));
  const dx = wide ? (1 - p) * 120 : 0;
  const dy = wide ? 0 : (1 - p) * 120;
  const bodyH = r.h - ch;
  return (
    <div style={{position: 'absolute', left: r.x, top: r.y, width: r.w, height: r.h, opacity: Math.min(1, p * 1.3), transform: `translate(${dx}px, ${dy}px) rotate(${(1 - p) * 2}deg)`}}>
      <div style={{position: 'absolute', inset: 0, borderRadius: 24, background: L.card, border: `2px solid ${L.border}`, boxShadow: `0 40px 90px rgba(0,0,0,0.45), 0 0 0 1px ${alpha(L.text, 0.04)}`, overflow: 'hidden', boxSizing: 'border-box'}}>
        <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: ch, background: L.surface, borderBottom: `2px solid ${L.border}`}} />
        {/* mock site */}
        <div style={{position: 'absolute', left: 20, top: ch + 18, width: bw, height: 26, opacity: item(0)}}>
          <div style={{position: 'absolute', left: 0, top: 0, width: 26, height: 26, borderRadius: 8, background: `linear-gradient(135deg, ${c.brandHover}, ${c.brand})`}} />
          {[0, 1, 2].map((k) => (
            <div key={k} style={{position: 'absolute', right: k * 70, top: 8, width: 52, height: 10, borderRadius: 5, background: alpha(L.text, 0.14)}} />
          ))}
        </div>
        <div style={{position: 'absolute', left: 20, top: ch + 62, width: bw, height: bodyH * 0.44, borderRadius: 16, background: `linear-gradient(135deg, ${c.brand}, ${c.brandHover} 60%, ${c.brandText})`, opacity: item(1), transform: `translateY(${(1 - item(1)) * 14}px)`, overflow: 'hidden'}}>
          <div style={{position: 'absolute', left: 26, top: '22%', width: '58%', height: 18, borderRadius: 9, background: 'rgba(255,255,255,0.92)'}} />
          <div style={{position: 'absolute', left: 26, top: '22%', marginTop: 30, width: '40%', height: 12, borderRadius: 6, background: 'rgba(255,255,255,0.6)'}} />
          <div style={{position: 'absolute', left: 26, bottom: '18%', width: 96, height: 30, borderRadius: 15, background: '#fff'}} />
          <div style={{position: 'absolute', right: -30, top: -30, width: 160, height: 160, borderRadius: 80, background: 'rgba(255,255,255,0.12)'}} />
        </div>
        {[0, 1, 2].map((k) => {
          const cw = (bw - 2 * 14) / 3;
          const top = ch + 62 + bodyH * 0.44 + 16;
          return (
            <div key={k} style={{position: 'absolute', left: 20 + k * (cw + 14), top, width: cw, height: Math.max(20, r.h - top - 18), borderRadius: 12, background: L.surface, border: `2px solid ${L.border}`, boxSizing: 'border-box', opacity: item(2 + k)}}>
              <div style={{position: 'absolute', left: 12, top: 12, width: 22, height: 22, borderRadius: 7, background: alpha(c.brand, 0.2)}} />
              <div style={{position: 'absolute', left: 12, right: 18, top: 44, height: 8, borderRadius: 4, background: alpha(L.text, 0.12)}} />
            </div>
          );
        })}
      </div>
      {[c.danger, c.warning, c.success].map((col, i) => (
        <div key={col} style={{position: 'absolute', left: 22 + i * 26, top: ch / 2 - 7, width: 14, height: 14, borderRadius: 7, background: col, opacity: 0.9}} />
      ))}
      <div style={{position: 'absolute', left: urlS.x - r.x - 16, top: 10, width: r.w - (urlS.x - r.x - 16) - 16, height: ch - 20, borderRadius: (ch - 20) / 2, background: L.card, border: `2px solid ${L.border}`, boxSizing: 'border-box'}} />
      <div style={{position: 'absolute', left: urlS.x - r.x - 4, top: 10 + (ch - 20 - 22) / 2}}>
        <Icon name="lock" size={22} color={L.success} stroke={2.6} />
      </div>
      <Txt s={{...urlS, x: urlS.x - r.x + 24, y: urlS.y - r.y, w: urlS.w - 24}} color={L.text} />
    </div>
  );
};

// ------------------------------------------------------------------------------------------------ server-stack
export const ServerStack: React.FC<P<'server-stack'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, ink, surface} = useEngine();
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const c = theme.colors;
  const g = geomServerStack(block, w);
  const next = reader(g.texts);
  const titleS = block.title ? next() : undefined;
  const nodes = block.nodes.slice(0, 4);
  const labelS = nodes.map(() => next());
  const statusS = g.status ? next() : undefined;
  const lastAt = nodes.length ? Math.max(...nodes.map((n) => n.at)) : appear;
  const pulseAt = block.pulseAt ?? lastAt + 0.3;
  const flowing = t >= pulseAt;
  const flowK = lin(t, pulseAt, pulseAt + 0.4);
  const globeOn = spc(t, pulseAt - 0.1, fps, SPRING.pop);
  const st = block.status;
  const stP = st ? spc(t, st.at, fps, SPRING.badge) : 0;
  const stCol = st ? toneColor(theme, st.tone ?? 'success') : c.success;
  const rack = g.rack;
  const unitBg = 'linear-gradient(180deg, #1d1d27 0%, #16161e 100%)';
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {titleS ? <Txt s={titleS} color={ink.text2} /> : null}
      {/* links + pulses */}
      <svg width={w} height={h} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible'}}>
        <defs>
          <radialGradient id={`sb-pulse-${uid}`}>
            <stop offset="0" stopColor="#fff" stopOpacity="1" />
            <stop offset="0.35" stopColor={c.brandText} stopOpacity="0.9" />
            <stop offset="1" stopColor={c.brand} stopOpacity="0" />
          </radialGradient>
        </defs>
        {g.links.map((l, i) => {
          const on = lin(t, nodes[i].at, nodes[i].at + 0.35);
          const d = `M${l.x0},${l.y0} Q${l.cx},${l.cy} ${l.x1},${l.y1}`;
          return (
            <g key={i}>
              <path d={d} fill="none" stroke={surface === 'light' ? alpha(c.light.text, 0.12) : 'rgba(255,255,255,0.08)'} strokeWidth={6} strokeLinecap="round" />
              <path d={d} fill="none" stroke={alpha(c.brandText, 0.55 * on + 0.25 * flowK)} strokeWidth={3} strokeLinecap="round" strokeDasharray="10 12" strokeDashoffset={flowing ? -(t - pulseAt) * 60 : 0} />
              {flowing
                ? [0, 0.5].map((k) => {
                    const ph = ((t - pulseAt) * 0.55 + i * 0.27 + k) % 1;
                    const q = quadAt(l, EASE.inOutSine(ph));
                    const o = Math.min(1, ph / 0.12, (1 - ph) / 0.12) * flowK;
                    return <circle key={k} cx={q.x} cy={q.y} r={16} fill={`url(#sb-pulse-${uid})`} opacity={o} />;
                  })
                : null}
            </g>
          );
        })}
      </svg>
      {/* rack enclosure */}
      <div style={{position: 'absolute', left: rack.x, top: rack.y, width: rack.w, height: rack.h, borderRadius: 26, background: 'linear-gradient(180deg, #14141b, #0d0d12)', border: '2px solid rgba(255,255,255,0.12)', boxShadow: '0 40px 90px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.07)', boxSizing: 'border-box'}} />
      {g.units.map((u, i) => {
        const nd = nodes[i];
        const on = spc(t, nd.at - LEAD.row, fps, SPRING.pop);
        const lit = t >= nd.at;
        const sheen = lin(t, nd.at, nd.at + 0.6);
        const act = lit && Math.sin(t * (flowing ? 23 : 9) + i * 2.3) + Math.sin(t * 13.7 + i) > (flowing ? -0.2 : 0.6);
        return (
          <React.Fragment key={i}>
            <div style={{position: 'absolute', left: u.x, top: u.y, width: u.w, height: u.h, borderRadius: 16, background: unitBg, border: `2px solid ${lit ? alpha(c.brandText, 0.18 + 0.2 * (1 - sheen)) : 'rgba(255,255,255,0.07)'}`, boxSizing: 'border-box', boxShadow: lit ? `0 0 ${30 * (1 - sheen) + 10}px ${alpha(c.brand, 0.18)}` : undefined, overflow: 'hidden'}}>
              <Sheen p={sheen} radius={16} strength={0.12} />
            </div>
            {/* LEDs */}
            {[0, 1].map((k) => {
              const col = k === 0 ? c.success : c.info;
              const glow = k === 0 ? lit : act;
              return <div key={k} style={{position: 'absolute', left: u.x + 22, top: u.y + u.h / 2 - 22 + k * 30, width: 13, height: 13, borderRadius: 7, background: glow ? col : 'rgba(255,255,255,0.12)', boxShadow: glow ? `0 0 12px ${col}, 0 0 3px ${col}` : undefined}} />;
            })}
            {/* icon tile */}
            <div
              style={{
                position: 'absolute',
                left: u.tile.x,
                top: u.tile.y,
                width: u.tile.s,
                height: u.tile.s,
                borderRadius: 20,
                background: lit ? `linear-gradient(140deg, ${c.brandHover}, ${c.brand})` : 'rgba(255,255,255,0.06)',
                boxShadow: lit ? `0 10px 26px ${alpha(c.brand, 0.45)}` : undefined,
                transform: `scale(${lit ? mix(0.85, 1, on) : 1})`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Icon name={nd.icon ?? 'server'} size={u.tile.s * 0.52} color={lit ? '#fff' : c.muted} stroke={2.3} />
            </div>
            <Txt s={labelS[i]} color={lit ? c.text : c.muted} />
            {/* drive bays */}
            {Array.from({length: 6}).map((_, k) => {
              const bx = u.bays.x + k * (u.bays.w / 6);
              const blink = lit && Math.sin(t * (flowing ? 17 : 6) + k * 1.9 + i * 0.7) > (flowing ? 0.1 : 0.75);
              return (
                <div key={k} style={{position: 'absolute', left: bx, top: u.bays.y, width: u.bays.w / 6 - 8, height: u.bays.h, borderRadius: 6, background: 'linear-gradient(180deg, #23232d, #1a1a22)', border: '1px solid rgba(255,255,255,0.08)', boxSizing: 'border-box'}}>
                  <div style={{position: 'absolute', left: '50%', marginLeft: -3, bottom: 8, width: 6, height: 6, borderRadius: 3, background: blink ? c.success : 'rgba(255,255,255,0.15)', boxShadow: blink ? `0 0 8px ${c.success}` : undefined}} />
                  <div style={{position: 'absolute', left: 5, right: 5, top: 9, height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.08)'}} />
                  <div style={{position: 'absolute', left: 5, right: 5, top: 16, height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.06)'}} />
                </div>
              );
            })}
          </React.Fragment>
        );
      })}
      {/* website node */}
      <GlobeNode cx={g.globe.cx} cy={g.globe.cy} r={g.globe.r} on={globeOn} flowing={flowing} t={t} pulseAt={pulseAt} icon={block.target?.icon ?? 'globe'} />
      {g.status && statusS && st ? (
        <div style={{position: 'absolute', left: 0, top: 0, opacity: Math.min(1, stP * 1.4), transform: `translateY(${(1 - stP) * 14}px)`}}>
          <div style={{position: 'absolute', left: g.status.x, top: g.status.y, width: g.status.w, height: g.status.h, borderRadius: 999, background: surface === 'light' ? '#fff' : alpha(stCol, 0.14), border: `2px solid ${alpha(stCol, 0.55)}`, boxSizing: 'border-box', boxShadow: surface === 'light' ? `0 10px 30px ${alpha(c.light.text, 0.1)}` : undefined}} />
          <div style={{position: 'absolute', left: g.status.x + 28, top: g.status.y + g.status.h / 2 - 9, width: 18, height: 18, borderRadius: 9, background: stCol, boxShadow: `0 0 0 ${5 + 4 * Math.max(0, Math.sin((t - st.at) * 4))}px ${alpha(stCol, 0.25)}`}} />
          <Txt s={statusS} color={surface === 'light' ? ink.text : c.text} />
        </div>
      ) : null}
    </div>
  );
};

const GlobeNode: React.FC<{cx: number; cy: number; r: number; on: number; flowing: boolean; t: number; pulseAt: number; icon?: IconName}> = ({cx, cy, r, on, flowing, t, pulseAt, icon = 'globe'}) => {
  const {theme} = useEngine();
  const c = theme.colors;
  const rings = flowing ? [0, 0.5].map((k) => ((t - pulseAt) * 0.55 + k) % 1) : [];
  return (
    <>
      {rings.map((p, i) => (
        <div key={i} style={{position: 'absolute', left: cx - r - 50 * p, top: cy - r - 50 * p, width: 2 * (r + 50 * p), height: 2 * (r + 50 * p), borderRadius: '50%', border: `3px solid ${alpha(c.brandText, 0.45 * (1 - p))}`, boxSizing: 'border-box'}} />
      ))}
      <div
        style={{
          position: 'absolute',
          left: cx - r,
          top: cy - r,
          width: 2 * r,
          height: 2 * r,
          borderRadius: '50%',
          background: `radial-gradient(circle at 35% 30%, ${c.brandHover} 0%, ${c.brand} 55%, ${c.brandActive} 100%)`,
          boxShadow: `0 0 ${30 + 40 * on}px ${alpha(c.brand, 0.35 + 0.3 * on)}, inset 0 2px 0 rgba(255,255,255,0.25)`,
          opacity: mix(0.55, 1, on),
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon name={icon} size={r * 1.05} color="#fff" stroke={1.8} />
      </div>
    </>
  );
};

