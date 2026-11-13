import React from 'react';
import {easeOut, life, lin, mix, range, sp} from '../anim';
import {B, BT, EV, SANS, TL} from '../brand';
import {At, Card, Check, Icon, Pill} from '../ui';

/** Act 3: "Meet Shroti Host. Fast NVMe hosting starting at just 49 rupees a month—with the exact same price on renewal."
 *  The logo itself is the persistent <BrandLogo/> in the main composition (reveal centre → dock at top). */
export const Turn: React.FC<{t: number}> = ({t}) => {
  const [start, end] = TL.acts.turn;
  const o = life(t, start, end, 0.01);
  // halo rings radiate from the logo as it lands on "Shroti"
  const rings = [0, 0.18, 0.36].map((d) => lin(t, BT.shroti + d, BT.shroti + d + 1.1));
  const chip = sp(t, BT.nvme - 0.08, 12, 0.7);
  const priceIn = sp(t, BT.starting - 0.1, 15, 0.8);
  const count = Math.round(range(t, [BT.n49 - 0.02, EV.priceCountEnd], [0, 49]));
  const land = sp(t, EV.priceCountEnd, 8, 0.5);
  const breathe = 1 + 0.012 * Math.sin((t - BT.n49) * 3);
  const rowToday = sp(t, BT.with - 0.05, 15, 0.8);
  const rowRenew = sp(t, BT.same - 0.1, 15, 0.8);
  const same = sp(t, BT.renewal2, 10, 0.6);
  return (
    <div style={{opacity: o}}>
      {rings.map((p, i) =>
        p > 0 && p < 1 ? (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: 540 - (300 + 500 * p),
              top: 820 - (300 + 500 * p),
              width: 2 * (300 + 500 * p),
              height: 2 * (300 + 500 * p),
              borderRadius: '50%',
              border: `${6 - 4 * p}px solid rgba(207,108,242,${0.5 * (1 - p)})`,
            }}
          />
        ) : null,
      )}

      <At y={300} w={1000} style={{textAlign: 'center', opacity: chip, transform: `scale(${mix(0.6, 1, chip)})`}}>
        <Pill bg="rgba(168,16,199,0.16)" color={B.purpleText} style={{fontSize: 46, border: `3px solid ${B.purple}`, padding: '14px 36px'}}>
          <Icon name="zap" size={46} color={B.purpleText} stroke={2.6} />
          Fast NVMe hosting
        </Pill>
      </At>

      <At y={440} w={1000} style={{textAlign: 'center', opacity: priceIn, transform: `translateY(${(1 - priceIn) * 60}px)`}}>
        <div style={{fontFamily: SANS, fontWeight: 700, fontSize: 46, color: B.text2}}>
          Launch plan · starting at <span style={{color: B.text}}>just</span>
        </div>
        <div style={{position: 'relative', display: 'inline-flex', alignItems: 'baseline', marginTop: 6, transform: `scale(${mix(1.12, 1, land) * breathe})`}}>
          <div style={{position: 'absolute', inset: '-30px -60px', background: 'radial-gradient(ellipse, rgba(168,16,199,0.45) 0%, rgba(0,0,0,0) 70%)'}} />
          <span style={{position: 'relative', fontFamily: SANS, fontWeight: 800, fontSize: 290, letterSpacing: -10, color: B.text, textShadow: `8px 8px 0 ${B.purple}, 0 0 50px rgba(168,16,199,0.5)`, lineHeight: 1}}>
            ₹{count}
          </span>
          <span style={{position: 'relative', fontFamily: SANS, fontWeight: 800, fontSize: 84, color: B.text2, marginLeft: 12}}>/mo</span>
        </div>
        <div style={{fontFamily: SANS, fontWeight: 600, fontSize: 30, color: B.muted, marginTop: 6, opacity: lin(t, EV.priceCountEnd, EV.priceCountEnd + 0.3)}}>excl. taxes</div>
      </At>

      <At y={910} w={860} style={{opacity: rowToday, transform: `translateY(${(1 - rowToday) * 80}px)`}}>
        <Card light style={{padding: '20px 40px', position: 'relative'}}>
          {[
            {label: 'Today', p: rowToday, at: BT.with + 0.1},
            {label: 'On renewal', p: rowRenew, at: BT.same},
          ].map((r, i) => (
            <div
              key={r.label}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 26,
                padding: '22px 0',
                borderTop: i ? `2px solid ${B.light.border}` : 'none',
                opacity: r.p,
                transform: `translateX(${(1 - r.p) * -80}px)`,
              }}
            >
              <Check t={t} at={r.at} size={66} color={B.light.success} />
              <div style={{flex: 1, fontWeight: 700, fontSize: 48, color: B.light.text2}}>{r.label}</div>
              <div style={{fontWeight: 800, fontSize: 60, color: B.light.text}}>₹49<span style={{fontSize: 36, color: B.light.muted}}>/mo</span></div>
            </div>
          ))}
          <div style={{position: 'absolute', right: -26, top: -40, transform: `scale(${same}) rotate(4deg)`}}>
            <Pill bg={B.success} color="#fff" style={{fontSize: 40, boxShadow: '0 14px 40px rgba(34,197,94,0.45)'}}>
              Same price
            </Pill>
          </div>
        </Card>
      </At>
    </div>
  );
};

/** The Shroti Host logo: hidden → wipes in at centre on "Meet Shroti Host" → docks at the top on "Fast" → leaves at the resolution. */
export const BrandLogo: React.FC<{t: number; render: (width: number) => React.ReactNode}> = ({t, render}) => {
  const revealStart = BT.turn + 0.05;
  if (t < revealStart || t > TL.acts.resolution[0]) return null;
  const wipe = easeOut(t, revealStart, BT.shroti + 0.12);
  const pop = sp(t, revealStart, 12, 0.8);
  const dock = range(t, [EV.logoMove, EV.logoMove + 0.45], [0, 1]);
  const d = dock * dock * (3 - 2 * dock); // smoothstep
  const width = mix(840, 380, d);
  const cy = mix(820, 160, d);
  const out = 1 - Math.pow(lin(t, TL.acts.resolution[0] - 0.22, TL.acts.resolution[0]), 1.5);
  return (
    <div
      style={{
        position: 'absolute',
        left: 540 - width / 2,
        top: cy - width / 10,
        width,
        opacity: out,
        transform: `scale(${mix(0.9, 1, pop)})`,
        clipPath: `inset(-20% ${100 - wipe * 100}% -20% -5%)`,
        filter: `drop-shadow(0 0 ${mix(40, 16, d)}px rgba(168,16,199,0.55))`,
      }}
    >
      {render(width)}
    </div>
  );
};
