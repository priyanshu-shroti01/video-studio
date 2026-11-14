// Frame-accurate storyboard preview: the real engine (src/engine Storyboard) in @remotion/player, fed with the exact
// RenderProps the renderer would use (pipeline/preview_player.py), so every frame can be judged before the full render.
//
// GET /api/productions/<id>/player-props?format=short|landscape  ->  PlayerPayload (below):
// {
//   productionId: string, storyboardHash: string,
//   format: 'short' | 'landscape', formats: string[], projectFormats: string[], inProject: boolean,
//   timing: 'estimated', timingNote: string,
//   fps: number, durationInFrames: number, width: number, height: number,
//   staticBase: '/files/public',          // window.remotion_staticBase: staticFile('x') -> /files/public/x
//   props: RenderProps,                   // unchanged, as the renderer writes props-<fmt>.json
//   propsHash: string,
//   scenes: [{id, purpose, start, end, startFrame, endFrame}],
//   assets: [{path, url, exists}], missingAssets: string[], warnings: string[]
// }
// Errors use the Studio's usual {error: {code, message, detail}} body (404 when there is no storyboard yet).
//
// Assets: the engine loads fonts, logos, images and footage with staticFile(). Setting window.remotion_staticBase to
// payload.staticBase makes those resolve to the Studio's existing /files/public/... route (pipeline.api.safe_output_file).
// The renderer's calculateStoryboardMetadata (intrinsic asset aspects, footage durations) runs here too, before the
// Player mounts, so the layout matches the render.
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Player, PlayerRef} from '@remotion/player';
import {calculateStoryboardMetadata, Storyboard} from '../../../../src/engine/Storyboard';
import type {RenderProps} from '../../../../src/engine/types';
import {api} from '../api';
import {Alert, Badge, Button, Card, ErrorBox, isTyping} from '../ui';

export type Format = 'short' | 'landscape';
export type PlayerScene = {id: string; purpose: string; start: number; end: number; startFrame: number; endFrame: number};
export type PlayerPayload = {
  productionId: string;
  storyboardHash: string;
  format: Format;
  formats: Format[];
  projectFormats: Format[];
  inProject: boolean;
  timing: 'estimated' | 'voice';
  timingNote: string;
  fps: number;
  durationInFrames: number;
  width: number;
  height: number;
  staticBase: string;
  props: RenderProps;
  propsHash: string;
  scenes: PlayerScene[];
  assets: {path: string; url: string; exists: boolean}[];
  missingAssets: string[];
  warnings: string[];
};

/** Same resolution the renderer does in calculateMetadata (asset aspects + footage durations), via the Studio route. */
async function resolveProps(p: PlayerPayload, signal: AbortSignal): Promise<RenderProps> {
  window.remotion_staticBase = p.staticBase;
  const meta = await calculateStoryboardMetadata({props: p.props, defaultProps: p.props, abortSignal: signal, compositionId: 'Storyboard', isRendering: false});
  return (meta.props as RenderProps | undefined) ?? p.props;
}

const pad = (n: number, w: number) => String(n).padStart(w, '0');
const clock = (s: number) => `${Math.floor(s / 60)}:${pad(Math.floor(s % 60), 2)}.${pad(Math.floor((s % 1) * 100), 2)}`;

// The Studio's page CSS (body font, line-height, colour scheme) is inherited by the Player's DOM; the renderer's page has
// browser defaults. Reset the inherited properties so text measures and draws as in the render.
const RENDER_DEFAULTS: React.CSSProperties = {
  font: 'normal 400 16px/normal serif', color: '#000', letterSpacing: 'normal', textAlign: 'start', textTransform: 'none',
  WebkitFontSmoothing: 'auto', colorScheme: 'light',
};

export const PreviewPlayer: React.FC<{productionId: string; format?: Format}> = ({productionId, format}) => {
  const [fmt, setFmt] = useState<Format | undefined>(format);
  useEffect(() => setFmt(format), [format]);
  const [payload, setPayload] = useState<PlayerPayload | null>(null);
  const [resolved, setResolved] = useState<RenderProps | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    setPayload(null);
    setResolved(null);
    setError(null);
    const q = fmt ? `?format=${encodeURIComponent(fmt)}` : '';
    (async () => {
      const p = await api.get<PlayerPayload>(`/api/productions/${encodeURIComponent(productionId)}/player-props${q}`);
      if (ctl.signal.aborted) return;
      setPayload(p);
      const r = await resolveProps(p, ctl.signal);
      if (!ctl.signal.aborted) setResolved(r);
    })().catch((e) => { if (!ctl.signal.aborted) setError(e); });
    return () => ctl.abort();
  }, [productionId, fmt, nonce]);

  const reload = <Button variant="ghost" onClick={() => setNonce((n) => n + 1)} title="Rebuild from the saved storyboard">Reload</Button>;
  const tabs = (payload?.formats ?? (['short', 'landscape'] as Format[])).map((f) => (
    <button key={f} className={`tab ${f === (payload?.format ?? fmt) ? 'on' : ''}`} onClick={() => setFmt(f)}
      title={payload && !payload.projectFormats.includes(f) ? 'This project does not render this format' : undefined}>
      {f}{payload && !payload.projectFormats.includes(f) ? ' (not rendered)' : ''}
    </button>
  ));
  return (
    <Card title="Frame-accurate preview" actions={<>{tabs}{payload?.timing === 'voice' ? <Badge tone="success">voice timing</Badge> : <Badge tone="warning" title={payload?.timingNote}>estimated timing</Badge>}{reload}</>}>
      {error ? <ErrorBox error={error} title="Could not load the preview" /> : !payload || !resolved ? <div className="skeleton" style={{height: 320}} /> : (
        <Stage key={`${payload.format}:${payload.propsHash}`} payload={payload} props={resolved} />
      )}
    </Card>
  );
};

const Stage: React.FC<{payload: PlayerPayload; props: RenderProps}> = ({payload, props}) => {
  const ref = useRef<PlayerRef>(null);
  const [loop, setLoop] = useState<string | null>(null);
  const {fps, durationInFrames: N, width, height, scenes} = payload;
  const looped = scenes.find((s) => s.id === loop) ?? null;
  const portrait = height > width;
  const playerStyle = useMemo<React.CSSProperties>(() => ({width: '100%', aspectRatio: `${width} / ${height}`, background: '#000'}), [width, height]);
  const errorFallback = useCallback(({error}: {error: Error}) => <div style={{color: '#fff', padding: 24, font: '600 28px/1.4 system-ui'}}>Engine error: {error.message}</div>, []);

  return (
    <div style={{display: 'grid', gridTemplateColumns: portrait ? 'minmax(0, 360px) minmax(0, 1fr)' : 'minmax(0, 1fr)', gap: 16, alignItems: 'start'}}>
      <div style={{...RENDER_DEFAULTS, width: '100%', maxWidth: portrait ? 360 : 960, borderRadius: 8, overflow: 'hidden'}}>
        <Player
          ref={ref}
          component={Storyboard}
          inputProps={props}
          durationInFrames={N}
          fps={fps}
          compositionWidth={width}
          compositionHeight={height}
          style={playerStyle}
          controls={false}
          clickToPlay
          spaceKeyToPlayOrPause={false}
          doubleClickToFullscreen
          loop={!!looped}
          inFrame={looped ? looped.startFrame : null}
          outFrame={looped ? looped.endFrame : null}
          moveToBeginningWhenEnded={false}
          numberOfSharedAudioTags={0}  // the engine has no audio; shared tags would load a data: mp3 the Studio CSP blocks
          errorFallback={errorFallback}
        />
      </div>
      <Controls player={ref} payload={payload} loop={looped} setLoop={setLoop} />
    </div>
  );
};

function usePlayerState(player: React.RefObject<PlayerRef | null>) {
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    const p = player.current;
    if (!p) return;
    const onFrame = (e: {detail: {frame: number}}) => setFrame(e.detail.frame);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    p.addEventListener('frameupdate', onFrame);
    p.addEventListener('seeked', onFrame);
    p.addEventListener('play', onPlay);
    p.addEventListener('pause', onPause);
    p.addEventListener('ended', onPause);
    setFrame(p.getCurrentFrame());
    return () => {
      p.removeEventListener('frameupdate', onFrame);
      p.removeEventListener('seeked', onFrame);
      p.removeEventListener('play', onPlay);
      p.removeEventListener('pause', onPause);
      p.removeEventListener('ended', onPause);
    };
  }, [player]);
  return {frame, playing};
}

const Controls: React.FC<{player: React.RefObject<PlayerRef | null>; payload: PlayerPayload; loop: PlayerScene | null; setLoop: (id: string | null) => void}> =
  ({player, payload, loop, setLoop}) => {
    const {frame, playing} = usePlayerState(player);
    const {fps, durationInFrames: N, scenes} = payload;
    const lo = loop ? loop.startFrame : 0;
    const hi = loop ? loop.endFrame : N - 1;
    const seek = useCallback((f: number) => player.current?.seekTo(Math.max(lo, Math.min(hi, Math.round(f)))), [player, lo, hi]);
    const step = useCallback((d: number) => { player.current?.pause(); seek((player.current?.getCurrentFrame() ?? 0) + d); }, [player, seek]);
    const current = scenes.find((s) => frame >= s.startFrame && frame <= s.endFrame) ?? null;
    const toggleLoop = (s: PlayerScene) => {
      if (loop?.id === s.id) return setLoop(null);
      setLoop(s.id);
      player.current?.seekTo(s.startFrame);
    };

    const onKey = (e: React.KeyboardEvent) => {
      if (isTyping(e.nativeEvent)) return;
      const big = e.shiftKey ? fps : 1;
      if (e.key === 'ArrowLeft') step(-big);
      else if (e.key === 'ArrowRight') step(big);
      else if (e.key === ' ' || e.key === 'k') player.current?.toggle();
      else if (e.key === 'Home') seek(lo);
      else if (e.key === 'End') seek(hi);
      else return;
      e.preventDefault();
    };

    return (
      <div tabIndex={0} onKeyDown={onKey} aria-label="Preview controls (arrow keys step a frame, Shift+arrow a second, space plays)" style={{outline: 'none', minWidth: 0}}>
        <div className="row wrap">
          <Button variant="primary" onClick={() => player.current?.toggle()} kbd="space" style={{minWidth: 96}}>{playing ? 'Pause' : 'Play'}</Button>
          <Button onClick={() => step(-fps)} title="Back 1 second (Shift+←)">−1 s</Button>
          <Button onClick={() => step(-1)} title="Back 1 frame (←)">−1 f</Button>
          <Button onClick={() => step(1)} title="Forward 1 frame (→)">+1 f</Button>
          <Button onClick={() => step(fps)} title="Forward 1 second (Shift+→)">+1 s</Button>
        </div>
        <input
          type="range" min={0} max={N - 1} step={1} value={frame} aria-label="Scrub"
          onChange={(e) => seek(Number(e.target.value))}
          style={{width: '100%', height: 22, padding: 0, border: 0, background: 'transparent', accentColor: 'var(--brand)', marginTop: 12}}
        />
        <div className="row between mono sm">
          <span>{clock(frame / fps)} / {clock(N / fps)}</span>
          <span>frame {frame} / {N - 1} · {fps} fps</span>
        </div>
        <div className="muted sm mt-s">
          {current ? <>Scene <b>{current.id}</b> ({current.purpose}) · {clock(current.start)}–{clock(current.end)}</> : 'Between scenes'}
          {loop ? <> · looping <b>{loop.id}</b></> : null}
        </div>

        <div className="h4 mt">Scenes</div>
        <div style={{display: 'grid', gap: 4}}>
          {scenes.map((s, i) => {
            const here = current?.id === s.id;
            return (
              <div key={s.id} className="row" style={{gap: 6}}>
                <button className={`tab ${here ? 'on' : ''}`} style={{flex: 1, textAlign: 'left'}} onClick={() => { if (loop && loop.id !== s.id) setLoop(null); player.current?.seekTo(s.startFrame); }}
                  title={`Go to frame ${s.startFrame}`}>
                  {i + 1}. {s.id} <span className="muted">· {s.purpose} · {(s.end - s.start).toFixed(1)} s · f{s.startFrame}–{s.endFrame}</span>
                </button>
                <button className={`tab ${loop?.id === s.id ? 'on' : ''}`} onClick={() => toggleLoop(s)} aria-pressed={loop?.id === s.id} title="Loop this scene">loop</button>
              </div>
            );
          })}
        </div>

        <Alert tone="info" title={payload.timing === 'estimated' ? 'Estimated timing' : 'Timing'}>
          {payload.timingNote} The preview is silent; voice, sound effects and music are mixed in the full render.
        </Alert>
        {payload.missingAssets.length ? <Alert tone="danger" title="Missing assets">{payload.missingAssets.join(', ')}</Alert> : null}
        {payload.warnings.length ? (
          <details className="mt-s sm">
            <summary className="muted">{payload.warnings.length} timeline warning{payload.warnings.length === 1 ? '' : 's'}</summary>
            <ul>{payload.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </details>
        ) : null}
        {!payload.inProject ? <div className="muted sm mt-s">This project does not render {payload.format}; this is a what-if preview.</div> : null}
      </div>
    );
  };
