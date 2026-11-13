import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {pageWords, VoiceoverTiming} from '../lib/voiceover';
import {C, FONT} from '../theme';

/**
 * Word-synced karaoke caption driven by edge-tts WordBoundary timings.
 * Shows one short "page" of words at a time; the current word is highlighted.
 */
export const SyncedCaption: React.FC<{
  timing: VoiceoverTiming | null;
  /** seconds the narration is delayed in the final audio */
  offset?: number;
  maxWords: number;
  fontSize: number;
  /** distance from the bottom edge, px */
  bottom: number;
  maxWidthFrac?: number;
  highlight?: string;
  fontFamily?: string;
}> = ({timing, offset = 0, maxWords, fontSize, bottom, maxWidthFrac = 0.84, highlight = C.highlight, fontFamily = FONT}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  if (!timing || timing.words.length === 0) return null;
  const t = frame / fps - offset;
  const pages = pageWords(timing.words, maxWords);
  // current page = last page whose first word has started (hold it until the next page starts)
  let idx = -1;
  for (let i = 0; i < pages.length; i++) if (t >= pages[i][0].start - 0.05) idx = i;
  if (idx < 0) return null;
  const page = pages[idx];
  const pageEnd = page[page.length - 1].end;
  if (idx === pages.length - 1 && t > pageEnd + 0.6) return null; // clear after the last word

  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom, display: 'flex', justifyContent: 'center'}}>
      <div
        style={{
          maxWidth: width * maxWidthFrac,
          textAlign: 'center',
          fontFamily,
          fontWeight: 800,
          fontSize,
          lineHeight: 1.15,
          padding: `${fontSize * 0.25}px ${fontSize * 0.5}px`,
          borderRadius: fontSize * 0.35,
          background: 'rgba(0,0,0,0.55)',
          textShadow: '0 4px 18px rgba(0,0,0,0.6)',
        }}
      >
        {page.map((w, i) => {
          const current = t >= w.start && t <= w.end;
          const spoken = t > w.end;
          return (
            <span
              key={i}
              style={{
                color: current ? highlight : spoken ? C.ink : 'rgba(255,255,255,0.45)',
                display: 'inline-block',
                transform: current ? 'scale(1.08)' : 'scale(1)',
                margin: `0 ${fontSize * 0.2}px`,
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
