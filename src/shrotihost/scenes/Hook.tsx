import React from 'react';
import {easeInOut, easeOut, life, lin, mix, sp} from '../anim';
import {B, BT, MONO, SANS, TL} from '../brand';
import {At, Card, Pill} from '../ui';

/** Act 1 (0 → "Most"): "Building a website in India? Stop overpaying for slow hosting." */
export const Hook: React.FC<{t: number}> = ({t}) => {
  const [, end] = TL.acts.hook;
  const swap = BT.stop - 0.12; // question exits, "Stop" beat enters
  return (
    <>
      {t < swap + 0.05 ? <Question t={t} out={swap} /> : null}
      {t >= swap - 0.05 ? <SlowHosting t={t} start={swap} end={end} /> : null}
    </>
  );
};

const Question: React.FC<{t: number; out: number}> = ({t, out}) => {
  const lines: {text: string; at: number; color?: string}[][] = [
    [{text: 'Building a', at: BT.building}],
    [{text: 'website', at: BT.website}, {text: 'in', at: BT.in}],
    [{text: 'India?', at: BT.india, color: B.purpleText}],
  ];
  const o = 1 - Math.pow(lin(t, out - 0.2, out), 1.5);
  const push = mix(1, 1.05, easeInOut(t, 0, out)); // slow push-in: never fully still
  const underline = easeOut(t, BT.india + 0.15, BT.india + 0.5);
  return (
    <At y={560} w={1000} style={{opacity: o, transform: `scale(${push}) translateY(${-40 * lin(t, out - 0.2, out)}px)`, textAlign: 'center'}}>
      {lines.map((ln, i) => (
        <div key={i} style={{fontFamily: SANS, fontWeight: 800, fontSize: 150, lineHeight: 1.08, letterSpacing: -4, color: B.text}}>
          {ln.map((w, j) => {
            const p = sp(t, w.at - 0.06, 13, 0.6);
            return (
              <span key={j} style={{display: 'inline-block', margin: '0 18px', opacity: p, transform: `translateY(${(1 - p) * 50}px)`, color: w.color ?? B.text}}>
                {w.text}
              </span>
            );
          })}
        </div>
      ))}
      <div style={{margin: '18px auto 0', width: 420 * underline, height: 14, borderRadius: 7, background: `linear-gradient(90deg, ${B.purple}, ${B.purpleHover})`, boxShadow: `0 0 30px ${B.purple}`}} />
    </At>
  );
};

const SlowHosting: React.FC<{t: number; start: number; end: number}> = ({t, start, end}) => {
  const o = life(t, start, end);
  const stamp = sp(t, BT.stop, 11, 0.6);
  const strike = easeOut(t, BT.overpaying + 0.35, BT.overpaying + 0.7);
  const card = sp(t, BT.overpaying - 0.05, 15, 0.8);
  // page load crawls, then stalls on "slow" and turns red
  const crawl = mix(0.06, 0.3, easeOut(t, start + 0.2, BT.slow)) + 0.03 * lin(t, BT.slow, end);
  const stalled = lin(t, BT.slow, BT.slow + 0.25);
  const secs = Math.max(0, (t - start) * 2.1 + 1.2);
  const barColor = stalled > 0.5 ? B.error : B.warning;
  const tag = sp(t, BT.overpaying + 0.05, 9, 0.6);
  const shake = Math.sin((t - BT.overpaying) * 40) * 6 * Math.max(0, 1 - (t - BT.overpaying) * 2.5) * (t > BT.overpaying ? 1 : 0);
  return (
    <div style={{opacity: o}}>
      <At y={250} w={1000} style={{textAlign: 'center'}}>
        <div style={{display: 'inline-block', transform: `scale(${mix(1.6, 1, stamp)}) rotate(-4deg)`, opacity: Math.min(1, stamp * 1.5)}}>
          <Pill bg={B.error} color="#fff" style={{fontSize: 76, padding: '10px 44px', letterSpacing: 6, boxShadow: '0 16px 50px rgba(240,87,107,0.45)'}}>
            STOP
          </Pill>
        </div>
        <div style={{position: 'relative', display: 'inline-block', marginTop: 34, fontFamily: SANS, fontWeight: 800, fontSize: 132, letterSpacing: -4, color: B.text, opacity: sp(t, BT.overpaying - 0.05)}}>
          overpaying
          <div style={{position: 'absolute', left: -10, top: '54%', height: 14, width: `${104 * strike}%`, background: B.error, borderRadius: 7, transform: 'rotate(-3deg)', boxShadow: '0 0 24px rgba(240,87,107,0.6)'}} />
        </div>
        <div style={{fontFamily: SANS, fontWeight: 700, fontSize: 64, color: B.text2, marginTop: 4, opacity: sp(t, BT.slow - 0.1)}}>
          for <span style={{color: B.error}}>slow</span> hosting
        </div>
      </At>

      <At y={680} w={880} style={{opacity: card, transform: `translateY(${(1 - card) * 120}px)`}}>
        <Card style={{overflow: 'hidden'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 14, padding: '26px 30px', borderBottom: `2px solid ${B.border}`, background: B.raised, borderRadius: '30px 30px 0 0'}}>
            {['#f0576b', '#f5a524', '#22c55e'].map((c) => (
              <div key={c} style={{width: 22, height: 22, borderRadius: 11, background: c, opacity: 0.85}} />
            ))}
            <div style={{marginLeft: 18, flex: 1, height: 52, borderRadius: 26, background: B.bg, color: B.text2, fontFamily: MONO, fontSize: 30, display: 'flex', alignItems: 'center', paddingLeft: 26}}>
              your-website.in
            </div>
          </div>
          <div style={{height: 10, background: 'rgba(255,255,255,0.06)'}}>
            <div style={{height: 10, width: `${crawl * 100}%`, background: barColor, boxShadow: `0 0 18px ${barColor}`}} />
          </div>
          <div style={{padding: 40, display: 'flex', flexDirection: 'column', gap: 22}}>
            {[0.7, 0.95, 0.85, 0.5].map((w, i) => (
              <div key={i} style={{height: i === 0 ? 56 : 30, width: `${w * 100}%`, borderRadius: 12, background: `rgba(255,255,255,${0.07 + 0.03 * Math.sin(t * 5 + i)})`}} />
            ))}
            <div style={{display: 'flex', alignItems: 'center', gap: 22, marginTop: 14}}>
              <svg width="56" height="56" viewBox="0 0 50 50" style={{transform: `rotate(${t * 400}deg)`}}>
                <circle cx="25" cy="25" r="20" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="6" />
                <path d="M25 5a20 20 0 0 1 20 20" fill="none" stroke={barColor} strokeWidth="6" strokeLinecap="round" />
              </svg>
              <div style={{fontFamily: MONO, fontSize: 40, color: stalled > 0.5 ? B.error : B.text2}}>Loading… {secs.toFixed(1)}s</div>
            </div>
          </div>
        </Card>
        <div style={{position: 'absolute', right: -30, top: 20, transform: `scale(${tag}) rotate(${8 + shake}deg)`}}>
          <Pill bg={B.light.card} color={B.error} style={{fontSize: 46, boxShadow: '0 14px 40px rgba(0,0,0,0.5)', border: `3px solid ${B.error}`}}>
            ₹₹₹ /mo
          </Pill>
        </div>
      </At>
    </div>
  );
};
