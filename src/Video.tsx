import React from 'react';
import {AbsoluteFill, Audio, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {FadeSlide} from './components/FadeSlide';
import {GradientBackground} from './components/GradientBackground';
import {SyncedCaption} from './components/SyncedCaption';
import {VoiceoverTiming} from './lib/voiceover';
import {C, FONT} from './theme';

export type VideoProps = {
  headline: string;
  subline: string;
  /** timing JSON in public/ written by scripts/legacy/voiceover.py (drives duration + captions) */
  voiceover: string | null;
  /** audio to play, relative to public/. Use the final mix from scripts/legacy/mix_audio.py;
   *  if null, the raw voiceover mp3 from the timing JSON is used. */
  audio: string | null;
  /** where the narration starts inside `audio` (the --voice FILE@START_S you gave mix_audio.py) */
  voiceStart: number;
  /** seconds to hold after the audio ends */
  tailSeconds: number;
  /** filled in by calculateMetadata — leave null */
  timing: VoiceoverTiming | null;
};

export const defaultVideoProps: VideoProps = {
  headline: 'Shroti Host',
  subline: 'Your story, told in seconds.',
  voiceover: 'voiceover/test.json',
  audio: null,
  voiceStart: 0,
  tailSeconds: 0.5,
  timing: null,
};

/** One composition component; layout adapts to 9:16 vs 16:9 from the video config. */
export const MainVideo: React.FC<VideoProps> = ({headline, subline, audio, voiceStart, timing}) => {
  const frame = useCurrentFrame();
  const {width, height, durationInFrames} = useVideoConfig();
  const vertical = height > width;
  const fadeOut = interpolate(frame, [durationInFrames - 10, durationInFrames - 1], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const src = audio ?? timing?.audio ?? null;

  return (
    <AbsoluteFill style={{opacity: fadeOut, fontFamily: FONT, color: C.ink}}>
      <GradientBackground />
      {src ? <Audio src={staticFile(src)} /> : null}

      <AbsoluteFill
        style={{
          justifyContent: 'center',
          alignItems: 'center',
          textAlign: 'center',
          // Shorts: keep content in the upper-middle, clear of the platform UI at the bottom/right
          paddingBottom: vertical ? height * 0.18 : 0,
          paddingLeft: width * 0.08,
          paddingRight: width * 0.08,
        }}
      >
        <FadeSlide delay={4} damping={20}>
          <div style={{fontSize: vertical ? 132 : 140, fontWeight: 900, letterSpacing: -2, lineHeight: 1}}>
            {headline}
          </div>
        </FadeSlide>
        <FadeSlide delay={14}>
          <div style={{marginTop: 28, fontSize: vertical ? 54 : 52, fontWeight: 600, color: C.soft}}>{subline}</div>
        </FadeSlide>
      </AbsoluteFill>

      <SyncedCaption
        timing={timing}
        offset={audio ? voiceStart : 0}
        maxWords={vertical ? 4 : 8}
        fontSize={vertical ? 76 : 56}
        bottom={vertical ? height * 0.27 : 90}
      />
    </AbsoluteFill>
  );
};
