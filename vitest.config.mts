import {defineConfig} from 'vitest/config';

// Unit tests for pure engine logic (layout, timing, captions). No DOM / Chromium needed.
export default defineConfig({
  test: {
    include: ['src/**/__tests__/**/*.test.ts'],
    environment: 'node',
  },
});
