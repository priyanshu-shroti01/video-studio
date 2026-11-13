import React from 'react';
import {easeInOut, life, lin, mix, sp} from '../anim';
import {B, BT, EV, MONO, SANS, TL} from '../brand';
import {At, Card, Check, Cursor, Icon, Pill} from '../ui';

/** Act 4: "Pick the Grow plan at 79 rupees, type your domain, and launch in minutes
 *  with LiteSpeed servers, free SSL, and daily backups." */
export const Journey: React.FC<{t: number}> = ({t}) => {
  const [start, end] = TL.acts.journey;
  const plansOut = BT.type - 0.05;
  return (
    <>
      {t < plansOut + 0.02 ? <Plans t={t} start={start} end={plansOut} /> : null}
      {t >= plansOut - 0.15 ? <Launch t={t} start={plansOut - 0.15} end={end} /> : null}
    </>
  );
};

// Real plans from shrotihost.in (monthly, excl. taxes)
const PLANS = [
  {name: 'Launch', price: 49, disk: '10 GB NVMe'},
  {name: 'Grow', price: 79, disk: '50 GB NVMe', popular: true},
  {name: 'Turbo', price: 149, disk: '100 GB NVMe'},
];

const Plans: React.FC<{t: number; start: number; end: number}> = ({t, start, end}) => {
  const o = life(t, start, end, 0.12, 0.25);
  const sel = lin(t, EV.growClick, EV.growClick + 0.2);
  const priceHit = sp(t, BT.n79 - 0.05, 8, 0.5);
  // cursor travels in from bottom-right to the Grow card, clicks on EV.growClick
  const c = easeInOut(t, BT.grow - 0.05, EV.growClick - 0.03);
  const cx = mix(930, 585, c);
  const cy = mix(1250, 820, c);
  return (
    <div style={{opacity: o}}>
      <At y={290} w={1000} style={{textAlign: 'center', fontFamily: SANS, fontWeight: 800, fontSize: 64, color: B.text, opacity: sp(t, start)}}>
        Pick your plan
      </At>
      <div style={{position: 'absolute', top: 430, left: 40, right: 40, display: 'flex', gap: 24, justifyContent: 'center'}}>
        {PLANS.map((p, i) => {
          const inP = sp(t, EV.planCards[i], 14, 0.7);
          const isGrow = !!p.popular;
          const scale = isGrow ? mix(1, 1.08, sel) : mix(1, 0.94, sel);
          const dim = isGrow ? 1 : mix(1, 0.45, sel);
          return (
            <div key={p.name} style={{width: 312, opacity: inP * dim, transform: `translateY(${(1 - inP) * 140}px) scale(${scale})`}}>
              <Card
                style={{
                  padding: '34px 26px 30px',
                  textAlign: 'center',
                  position: 'relative',
                  border: `${isGrow ? 4 : 2}px solid ${isGrow && sel > 0 ? B.purple : B.border}`,
                  boxShadow: isGrow && sel > 0 ? `0 0 ${60 * sel}px rgba(168,16,199,0.6), 0 30px 80px rgba(0,0,0,0.5)` : undefined,
                }}
              >
                {isGrow ? (
                  <div style={{position: 'absolute', left: 0, right: 0, top: -26, textAlign: 'center'}}>
                    <Pill bg={B.purple} color="#fff" style={{fontSize: 26, padding: '8px 20px'}}>Most popular</Pill>
                  </div>
                ) : null}
                <div style={{fontWeight: 800, fontSize: 46, color: B.text}}>{p.name}</div>
                <div style={{fontWeight: 800, fontSize: 92, letterSpacing: -3, color: isGrow ? B.text : B.text2, margin: '14px 0 0', transform: isGrow ? `scale(${mix(1, 1.12, priceHit) - 0.12 * lin(t, BT.n79 + 0.3, BT.n79 + 0.6)})` : undefined}}>
                  ₹{p.price}
                </div>
                <div style={{fontWeight: 700, fontSize: 30, color: B.muted}}>/mo</div>
                <div style={{marginTop: 22, paddingTop: 20, borderTop: `2px solid ${B.border}`, fontWeight: 700, fontSize: 30, color: B.text2}}>{p.disk}</div>
                <div style={{marginTop: 24, borderRadius: 16, padding: '16px 0', fontWeight: 800, fontSize: 32, background: isGrow && sel > 0.5 ? B.purple : 'rgba(255,255,255,0.08)', color: '#fff'}}>
                  {isGrow && sel > 0.5 ? 'Selected ✓' : 'Choose'}
                </div>
              </Card>
            </div>
          );
        })}
      </div>
      {t > BT.grow - 0.1 ? <Cursor x={cx} y={cy} t={t} clickAt={EV.growClick} opacity={lin(t, BT.grow - 0.1, BT.grow + 0.1)} /> : null}
    </div>
  );
};

const FEATURES: {label: string; icon: 'server' | 'lock' | 'cloud'; at: number}[] = [
  {label: 'LiteSpeed servers', icon: 'server', at: BT.litespeed},
  {label: 'Free SSL', icon: 'lock', at: BT.free},
  {label: 'Daily backups', icon: 'cloud', at: BT.daily},
];

const Launch: React.FC<{t: number; start: number; end: number}> = ({t, start, end}) => {
  const o = life(t, start, end, 0.2, 0.25);
  const cardIn = sp(t, start, 15, 0.8);
  const typed = EV.keyTimes.filter((k) => t >= k).length;
  const caret = typed < TL.domain.length || Math.floor(t * 2.2) % 2 === 0;
  const avail = sp(t, EV.available, 12, 0.6);
  const btnIn = sp(t, EV.available - 0.05, 14, 0.7);
  const pressed = t >= EV.launchClick && t < EV.launchClick + 0.14;
  const fill = easeInOut(t, EV.launchClick + 0.08, EV.live);
  const live = t >= EV.live;
  const liveP = sp(t, EV.live, 10, 0.6);
  const ca = easeInOut(t, EV.available + 0.05, EV.launchClick - 0.05);
  const push = mix(1, 1.025, lin(t, EV.live, end)); // slow push while features stack in
  return (
    <div style={{opacity: o, transform: `scale(${push})`, transformOrigin: '540px 700px'}}>
      <At y={290} w={900} style={{opacity: cardIn, transform: `translateY(${(1 - cardIn) * 120}px)`}}>
        <Card light style={{padding: '40px 44px 44px'}}>
          <div style={{fontWeight: 800, fontSize: 50, color: B.light.text, marginBottom: 26}}>Find your domain</div>
          <div style={{display: 'flex', alignItems: 'center', gap: 20, height: 112, padding: '0 28px', borderRadius: 20, border: `3px solid ${typed > 0 ? B.purple : B.light.border}`, background: B.light.surface}}>
            <Icon name="globe" size={50} color={B.light.muted} />
            <div style={{fontFamily: MONO, fontSize: 56, color: B.light.text, letterSpacing: -1}}>
              {TL.domain.slice(0, typed)}
              <span style={{display: 'inline-block', width: 4, height: 60, marginLeft: 4, verticalAlign: 'middle', background: B.purple, opacity: caret ? 1 : 0}} />
            </div>
          </div>
          <div style={{height: 64, display: 'flex', alignItems: 'center', gap: 14, marginTop: 14, opacity: avail, fontWeight: 700, fontSize: 36, color: B.light.success}}>
            <Check t={t} at={EV.available} size={44} color={B.light.success} />
            <span>
              {/* proportional font: monospace gives "." a full-width cell, reading as "yourbrand .in" */}
              <span style={{fontFamily: SANS, fontWeight: 800}}>{TL.domain}</span> is available
            </span>
          </div>
          <div
            style={{
              position: 'relative',
              overflow: 'hidden',
              marginTop: 18,
              height: 116,
              borderRadius: 22,
              background: live ? B.success : pressed ? B.purpleActive : B.purple,
              opacity: btnIn,
              transform: `scale(${pressed ? 0.97 : 1}) translateY(${(1 - btnIn) * 30}px)`,
              boxShadow: live ? `0 0 ${50 * liveP}px rgba(34,197,94,0.55)` : '0 14px 40px rgba(168,16,199,0.45)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 18,
              color: '#fff',
              fontWeight: 800,
              fontSize: 50,
            }}
          >
            {!live && fill > 0 ? <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${fill * 100}%`, background: 'rgba(255,255,255,0.22)'}} /> : null}
            <span style={{position: 'relative', display: 'flex', alignItems: 'center', gap: 18}}>
              {live ? (
                <>
                  <span style={{width: 26, height: 26, borderRadius: 13, background: '#fff', boxShadow: `0 0 0 ${8 + 6 * Math.sin(t * 6)}px rgba(255,255,255,0.25)`}} />
                  Your site is live
                </>
              ) : fill > 0 ? (
                'Launching…'
              ) : (
                <>
                  Launch site <Icon name="arrowRight" size={50} color="#fff" stroke={3} />
                </>
              )}
            </span>
          </div>
        </Card>
      </At>

      {t > EV.available && t < EV.live + 0.6 ? (
        <Cursor x={mix(1010, 650, ca)} y={mix(1150, 670, ca)} t={t} clickAt={EV.launchClick} opacity={lin(t, EV.available, EV.available + 0.15) * (1 - lin(t, EV.live + 0.3, EV.live + 0.6))} />
      ) : null}

      <div style={{position: 'absolute', top: 810, left: 120, right: 120, display: 'flex', flexDirection: 'column', gap: 22}}>
        {FEATURES.map((f) => {
          const p = sp(t, f.at - 0.08, 13, 0.7);
          return (
            <div key={f.label} style={{opacity: p, transform: `translateX(${(1 - p) * -120}px)`}}>
              <Card style={{display: 'flex', alignItems: 'center', gap: 28, padding: '22px 34px', borderRadius: 26}}>
                <Check t={t} at={f.at + 0.05} size={64} />
                <Icon name={f.icon} size={54} color={B.purpleText} />
                <div style={{fontWeight: 800, fontSize: 52, color: B.text}}>{f.label}</div>
              </Card>
            </div>
          );
        })}
      </div>
    </div>
  );
};
