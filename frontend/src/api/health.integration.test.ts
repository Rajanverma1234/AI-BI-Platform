/**
 * Live frontend -> backend connectivity check.
 *
 * Skipped unless a backend is running and pointed at explicitly, so the normal
 * `npm test` run stays hermetic:
 *
 *   VITE_API_BASE_URL=http://127.0.0.1:8000 npm test -- health.integration
 */

import { describe, expect, it } from 'vitest';

import { fetchHealth, fetchReadiness } from '@/api/health';

const liveBackend = process.env.RUN_API_INTEGRATION === '1';

describe.skipIf(!liveBackend)('health API against a live backend', () => {
  it('reaches /api/v1/health through the real API client', async () => {
    const health = await fetchHealth();

    expect(health.status).toBe('ok');
    expect(health.service).toBeTruthy();
    expect(health.version).toBeTruthy();
  });

  it('reaches /api/v1/health/ready and reports the database', async () => {
    const readiness = await fetchReadiness();

    const database = readiness.dependencies.find((d) => d.name === 'database');
    expect(database?.status).toBe('ok');
  });
});
