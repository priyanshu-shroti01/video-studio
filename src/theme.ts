export const FPS = 30;

export const FORMATS = {
  short: {width: 1080, height: 1920}, // 9:16 — YouTube Shorts / Reels / TikTok
  landscape: {width: 1920, height: 1080}, // 16:9 — YouTube / presentations
} as const;

// Placeholder palette — swap for the Shroti Host brand colours.
export const C = {
  bg: '#07090F',
  surface: '#121726',
  brand: '#6C5CE7',
  brand2: '#00D2D3',
  accent: '#FFB86B',
  ink: '#F5F6FA',
  soft: '#A4ABC4',
  highlight: '#FFD54A',
};

export const FONT =
  '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", "Helvetica Neue", Arial, sans-serif';
