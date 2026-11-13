import {getAudioDurationInSeconds} from '@remotion/media-utils';
import React from 'react';
import {CalculateMetadataFunction, Composition, staticFile} from 'remotion';
import {loadVoiceover} from './lib/voiceover';
import {ShrotiHostShort, shrotiDefaults, ShrotiProps} from './shrotihost/ShrotiHostShort';
import {TL} from './shrotihost/brand';
import {defaultVideoProps, MainVideo, VideoProps} from './Video';
import sampleShortJson from './engine/fixtures/sample-short.json';
import {calculateStoryboardMetadata, Storyboard} from './engine/Storyboard';
import {RenderProps} from './engine/types';
import {FORMATS, FPS} from './theme';

const FALLBACK_SECONDS = 6;
const sampleShort = sampleShortJson as unknown as RenderProps;

/** Duration = exact voiceover duration + tail, so the video is never longer than the narration needs. */
const calculateMetadata: CalculateMetadataFunction<VideoProps> = async ({props}) => {
  const timing = await loadVoiceover(props.voiceover);
  const offset = props.audio ? props.voiceStart : 0;
  let seconds = timing ? offset + timing.duration + props.tailSeconds : FALLBACK_SECONDS;
  // a final mix (music tail, late SFX) can run longer than the narration — never cut it off
  if (props.audio) seconds = Math.max(seconds, await getAudioDurationInSeconds(staticFile(props.audio)));
  return {durationInFrames: Math.max(1, Math.ceil(seconds * FPS)), props: {...props, timing}};
};

/** Shroti Host Short: length comes from the beat sheet (voiceover + tail), captions from the word timings. */
const shrotiMetadata: CalculateMetadataFunction<ShrotiProps> = async ({props}) => {
  const timing = await loadVoiceover(props.voiceover);
  return {durationInFrames: Math.round(TL.duration * FPS), props: {...props, timing}};
};

export const RemotionRoot: React.FC = () => (
  <>
    {/* 9:16 YouTube Short — Shroti Host */}
    <Composition
      id="Short"
      component={ShrotiHostShort}
      fps={FPS}
      width={FORMATS.short.width}
      height={FORMATS.short.height}
      durationInFrames={Math.round(TL.duration * FPS)}
      defaultProps={shrotiDefaults}
      calculateMetadata={shrotiMetadata}
    />
    {/* generic starter templates (used by scripts/verify.sh) */}
    <Composition
      id="StarterShort"
      component={MainVideo}
      fps={FPS}
      width={FORMATS.short.width}
      height={FORMATS.short.height}
      durationInFrames={FALLBACK_SECONDS * FPS}
      defaultProps={defaultVideoProps}
      calculateMetadata={calculateMetadata}
    />
    <Composition
      id="Landscape"
      component={MainVideo}
      fps={FPS}
      width={FORMATS.landscape.width}
      height={FORMATS.landscape.height}
      durationInFrames={FALLBACK_SECONDS * FPS}
      defaultProps={defaultVideoProps}
      calculateMetadata={calculateMetadata}
    />
    {/* data-driven engine: everything (format, duration, theme, scenes, captions) comes from RenderProps
        produced by the Python orchestrator; size/fps/duration are set by calculateMetadata */}
    <Composition
      id="Storyboard"
      component={Storyboard}
      fps={FPS}
      width={FORMATS.short.width}
      height={FORMATS.short.height}
      durationInFrames={sampleShort.durationInFrames}
      defaultProps={sampleShort}
      calculateMetadata={calculateStoryboardMetadata}
    />
  </>
);
