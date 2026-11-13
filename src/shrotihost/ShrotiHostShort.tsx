import React from 'react';
import {AbsoluteFill, Audio, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {SyncedCaption} from '../components/SyncedCaption';
import {VoiceoverTiming} from '../lib/voiceover';
import {lin, useT} from './anim';
import {B, BT, loadBrandFonts, SANS, TL} from './brand';
import {Hook} from './scenes/Hook';
import {Journey} from './scenes/Journey';
import {Problem} from './scenes/Problem';
import {Resolution} from './scenes/Resolution';
import {BrandLogo, Turn} from './scenes/Turn';
import {Backdrop, Logo} from './ui';

loadBrandFonts();

export type ShrotiProps = {
  /** final mix from scripts/legacy/mix_audio.py (relative to public/) */
  audio: string;
  /** word timings from scripts/legacy/voiceover.py */
  voiceover: string;
  /** filled in by calculateMetadata */
  timing: VoiceoverTiming | null;
};

export const shrotiDefaults: ShrotiProps = {
  audio: 'audio/shrotihost-mix.wav',
  voiceover: 'voiceover/shrotihost.json',
  timing: null,
};

const inAct = (t: number, act: keyof typeof TL.acts, pad = 0.15) => t >= TL.acts[act][0] - pad && t <= TL.acts[act][1] + 0.05;

export const ShrotiHostShort: React.FC<ShrotiProps> = ({audio, timing}) => {
  const t = useT();
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames - 1], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  // backdrop mood: red tint while the problem plays, a purple bloom behind the logo reveal
  const danger = Math.min(lin(t, TL.acts.problem[0] - 0.2, TL.acts.problem[0] + 0.3), 1 - lin(t, TL.acts.turn[0] - 0.3, TL.acts.turn[0]));
  const bloom = Math.min(lin(t, BT.turn, BT.shroti + 0.1), 1 - lin(t, BT.fast, BT.fast + 0.6)) * 0.9;

  return (
    <AbsoluteFill style={{background: B.bg, fontFamily: SANS, opacity: fadeOut}}>
      <Backdrop t={t} danger={danger} bloom={bloom} />
      <Audio src={staticFile(audio)} />

      {inAct(t, 'hook') ? <Hook t={t} /> : null}
      {inAct(t, 'problem') ? <Problem t={t} /> : null}
      {inAct(t, 'turn') ? <Turn t={t} /> : null}
      <BrandLogo t={t} render={(w) => <Logo width={w} />} />
      {inAct(t, 'journey') ? <Journey t={t} /> : null}
      {inAct(t, 'resolution') ? <Resolution t={t} /> : null}

      {/* word-synced captions in the bottom-centre safe zone (clear of the Shorts title/buttons overlay) */}
      <SyncedCaption
        timing={timing}
        offset={TL.voiceStart}
        maxWords={4}
        fontSize={66}
        bottom={520}
        maxWidthFrac={0.8}
        highlight={B.purpleText}
        fontFamily={SANS}
      />
    </AbsoluteFill>
  );
};
