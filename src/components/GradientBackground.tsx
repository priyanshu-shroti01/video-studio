import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {C} from '../theme';

/** Dark gradient with two orbs drifting on sine paths (demo-video-skill pattern). */
export const GradientBackground: React.FC<{a?: string; b?: string}> = ({a = C.brand, b = C.brand2}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const t = frame / fps;
  const size = Math.max(width, height) * 0.75;
  const orb = (color: string, x: number, y: number): React.CSSProperties => ({
    position: 'absolute',
    width: size,
    height: size,
    left: x - size / 2,
    top: y - size / 2,
    borderRadius: '50%',
    background: `radial-gradient(circle, ${color}55 0%, ${color}00 65%)`,
  });
  return (
    <AbsoluteFill style={{background: `linear-gradient(160deg, ${C.bg} 0%, ${C.surface} 100%)`}}>
      <div style={orb(a, width * (0.25 + 0.08 * Math.sin(t * 0.6)), height * (0.3 + 0.06 * Math.cos(t * 0.5)))} />
      <div style={orb(b, width * (0.75 + 0.08 * Math.cos(t * 0.45)), height * (0.7 + 0.06 * Math.sin(t * 0.55)))} />
    </AbsoluteFill>
  );
};
