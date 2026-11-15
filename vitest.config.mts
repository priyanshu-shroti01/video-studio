import {defineConfig} from 'vitest/config';

// Unit tests for pure engine logic (layout, timing, captions) and the Studio's pure helpers. No DOM / Chromium needed.
export default defineConfig({
  test: {
    include: ['src/**/__tests__/**/*.test.ts', 'studio/web/src/**/__tests__/**/*.test.ts'],
    environment: 'node',
  },
});
