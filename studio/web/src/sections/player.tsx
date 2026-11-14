// Frame-accurate storyboard preview: the real engine (src/engine Storyboard) in @remotion/player, fed with the exact
// RenderProps the renderer would use (pipeline/preview_player.py), so every frame can be judged before the full render.
//
// GET /api/productions/<id>/player-props?format=short|landscape  ->  PlayerPayload (below):
// {
//   productionId: string, storyboardHash: string,
//   format: 'short' | 'landscape', formats: string[], projectFormats: string[], inProject: boolean,
//   timing: 'estimated' | 'voice', timingNote: string,
//   audio: {url, durationS} | null,       // timing 'voice': the preview voiceover (served by /files/), else null
//   voiceKey: string | null,              // preview-voice cache key of the current narration
//   fps: number, durationInFrames: number, width: number, height: number,
//   staticBase: '/files/public',          // window.remotion_staticBase: staticFile('x') -> /files/public/x
//   props: RenderProps,                   // unchanged, as the renderer writes props-<fmt>.json
//   propsHash: string,
//   scenes: [{id, purpose, start, end, startFrame, endFrame}],
//   assets: [{path, url, exists}], missingAssets: string[], warnings: string[]
// }
// Errors use the Studio's usual {error: {code, message, detail}} body (404 when there is no storyboard yet).
//
// Real voice: POST /api/productions/<id>/preview-voice starts a task that synthesises the narration with the local voice
// (the render's TTS path, queued by the scheduler so it never overlaps a render); GET of the same route reports
// {ready, state, progress, audio}. Once ready, player-props come back with timing 'voice' (real word timings, as the
// render builds them) and `audio`, which plays through remotion's <Html5Audio> inside a wrapper composition: the
// Player itself keeps it in sync on play, seek, frame steps and scene loops (CSP media-src 'self' allows /files/).
//
// Assets: the engine loads fonts, logos, images and footage with staticFile(). Setting window.remotion_staticBase to
// payload.staticBase makes those resolve to the Studio's existing /files/public/... route (pipeline.api.safe_output_file).
// The renderer's calculateStoryboardMetadata (intrinsic asset aspects, footage durations) runs here too, before the
// Player mounts, so the layout matches the render.
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Player, PlayerRef} from '@remotion/player';
import {Html5Audio} from 'remotion';
import {calculateStoryboardMetadata, Storyboard} from '../../../../src/engine/Storyboard';
import type {RenderProps} from '../../../../src/engine/types';
import {api, waitTask} from '../api';
import {Alert, Badge, Button, Card, ErrorBox, isTyping, Progress} from '../ui';

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
  audio?: {url: string; durationS: number} | null;   // optional: older servers omit it
  voiceKey?: string | null;
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

type VoiceStatus = {ready: boolean; state: string; progress: number; error: string | null; audio: {url: string; durationS: number} | null; provider: string; voice: string};

/** The storyboard plus the preview voiceover: the Player owns playback, so <Html5Audio> follows play/seek/loop/step. */
const StoryboardWithVoice: React.FC<{props: RenderProps; audioUrl: string | null}> = ({props, audioUrl}) => (
  <>
    <Storyboard {...props} />
    {audioUrl ? <Html5Audio src={audioUrl} pauseWhenBuffering /> : null}
  </>
);

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

  const [voice, setVoice] = useState<{busy: boolean; status: VoiceStatus | null; error: unknown; t0: number}>({busy: false, status: null, error: null, t0: 0});
  const [, tick] = useState(0);
  const pvUrl = `/api/productions/${encodeURIComponent(productionId)}/preview-voice`;
  const useVoice = async () => {
    const t0 = Date.now();
    setVoice({busy: true, status: null, error: null, t0});
    try {
      const r = await api.post<{task: {id: string}}>(pvUrl, {});
      const t = await waitTask(r.task.id, () => {
        tick((n) => n + 1);
        api.get<VoiceStatus>(pvUrl).then((status) => setVoice((v) => (v.busy ? {...v, status} : v))).catch(() => {});
      }, 1000);
      if (t.status === 'failed') throw Object.assign(new Error(t.error?.message ?? 'voice generation failed'), {detail: t.error?.detail, code: t.error?.code});
      setVoice({busy: false, status: null, error: null, t0});
      setNonce((n) => n + 1);
    } catch (e) {
      setVoice({busy: false, status: null, error: e, t0});
    }
  };
  const voiceState = voice.status?.state;
  const voiceLabel = voiceState === 'waiting' ? 'Waiting for its turn (render / AI model)…' : voiceState === 'assembling' ? 'Assembling the voiceover…' : 'Recording the voice…';

  const reload = <Button variant="ghost" onClick={() => setNonce((n) => n + 1)} title="Rebuild from the saved storyboard">Reload</Button>;
  const voiceBtn = payload && payload.timing !== 'voice' ? (
    <Button onClick={useVoice} busy={voice.busy} disabled={voice.busy} title="Synthesise the narration with the local voice (no render) so the preview plays with the real voice and exact timing">Use the real voice</Button>
  ) : null;
  const tabs = (payload?.formats ?? (['short', 'landscape'] as Format[])).map((f) => (
    <button key={f} className={`tab ${f === (payload?.format ?? fmt) ? 'on' : ''}`} onClick={() => setFmt(f)}
      title={payload && !payload.projectFormats.includes(f) ? 'This project does not render this format' : undefined}>
      {f}{payload && !payload.projectFormats.includes(f) ? ' (not rendered)' : ''}
    </button>
  ));
  return (
    <Card title="Frame-accurate preview" actions={<>{tabs}{payload?.timing === 'voice' ? <Badge tone="success" title={payload?.timingNote}>real voice timing</Badge> : <Badge tone="warning" title={payload?.timingNote}>estimated timing</Badge>}{voiceBtn}{reload}</>}>
      {voice.busy ? (
        <div style={{marginBottom: 12}}>
          <div className="row between sm"><span>{voiceLabel}</span><span className="mono">{Math.round((Date.now() - voice.t0) / 1000)} s</span></div>
          <Progress value={voice.status?.progress ?? 0} />
        </div>
      ) : null}
      {voice.error ? <ErrorBox error={voice.error} title="Could not generate the preview voice" /> : null}
      {error ? <ErrorBox error={error} title="Could not load the preview" /> : !payload || !resolved ? <div className="skeleton" style={{height: 320}} /> : (
        <Stage key={`${payload.format}:${payload.propsHash}`} payload={payload} props={resolved} />
      )}
    </Card>
  );
};

const Stage: React.FC<{payload: PlayerPayload; props: RenderProps}> = ({payload, props}) => {
  const ref = useRef<PlayerRef>(null);
  const [loop, setLoop] = useState<string | null>(null);
  const audioUrl = payload.timing === 'voice' && payload.audio ? payload.audio.url : null;
  const inputProps = useMemo(() => ({props, audioUrl}), [props, audioUrl]);
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
          component={StoryboardWithVoice}
          inputProps={inputProps}
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
          numberOfSharedAudioTags={0}  // shared tags would load a data: mp3 the Studio CSP blocks; the voice gets its own <audio>
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
  const [muted, setMuted] = useState(false);
  useEffect(() => {
    const p = player.current;
    if (!p) return;
    const onFrame = (e: {detail: {frame: number}}) => setFrame(e.detail.frame);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onMute = (e: {detail: {isMuted: boolean}}) => setMuted(e.detail.isMuted);
    p.addEventListener('mutechange', onMute);
    p.addEventListener('frameupdate', onFrame);
    p.addEventListener('seeked', onFrame);
    p.addEventListener('play', onPlay);
    p.addEventListener('pause', onPause);
    p.addEventListener('ended', onPause);
    setFrame(p.getCurrentFrame());
    setMuted(p.isMuted());
    return () => {
      p.removeEventListener('mutechange', onMute);
      p.removeEventListener('frameupdate', onFrame);
      p.removeEventListener('seeked', onFrame);
      p.removeEventListener('play', onPlay);
      p.removeEventListener('pause', onPause);
      p.removeEventListener('ended', onPause);
    };
  }, [player]);
  return {frame, playing, muted};
}

const Controls: React.FC<{player: React.RefObject<PlayerRef | null>; payload: PlayerPayload; loop: PlayerScene | null; setLoop: (id: string | null) => void}> =
  ({player, payload, loop, setLoop}) => {
    const {frame, playing, muted} = usePlayerState(player);
    const hasVoice = payload.timing === 'voice' && !!payload.audio;
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
      else if (e.key === 'm' && hasVoice) { if (player.current?.isMuted()) player.current.unmute(); else player.current?.mute(); }
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
          {hasVoice ? (
            <Button variant="ghost" onClick={() => (muted ? player.current?.unmute() : player.current?.mute())} aria-pressed={muted} kbd="m" title="Mute or unmute the preview voice (M)">
              {muted ? 'Unmute' : 'Mute'}
            </Button>
          ) : null}
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

        <Alert tone="info" title={payload.timing === 'estimated' ? 'Estimated timing' : 'Real voice timing'}>
          {payload.timingNote}{' '}
          {hasVoice
            ? `You hear the narration only (${payload.audio!.durationS.toFixed(1)} s); sound effects and music are mixed in the full render.`
            : 'The preview is silent; use the real voice to hear the narration with exact timing. Sound effects and music are mixed in the full render.'}
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
