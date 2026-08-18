import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
// `vitest/config` re-exports Vite's defineConfig with the `test` block typed.
import { defineConfig } from 'vitest/config';

/**
 * Refuse to ship a production bundle that would call localhost.
 *
 * `src/config/env.ts` falls back to http://localhost:8000 when
 * VITE_API_BASE_URL is absent. That default is right for `npm run dev` and
 * silently wrong for a deployed build: the bundle compiles cleanly, passes
 * every test, and only fails in the user's browser, which cannot reach the
 * developer's laptop. A build is the last moment this is cheap to catch, so
 * catch it here instead of in DevTools.
 *
 * `loadEnv` sees both .env files and real environment variables, which is how
 * a host that injects configuration through its dashboard (Vercel, Netlify,
 * Cloudflare Pages) rather than a file still satisfies the check.
 *
 * Escape hatch for building a throwaway bundle against a local API:
 *   ALLOW_DEFAULT_API_URL=1 npm run build
 */
function assertProductionApiUrl(mode: string): void {
  if (process.env.ALLOW_DEFAULT_API_URL) return;

  const apiBaseUrl = loadEnv(mode, process.cwd(), 'VITE_').VITE_API_BASE_URL?.trim();

  if (!apiBaseUrl) {
    throw new Error(
      'VITE_API_BASE_URL is not set, so this production build would fall back to\n' +
        'http://localhost:8000 and every API call would fail once deployed.\n\n' +
        'Set it in your host\'s environment variables (Vercel: Project Settings ->\n' +
        'Environment Variables, scoped to Production AND Preview), or in a local\n' +
        'frontend/.env.production.local file.\n\n' +
        'To build against a local API anyway: ALLOW_DEFAULT_API_URL=1 npm run build',
    );
  }

  if (/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i.test(apiBaseUrl)) {
    throw new Error(
      `VITE_API_BASE_URL points at ${apiBaseUrl}, which no deployed browser can reach.\n` +
        'Use the public API origin, or pass ALLOW_DEFAULT_API_URL=1 if this build is\n' +
        'only ever going to be served from your own machine.',
    );
  }
}

export default defineConfig(({ command, mode }) => {
  if (command === 'build' && mode === 'production') {
    assertProductionApiUrl(mode);
  }

  return {
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
          // Charting is only needed on the Explore screen; splitting it keeps
          // the main bundle small and lets it be cached separately.
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
  };
});
