// Frame-rate independence (quality presets: 30 fps standard, 60 fps smooth/ultra). Everything is a function of
// t = frame / fps in seconds; only constants that were counted in frames need converting.
import {describe, expect, it} from 'vitest';
import {VIDEO_FADE_S, videoFadeFrames} from '../motion/durations';
import {blockEntrance, motionBlurLevel, springAt} from '../motion/entrances';
import {MOTION_PRESETS} from '../motion/presets';
import {SPRING} from '../motion/easings';

describe('engine at 60 fps', () => {
  it('end-of-video fade lasts the same time at every frame rate (12 frames at 30 fps, as before)', () => {
    expect(videoFadeFrames(30)).toBe(12);
    expect(videoFadeFrames(60)).toBe(24);
    expect(videoFadeFrames(60) / 60).toBeCloseTo(VIDEO_FADE_S, 6);
  });

  it('springs are time-based: the same t gives the same progress at 30 and 60 fps', () => {
    for (const t of [10, 10.1, 10.2, 10.5, 11]) {
      expect(springAt(t, 10, 60, SPRING.pop)).toBeCloseTo(springAt(t, 10, 30, SPRING.pop), 6);
    }
    // 60 fps samples halfway between 30-fps frames: progress lies between its neighbours (monotone entrance)
    const mid = springAt(10 + 1.5 / 30, 10, 60, SPRING.land);
    expect(mid).toBeGreaterThan(springAt(10 + 1 / 30, 10, 30, SPRING.land));
    expect(mid).toBeLessThan(springAt(10 + 2 / 30, 10, 30, SPRING.land));
  });

  it('block entrance position is identical at shared instants', () => {
    const m = MOTION_PRESETS.energetic;
    for (const t of [9.9, 10.0, 10.1, 10.3]) {
      const a = blockEntrance(t, 10, 30, m);
      const b = blockEntrance(t, 10, 60, m);
      expect(b.dy).toBeCloseTo(a.dy, 6);
      expect(b.opacity).toBeCloseTo(a.opacity, 6);
    }
  });

  it('motion blur is per output frame (fixed shutter): never more smear at 60 fps than at 30', () => {
    const m = MOTION_PRESETS.energetic;
    let any30 = 0;
    for (let i = 0; i < 30; i++) {
      const t = 9.95 + i / 30;
      const l30 = motionBlurLevel(t, 10, 30, m, m.entrance.offsetY);
      const l60 = motionBlurLevel(t, 10, 60, m, m.entrance.offsetY);
      any30 = Math.max(any30, l30);
      expect(l60).toBeLessThanOrEqual(l30);
    }
    expect(any30).toBeGreaterThan(0);
  });
});
