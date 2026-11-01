import { defineConfig } from 'vitest/config';

// The site's pattern: plain Node with hand-written binding stubs, no workerd.
export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
});
