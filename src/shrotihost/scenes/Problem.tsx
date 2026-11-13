import React from 'react';
import {easeInOut, easeOut, life, lin, mix, sp} from '../anim';
import {B, BT, TL} from '../brand';
import {At, Card, Icon, Pill} from '../ui';

/** Act 2: "Most hosts hook you with cheap intros, then triple the price on renewal." */
export const Problem: React.FC<{t: number}> = ({t}) => {
  const [start, end] = TL.acts.problem;
  const o = life(t, start, end);
  // the "intro offer" tag drops on a fishing line and swings (damped pendulum)
  const drop = sp(t, BT.hook - 0.1, 12, 0.8);
  const k = Math.max(0, t - BT.hook);
  const swing = t < BT.hook ? 0 : 16 * Math.exp(-0.9 * k) * Math.sin(k * 5.2) + 2 * Math.sin(t * 2.2);
  const cheap = sp(t, BT.cheap - 0.05);
  // bars: intro (1x) rises on "cheap", renewal climbs to 3x on "triple"
  const chart = sp(t, BT.cheap - 0.15, 15, 0.8);
  const introH = 100 * easeOut(t, BT.cheap, BT.cheap + 0.45);
  const renewH = mix(0, 300, easeInOut(t, BT.triple - 0.05, BT.triple + 0.55));
  const badge = sp(t, BT.triple + 0.55, 9, 0.6);
  const pulse = 1 + 0.04 * Math.sin(Math.max(0, t - BT.triple - 0.9) * 6) * (t > BT.triple + 0.9 ? 1 : 0);
  const renewalLabel = lin(t, BT.renewal - 0.1, BT.renewal + 0.15);
  return (
    <div style={{opacity: o}}>
      {/* hook + line + tag */}
      <div style={{position: 'absolute', left: 540, top: 0, transformOrigin: '0 0', transform: `rotate(${swing}deg) translateY(${(drop - 1) * 520}px)`}}>
        <div style={{position: 'absolute', left: -2, top: 0, width: 4, height: 300, background: 'rgba(255,255,255,0.35)'}} />
        <svg width="90" height="110" viewBox="0 0 90 110" style={{position: 'absolute', left: -45, top: 280}}>
          <path d="M45 0v60a24 24 0 1 1-30-23" fill="none" stroke="#d5d5dc" strokeWidth="9" strokeLinecap="round" />
          <path d="M15 37l-6 18 16-6z" fill="#d5d5dc" />
        </svg>
        <div style={{position: 'absolute', left: -230, top: 380, width: 460, transform: 'rotate(-3deg)'}}>
          <Card light style={{padding: '30px 36px', textAlign: 'center', borderRadius: 26}}>
            <div style={{fontWeight: 800, fontSize: 32, letterSpacing: 4, color: B.warning}}>INTRO OFFER</div>
            <div style={{fontWeight: 800, fontSize: 88, color: B.light.text, letterSpacing: -2, transform: `scale(${mix(0.7, 1, cheap)})`, opacity: cheap}}>Cheap!</div>
            <div style={{fontWeight: 600, fontSize: 30, color: B.light.muted}}>first term only</div>
          </Card>
        </div>
      </div>

      {/* bill chart */}
      <At y={680} w={900} style={{opacity: chart, transform: `translateY(${(1 - chart) * 100}px)`}}>
        <Card style={{padding: '36px 50px 30px', height: 500, position: 'relative'}}>
          <div style={{fontWeight: 700, fontSize: 38, color: B.text2}}>Your hosting bill</div>
          <div style={{position: 'absolute', left: 50, right: 50, bottom: 92, borderTop: `2px solid ${B.border}`}} />
          <div style={{position: 'absolute', left: 50, right: 50, bottom: 92 + introH, borderTop: `3px dashed rgba(255,255,255,${0.25 * lin(t, BT.triple, BT.triple + 0.3)})`}} />
          {[
            {label: 'Intro', h: introH, color: B.text2, x: 150},
            {label: 'Renewal', h: renewH, color: B.error, x: 520},
          ].map((bar) => (
            <div key={bar.label} style={{position: 'absolute', left: bar.x, bottom: 92, width: 200}}>
              <div style={{height: bar.h, borderRadius: '18px 18px 4px 4px', background: bar.color, boxShadow: bar.label === 'Renewal' ? '0 0 50px rgba(240,87,107,0.55)' : 'none'}} />
              <div style={{position: 'absolute', top: '100%', width: 200, textAlign: 'center', marginTop: 18, fontWeight: 800, fontSize: 38, color: bar.label === 'Renewal' ? mixColor(renewalLabel) : B.text2}}>
                {bar.label}
              </div>
            </div>
          ))}
          <div style={{position: 'absolute', left: 520 + 100, bottom: 92 + renewH + 24, transform: `translateX(-50%) scale(${badge * pulse})`}}>
            <Pill bg={B.error} color="#fff" style={{fontSize: 70, padding: '6px 30px', gap: 6, boxShadow: '0 12px 40px rgba(240,87,107,0.5)'}}>
              <Icon name="arrowUp" size={58} color="#fff" stroke={3.2} />3×
            </Pill>
          </div>
        </Card>
      </At>
    </div>
  );
};

const mixColor = (p: number) => (p > 0.5 ? B.error : B.text2);
