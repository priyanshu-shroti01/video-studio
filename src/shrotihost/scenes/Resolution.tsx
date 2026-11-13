import React from 'react';
import {easeOut, life, lin, mix, sp} from '../anim';
import {B, BT, EV, SANS, TL} from '../brand';
import {At, Card, Cursor, Icon, Logo, Pill} from '../ui';

/** Act 5: "No hidden hikes. Launch your site today at shrotihost.in." — callbacks the 3× chart as a flat line. */
export const Resolution: React.FC<{t: number}> = ({t}) => {
  const [start, end] = TL.acts.resolution;
  const ctaStart = BT.launch2 - 0.15;
  return (
    <>
      {t < ctaStart + 0.02 ? <NoHikes t={t} start={start} end={ctaStart} /> : null}
      {t >= ctaStart - 0.1 ? <Cta t={t} start={ctaStart - 0.1} end={end} /> : null}
    </>
  );
};

const NoHikes: React.FC<{t: number; start: number; end: number}> = ({t, start, end}) => {
  const o = life(t, start, end, 0.15, 0.2);
  const w1 = sp(t, BT.resolution - 0.05, 13, 0.6);
  const w2 = sp(t, BT.hidden - 0.05, 13, 0.6);
  const w3 = sp(t, BT.hikes - 0.05, 13, 0.6);
  const strike = easeOut(t, BT.hikes + 0.1, BT.hikes + 0.4);
  const line = easeOut(t, BT.hidden, BT.hikes + 0.35);
  return (
    <div style={{opacity: o}}>
      <At y={300} w={1000} style={{textAlign: 'center', fontFamily: SANS, fontWeight: 800, fontSize: 150, letterSpacing: -5, lineHeight: 1.05, color: B.text}}>
        <span style={{display: 'inline-block', opacity: w1, transform: `translateY(${(1 - w1) * 40}px)`}}>No</span>{' '}
        <span style={{display: 'inline-block', opacity: w2, transform: `translateY(${(1 - w2) * 40}px)`}}>hidden</span>
        <br />
        <span style={{position: 'relative', display: 'inline-block', opacity: w3, transform: `translateY(${(1 - w3) * 40}px)`, color: B.error}}>
          hikes.
          <span style={{position: 'absolute', left: -12, top: '52%', height: 16, width: `${108 * strike}%`, borderRadius: 8, background: B.text, transform: 'rotate(-4deg)'}} />
        </span>
      </At>
      {/* the renewal chart again — now flat */}
      <At y={720} w={900} style={{opacity: sp(t, BT.hidden - 0.1, 15, 0.8)}}>
        <Card style={{padding: '40px 50px', position: 'relative', height: 330}}>
          <div style={{fontWeight: 700, fontSize: 36, color: B.text2}}>Your Shroti Host bill</div>
          <div style={{position: 'absolute', left: 90, top: 190, height: 8, width: 720 * line, borderRadius: 4, background: B.success, boxShadow: '0 0 24px rgba(34,197,94,0.6)'}} />
          {['Year 1', 'Year 2', 'Year 3'].map((y, i) => {
            const p = lin(line, i * 0.4, i * 0.4 + 0.2);
            return (
              <div key={y} style={{position: 'absolute', left: 90 + i * 360 - 70, top: 120, width: 140, textAlign: 'center', opacity: p}}>
                <div style={{fontWeight: 800, fontSize: 44, color: B.text}}>₹79</div>
                <div style={{margin: '18px auto', width: 30, height: 30, borderRadius: 15, background: B.success}} />
                <div style={{fontWeight: 700, fontSize: 28, color: B.muted}}>{y}</div>
              </div>
            );
          })}
        </Card>
      </At>
    </div>
  );
};

const Cta: React.FC<{t: number; start: number; end: number}> = ({t, start, end}) => {
  const o = life(t, start, end + 1, 0.2, 0.01); // final fade handled by the composition
  const logo = sp(t, start + 0.05, 13, 0.8);
  const words = ['Launch', 'your', 'site', 'today'];
  const btn = sp(t, BT.url - 0.12, 9, 0.6);
  const ring = lin(t, BT.url, BT.url + 1.0);
  const pulse = 1 + 0.025 * Math.sin(Math.max(0, t - BT.url - 0.4) * 5);
  const press = t >= EV.ctaClick && t < EV.ctaClick + 0.12 ? 0.96 : 1;
  const c = easeOut(t, BT.url + 0.1, EV.ctaClick - 0.02);
  const push = mix(1, 1.04, lin(t, start, end));
  return (
    <div style={{opacity: o, transform: `scale(${push})`, transformOrigin: '540px 760px'}}>
      <At y={330} w={760} style={{opacity: logo, transform: `scale(${mix(0.85, 1, logo)})`, filter: 'drop-shadow(0 0 36px rgba(168,16,199,0.55))'}}>
        <Logo width={760} />
      </At>
      <At y={560} w={1000} style={{textAlign: 'center', fontFamily: SANS, fontWeight: 800, fontSize: 92, letterSpacing: -3, color: B.text}}>
        {words.map((w, i) => {
          const at = [BT.launch2, BT.launch2 + 0.32, BT.launch2 + 0.6, BT.today][i];
          const p = sp(t, at - 0.06, 13, 0.6);
          return (
            <span key={w} style={{display: 'inline-block', margin: '0 14px', opacity: p, transform: `translateY(${(1 - p) * 40}px)`, color: w === 'today' ? B.purpleText : B.text}}>
              {w}
            </span>
          );
        })}
      </At>
      <At y={790} w={1000} style={{textAlign: 'center'}}>
        <div style={{position: 'relative', display: 'inline-block', transform: `scale(${btn * pulse * press})`}}>
          {ring > 0 && ring < 1 ? (
            <div style={{position: 'absolute', inset: -40 * ring, borderRadius: 999, border: `5px solid rgba(207,108,242,${0.7 * (1 - ring)})`}} />
          ) : null}
          <Pill bg={`linear-gradient(135deg, ${B.purple}, ${B.purpleHover})`} color="#fff" style={{fontSize: 80, padding: '30px 60px', gap: 22, boxShadow: '0 20px 70px rgba(168,16,199,0.6)', letterSpacing: -1}}>
            shrotihost.in <Icon name="arrowRight" size={72} color="#fff" stroke={3} />
          </Pill>
        </div>
        <div style={{marginTop: 34, fontFamily: SANS, fontWeight: 700, fontSize: 38, color: B.text2, opacity: lin(t, BT.url + 0.3, BT.url + 0.7)}}>
          Same price on renewal · NVMe · LiteSpeed
        </div>
      </At>
      {t > BT.url + 0.1 ? <Cursor x={mix(1000, 700, c)} y={mix(1200, 880, c)} t={t} clickAt={EV.ctaClick} opacity={lin(t, BT.url + 0.1, BT.url + 0.3)} /> : null}
    </div>
  );
};
