import React, {useId} from 'react';
import {Img, staticFile} from 'remotion';
import {countValueDec, easeInOut, easeOut, lin, mix, spc} from './anim';
import {
  chartValueText,
  counterText,
  geomChart,
  geomCounter,
  geomDashboard,
  geomDevice,
  geomFeatureCompare,
  geomImage,
  geomKinetic,
  geomLogoSting,
  geomOutro,
  geomPriceCompare,
  geomProgress,
  geomScrollDemo,
  geomTerminal,
  specWidth,
  terminalTypeEnd,
  TextSpec,
} from './geometry';
import {ACCENT, DUR, LEAD} from './motion/durations';
import {EASE, SPRING} from './motion/easings';
import {toneColor, toneFill} from './theme';
import {Block, BlockV2} from './types';
import {alpha, Check, Icon, inkTone, Logo, useEngine} from './ui';
import {InstallFlow, PlanCard, ServerStack} from './blocks-v2b';
import {Footage} from './blocks-footage';
import {Composition} from './blocks-composition';
import {reader, Txt} from './prim';

export type P<K extends BlockV2['type']> = {
  block: Extract<Block, {type: K}>;
  w: number;
  h: number;
  appear: number;
  boxY: number;
  scale: number;
  sceneStart?: number;
  sceneEnd?: number;
};

const darkCard = (theme: ReturnType<typeof useEngine>['theme'], extra: React.CSSProperties = {}): React.CSSProperties => ({
  position: 'absolute',
  inset: 0,
  background: theme.colors.card,
  border: `2px solid ${theme.colors.border}`,
  borderRadius: theme.radius.card,
  boxShadow: '0 30px 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06)',
  boxSizing: 'border-box',
  overflow: 'hidden',
  ...extra,
});

// ------------------------------------------------------------------------------------------------
const KineticText: React.FC<P<'kinetic-text'>> = ({block, w, appear}) => {
  const {theme, t, fps, motion: m, polish, ink} = useEngine();
  const c = theme.colors;
  const g = geomKinetic(block, w);
  return (
    <div style={{position: 'relative', width: w, height: g.h}}>
      {g.words.map((wd) => {
        const word = block.words[wd.i];
        const at = word.at ?? appear + wd.i * m.word.stagger;
        const p = spc(t, at - LEAD.word, fps, m.word.spring);
        const emph = !!word.emphasis;
        const pop = emph ? mix(1.32, 1, spc(t, at - LEAD.word, fps, SPRING.stamp)) : 1;
        const under = emph ? easeOut(t, at + 0.12, at + 0.12 + DUR.medium) : 0;
        const color = polish ? inkTone(ink, theme, word.tone, emph ? ink.accent : ink.text) : word.tone ? toneColor(theme, word.tone) : emph ? c.brandText : c.text;
        return (
          <div key={wd.i} style={{position: 'absolute', left: wd.x, top: wd.y, width: wd.w, height: g.lineH, opacity: Math.min(1, p * 1.3)}}>
            {emph && under > 0 ? (
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  // v2b: a clean underline below the baseline (the v2 marker bar sat on the glyphs)
                  top: polish ? g.lineH / 2 + 0.36 * wd.fs + 0.1 * g.fs : g.lineH * 0.62,
                  height: polish ? Math.max(6, g.fs * 0.07) : g.fs * 0.22,
                  width: wd.w * under,
                  borderRadius: g.fs * 0.06,
                  background: polish ? `linear-gradient(90deg, ${c.brand}, ${c.brandHover}, ${alpha(c.brandText, 0.4)})` : `linear-gradient(90deg, ${alpha(c.brand, 0.75)}, ${alpha(c.brandHover, 0.45)})`,
                }}
              />
            ) : null}
            <div
              style={{
                position: 'relative',
                height: g.lineH,
                lineHeight: `${g.lineH}px`,
                fontSize: wd.fs,
                fontWeight: 800,
                letterSpacing: -0.02 * wd.fs,
                textAlign: 'center',
                whiteSpace: 'nowrap',
                color,
                textShadow: emph ? `0 0 40px ${alpha(c.brand, 0.55)}` : undefined,
                transform: `translateY(${(1 - p) * g.fs * m.word.rise}px) scale(${pop})`,
                transformOrigin: '50% 60%',
              }}
            >
              {word.text}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Counter: React.FC<P<'counter'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, ink} = useEngine();
  const c = {...theme.colors, text: ink.text, text2: ink.text2};
  const g = geomCounter(block, w);
  const end = block.countEnd ?? appear + DUR.slower;
  const v = countValueDec(t, appear, end, block.from ?? 0, block.to, block.decimals ?? 0);
  const land = spc(t, end, fps, SPRING.land);
  const next = reader(g.texts);
  const label = block.label ? next() : undefined;
  const num = next();
  const col = block.tone ? inkTone(ink, theme, block.tone, ink.text) : c.text;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={{position: 'absolute', left: w * 0.1, right: w * 0.1, top: g.labelH, height: g.numH, background: `radial-gradient(ellipse, ${alpha(c.brand, 0.4)} 0%, rgba(0,0,0,0) 70%)`}} />
      {label ? <Txt s={label} color={c.text2} /> : null}
      <Txt s={num} color={col} style={{fontVariantNumeric: 'tabular-nums', transform: `scale(${mix(1.06, 1, land)})`, textShadow: `0 0 50px ${alpha(c.brand, 0.5)}`}}>
        {counterText(block, v)}
      </Txt>
    </div>
  );
};

const PriceCompare: React.FC<P<'price-compare'>> = ({block, w, h}) => {
  const {theme, t, fps, motion: m, aspects} = useEngine();
  const c = theme.colors;
  const g = geomPriceCompare(block, w, aspects.polish);
  const next = reader(g.texts);
  const title = block.title ? next() : undefined;
  const heads = block.columns.map(() => next());
  const rows = block.rows.map((r) => ({label: next(), values: r.values.map(() => next())}));
  const badgeSpec = g.badge ? next() : undefined;
  const lastAt = block.rows.length ? Math.max(...block.rows.map((r) => r.at)) : 0;
  const winAt = block.winnerAt ?? lastAt + DUR.base;
  const wp = block.winner !== undefined ? spc(t, winAt, fps, SPRING.pop) : 0;
  const tableBottom = g.rowsY + block.rows.length * g.rowH;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={darkCard(theme)} />
      {title ? <Txt s={title} color={c.text2} /> : null}
      {block.winner !== undefined && wp > 0 ? (
        <div
          style={{
            position: 'absolute',
            left: g.colX(block.winner) + 4,
            top: g.y0 - 4,
            width: g.colW - 8,
            height: tableBottom - g.y0 + 8,
            borderRadius: 22,
            border: `3px solid ${c.brand}`,
            background: alpha(c.brand, 0.12),
            boxShadow: `0 0 ${44 * wp}px ${alpha(c.brand, 0.5)}`,
            opacity: Math.min(1, wp * 1.4),
            transform: `scale(${mix(0.96, 1, wp)})`,
            boxSizing: 'border-box',
          }}
        />
      ) : null}
      {heads.map((s, ci) => (
        <Txt key={ci} s={s} color={block.winner === ci ? c.brandText : c.text2} />
      ))}
      {block.rows.map((r, ri) => {
        const p = spc(t, r.at - LEAD.card, fps, m.card.spring);
        const y = g.rowsY + ri * g.rowH;
        const strikeP = easeOut(t, r.at + 0.25, r.at + 0.25 + DUR.base);
        return (
          <div key={ri} style={{position: 'absolute', left: 0, top: 0, width: w, height: h, opacity: p, transform: `translateX(${(1 - p) * -40}px)`}}>
            <div style={{position: 'absolute', left: g.pad, right: g.pad, top: y, borderTop: `2px solid ${c.border}`}} />
            {r.highlight !== undefined ? (
              <div style={{position: 'absolute', left: g.colX(r.highlight) + 10, top: y + 10, width: g.colW - 20, height: g.rowH - 20, borderRadius: 14, background: alpha(c.brand, 0.2)}} />
            ) : null}
            <Txt s={rows[ri].label} color={c.text2} />
            {rows[ri].values.map((s, ci) => {
              const struck = r.strike?.includes(ci);
              const hike = r.hike?.includes(ci);
              const col = struck ? c.muted : hike ? c.danger : block.winner === ci ? c.text : c.text;
              const ew = Math.min(specWidth(s), s.w);
              return (
                <React.Fragment key={ci}>
                  <Txt s={s} color={col} />
                  {struck && strikeP > 0 ? (
                    <div
                      style={{
                        position: 'absolute',
                        left: s.x + (s.w - ew) / 2 - 6,
                        top: y + g.rowH / 2 - 3,
                        width: (ew + 12) * strikeP,
                        height: 6,
                        borderRadius: 3,
                        background: c.danger,
                        transform: 'rotate(-6deg)',
                        transformOrigin: '0 50%',
                      }}
                    />
                  ) : null}
                  {hike ? (
                    <div style={{position: 'absolute', left: g.colX(ci) + g.colW - 12 - g.hikeW + 4, top: y + (g.rowH - 36) / 2, opacity: lin(t, r.at + 0.2, r.at + 0.4)}}>
                      <Icon name="arrowUp" size={36} color={c.danger} stroke={3} />
                    </div>
                  ) : null}
                </React.Fragment>
              );
            })}
          </div>
        );
      })}
      {g.badge && badgeSpec && wp > 0 ? (
        <div style={{position: 'absolute', left: 0, top: 0, opacity: Math.min(1, wp * 1.4), transform: `translateY(${(1 - wp) * 12}px)`}}>
          <div style={{position: 'absolute', left: g.badge.x, top: g.badge.y, width: g.badge.w, height: g.badge.h, borderRadius: 999, background: c.brand, boxShadow: `0 10px 30px ${alpha(c.brand, 0.5)}`}} />
          <Txt s={badgeSpec} color="#fff" />
        </div>
      ) : null}
    </div>
  );
};

const Terminal: React.FC<P<'terminal'>> = ({block, w, h}) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  const g = geomTerminal(block, w);
  const next = reader(g.texts);
  const title = block.title ? next() : undefined;
  const specs = block.lines.map(() => next());
  const started = block.lines.filter((l) => t >= l.at).length;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={darkCard(theme, {background: '#0c0c12'})} />
      <div style={{position: 'absolute', left: 0, top: 0, width: w, height: g.chromeH, background: c.raised, borderRadius: `${theme.radius.card}px ${theme.radius.card}px 0 0`, borderBottom: `2px solid ${c.border}`, boxSizing: 'border-box'}} />
      {[c.danger, c.warning, c.success].map((col, i) => (
        <div key={col} style={{position: 'absolute', left: 30 + i * 34, top: g.chromeH / 2 - 11, width: 22, height: 22, borderRadius: 11, background: col, opacity: 0.85}} />
      ))}
      {title ? <Txt s={title} color={c.muted} /> : null}
      {block.lines.map((l, i) => {
        if (t < l.at) return null;
        const kind = l.kind ?? 'out';
        const s = specs[i];
        const p = lin(t, l.at, l.at + DUR.micro);
        if (kind === 'cmd') {
          const end = terminalTypeEnd(l);
          const n = Math.floor(l.text.length * lin(t, l.at, end));
          const typing = t < end;
          const isLast = i === started - 1;
          const caretOn = isLast && (typing || Math.floor(t * ACCENT.caretHz) % 2 === 0);
          return (
            <Txt key={i} s={s} color={c.text}>
              <span style={{color: c.brandText}}>{block.prompt ?? '$'}</span> {l.text.slice(0, n)}
              <span style={{display: 'inline-block', width: s.fs * 0.55, height: s.fs * 1.05, marginLeft: 4, verticalAlign: 'middle', background: c.brandText, opacity: caretOn ? 0.9 : 0}} />
            </Txt>
          );
        }
        const col = kind === 'ok' ? c.success : kind === 'err' ? c.danger : kind === 'dim' ? c.muted : c.text2;
        return <Txt key={i} s={s} color={col} style={{opacity: p, transform: `translateY(${(1 - p) * 8}px)`}} />;
      })}
    </div>
  );
};

const Dashboard: React.FC<P<'dashboard'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, motion: m, aspects} = useEngine();
  const c = theme.colors;
  const g = geomDashboard(block, w, aspects);
  const next = reader(g.texts);
  const navSpecs = g.nav.map(() => next());
  const title = block.title ? next() : undefined;
  const tileSpecs = block.stats.slice(0, 4).map((s) => ({label: next(), value: next(), delta: s.delta ? next() : undefined}));
  const chartTitle = block.chart?.title ? next() : undefined;
  const barLabels = (block.chart?.bars ?? []).map(() => next());
  const active = block.active ?? 0;
  const growEnd = block.chart?.growEnd ?? appear + 1.2;
  const hl = block.chart?.highlight;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={darkCard(theme)} />
      <div style={{position: 'absolute', left: 0, top: 0, width: g.sideW, height: h, background: c.surface, borderRight: `2px solid ${c.border}`, borderRadius: `${theme.radius.card}px 0 0 ${theme.radius.card}px`, boxSizing: 'border-box'}} />
      <div style={{position: 'absolute', left: g.mark.x, top: g.mark.y}}>
        <Logo variant="mark" width={g.mark.w} height={g.mark.h} />
      </div>
      {g.nav.map((n, i) => {
        const on = i === active;
        const p = lin(t, appear + 0.1 + i * 0.06, appear + 0.3 + i * 0.06);
        return (
          <div key={i} style={{opacity: p}}>
            <div style={{position: 'absolute', left: n.x, top: n.y, width: n.w, height: n.h, borderRadius: 14, background: on ? alpha(c.brand, 0.22) : 'transparent'}} />
            {on ? <div style={{position: 'absolute', left: n.x, top: n.y + 10, width: 5, height: n.h - 20, borderRadius: 3, background: c.brandText}} /> : null}
            <Txt s={navSpecs[i]} color={on ? c.text : c.text2} />
          </div>
        );
      })}
      {title ? <Txt s={title} color={c.text} /> : null}
      {g.tiles.map((r, i) => {
        const p = spc(t, appear + 0.15 + i * 0.1 - LEAD.row, fps, m.row.spring);
        const s = block.stats[i];
        const ts = tileSpecs[i];
        return (
          <div key={i} style={{position: 'absolute', left: 0, top: 0, opacity: p, transform: `translateY(${(1 - p) * 30}px)`}}>
            <div style={{position: 'absolute', left: r.x, top: r.y, width: r.w, height: r.h, borderRadius: 22, background: c.raised, border: `2px solid ${c.border}`, boxSizing: 'border-box'}} />
            <Txt s={ts.label} color={c.muted} />
            <Txt s={ts.value} color={c.text} />
            {ts.delta ? <Txt s={ts.delta} color={toneColor(theme, s.tone ?? 'success')} /> : null}
          </div>
        );
      })}
      <div style={{position: 'absolute', left: g.chart.x, top: g.chart.y, width: g.chart.w, height: g.chart.h, borderRadius: 22, background: c.surface, border: `2px solid ${c.border}`, boxSizing: 'border-box'}} />
      {chartTitle ? <Txt s={chartTitle} color={c.text2} /> : null}
      {[0.33, 0.66].map((f) => (
        <div key={f} style={{position: 'absolute', left: g.chart.x + 20, width: g.chart.w - 40, top: g.plotBottom - (g.plotBottom - g.plotTop) * f, borderTop: '2px dashed rgba(255,255,255,0.07)'}} />
      ))}
      <div style={{position: 'absolute', left: g.chart.x + 20, width: g.chart.w - 40, top: g.plotBottom, borderTop: `2px solid ${c.border}`}} />
      {g.barRects.map((r, i) => {
        const grow = easeInOut(t, appear + 0.3 + i * 0.06, Math.max(appear + 0.5 + i * 0.06, growEnd));
        const on = hl === undefined || hl === i;
        return (
          <React.Fragment key={i}>
            <div
              style={{
                position: 'absolute',
                left: r.x,
                top: r.y + r.h * (1 - grow),
                width: r.w,
                height: r.h * grow,
                borderRadius: '12px 12px 4px 4px',
                background: on ? `linear-gradient(180deg, ${c.brandHover}, ${c.brand})` : 'rgba(255,255,255,0.16)',
                boxShadow: on && hl !== undefined ? `0 0 30px ${alpha(c.brand, 0.55)}` : undefined,
              }}
            />
            <Txt s={barLabels[i]} color={on && hl !== undefined ? c.text : c.muted} />
          </React.Fragment>
        );
      })}
    </div>
  );
};

const Device: React.FC<P<'device'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, aspects} = useEngine();
  const c = theme.colors;
  const g = geomDevice(block, w, aspects);
  const s = g.screen;
  const glare = lin(t, appear + 0.2, appear + 1.1);
  const next = reader(g.texts);
  const ui = g.ui;
  const title = ui ? next() : undefined;
  const subs: TextSpec[] = ui ? Array.from({length: ui.subLines}, () => next()) : [];
  const rowSpecs = ui ? ui.rows.map(() => next()) : [];
  const btnSpec = ui?.button ? next() : undefined;
  const r = g.phone ? 50 : 10;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {/* body */}
      <div
        style={{
          position: 'absolute',
          left: g.body.x,
          top: g.body.y,
          width: g.body.w,
          height: g.body.h,
          borderRadius: g.phone ? 66 : '26px 26px 10px 10px',
          background: 'linear-gradient(160deg, #2a2a33, #141419)',
          border: `2px solid ${c.borderStrong}`,
          boxShadow: '0 40px 90px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.12)',
          boxSizing: 'border-box',
        }}
      />
      {!g.phone ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: g.body.h - 2,
            width: w,
            height: 34,
            background: 'linear-gradient(180deg, #3a3a44, #1d1d24)',
            clipPath: 'polygon(3% 0, 97% 0, 100% 70%, 99% 100%, 1% 100%, 0 70%)',
          }}
        >
          <div style={{position: 'absolute', left: w / 2 - 70, top: 0, width: 140, height: 10, borderRadius: '0 0 10px 10px', background: '#15151b'}} />
        </div>
      ) : null}
      {/* screen */}
      <div style={{position: 'absolute', left: s.x, top: s.y, width: s.w, height: s.h, borderRadius: r, overflow: 'hidden', background: block.asset ? '#0e0e14' : c.surface}}>
        {block.asset ? <Img src={staticFile(block.asset)} style={{width: '100%', height: '100%', objectFit: block.fit ?? 'contain', display: 'block'}} /> : null}
        {glare > 0 && glare < 1 ? (
          <div style={{position: 'absolute', top: -s.h * 0.2, bottom: -s.h * 0.2, width: s.w * 0.35, left: mix(-s.w * 0.5, s.w * 1.2, EASE.inOutSine(glare)), background: 'linear-gradient(100deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.10) 50%, rgba(255,255,255,0) 100%)', transform: 'skewX(-14deg)'}} />
        ) : null}
      </div>
      {g.phone ? <div style={{position: 'absolute', left: w / 2 - 60, top: s.y + 14, width: 120, height: 34, borderRadius: 17, background: '#050507'}} /> : null}
      {ui && title ? (
        <>
          <div style={{position: 'absolute', left: ui.mark.x, top: ui.mark.y}}>
            <Logo variant="mark" width={ui.mark.w} height={ui.mark.h} />
          </div>
          <Txt s={title} color={c.text} />
          {subs.map((x, i) => (
            <Txt key={i} s={x} color={c.text2} />
          ))}
          {ui.rows.map((row, i) => {
            const at = appear + 0.35 + i * 0.16;
            const p = spc(t, at - LEAD.row, fps, SPRING.row);
            return (
              <div key={i} style={{opacity: p, transform: `translateY(${(1 - p) * 20}px)`}}>
                <div style={{position: 'absolute', left: row.x, top: row.y, width: row.w, height: row.h, borderRadius: 18, background: c.raised, border: `2px solid ${c.border}`, boxSizing: 'border-box'}} />
                <div style={{position: 'absolute', left: row.x + 20, top: row.y + (row.h - row.icon) / 2}}>
                  <Check at={at + 0.05} size={row.icon} />
                </div>
                <Txt s={rowSpecs[i]} color={c.text} />
              </div>
            );
          })}
          {ui.button && btnSpec ? (
            <div style={{opacity: lin(t, appear + 0.5, appear + 0.8)}}>
              <div style={{position: 'absolute', left: ui.button.x, top: ui.button.y, width: ui.button.w, height: ui.button.h, borderRadius: 20, background: `linear-gradient(135deg, ${c.brand}, ${c.brandHover})`, boxShadow: `0 12px 30px ${alpha(c.brand, 0.5)}`}} />
              <Txt s={btnSpec} color="#fff" />
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
};

const ImageBlock: React.FC<P<'image'>> = ({block, w, h, appear, sceneEnd}) => {
  const {t, aspects, ink} = useEngine();
  const g = geomImage(block, w, aspects);
  const reveal = block.reveal ?? 'mask';
  const rp = EASE.inOutCubic(lin(t, appear, appear + DUR.slower));
  const F = 22;
  const edge = rp * (100 + F) - F;
  const mask = reveal === 'mask' && rp < 1 ? `linear-gradient(180deg, black ${edge.toFixed(2)}%, transparent ${(edge + F).toFixed(2)}%)` : undefined;
  const opacity = reveal === 'fade' ? lin(t, appear, appear + DUR.medium) : 1;
  // slow settle 0.96 → 1 of the whole frame: never crops the asset and never leaves the box
  const kb = block.kenBurns ? mix(0.96, 1, EASE.inOutSine(lin(t, appear, sceneEnd ?? appear + 6))) : 1;
  const cap = g.texts[0];
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div
        style={{
          position: 'absolute',
          left: g.img.x,
          top: g.img.y,
          width: g.img.w,
          height: g.img.h,
          borderRadius: 24,
          overflow: 'hidden',
          opacity,
          maskImage: mask,
          WebkitMaskImage: mask,
          transform: kb !== 1 ? `scale(${kb})` : undefined,
        }}
      >
        <Img src={staticFile(block.asset)} style={{width: '100%', height: '100%', objectFit: 'contain', display: 'block'}} />
      </div>
      {cap ? <Txt s={cap} color={ink.text2} style={{opacity: lin(t, appear + 0.4, appear + 0.7)}} /> : null}
    </div>
  );
};

const Progress: React.FC<P<'progress'>> = ({block, w, h}) => {
  const {theme, t, fps, ink, surface} = useEngine();
  const c = {...theme.colors, text: ink.text, text2: ink.text2, muted: ink.muted};
  const g = geomProgress(block, w);
  const next = reader(g.texts);
  const title = block.title ? next() : undefined;
  const specs = block.steps.map(() => ({num: next(), label: next()}));
  const active = block.steps.filter((s) => t >= s.at - LEAD.block).length - 1;
  const first = g.steps[0];
  const last = g.steps[g.steps.length - 1];
  let fillTo = first ? first.cx : 0;
  block.steps.forEach((s, i) => {
    if (i === 0 || !g.steps[i]) return;
    const p = easeInOut(t, s.at - LEAD.block, s.at + DUR.base);
    if (p > 0) fillTo = mix(g.steps[i - 1].cx, g.steps[i].cx, p);
  });
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      {title ? <Txt s={title} color={c.text2} /> : null}
      {first && last ? (
        <>
          <div style={{position: 'absolute', left: first.cx, width: last.cx - first.cx, top: g.cy - 4, height: 8, borderRadius: 4, background: surface === 'light' ? alpha(c.light.text, 0.1) : 'rgba(255,255,255,0.12)'}} />
          <div style={{position: 'absolute', left: first.cx, width: Math.max(0, fillTo - first.cx), top: g.cy - 4, height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${c.success}, ${c.brand})`, boxShadow: `0 0 18px ${alpha(c.brand, 0.5)}`}} />
        </>
      ) : null}
      {block.steps.map((s, i) => {
        const st = g.steps[i];
        const isActive = i === active;
        const done = i < active;
        const pop = isActive ? mix(1.18, 1, spc(t, s.at - LEAD.block, fps, SPRING.pop)) : 1;
        const bg = done ? c.success : isActive ? c.brand : c.card;
        return (
          <React.Fragment key={i}>
            <div
              style={{
                position: 'absolute',
                left: st.cx - g.d / 2,
                top: g.cy - g.d / 2,
                width: g.d,
                height: g.d,
                borderRadius: g.d / 2,
                background: bg,
                border: done || isActive ? 'none' : `3px solid ${c.borderStrong}`,
                boxSizing: 'border-box',
                boxShadow: isActive ? `0 0 0 10px ${alpha(c.brand, 0.22)}, 0 0 30px ${alpha(c.brand, 0.6)}` : undefined,
                transform: `scale(${pop})`,
              }}
            />
            <Txt s={specs[i].num} color={done || isActive ? '#fff' : theme.colors.text2} />
            <Txt s={specs[i].label} color={isActive ? c.text : done ? c.text2 : c.muted} />
          </React.Fragment>
        );
      })}
    </div>
  );
};

const ScrollDemo: React.FC<P<'scroll-demo'>> = ({block, w, h, appear}) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  const g = geomScrollDemo(block, w);
  const off = g.scrollMax * EASE.inOutCubic(lin(t, appear, block.scrollEnd));
  const url = g.texts[0];
  const roleColor = (s: TextSpec) => (s.role === 'body' ? c.text2 : s.role === 'label' ? c.text2 : c.text);
  const thumbH = g.viewportH * Math.min(1, g.viewportH / Math.max(1, g.contentH));
  const thumbY = g.scrollMax > 0 ? (off / g.scrollMax) * (g.viewportH - thumbH) : 0;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={darkCard(theme)} />
      <div style={{position: 'absolute', left: 0, top: 0, width: w, height: g.chromeH, background: c.raised, borderRadius: `${theme.radius.card}px ${theme.radius.card}px 0 0`, borderBottom: `2px solid ${c.border}`, boxSizing: 'border-box'}} />
      {[c.danger, c.warning, c.success].map((col, i) => (
        <div key={col} style={{position: 'absolute', left: 30 + i * 32, top: g.chromeH / 2 - 10, width: 20, height: 20, borderRadius: 10, background: col, opacity: 0.85}} />
      ))}
      <div style={{position: 'absolute', left: 130, top: 18, width: w - 160, height: 52, borderRadius: 26, background: c.bg}} />
      <Txt s={url} color={c.text2} />
      <div style={{position: 'absolute', left: 2, top: g.chromeH, width: w - 4, height: g.viewportH - 2, overflow: 'hidden', borderRadius: `0 0 ${theme.radius.card - 2}px ${theme.radius.card - 2}px`}}>
        <div style={{position: 'absolute', left: -2, top: 0, width: w, height: g.contentH, transform: `translateY(${-off}px)`}}>
          {g.sections.map((s, i) => {
            const inner = g.innerW;
            if (s.kind === 'hero')
              return (
                <React.Fragment key={i}>
                  <div style={{position: 'absolute', left: 0, top: s.top, width: w, height: s.h, background: `linear-gradient(180deg, ${alpha(c.brand, 0.22)}, rgba(0,0,0,0))`}} />
                  <div style={{position: 'absolute', left: g.pad, top: s.top + s.h - 110, width: 220, height: 64, borderRadius: 32, background: `linear-gradient(135deg, ${c.brand}, ${c.brandHover})`, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                    <Icon name="arrowRight" size={36} color="#fff" stroke={3} />
                  </div>
                </React.Fragment>
              );
            if (s.kind === 'features' || s.kind === 'pricing') {
              const k = Math.max(1, Math.min(3, s.items.length || 3));
              const tw = (inner - (k - 1) * 20) / k;
              return (
                <React.Fragment key={i}>
                  {Array.from({length: k}).map((_, j) => (
                    <div key={j} style={{position: 'absolute', left: g.pad + j * (tw + 20), top: s.top + 130, width: tw, height: s.kind === 'pricing' ? 220 : 190, borderRadius: 22, background: c.raised, border: `2px solid ${s.kind === 'pricing' && j === 1 ? c.brand : c.border}`, boxSizing: 'border-box'}}>
                      {s.kind === 'features' ? (
                        <div style={{position: 'absolute', left: tw / 2 - 30, top: 26, width: 60, height: 60, borderRadius: 18, background: alpha(c.brand, 0.2), display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                          <Icon name={(['zap', 'shield', 'cloud'] as const)[j % 3]} size={34} color={c.brandText} />
                        </div>
                      ) : (
                        <>
                          <div style={{position: 'absolute', left: 24, right: 24, top: 30, height: 14, borderRadius: 7, background: 'rgba(255,255,255,0.12)'}} />
                          <div style={{position: 'absolute', left: 24, right: 60, top: 150, height: 12, borderRadius: 6, background: 'rgba(255,255,255,0.08)'}} />
                          <div style={{position: 'absolute', left: 24, right: 90, top: 176, height: 12, borderRadius: 6, background: 'rgba(255,255,255,0.08)'}} />
                        </>
                      )}
                    </div>
                  ))}
                </React.Fragment>
              );
            }
            if (s.kind === 'cta') return <div key={i} style={{position: 'absolute', left: g.pad - 14, top: s.top + 50, width: inner + 28, height: s.h - 100, borderRadius: 26, background: `linear-gradient(135deg, ${c.brand}, ${c.brandHover})`}} />;
            return (
              <React.Fragment key={i}>
                <div style={{position: 'absolute', left: g.pad, right: g.pad, top: s.top, borderTop: `2px solid ${c.border}`}} />
                {[0.9, 0.7].map((f, j) => (
                  <div key={j} style={{position: 'absolute', left: g.pad, width: inner * f, top: s.top + s.h - 70 + j * 26, height: 12, borderRadius: 6, background: 'rgba(255,255,255,0.07)'}} />
                ))}
              </React.Fragment>
            );
          })}
          {g.inner.map((s, i) => {
            const sec = g.sections.find((x) => s.y >= x.top && s.y < x.top + x.h);
            return <Txt key={i} s={s} color={sec?.kind === 'cta' ? '#fff' : roleColor(s)} />;
          })}
        </div>
        {g.scrollMax > 0 ? (
          <div style={{position: 'absolute', right: 8, top: 8, width: 8, height: g.viewportH - 16, borderRadius: 4, background: 'rgba(255,255,255,0.06)'}}>
            <div style={{position: 'absolute', left: 0, top: thumbY * ((g.viewportH - 16) / g.viewportH), width: 8, height: thumbH * ((g.viewportH - 16) / g.viewportH), borderRadius: 4, background: 'rgba(255,255,255,0.35)'}} />
          </div>
        ) : null}
      </div>
    </div>
  );
};

const Chart: React.FC<P<'chart'>> = ({block, w, h, appear}) => {
  const {theme, t, aspects} = useEngine();
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const c = theme.colors;
  const g = geomChart(block, w, aspects.polish);
  const next = reader(g.texts);
  const title = block.title ? next() : undefined;
  const specs = block.data.map(() => ({value: next(), label: next()}));
  const end = block.growEnd ?? appear + 0.9;
  const main = block.tone ? toneFill(theme, block.tone) : c.brand;
  const mainHi = block.tone ? toneColor(theme, block.tone) : c.brandHover;
  const hl = block.highlight;
  const n = block.data.length;
  const grid = [0.25, 0.5, 0.75].map((f) => <div key={f} style={{position: 'absolute', left: g.pad, right: g.pad, top: g.plotBottom - g.plotH * f, borderTop: '2px dashed rgba(255,255,255,0.07)'}} />);
  if (block.kind === 'line') {
    const prog = easeInOut(t, appear, end);
    const pts = g.points.map((p) => `${p.cx.toFixed(1)},${p.top.toFixed(1)}`).join(' ');
    const area = `${g.points[0]?.cx ?? 0},${g.plotBottom} ${pts} ${g.points[n - 1]?.cx ?? 0},${g.plotBottom}`;
    const x0 = g.points[0]?.cx ?? 0;
    const x1 = g.points[n - 1]?.cx ?? 0;
    const reveal = mix(x0, x1, prog);
    return (
      <div style={{position: 'relative', width: w, height: h}}>
        <div style={darkCard(theme)} />
        {title ? <Txt s={title} color={c.text2} /> : null}
        {grid}
        <div style={{position: 'absolute', left: g.pad, right: g.pad, top: g.plotBottom, borderTop: `2px solid ${c.border}`}} />
        <svg width={w} height={h} style={{position: 'absolute', left: 0, top: 0}}>
          <defs>
            <linearGradient id={`sb-area-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={main} stopOpacity={0.35} />
              <stop offset="100%" stopColor={main} stopOpacity={0} />
            </linearGradient>
            <clipPath id={`sb-clip-${uid}`}>
              <rect x={0} y={0} width={Math.max(0, reveal + 4)} height={h} />
            </clipPath>
          </defs>
          <g clipPath={`url(#sb-clip-${uid})`}>
            <polygon points={area} fill={`url(#sb-area-${uid})`} />
            <polyline points={pts} fill="none" stroke={mainHi} strokeWidth={7} strokeLinejoin="round" strokeLinecap="round" />
          </g>
        </svg>
        {g.points.map((p, i) => {
          const on = p.cx <= reveal + 1;
          const isHi = hl === i;
          const q = on ? 1 : 0;
          return (
            <React.Fragment key={i}>
              <div style={{position: 'absolute', left: p.cx - (isHi ? 14 : 10), top: p.top - (isHi ? 14 : 10), width: isHi ? 28 : 20, height: isHi ? 28 : 20, borderRadius: 14, background: isHi ? '#fff' : mainHi, border: isHi ? `5px solid ${main}` : 'none', boxSizing: 'border-box', opacity: q, boxShadow: isHi ? `0 0 0 10px ${alpha(main, 0.25)}` : undefined}} />
              <Txt s={specs[i].value} color={isHi ? c.text : c.text2} style={{opacity: on ? lin(t, appear, appear + 0.2) : 0}} />
              <Txt s={specs[i].label} color={c.muted} />
            </React.Fragment>
          );
        })}
      </div>
    );
  }
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={darkCard(theme)} />
      {title ? <Txt s={title} color={c.text2} /> : null}
      {grid}
      <div style={{position: 'absolute', left: g.pad, right: g.pad, top: g.plotBottom, borderTop: `2px solid ${c.border}`}} />
      {g.points.map((p, i) => {
        const s0 = appear + i * 0.08;
        const grow = easeInOut(t, s0, Math.max(s0 + DUR.base, end));
        const on = hl === undefined || hl === i;
        const bh = p.vh * grow;
        return (
          <React.Fragment key={i}>
            <div
              style={{
                position: 'absolute',
                left: p.bar.x,
                top: g.plotBottom - bh,
                width: p.bar.w,
                height: bh,
                borderRadius: '16px 16px 4px 4px',
                background: on ? `linear-gradient(180deg, ${mainHi}, ${main})` : 'rgba(255,255,255,0.16)',
                boxShadow: on && hl !== undefined ? `0 0 40px ${alpha(main, 0.55)}` : undefined,
              }}
            />
            <Txt s={specs[i].value} color={on ? c.text : c.text2} style={{opacity: lin(grow, 0.6, 1), transform: `translateY(${p.vh * (1 - grow)}px)`}}>
              {chartValueText(block, block.data[i].value)}
            </Txt>
            <Txt s={specs[i].label} color={on && hl !== undefined ? c.text : c.muted} />
          </React.Fragment>
        );
      })}
    </div>
  );
};

const FeatureCompare: React.FC<P<'feature-compare'>> = ({block, w, h}) => {
  const {theme, t, fps, motion: m, aspects} = useEngine();
  const c = theme.colors;
  const g = geomFeatureCompare(block, w, aspects.polish);
  const next = reader(g.texts);
  const title = block.title ? next() : undefined;
  const heads = block.columns.map(() => next());
  const rows = block.rows.map((r) => ({label: next(), values: r.values.map((v) => (typeof v === 'string' ? next() : undefined))}));
  const lastAt = block.rows.length ? Math.max(...block.rows.map((r) => r.at)) : 0;
  const hp = block.highlight !== undefined ? spc(t, block.highlightAt ?? lastAt + DUR.base, fps, SPRING.pop) : 0;
  const tableBottom = g.rowsY + block.rows.length * g.rowH;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={darkCard(theme)} />
      {title ? <Txt s={title} color={c.text2} /> : null}
      {block.highlight !== undefined && hp > 0 ? (
        <div
          style={{
            position: 'absolute',
            left: g.colX(block.highlight) + 4,
            top: g.y0 - 4,
            width: g.colW - 8,
            height: tableBottom - g.y0 + 8,
            borderRadius: 22,
            border: `3px solid ${c.brand}`,
            background: alpha(c.brand, 0.12),
            boxShadow: `0 0 ${44 * hp}px ${alpha(c.brand, 0.5)}`,
            opacity: Math.min(1, hp * 1.4),
            transform: `scale(${mix(0.96, 1, hp)})`,
            boxSizing: 'border-box',
          }}
        />
      ) : null}
      {heads.map((s, ci) => (
        <Txt key={ci} s={s} color={block.highlight === ci ? c.brandText : c.text2} />
      ))}
      {block.rows.map((r, ri) => {
        const p = spc(t, r.at - LEAD.card, fps, m.card.spring);
        const y = g.rowsY + ri * g.rowH;
        return (
          <div key={ri} style={{position: 'absolute', left: 0, top: 0, width: w, height: h, opacity: p, transform: `translateX(${(1 - p) * -40}px)`}}>
            <div style={{position: 'absolute', left: g.pad, right: g.pad, top: y, borderTop: `2px solid ${c.border}`}} />
            <Txt s={rows[ri].label} color={c.text2} />
            {r.values.map((v, ci) => {
              const cx = g.colX(ci) + g.colW / 2;
              const cy = y + g.rowH / 2;
              const at = r.at + 0.08 + ci * 0.08;
              if (typeof v === 'string') return <Txt key={ci} s={rows[ri].values[ci] as TextSpec} color={c.text} />;
              if (v)
                return (
                  <div key={ci} style={{position: 'absolute', left: cx - g.icon / 2, top: cy - g.icon / 2}}>
                    <Check at={at} size={g.icon} />
                  </div>
                );
              const q = spc(t, at, fps, SPRING.pop);
              return (
                <svg key={ci} width={g.icon} height={g.icon} viewBox="0 0 24 24" style={{position: 'absolute', left: cx - g.icon / 2, top: cy - g.icon / 2, transform: `scale(${q})`}}>
                  <circle cx="12" cy="12" r="11" fill={alpha(c.danger, 0.18)} />
                  <path d="M8.2 8.2l7.6 7.6M15.8 8.2l-7.6 7.6" stroke={c.danger} strokeWidth="2.6" strokeLinecap="round" />
                </svg>
              );
            })}
          </div>
        );
      })}
    </div>
  );
};

const LogoSting: React.FC<P<'logo-sting'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, motion: m, aspects, surface, ink} = useEngine();
  const c = {...theme.colors, text2: ink.text2};
  const g0 = geomLogoSting(block, w, aspects);
  // v2b: on the light backdrop the onDark logo is swapped for onLight (same geometry)
  const g = surface === 'light' && g0.variant === 'onDark' ? {...g0, variant: 'onLight' as const} : g0;
  const L = g.logo;
  const glow = spc(t, appear - LEAD.block, fps, SPRING.soft);
  const wipe = EASE.inOutCubic(lin(t, appear + 0.1, appear + 0.1 + DUR.slower * 0.8));
  const F = 16;
  const edge = wipe * (100 + F) - F;
  const mask = wipe < 1 ? `linear-gradient(90deg, black ${edge.toFixed(2)}%, transparent ${(edge + F).toFixed(2)}%)` : undefined;
  const scale = mix(0.94, 1, spc(t, appear, fps, SPRING.logo));
  const sheen = lin(t, appear + 0.75, appear + 1.3);
  const src = staticFile(theme.logo[g.variant]);
  const tag = g.texts[0];
  const tp = spc(t, appear + 0.55 - LEAD.word, fps, m.word.spring);
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(ellipse at 50% 45%, ${alpha(c.brand, 0.45 * glow)} 0%, rgba(0,0,0,0) 65%)`, transform: `scale(${mix(0.6, 1, glow)})`}} />
      <div style={{position: 'absolute', left: L.x, top: L.y, width: L.w, height: L.h, transform: `scale(${scale})`, maskImage: mask, WebkitMaskImage: mask, filter: 'drop-shadow(0 0 30px rgba(0,0,0,0.35))'}}>
        <Logo variant={g.variant} width={L.w} height={L.h} />
        {sheen > 0 && sheen < 1 ? (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              maskImage: `url(${src})`,
              WebkitMaskImage: `url(${src})`,
              maskSize: 'contain',
              WebkitMaskSize: 'contain',
              maskRepeat: 'no-repeat',
              WebkitMaskRepeat: 'no-repeat',
              maskPosition: 'center',
              WebkitMaskPosition: 'center',
              background: `linear-gradient(105deg, rgba(255,255,255,0) ${(sheen * 140 - 40).toFixed(1)}%, rgba(255,255,255,0.75) ${(sheen * 140 - 25).toFixed(1)}%, rgba(255,255,255,0) ${(sheen * 140 - 10).toFixed(1)}%)`,
            }}
          />
        ) : null}
      </div>
      {tag ? <Txt s={tag} color={c.text2} style={{opacity: tp, transform: `translateY(${(1 - tp) * 18}px)`}} /> : null}
    </div>
  );
};

const Outro: React.FC<P<'outro'>> = ({block, w, h, appear}) => {
  const {theme, t, fps, motion: m, aspects, surface, ink} = useEngine();
  const c = {...theme.colors, text: ink.text, text2: ink.text2};
  const g = geomOutro(block, w, aspects);
  const next = reader(g.texts);
  const tagline = block.tagline ? next() : undefined;
  const ctas = g.ctaLines.map(() => next());
  const url = next();
  const lp = spc(t, appear, fps, SPRING.logo);
  const urlAt = block.urlAt ?? appear + 0.6;
  const btn = spc(t, urlAt - LEAD.button, fps, SPRING.badge);
  const ring = lin(t, urlAt, urlAt + ACCENT.ring);
  const pulse = 1 + 0.02 * Math.sin(Math.max(0, t - urlAt - ACCENT.pulseDelay) * 5);
  const B = g.button;
  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={{position: 'absolute', left: g.logo.x, top: g.logo.y, width: g.logo.w, height: g.logo.h, opacity: Math.min(1, lp * 1.4), transform: `scale(${mix(0.9, 1, lp)})`, filter: 'drop-shadow(0 0 30px rgba(0,0,0,0.35))'}}>
        <Logo variant={surface === 'light' ? 'onLight' : 'onDark'} width={g.logo.w} height={g.logo.h} />
      </div>
      {tagline ? <Txt s={tagline} color={c.text2} style={{opacity: lin(t, appear + 0.25, appear + 0.5)}} /> : null}
      {ctas.map((s, i) => {
        const p = spc(t, appear + 0.35 + i * m.word.ctaStagger - LEAD.word, fps, m.word.spring);
        return <Txt key={i} s={s} color={c.text} style={{opacity: p, transform: `translateY(${(1 - p) * 30}px)`}} />;
      })}
      <div style={{position: 'absolute', left: B.x, top: B.y, width: B.w, height: B.h, transform: `scale(${btn * pulse})`}}>
        {ring > 0 && ring < 1 ? <div style={{position: 'absolute', inset: -30 * ring, borderRadius: 999, border: `5px solid ${alpha(c.brandText, 0.7 * (1 - ring))}`}} /> : null}
        <div style={{position: 'absolute', inset: 0, borderRadius: 999, background: `linear-gradient(135deg, ${c.brand}, ${c.brandHover})`, boxShadow: `0 20px 70px ${alpha(c.brand, 0.6)}`}} />
        <Txt s={{...url, x: url.x - B.x, y: 0}} color="#fff" />
        <div style={{position: 'absolute', right: 48, top: (B.h - g.arrow) / 2}}>
          <Icon name="arrowRight" size={g.arrow} color="#fff" stroke={3} />
        </div>
      </div>
    </div>
  );
};

/** Dispatch for the v2 block types. */
export const BlockV2View: React.FC<{block: BlockV2; w: number; h: number; appear: number; boxY: number; scale: number; sceneStart?: number; sceneEnd?: number}> = (p) => {
  const b = p.block;
  switch (b.type) {
    case 'kinetic-text':
      return <KineticText {...p} block={b} />;
    case 'counter':
      return <Counter {...p} block={b} />;
    case 'price-compare':
      return <PriceCompare {...p} block={b} />;
    case 'terminal':
      return <Terminal {...p} block={b} />;
    case 'dashboard':
      return <Dashboard {...p} block={b} />;
    case 'device':
      return <Device {...p} block={b} />;
    case 'image':
      return <ImageBlock {...p} block={b} />;
    case 'progress':
      return <Progress {...p} block={b} />;
    case 'scroll-demo':
      return <ScrollDemo {...p} block={b} />;
    case 'chart':
      return <Chart {...p} block={b} />;
    case 'feature-compare':
      return <FeatureCompare {...p} block={b} />;
    case 'logo-sting':
      return <LogoSting {...p} block={b} />;
    case 'outro':
      return <Outro {...p} block={b} />;
    case 'plan-card':
      return <PlanCard {...p} block={b} />;
    case 'install-flow':
      return <InstallFlow {...p} block={b} />;
    case 'server-stack':
      return <ServerStack {...p} block={b} />;
    case 'footage':
      return <Footage {...p} block={b} />;
    case 'composition':
      return <Composition {...p} block={b} />;
  }
};
