import React from 'react';
import {TextSpec} from './geometry';
import {useEngine} from './ui';

/** A text run drawn exactly where geometry.ts (and therefore the QA manifest) says it is. */
export const Txt: React.FC<{s: TextSpec; color: string; style?: React.CSSProperties; children?: React.ReactNode}> = ({s, color, style, children}) => {
  const {sans, mono} = useEngine();
  return (
    <div
      style={{
        position: 'absolute',
        left: s.x,
        top: s.y,
        width: s.w,
        height: s.h,
        lineHeight: `${s.h}px`,
        fontFamily: s.mono ? mono : sans,
        fontSize: s.fs,
        fontWeight: s.weight,
        letterSpacing: s.ls,
        textAlign: s.align,
        whiteSpace: 'nowrap',
        color,
        ...style,
      }}
    >
      {children ?? s.text}
    </div>
  );
};

/** Sequential reader over a geometry's text list (geometry pushes runs in a fixed order). */
export const reader = (texts: TextSpec[]) => {
  let i = 0;
  return () => texts[i++];
};

