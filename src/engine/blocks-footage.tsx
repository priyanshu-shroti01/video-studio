/**
 * `footage` block: a real video clip (screen recording, product footage) in browser / laptop / phone chrome or bare.
 * Drawn exactly from geometry-footage.ts (the numbers the QA manifest reports). The clip is always muted and frame-
 * accurate: <OffthreadVideo> is frozen at the clip time computed from t (clipTime), so playback, startFrom,
 * playbackRate and the last-frame hold are pure functions of t, like every other block.
 */
import React from 'react';
import {Freeze, OffthreadVideo, staticFile} from 'remotion';
import {lin, mix} from './anim';
import {geomFootage, seekTime, zoomAt, zoomRect} from './geometry-footage';
import {EASE} from './motion/easings';
import {Txt} from './prim';
import {Block} from './types';
import {alpha, useEngine} from './ui';

type P = {block: Extract<Block, {type: 'footage'}>; w: number; h: number; appear: number};

/** The clip inside its viewport (w × h, the clip's own aspect), at the clip time and zoom of t. */
const Clip: React.FC<{block: P['block']; w: number; h: number; appear: number}> = ({block, w, h, appear}) => {
  const {t, fps} = useEngine();
  const ct = seekTime(block, t, appear);
  const r = zoomRect(zoomAt(block.zooms, t), w, h);
  return (
    <Freeze frame={ct * fps}>
      <OffthreadVideo
        src={staticFile(block.asset)}
        muted
        style={{position: 'absolute', left: r.x, top: r.y, width: r.w, height: r.h, objectFit: 'cover', display: 'block', maxWidth: 'none'}}
      />
    </Freeze>
  );
};

export const Footage: React.FC<P> = ({block, w, h, appear}) => {
  const {theme, t, surface, ink, aspects} = useEngine();
  const c = theme.colors;
  const L = c.light;
  const light = surface === 'light';
  const g = geomFootage(block, w, aspects);
  const s = g.screen;
  const shadow = light ? `0 40px 90px rgba(0,0,0,0.38), 0 10px 30px ${alpha(L.text, 0.12)}` : '0 40px 90px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.12)';
  const glare = lin(t, appear + 0.2, appear + 1.1);
  const viewport = (radius: number | string) => (
    <div style={{position: 'absolute', left: s.x, top: s.y, width: s.w, height: s.h, borderRadius: radius, overflow: 'hidden', background: '#0e0e14'}}>
      <Clip block={block} w={s.w} h={s.h} appear={appear} />
      {glare > 0 && glare < 1 && (g.frame === 'laptop' || g.frame === 'phone') ? (
        <div style={{position: 'absolute', top: -s.h * 0.2, bottom: -s.h * 0.2, width: s.w * 0.35, left: mix(-s.w * 0.5, s.w * 1.2, EASE.inOutSine(glare)), background: 'linear-gradient(100deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.10) 50%, rgba(255,255,255,0) 100%)', transform: 'skewX(-14deg)'}} />
      ) : null}
    </div>
  );
  const cap = g.caption ? <Txt s={g.caption} color={ink.text2} style={{opacity: lin(t, appear + 0.4, appear + 0.7)}} /> : null;

  if (g.frame === 'browser') {
    const R = theme.radius.card;
    const ch = s.y;
    return (
      <div style={{position: 'relative', width: w, height: h}}>
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: g.body.w,
            height: g.body.h,
            borderRadius: R,
            background: light ? L.card : c.card,
            border: `2px solid ${light ? L.border : c.border}`,
            boxShadow: light ? shadow : '0 30px 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06)',
            boxSizing: 'border-box',
            overflow: 'hidden',
          }}
        >
          <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: ch, background: light ? L.surface : c.raised, borderBottom: `2px solid ${light ? L.border : c.border}`, boxSizing: 'border-box'}} />
        </div>
        {[c.danger, c.warning, c.success].map((col, i) => (
          <div key={col} style={{position: 'absolute', left: 30 + i * 34, top: ch / 2 - 10, width: 20, height: 20, borderRadius: 10, background: col, opacity: 0.9}} />
        ))}
        {g.title ? (
          <>
            <div style={{position: 'absolute', left: g.title.x - 20, top: g.title.y, width: g.title.w + 40, height: g.title.h, borderRadius: g.title.h / 2, background: light ? L.card : c.bg, border: light ? `2px solid ${L.border}` : undefined, boxSizing: 'border-box'}} />
            <Txt s={g.title} color={light ? L.muted : c.text2} />
          </>
        ) : null}
        {viewport(`0 0 ${R - 2}px ${R - 2}px`)}
        {cap}
      </div>
    );
  }

  if (g.frame === 'laptop' || g.frame === 'phone') {
    const phone = g.frame === 'phone';
    const portrait = s.h >= s.w;
    return (
      <div style={{position: 'relative', width: w, height: h}}>
        <div
          style={{
            position: 'absolute',
            left: g.body.x,
            top: g.body.y,
            width: g.body.w,
            height: g.body.h,
            borderRadius: phone ? g.radius + 16 : '26px 26px 10px 10px',
            background: 'linear-gradient(160deg, #2a2a33, #141419)',
            border: `2px solid ${c.borderStrong}`,
            boxShadow: shadow,
            boxSizing: 'border-box',
          }}
        />
        {!phone ? (
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
        {viewport(g.radius)}
        {phone ? (
          portrait ? (
            <div style={{position: 'absolute', left: w / 2 - 60, top: s.y + 14, width: 120, height: 34, borderRadius: 17, background: '#050507'}} />
          ) : (
            <div style={{position: 'absolute', left: s.x + 14, top: s.y + s.h / 2 - 60, width: 34, height: 120, borderRadius: 17, background: '#050507'}} />
          )
        ) : null}
        {cap}
      </div>
    );
  }

  return (
    <div style={{position: 'relative', width: w, height: h}}>
      <div style={{position: 'absolute', left: s.x, top: s.y, width: s.w, height: s.h, borderRadius: g.radius, boxShadow: light ? shadow : '0 30px 80px rgba(0,0,0,0.5)'}} />
      {viewport(g.radius)}
      {cap}
    </div>
  );
};
