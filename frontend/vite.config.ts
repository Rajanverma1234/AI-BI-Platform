import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
// `vitest/config` re-exports Vite's defineConfig with the `test` block typed.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    // Docker bind mounts do not always deliver native FS events.
    watch: { usePolling: true },
  },
  preview: {
    host: true,
    port: 4173,
  },
  build: {
    rollupOptions: {
      output: {
        // Charting is only needed on the Explore screen; splitting it keeps the
        // main bundle small and lets it be cached separately.
        manualChunks: {
          charts: ['recharts'],
          react: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // Vitest defaults to 5s per test, which is not enough for a screen that
    // renders React 19 + recharts in jsdom and waits on two chained fetches.
    // On a busy machine (or CI alongside a Docker stack) that produced
    // failures that moved around between runs. These raise the ceiling only;
    // a passing test still finishes in well under a second.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
