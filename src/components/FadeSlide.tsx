import React from 'react';
import {spring, useCurrentFrame, useVideoConfig} from 'remotion';

type Dir = 'up' | 'down' | 'left' | 'right';

/** Spring entrance (opacity + translate). `delay` is in frames. damping 15 / mass 0.8 per demo-video-skill. */
export const FadeSlide: React.FC<{
  delay?: number;
  direction?: Dir;
  distance?: number;
  damping?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({delay = 0, direction = 'up', distance = 40, damping = 15, children, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame: frame - delay, fps, config: {damping, mass: 0.8}});
  const off = (1 - p) * distance;
  const tx = direction === 'left' ? off : direction === 'right' ? -off : 0;
  const ty = direction === 'up' ? off : direction === 'down' ? -off : 0;
  return <div style={{opacity: p, transform: `translate(${tx}px, ${ty}px)`, ...style}}>{children}</div>;
};
