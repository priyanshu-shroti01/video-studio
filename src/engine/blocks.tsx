import React from 'react';
import {countValue, easeInOut, easeOut, lin, mix, spc} from './anim';
import {BlockV2View} from './blocks-v2';
import {CTA_FS, HEADLINE_FS, splitText, TEXT_FS, wrapWords} from './layout';
import {ACCENT, LEAD} from './motion/durations';
import {SPRING} from './motion/easings';
import {toneColor, toneFill} from './theme';
import {Block, BlockV2} from './types';
import {alpha, Card, Check, Cursor, Icon, inkTone, Logo, Pill, useEngine} from './ui';

export {firstInternalTime} from './layout';

/** Props every block renderer gets. All sizes are design units (the box is scaled by the scene). */
export type BlockProps<T extends Block['type']> = {
  block: Extract<Block, {type: T}>;
  w: number;
  h: number;
  appear: number;
  /** absolute y of the box top in px and the box scale (for elements that reach to the frame edge) */
  boxY: number;
  scale: number;
  /** v2: scene bounds (ken-burns etc.) and the absolute y a hook-tag string hangs from (0 = frame top) */
  sceneStart?: number;
  sceneEnd?: number;
  ceilingY?: number;
};

const LogoBlock: React.FC<BlockProps<'logo'>> = ({block, w, h, appear}) => {
  const {t, fps, surface} = useEngine();
  const p = spc(t, appear, fps, SPRING.logo);
  const variant = surface === 'light' && block.variant === 'onDark' ? 'onLight' : block.variant;
  return (
    <div style={{transform: `scale(${mix(0.88, 1, p)})`, filter: surface === 'light' ? 'drop-shadow(0 10px 30px rgba(21,17,28,0.10))' : 'drop-shadow(0 0 30px rgba(0,0,0,0.35))'}}>
      <Logo variant={variant} width={w} height={h} />
    </div>
  );
};

const Headline: React.FC<BlockProps<'headline'>> = ({block, w, appear}) => {
  const {theme, t, fps, sans, motion: m, ink} = useEngine();
  const fs = HEADLINE_FS[block.size];
  const lines = wrapWords(block.words.map((x) => x.text), fs, w);
  const align = block.align ?? 'center';
  return (
    <div style={{fontFamily: sans, fontWeight: 800, fontSize: fs, lineHeight: 1.08, letterSpacing: -0.025 * fs, textAlign: align}}>
      {lines.map((line, li) => (
        <div key={li} style={{whiteSpace: 'nowrap'}}>
          {line.map((wi) => {
            const word = block.words[wi];
            const p = spc(t, (word.at ?? appear + wi * m.word.stagger) - LEAD.word, fps, m.word.spring);
            const strike = block.strike && block.strike.word === wi ? easeOut(t, block.strike.at, block.strike.at + ACCENT.strike) : 0;
            return (
              <span
                key={wi}
                style={{
                  position: 'relative',
                  display: 'inline-block',
                  margin: `0 ${fs * 0.13}px`,
                  opacity: p,
                  transform: `translateY(${(1 - p) * fs * m.word.rise}px)`,
                  color: inkTone(ink, theme, word.tone, ink.text),
                }}
              >
                {word.text}
                {strike > 0 ? (
                  <span
                    style={{
                      position: 'absolute',
                      left: -fs * 0.06,
                      top: '52%',
                      height: fs * 0.1,
                      width: `${108 * strike}%`,
                      borderRadius: fs * 0.05,
                      background: toneColor(theme, block.strike?.tone ?? 'danger'),
                      transform: 'rotate(-3deg)',
                    }}
                  />
                ) : null}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};

const TextBlock: React.FC<BlockProps<'text'>> = ({block, w}) => {
  const {theme, sans, ink} = useEngine();
  const fs = TEXT_FS[block.size];
  const words = splitText(block.text);
  const lines = wrapWords(words, fs, w, 0.56);
  return (
    <div style={{fontFamily: sans, fontWeight: 700, fontSize: fs, lineHeight: 1.25, textAlign: 'center', color: inkTone(ink, theme, block.tone, ink.text2)}}>
      {lines.map((l, i) => (
        <div key={i} style={{whiteSpace: 'nowrap'}}>
          {l.map((x) => words[x]).join(' ')}
        </div>
      ))}
    </div>
  );
};

const PillBlock: React.FC<BlockProps<'pill'>> = ({block, appear}) => {
  const {theme, t, fps, ink} = useEngine();
  const fill = toneFill(theme, block.tone);
  if (block.stamp) {
    const s = spc(t, appear, fps, SPRING.stamp);
    return (
      <div style={{textAlign: 'center'}}>
        <div style={{display: 'inline-block', transform: `scale(${mix(1.6, 1, s)}) rotate(-4deg)`}}>
          <Pill bg={fill} color="#fff" style={{fontSize: 76, padding: '10px 44px', letterSpacing: 6, boxShadow: `0 16px 50px ${alpha(fill, 0.45)}`}}>
            {block.icon ? <Icon name={block.icon} size={70} color="#fff" stroke={2.8} /> : null}
            {block.text}
          </Pill>
        </div>
      </div>
    );
  }
  const color = inkTone(ink, theme, block.tone, ink.text);
  return (
    <div style={{textAlign: 'center'}}>
      <Pill bg={alpha(fill, 0.16)} color={color} style={{fontSize: 46, border: `3px solid ${fill}`, padding: '11px 36px'}}>
        {block.icon ? <Icon name={block.icon} size={46} color={color} stroke={2.6} /> : null}
        {block.text}
      </Pill>
    </div>
  );
};

const Price: React.FC<BlockProps<'price'>> = ({block, appear}) => {
  const {theme, t, fps, sans, ink} = useEngine();
  const c = {...theme.colors, text: ink.text, text2: ink.text2, muted: ink.muted};
  const end = block.countEnd ?? appear + ACCENT.count;
  const value = countValue(t, appear, end, block.countFrom ?? 0, block.amount);
  const land = spc(t, end, fps, SPRING.land);
  const breathe = 1 + 0.012 * Math.sin((t - appear) * 3);
  return (
    <div style={{textAlign: 'center', fontFamily: sans}}>
      {block.label ? <div style={{fontWeight: 700, fontSize: 46, lineHeight: '62px', color: c.text2}}>{block.label}</div> : null}
      <div style={{position: 'relative', display: 'inline-flex', alignItems: 'baseline', height: 300, transform: `scale(${mix(1.1, 1, land) * breathe})`}}>
        <div style={{position: 'absolute', inset: '-20px -60px', background: `radial-gradient(ellipse, ${alpha(c.brand, 0.45)} 0%, rgba(0,0,0,0) 70%)`}} />
        <span style={{position: 'relative', fontWeight: 800, fontSize: 280, lineHeight: '300px', letterSpacing: -10, color: c.text, textShadow: `8px 8px 0 ${c.brand}, 0 0 50px ${alpha(c.brand, 0.5)}`}}>
          {block.currency}
          {value}
        </span>
        {block.period ? <span style={{position: 'relative', fontWeight: 800, fontSize: 84, color: c.text2, marginLeft: 12}}>{block.period}</span> : null}
      </div>
      {block.note ? <div style={{fontWeight: 600, fontSize: 30, lineHeight: '44px', color: c.muted, opacity: lin(t, end, end + ACCENT.noteFade)}}>{block.note}</div> : null}
    </div>
  );
};

const Checklist: React.FC<BlockProps<'checklist'>> = ({block}) => {
  const {theme, t, fps, motion: m} = useEngine();
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: 22}}>
      {block.items.map((it, i) => {
        const p = spc(t, it.at - LEAD.row, fps, m.row.spring);
        return (
          <div key={i} style={{opacity: p, transform: `translateX(${(1 - p) * -m.row.travel}px)`}}>
            <Card style={{display: 'flex', alignItems: 'center', gap: 28, padding: '0 34px', height: 108}}>
              <Check at={it.at + 0.05} size={64} />
              {it.icon ? <Icon name={it.icon} size={54} color={theme.colors.brandText} /> : null}
              <div style={{fontWeight: 800, fontSize: 52, color: theme.colors.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{it.text}</div>
            </Card>
          </div>
        );
      })}
    </div>
  );
};

const BAR_MAX = 260;
const Bars: React.FC<BlockProps<'bars'>> = ({block, w, h}) => {
  const {theme, t, fps} = useEngine();
  const c = theme.colors;
  const maxV = Math.max(...block.bars.map((b) => b.value), 1e-9);
  const n = block.bars.length;
  const barW = Math.min(200, (w - 100) / n - 60);
  const slot = (w - 100) / n;
  const heights = block.bars.map((b) => (b.value / maxV) * BAR_MAX * easeInOut(t, b.at, b.growEnd ?? b.at + ACCENT.grow));
  const badge = block.badge;
  const bp = badge ? spc(t, badge.at, fps, SPRING.badge) : 0;
  const pulse = badge && t > badge.at + ACCENT.pulseDelay ? 1 + 0.04 * Math.sin((t - badge.at - ACCENT.pulseDelay) * 6) : 1;
  return (
    <Card style={{position: 'relative', height: h, padding: '36px 50px'}}>
      <div style={{fontWeight: 700, fontSize: 38, color: c.text2}}>{block.title}</div>
      <div style={{position: 'absolute', left: 50, right: 50, bottom: 92, borderTop: `2px solid ${c.border}`}} />
      {block.bars.map((b, i) => {
        const x = 50 + slot * i + (slot - barW) / 2;
        const col = toneColor(theme, b.tone, c.text2);
        return (
          <div key={i} style={{position: 'absolute', left: x, bottom: 92, width: barW}}>
            <div style={{height: heights[i], borderRadius: '18px 18px 4px 4px', background: col, boxShadow: b.tone === 'danger' ? `0 0 50px ${alpha(c.danger, 0.55)}` : 'none'}} />
            <div style={{position: 'absolute', top: '100%', width: barW, textAlign: 'center', marginTop: 18, fontWeight: 800, fontSize: 36, color: lin(t, b.at, b.at + 0.2) > 0.5 ? col : c.text2, whiteSpace: 'nowrap'}}>
              {b.label}
            </div>
          </div>
        );
      })}
      {badge && bp > 0 ? (
        <div style={{position: 'absolute', left: 50 + slot * badge.bar + slot / 2, bottom: 92 + heights[badge.bar] + 18, transform: `translateX(-50%) scale(${bp * pulse})`, transformOrigin: '50% 100%'}}>
          <Pill bg={toneFill(theme, badge.tone)} color="#fff" style={{fontSize: 64, padding: '4px 28px', gap: 6, boxShadow: `0 12px 40px ${alpha(toneFill(theme, badge.tone), 0.5)}`}}>
            <Icon name="arrowUp" size={52} color="#fff" stroke={3.2} />
            {badge.text}
          </Pill>
        </div>
      ) : null}
    </Card>
  );
};

const CompareRows: React.FC<BlockProps<'compare-rows'>> = ({block}) => {
  const {theme, t, fps, motion: m} = useEngine();
  const L = theme.colors.light;
  const badge = block.badge;
  const bp = badge ? spc(t, badge.at, fps, SPRING.sticker) : 0;
  // the card arrives with its first row (an explicit early `at` must not show an empty white card)
  const first = block.rows.length ? Math.min(...block.rows.map((r) => r.at)) : 0;
  const cardP = spc(t, first - LEAD.card, fps, m.card.spring);
  const rowTravel = (m.row.travel * 2) / 3;
  return (
    <div style={{paddingTop: 50, opacity: cardP, transform: `translateY(${(1 - cardP) * m.card.travel}px)`}}>
      <Card light style={{padding: '20px 40px', position: 'relative'}}>
        {block.rows.map((r, i) => {
          const p = spc(t, r.at - LEAD.card, fps, m.card.spring);
          return (
            <div
              key={i}
              style={{display: 'flex', alignItems: 'center', gap: 26, height: 110, borderTop: i ? `2px solid ${L.border}` : 'none', opacity: p, transform: `translateX(${(1 - p) * -rowTravel}px)`}}
            >
              <Check at={r.at} size={66} color={L.success} />
              <div style={{flex: 1, fontWeight: 700, fontSize: 48, color: L.text2}}>{r.label}</div>
              <div style={{fontWeight: 800, fontSize: 56, color: L.text, whiteSpace: 'nowrap'}}>{r.value}</div>
            </div>
          );
        })}
        {badge && bp > 0 ? (
          <div style={{position: 'absolute', right: -20, top: -40, transform: `scale(${bp}) rotate(4deg)`}}>
            <Pill bg={toneFill(theme, badge.tone)} color="#fff" style={{fontSize: 40, boxShadow: `0 14px 40px ${alpha(toneFill(theme, badge.tone), 0.45)}`}}>
              {badge.text}
            </Pill>
          </div>
        ) : null}
      </Card>
    </div>
  );
};

const Plans: React.FC<BlockProps<'plans'>> = ({block, w}) => {
  const {theme, t, fps} = useEngine();
  const c = theme.colors;
  const n = block.plans.length;
  const gap = 24;
  const cardW = (w - gap * (n - 1)) / n;
  const sel = block.select;
  const selP = sel ? lin(t, sel.clickAt, sel.clickAt + ACCENT.select) : 0;
  const emph = block.emphasizeAt !== undefined ? spc(t, block.emphasizeAt - LEAD.block, fps, SPRING.land) : 0;
  const emphBack = block.emphasizeAt !== undefined ? lin(t, block.emphasizeAt + ACCENT.emphasizeBackFrom, block.emphasizeAt + ACCENT.emphasizeBackTo) : 0;
  const cur = sel ? easeInOut(t, sel.cursorStart, sel.clickAt - 0.03) : 0;
  const target = sel ? {x: sel.index * (cardW + gap) + cardW / 2 + 20, y: 36 + 400} : {x: 0, y: 0};
  return (
    <div style={{position: 'relative', paddingTop: 36, display: 'flex', gap}}>
      {block.plans.map((p, i) => {
        const isSel = !!sel && sel.index === i;
        const scale = sel ? (isSel ? mix(1, 1.06, selP) : mix(1, 0.94, selP)) : 1;
        const dim = sel && !isSel ? mix(1, 0.45, selP) : 1;
        const priceScale = isSel ? mix(1, 1.12, emph) - 0.12 * emphBack : 1;
        return (
          <div key={i} style={{width: cardW, opacity: dim, transform: `scale(${scale})`}}>
            <Card
              style={{
                height: 450,
                padding: '34px 20px 26px',
                textAlign: 'center',
                position: 'relative',
                border: `${isSel ? 4 : 2}px solid ${isSel && selP > 0 ? c.brand : c.border}`,
                boxShadow: isSel && selP > 0 ? `0 0 ${60 * selP}px ${alpha(c.brand, 0.6)}, 0 30px 80px rgba(0,0,0,0.5)` : undefined,
              }}
            >
              {p.badge ? (
                <div style={{position: 'absolute', left: 0, right: 0, top: -26, textAlign: 'center'}}>
                  <Pill bg={c.brand} color="#fff" style={{fontSize: 26, padding: '8px 20px'}}>
                    {p.badge}
                  </Pill>
                </div>
              ) : null}
              <div style={{fontWeight: 800, fontSize: 46, color: c.text, whiteSpace: 'nowrap'}}>{p.name}</div>
              <div style={{fontWeight: 800, fontSize: Math.min(92, cardW / Math.max(3, p.price.length) / 0.62), letterSpacing: -3, color: isSel ? c.text : c.text2, marginTop: 14, transform: `scale(${priceScale})`, whiteSpace: 'nowrap'}}>
                {p.price}
              </div>
              <div style={{fontWeight: 700, fontSize: 30, color: c.muted, height: 36}}>{p.period ?? ''}</div>
              <div style={{marginTop: 18, paddingTop: 18, borderTop: `2px solid ${c.border}`, fontWeight: 700, fontSize: 28, color: c.text2, height: 40, whiteSpace: 'nowrap'}}>{p.detail ?? ''}</div>
              <div style={{position: 'absolute', left: 20, right: 20, bottom: 26, borderRadius: 16, padding: '16px 0', fontWeight: 800, fontSize: 30, background: isSel && selP > 0.5 ? c.brand : 'rgba(255,255,255,0.08)', color: '#fff'}}>
                {isSel && selP > 0.5 ? 'Selected ✓' : 'Choose'}
              </div>
            </Card>
          </div>
        );
      })}
      {sel && t > sel.cursorStart - 0.1 ? (
        <Cursor x={mix(w * 0.95, target.x, cur)} y={mix(36 + 470, target.y, cur)} clickAt={sel.clickAt} opacity={lin(t, sel.cursorStart - 0.1, sel.cursorStart + 0.1)} />
      ) : null}
    </div>
  );
};

const DomainInput: React.FC<BlockProps<'domain-input'>> = ({block, w}) => {
  const {theme, t, fps, sans, mono} = useEngine();
  const c = theme.colors;
  const L = c.light;
  const typed = block.keyTimes.filter((k) => t >= k).length;
  const caret = typed < block.domain.length || Math.floor(t * ACCENT.caretHz) % 2 === 0;
  const avail = spc(t, block.availableAt, fps, SPRING.pop);
  const b = block.button;
  const btnIn = spc(t, block.availableAt - LEAD.block, fps, SPRING.button);
  const pressed = t >= b.clickAt && t < b.clickAt + 0.14;
  const fill = easeInOut(t, b.clickAt + 0.08, b.doneAt);
  const done = t >= b.doneAt;
  const doneP = spc(t, b.doneAt, fps, SPRING.sticker);
  const ca = easeInOut(t, block.availableAt + 0.05, b.clickAt - 0.05);
  const btnY = 40 + 76 + 112 + 14 + 64 + 18;
  return (
    <div style={{position: 'relative'}}>
      <Card light style={{padding: '40px 44px 44px', height: 490}}>
        <div style={{fontWeight: 800, fontSize: 50, lineHeight: '50px', color: L.text, marginBottom: 26}}>{block.title}</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 20, height: 112, padding: '0 28px', borderRadius: 20, border: `3px solid ${typed > 0 ? c.brand : L.border}`, background: L.surface, boxSizing: 'border-box'}}>
          <Icon name="globe" size={50} color={L.muted} />
          <div style={{fontFamily: mono, fontSize: 56, color: L.text, letterSpacing: -1, whiteSpace: 'nowrap'}}>
            {block.domain.slice(0, typed)}
            <span style={{display: 'inline-block', width: 4, height: 60, marginLeft: 4, verticalAlign: 'middle', background: c.brand, opacity: caret ? 1 : 0}} />
          </div>
        </div>
        <div style={{height: 64, display: 'flex', alignItems: 'center', gap: 14, marginTop: 14, opacity: avail, fontFamily: sans, fontWeight: 700, fontSize: 36, color: L.success, whiteSpace: 'nowrap'}}>
          <Check at={block.availableAt} size={44} color={L.success} />
          {/* proportional font here: monospace gives "." a full cell and reads as "name .in" */}
          <span>
            <span style={{fontWeight: 800}}>{block.domain}</span> {block.availableText}
          </span>
        </div>
        <div
          style={{
            position: 'relative',
            overflow: 'hidden',
            marginTop: 18,
            height: 116,
            borderRadius: 22,
            background: done ? c.success : pressed ? c.brandActive : c.brand,
            opacity: btnIn,
            transform: `scale(${pressed ? 0.97 : 1}) translateY(${(1 - btnIn) * 30}px)`,
            boxShadow: done ? `0 0 ${50 * doneP}px ${alpha(c.success, 0.55)}` : `0 14px 40px ${alpha(c.brand, 0.45)}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 800,
            fontSize: 50,
          }}
        >
          {!done && fill > 0 ? <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${fill * 100}%`, background: 'rgba(255,255,255,0.22)'}} /> : null}
          <span style={{position: 'relative', display: 'flex', alignItems: 'center', gap: 18, whiteSpace: 'nowrap'}}>
            {done ? (
              <>
                <span style={{width: 26, height: 26, borderRadius: 13, background: '#fff', boxShadow: `0 0 0 ${8 + 6 * Math.sin(t * 6)}px rgba(255,255,255,0.25)`}} />
                {b.done}
              </>
            ) : fill > 0 ? (
              b.busy
            ) : (
              <>
                {b.idle} <Icon name="arrowRight" size={50} color="#fff" stroke={3} />
              </>
            )}
          </span>
        </div>
      </Card>
      {t > block.availableAt && t < b.doneAt + 0.6 ? (
        <Cursor x={mix(w + 20, w * 0.62, ca)} y={mix(490 + 40, btnY + 58, ca)} clickAt={b.clickAt} opacity={lin(t, block.availableAt, block.availableAt + 0.15) * (1 - lin(t, b.doneAt + 0.3, b.doneAt + 0.6))} />
      ) : null}
    </div>
  );
};

const Browser: React.FC<BlockProps<'browser'>> = ({block, h, appear}) => {
  const {theme, t, fps, mono} = useEngine();
  const c = theme.colors;
  const stall = block.stallAt ?? block.loadUntil;
  const crawl = mix(0.06, 0.32, easeOut(t, appear + 0.1, block.loadUntil)) + 0.03 * lin(t, block.loadUntil, block.loadUntil + 3);
  const stalled = lin(t, stall, stall + 0.25) > 0.5;
  const barColor = stalled ? c.danger : c.warning;
  const secs = Math.max(0, (t - appear) * 2.1 + 1.2);
  const tag = block.tag;
  const tp = tag ? spc(t, tag.at, fps, SPRING.badge) : 0;
  const shake = tag && t > tag.at ? Math.sin((t - tag.at) * 40) * 6 * Math.max(0, 1 - (t - tag.at) * 2.5) : 0;
  return (
    <div style={{position: 'relative'}}>
      <Card style={{overflow: 'hidden', height: h}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 14, padding: '26px 30px', height: 104, boxSizing: 'border-box', borderBottom: `2px solid ${c.border}`, background: c.raised}}>
          {[c.danger, c.warning, c.success].map((col) => (
            <div key={col} style={{width: 22, height: 22, borderRadius: 11, background: col, opacity: 0.85}} />
          ))}
          <div style={{marginLeft: 18, flex: 1, height: 52, borderRadius: 26, background: c.bg, color: c.text2, fontFamily: mono, fontSize: 30, display: 'flex', alignItems: 'center', paddingLeft: 26, whiteSpace: 'nowrap', overflow: 'hidden'}}>
            {block.url}
          </div>
        </div>
        <div style={{height: 10, background: 'rgba(255,255,255,0.06)'}}>
          <div style={{height: 10, width: `${crawl * 100}%`, background: barColor, boxShadow: `0 0 18px ${barColor}`}} />
        </div>
        <div style={{padding: '36px 40px', display: 'flex', flexDirection: 'column', gap: 22}}>
          {[0.7, 0.95, 0.85, 0.5].map((wf, i) => (
            <div key={i} style={{height: i === 0 ? 56 : 30, width: `${wf * 100}%`, borderRadius: 12, background: `rgba(255,255,255,${0.07 + 0.03 * Math.sin(t * 5 + i)})`}} />
          ))}
          <div style={{display: 'flex', alignItems: 'center', gap: 22, marginTop: 6}}>
            <svg width="52" height="52" viewBox="0 0 50 50" style={{transform: `rotate(${t * 400}deg)`}}>
              <circle cx="25" cy="25" r="20" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="6" />
              <path d="M25 5a20 20 0 0 1 20 20" fill="none" stroke={barColor} strokeWidth="6" strokeLinecap="round" />
            </svg>
            <div style={{fontFamily: mono, fontSize: 38, color: stalled ? c.danger : c.text2}}>Loading… {secs.toFixed(1)}s</div>
          </div>
        </div>
      </Card>
      {/* sticker sits on the card's own top bar — never above the card, so it can't cover text above */}
      {tag && tp > 0 ? (
        <div style={{position: 'absolute', right: -30, top: 18, transform: `scale(${tp}) rotate(${8 + shake}deg)`}}>
          <Pill bg={c.light.card} color={c.danger} style={{fontSize: 44, boxShadow: '0 14px 40px rgba(0,0,0,0.5)', border: `3px solid ${c.danger}`}}>
            {tag.text}
          </Pill>
        </div>
      ) : null}
    </div>
  );
};

const HookTag: React.FC<BlockProps<'hook-tag'>> = ({block, w, appear, boxY, scale, ceilingY = 0}) => {
  const {theme, t, fps, sans, surface} = useEngine();
  const c = theme.colors;
  // design units from the box top up to the anchor: the frame top, or (v2) just below the brand bar /
  // a top-centre watermark, so the string never crosses the logo
  const reach = (boxY - ceilingY) / scale;
  const drop = spc(t, appear - LEAD.drop, fps, SPRING.drop);
  const k = Math.max(0, t - appear);
  const swing = t < appear ? 0 : 16 * Math.exp(-0.9 * k) * Math.sin(k * 5.2) + 2 * Math.sin(t * 2.2);
  const tag = (
    <div style={{position: 'relative', width: w, height: 330, transformOrigin: `${w / 2}px ${-reach}px`, transform: `rotate(${swing}deg) translateY(${(drop - 1) * (reach + 330)}px)`}}>
      <div style={{position: 'absolute', left: w / 2 - 2, top: -reach, width: 4, height: reach + 20, background: surface === 'light' ? alpha(c.light.text, 0.3) : 'rgba(255,255,255,0.35)'}} />
      <svg width="90" height="110" viewBox="0 0 90 110" style={{position: 'absolute', left: w / 2 - 45, top: 0}}>
        <path d="M45 0v60a24 24 0 1 1-30-23" fill="none" stroke="#d5d5dc" strokeWidth="9" strokeLinecap="round" />
        <path d="M15 37l-6 18 16-6z" fill="#d5d5dc" />
      </svg>
      <div style={{position: 'absolute', left: 30, right: 30, top: 100, transform: 'rotate(-3deg)'}}>
        <Card light style={{padding: '26px 30px', textAlign: 'center'}}>
          <div style={{fontFamily: sans, fontWeight: 800, fontSize: 30, letterSpacing: 4, color: c.warning}}>{block.label}</div>
          <div style={{fontFamily: sans, fontWeight: 800, fontSize: 84, lineHeight: 1.1, color: c.light.text, letterSpacing: -2}}>{block.text}</div>
          {block.sub ? <div style={{fontFamily: sans, fontWeight: 600, fontSize: 28, color: c.light.muted}}>{block.sub}</div> : null}
        </Card>
      </div>
    </div>
  );
  if (ceilingY <= 0) return tag;
  // clip at the anchor: the dropping tag appears from under the brand bar instead of passing over it
  return <div style={{clipPath: `inset(${-reach}px -2000px -2000px -2000px)`}}>{tag}</div>;
};

const FlatLine: React.FC<BlockProps<'flat-line'>> = ({block, w, h, appear}) => {
  const {theme, t} = useEngine();
  const c = theme.colors;
  const line = easeOut(t, appear, block.drawEnd);
  const n = block.points.length;
  const x0 = 90;
  const span = w - 2 * x0;
  return (
    <Card style={{position: 'relative', height: h, padding: '40px 50px'}}>
      <div style={{fontWeight: 700, fontSize: 36, color: c.text2}}>{block.title}</div>
      <div style={{position: 'absolute', left: x0, top: 190, height: 8, width: span * line, borderRadius: 4, background: c.success, boxShadow: `0 0 24px ${alpha(c.success, 0.6)}`}} />
      {block.points.map((pt, i) => {
        const pos = n === 1 ? 0 : i / (n - 1);
        // fully visible exactly when the line reaches it (the last point included)
        const p = pos === 0 ? lin(line, 0, 0.08) : lin(line, pos - 0.12, pos);
        return (
          <div key={i} style={{position: 'absolute', left: x0 + pos * span - 90, top: 120, width: 180, textAlign: 'center', opacity: p}}>
            <div style={{fontWeight: 800, fontSize: 44, color: c.text, whiteSpace: 'nowrap'}}>{pt.value}</div>
            <div style={{margin: '18px auto', width: 30, height: 30, borderRadius: 15, background: c.success}} />
            <div style={{fontWeight: 700, fontSize: 28, color: c.muted, whiteSpace: 'nowrap'}}>{pt.label}</div>
          </div>
        );
      })}
    </Card>
  );
};

const Cta: React.FC<BlockProps<'cta'>> = ({block, w, appear}) => {
  const {theme, t, fps, sans, motion: m, ink} = useEngine();
  const rise = 40 * (m.word.rise / 0.33);
  const c = {...theme.colors, text: ink.text, text2: ink.text2};
  const words = splitText(block.text);
  const lines = wrapWords(words, CTA_FS, w);
  const btn = spc(t, block.urlAt - LEAD.button, fps, SPRING.badge);
  const ring = lin(t, block.urlAt, block.urlAt + ACCENT.ring);
  const pulse = 1 + 0.025 * Math.sin(Math.max(0, t - block.urlAt - ACCENT.pulseDelay) * 5);
  const press = block.clickAt !== undefined && t >= block.clickAt && t < block.clickAt + 0.12 ? 0.96 : 1;
  const textH = lines.length * CTA_FS * 1.1;
  const cur = block.clickAt !== undefined ? easeOut(t, block.urlAt + 0.1, block.clickAt - 0.02) : 0;
  return (
    <div style={{position: 'relative', textAlign: 'center', fontFamily: sans}}>
      <div style={{fontWeight: 800, fontSize: CTA_FS, lineHeight: 1.1, letterSpacing: -3, color: c.text, height: textH}}>
        {lines.map((l, li) => (
          <div key={li} style={{whiteSpace: 'nowrap'}}>
            {l.map((wi) => {
              const p = spc(t, appear + wi * m.word.ctaStagger - LEAD.word, fps, m.word.spring);
              return (
                <span key={wi} style={{display: 'inline-block', margin: '0 14px', opacity: p, transform: `translateY(${(1 - p) * rise}px)`}}>
                  {words[wi]}
                </span>
              );
            })}
          </div>
        ))}
      </div>
      <div style={{height: 30}} />
      <div style={{position: 'relative', display: 'inline-block', height: 150, transform: `scale(${btn * pulse * press})`}}>
        {ring > 0 && ring < 1 ? <div style={{position: 'absolute', inset: -40 * ring, borderRadius: 999, border: `5px solid ${alpha(c.brandText, 0.7 * (1 - ring))}`}} /> : null}
        <Pill bg={`linear-gradient(135deg, ${c.brand}, ${c.brandHover})`} color="#fff" style={{fontSize: 76, padding: '28px 56px', gap: 22, boxShadow: `0 20px 70px ${alpha(c.brand, 0.6)}`, letterSpacing: -1}}>
          {block.url} <Icon name="arrowRight" size={68} color="#fff" stroke={3} />
        </Pill>
      </div>
      {block.sub ? <div style={{marginTop: 24, height: 46, fontWeight: 700, fontSize: 36, color: c.text2, opacity: lin(t, block.urlAt + 0.3, block.urlAt + 0.7), whiteSpace: 'nowrap'}}>{block.sub}</div> : null}
      {block.clickAt !== undefined && t > block.urlAt + 0.1 ? (
        <Cursor x={mix(w * 0.95, w * 0.62, cur)} y={mix(textH + 200, textH + 30 + 95, cur)} clickAt={block.clickAt} opacity={lin(t, block.urlAt + 0.1, block.urlAt + 0.3)} />
      ) : null}
    </div>
  );
};

export type BlockViewProps = {block: Block; w: number; h: number; appear: number; boxY: number; scale: number; sceneStart?: number; sceneEnd?: number; ceilingY?: number};

/** Dispatch by block type. */
export const BlockView: React.FC<BlockViewProps> = (p) => {
  const b = p.block;
  switch (b.type) {
    case 'logo':
      return <LogoBlock {...p} block={b} />;
    case 'headline':
      return <Headline {...p} block={b} />;
    case 'text':
      return <TextBlock {...p} block={b} />;
    case 'pill':
      return <PillBlock {...p} block={b} />;
    case 'price':
      return <Price {...p} block={b} />;
    case 'checklist':
      return <Checklist {...p} block={b} />;
    case 'bars':
      return <Bars {...p} block={b} />;
    case 'compare-rows':
      return <CompareRows {...p} block={b} />;
    case 'plans':
      return <Plans {...p} block={b} />;
    case 'domain-input':
      return <DomainInput {...p} block={b} />;
    case 'browser':
      return <Browser {...p} block={b} />;
    case 'hook-tag':
      return <HookTag {...p} block={b} />;
    case 'flat-line':
      return <FlatLine {...p} block={b} />;
    case 'cta':
      return <Cta {...p} block={b} />;
    default:
      return <BlockV2View {...p} block={b as BlockV2} />;
  }
};
