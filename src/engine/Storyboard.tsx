import React, {useMemo, useState} from 'react';
import {AbsoluteFill, CalculateMetadataFunction, Img, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {exitFactor, lin, mix, sp} from './anim';
import {collectAssetPaths, collectFootageNeedingDuration, intrinsicAspect, videoInfo} from './assets';
import {BackdropStack} from './backdrops';
import {BlockView} from './blocks';
import {watermarkFactor} from './branding';
import {captionPageAt, wordState} from './captions';
import {assertContract, DIMENSIONS, isV2} from './contract';
import {captionBandTop} from './layout';
import {BRANDBAR_DUR, LEAD, VIDEO_FADE_FRAMES, VISIBLE_PAD} from './motion/durations';
import {EASE} from './motion/easings';
import {blockEntrance, MOTION_BLUR_LEVELS, motionBlurFilterId} from './motion/entrances';
import {life} from './motion/exits';
import {cameraAt, sceneTransition} from './motion/transitions';
import {backdropWeights} from './look';
import {Env, makeEnv, planScene} from './plan';
import {holdForFonts} from './theme';
import {RenderProps, Scene} from './types';
import {alpha, Backdrop, Ctx, EngineCtx, lightInk, Logo, makeCtx, useEngine} from './ui';

export {VISIBLE_PAD} from './motion/durations';
export {sceneTransition} from './motion/transitions';
export {brandBarActiveFor} from './plan';
export const sceneVisible = (s: Pick<Scene, 'start' | 'end'>, t: number) => t >= s.start - VISIBLE_PAD.before && t <= s.end + VISIBLE_PAD.after;

const SceneView: React.FC<{scene: Scene; env: Env}> = ({scene, env}) => {
  const base = useEngine();
  const {t, fps} = base;
  const {props, v2, width} = env;
  const P = useMemo(() => planScene(env, scene), [env, scene]);
  const L = P.layout;
  const tr = sceneTransition(scene, t);
  const ctx: Ctx = !v2 ? base : P.backdrop === 'light' ? {...base, motion: P.preset, surface: 'light', ink: lightInk(base.theme)} : {...base, motion: P.preset};
  let transform: string;
  if (!v2) {
    // v1: exactly the original push-in (scale 1 → 1.03), whatever `camera` says
    const push = mix(1, 1.03, lin(t, scene.start, scene.end));
    transform = `translateY(${tr.dy}px) scale(${push})`;
  } else {
    const cam = cameraAt(scene.camera, scene, t, width, P.preset.camera);
    transform = `translate(${cam.dx}px, ${tr.dy + cam.dy}px) scale(${cam.scale})`;
  }
  return (
    <EngineCtx.Provider value={ctx}>
      <AbsoluteFill style={{opacity: tr.opacity, transform, transformOrigin: `${P.cx}px ${P.cy}px`, maskImage: tr.mask, WebkitMaskImage: tr.mask}}>
        {scene.blocks.map((b, i) => {
          const box = L.boxes[i];
          const appear = P.appear[i];
          let style: React.CSSProperties;
          if (!v2) {
            const p = sp(t, appear - LEAD.block, fps, 15, 0.8);
            const o = Math.min(1, p * 1.4) * exitFactor(t, b.exitAt);
            style = {transform: `scale(${box.scale}) translateY(${(1 - p) * 40}px)`, opacity: o};
          } else {
            const e = blockEntrance(t, appear, fps, P.preset, box.scale);
            const sc = e.scale === 1 ? '' : ` translate(${box.designW / 2}px, ${box.designH / 2}px) scale(${e.scale}) translate(${-box.designW / 2}px, ${-box.designH / 2}px)`;
            const filters = [e.blurY > 0 ? `url(#${motionBlurFilterId(e.blurY)})` : '', e.blur > 0.05 ? `blur(${e.blur.toFixed(2)}px)` : ''].filter(Boolean).join(' ');
            style = {transform: `scale(${box.scale}) translateY(${e.dy}px)${sc}`, opacity: e.opacity * exitFactor(t, b.exitAt), filter: filters || undefined};
          }
          return (
            <div
              key={b.id ?? i}
              style={{position: 'absolute', left: box.x, top: box.y, width: box.designW, height: box.designH, transformOrigin: '0 0', ...style}}
            >
              <BlockView
                block={b}
                w={box.designW}
                h={box.designH}
                appear={appear}
                boxY={box.y}
                scale={box.scale}
                sceneStart={scene.start}
                sceneEnd={scene.end}
                ceilingY={P.ceilingY}
              />
            </div>
          );
        })}
      </AbsoluteFill>
      {tr.sweep !== undefined ? <Sweep p={tr.sweep} top={L.top} bottom={captionBandTop(props.format, props.captions)} width={width} /> : null}
    </EngineCtx.Provider>
  );
};

/** 'gradient-sweep' transition: a soft brand light band crossing the content area (never the caption band). */
const Sweep: React.FC<{p: number; top: number; bottom: number; width: number}> = ({p, top, bottom, width}) => {
  const {theme} = useEngine();
  const c = theme.colors;
  const y0 = Math.max(0, top - 60);
  const fade = Math.sin(Math.PI * p);
  const m = 'linear-gradient(180deg, transparent 0%, black 14%, black 86%, transparent 100%)';
  return (
    <div style={{position: 'absolute', left: 0, top: y0, width, height: bottom - y0, overflow: 'hidden', maskImage: m, WebkitMaskImage: m, pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          top: -100,
          bottom: -100,
          width: width * 0.6,
          left: mix(-width * 0.75, width * 1.15, EASE.inOutCubic(p)),
          opacity: fade,
          background: `linear-gradient(100deg, rgba(0,0,0,0) 0%, ${alpha(c.brand, 0.18)} 30%, ${alpha(c.brandHover, 0.42)} 48%, ${alpha(c.brandText, 0.5)} 50%, ${alpha(c.brandHover, 0.42)} 52%, ${alpha(c.brand, 0.18)} 70%, rgba(0,0,0,0) 100%)`,
          transform: 'skewX(-12deg)',
        }}
      />
    </div>
  );
};

/** Linear mix of two rgba()/#hex colours (v2b caption box over the light backdrop). */
const parseColor = (s: string): [number, number, number, number] => {
  const hex = /^#([0-9a-f]{6})$/i.exec(s);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
  }
  const m = /rgba?\(([^)]+)\)/.exec(s);
  if (!m) return [0, 0, 0, 0.55];
  const v = m[1].split(',').map((x) => parseFloat(x));
  return [v[0], v[1], v[2], v[3] ?? 1];
};
const mixRgba = (a: string, b: string, p: number) => {
  const x = parseColor(a);
  const y = parseColor(b);
  const q = (i: number) => x[i] + (y[i] - x[i]) * p;
  return `rgba(${Math.round(q(0))},${Math.round(q(1))},${Math.round(q(2))},${q(3).toFixed(3)})`;
};

const Captions: React.FC<{props: RenderProps; polish: boolean}> = ({props, polish}) => {
  const {t, theme, sans} = useEngine();
  const lightW = polish ? (backdropWeights(props.scenes, t).light ?? 0) : 0;
  const cap = props.captions;
  if (!cap.enabled) return null;
  const idx = captionPageAt(cap.pages, props.words, t);
  if (idx < 0) return null;
  const {width, height} = DIMENSIONS[props.format];
  const page = cap.pages[idx];
  const fs = cap.fontSize;
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: height * cap.bottomFrac, display: 'flex', justifyContent: 'center'}}>
      <div
        style={{
          maxWidth: width * cap.maxWidthFrac,
          textAlign: 'center',
          fontFamily: sans,
          fontWeight: 800,
          fontSize: fs,
          lineHeight: 1.15,
          padding: `${fs * 0.25}px ${fs * 0.5}px`,
          borderRadius: fs * 0.35,
          background: lightW > 0 ? mixRgba(theme.caption.box, alpha(theme.colors.light.text, 0.88), lightW) : theme.caption.box,
          textShadow: '0 4px 18px rgba(0,0,0,0.6)',
        }}
      >
        {page.wordIdx.map((wi) => {
          const w = props.words[wi];
          const st = cap.style === 'word' ? wordState(w, t) : 'spoken';
          return (
            <span
              key={wi}
              style={{
                display: 'inline-block',
                margin: `0 ${fs * 0.2}px`,
                color: st === 'current' ? theme.caption.highlight : st === 'spoken' ? theme.caption.text : theme.caption.dim,
                transform: st === 'current' ? 'scale(1.08)' : 'none',
              }}
            >
              {w.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};

const BrandBar: React.FC<{env: Env}> = ({env}) => {
  const {t} = useEngine();
  const bar = env.brandBar;
  if (!bar || t < bar.from - BRANDBAR_DUR.pad || t > bar.to + BRANDBAR_DUR.pad) return null;
  const o = life(t, bar.from, bar.to, BRANDBAR_DUR.fadeIn, BRANDBAR_DUR.fadeOut);
  if (env.polish) {
    const w = backdropWeights(env.props.scenes, t);
    return (
      <div style={{position: 'absolute', left: bar.x, top: bar.y, width: bar.w, height: bar.h, opacity: o}}>
        <SurfaceLogo variant="onDark" width={bar.w} height={bar.h} light={w.light ?? 0} panel={env.props.format === 'short' ? (w.split ?? 0) : 0} shadow="drop-shadow(0 0 16px rgba(0,0,0,0.4))" />
      </div>
    );
  }
  return (
    <div style={{position: 'absolute', left: bar.x, top: bar.y, opacity: o, filter: `drop-shadow(0 0 16px rgba(0,0,0,0.4))`}}>
      <Logo variant="onDark" width={bar.w} height={bar.h} />
    </div>
  );
};

/** v2b: a theme logo that stays legible on every backdrop — onDark ⇄ onLight crossfade over the light surface, and
 *  a white silhouette over the brand panel of the 'split' backdrop (where the purple logo would vanish). */
const SurfaceLogo: React.FC<{variant: 'onDark' | 'mark' | 'custom'; src?: string; width: number; height: number; light: number; panel: number; shadow: string}> = ({variant, src, width, height, light, panel, shadow}) => {
  const swap = variant === 'onDark' ? light : 0;
  const base = Math.max(0, 1 - swap - panel);
  const layer = (o: number, el: React.ReactNode, f?: string) =>
    o > 0.001 ? <div style={{position: 'absolute', inset: 0, opacity: Math.min(1, o), filter: f}}>{el}</div> : null;
  const img = (v: 'onDark' | 'onLight' | 'mark') => (src && variant === 'custom' ? <Logo variant="mark" src={src} width={width} height={height} /> : <Logo variant={v} width={width} height={height} />);
  const v0 = variant === 'custom' ? 'mark' : variant;
  return (
    <>
      {layer(base, img(v0), shadow)}
      {layer(swap, img('onLight'), 'drop-shadow(0 2px 10px rgba(21,17,28,0.12))')}
      {layer(panel, img(v0), 'brightness(0) invert(1) drop-shadow(0 2px 8px rgba(0,0,0,0.25))')}
    </>
  );
};

/** v2 watermark: hidden (faded) whenever a logo / cta / logo-sting / outro block or the brand bar is visible. */
const WatermarkView: React.FC<{env: Env}> = ({env}) => {
  const {t} = useEngine();
  const wm = env.watermark;
  if (!wm) return null;
  const f = watermarkFactor(wm, t);
  if (f <= 0) return null;
  if (env.polish) {
    const w = backdropWeights(env.props.scenes, t);
    const panel = env.props.format === 'short' && wm.position.startsWith('top') ? (w.split ?? 0) : 0;
    const variant = wm.variant === 'onLight' ? 'custom' : wm.variant;
    return (
      <div style={{position: 'absolute', left: wm.rect.x, top: wm.rect.y, width: wm.rect.w, height: wm.rect.h, opacity: wm.opacity * f}}>
        <SurfaceLogo variant={variant} src={wm.src} width={wm.rect.w} height={wm.rect.h} light={w.light ?? 0} panel={panel} shadow="drop-shadow(0 2px 8px rgba(0,0,0,0.45))" />
      </div>
    );
  }
  return (
    <div style={{position: 'absolute', left: wm.rect.x, top: wm.rect.y, width: wm.rect.w, height: wm.rect.h, opacity: wm.opacity * f, filter: 'drop-shadow(0 2px 8px rgba(0,0,0,0.45))'}}>
      <Img src={staticFile(wm.src)} style={{width: '100%', height: '100%', objectFit: 'contain', display: 'block'}} />
    </div>
  );
};

/** Directional (vertical) motion-blur filters, defined once; referenced by fast block entrances. */
const MotionBlurDefs: React.FC = () => (
  <svg width={0} height={0} style={{position: 'absolute'}} aria-hidden>
    <defs>
      {MOTION_BLUR_LEVELS.map((sd, level) =>
        level === 0 ? null : (
          <filter key={level} id={motionBlurFilterId(level)} x="-5%" y="-25%" width="110%" height="150%">
            <feGaussianBlur stdDeviation={`0 ${sd}`} />
          </filter>
        ),
      )}
    </defs>
  </svg>
);

/** Backdrop mood: smooth 0..1 per mood from the scenes active around t. */
export const moodAt = (scenes: Scene[], t: number, mood: 'danger' | 'brand') =>
  Math.max(0, ...scenes.filter((s) => s.mood === mood).map((s) => Math.min(lin(t, s.start - 0.2, s.start + 0.3), 1 - lin(t, s.end - 0.3, s.end))));

export const Storyboard: React.FC<RenderProps> = (props) => {
  assertContract(props);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  // fonts: request once per mount; delayRender blocks the frame until they're loaded
  useState(() => holdForFonts(props.theme));
  const env = useMemo(() => makeEnv(props), [props]);
  const t = frame / fps;
  const ctx: Ctx = makeCtx(props.theme, t, fps, {aspects: env.aspects, v2: env.v2, polish: env.polish});
  const {width, height} = DIMENSIONS[props.format];
  const fadeOut = 1 - lin(frame, durationInFrames - VIDEO_FADE_FRAMES, durationInFrames - 1);
  return (
    <EngineCtx.Provider value={ctx}>
      <AbsoluteFill style={{background: props.theme.colors.bg, opacity: fadeOut, fontFamily: ctx.sans}}>
        {env.v2 ? <MotionBlurDefs /> : null}
        {env.polish ? (
          <BackdropStack scenes={props.scenes} format={props.format} width={width} height={height} danger={moodAt(props.scenes, t, 'danger')} brand={moodAt(props.scenes, t, 'brand') * 0.8} />
        ) : (
          <Backdrop width={width} height={height} danger={moodAt(props.scenes, t, 'danger')} brand={moodAt(props.scenes, t, 'brand') * 0.8} />
        )}
        {props.scenes.filter((s) => sceneVisible(s, t)).map((s) => (
          <SceneView key={s.id} scene={s} env={env} />
        ))}
        <BrandBar env={env} />
        <WatermarkView env={env} />
        <Captions props={props} polish={env.polish} />
      </AbsoluteFill>
    </EngineCtx.Provider>
  );
};

/** Size/fps/duration from the props; v2 also resolves every asset's intrinsic aspect (SVG viewBox, PNG/JPEG
 *  header) once, so layout never distorts a logo or image and matches scripts/engine-layout.mjs. Footage blocks without
 *  `duration` (the pipeline always fills it from ffprobe) get it from the clip's header, so the last frame can hold. */
export const calculateStoryboardMetadata: CalculateMetadataFunction<RenderProps> = async ({props}) => {
  assertContract(props);
  const {width, height} = DIMENSIONS[props.format];
  const meta = {width, height, fps: props.fps, durationInFrames: props.durationInFrames};
  if (!isV2(props)) return meta;
  const cache = new Map<string, Promise<Uint8Array>>();
  const bytesOf = (p: string) => {
    if (!cache.has(p))
      cache.set(
        p,
        fetch(staticFile(p)).then(async (res) => {
          if (!res.ok) throw new Error(`asset not found in public/: ${p} (HTTP ${res.status})`);
          return new Uint8Array(await res.arrayBuffer());
        }),
      );
    return cache.get(p)!;
  };
  let next = props;
  const needDur = collectFootageNeedingDuration(props);
  if (needDur.length) {
    const durs = new Map(await Promise.all(needDur.map(async (p): Promise<[string, number | undefined]> => [p, videoInfo(await bytesOf(p))?.duration])));
    next = {
      ...next,
      scenes: next.scenes.map((s) => ({
        ...s,
        blocks: s.blocks.map((b) => (b.type === 'footage' && b.duration === undefined && durs.get(b.asset) ? {...b, duration: durs.get(b.asset)} : b)),
      })),
    };
  }
  if (props.assetAspects) return next === props ? meta : {...meta, props: next};
  const entries = await Promise.all(collectAssetPaths(props).map(async (p): Promise<[string, number | undefined]> => [p, intrinsicAspect(await bytesOf(p), p)]));
  const assetAspects: Record<string, number> = {};
  for (const [p, a] of entries) if (a) assetAspects[p] = a;
  return {...meta, props: {...next, assetAspects}};
};
