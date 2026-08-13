import { describe, expect, it } from 'vitest';

import { apiUrl, env } from '@/config/env';

describe('env configuration', () => {
  it('falls back to sane local defaults', () => {
    expect(env.apiBaseUrl).toMatch(/^https?:\/\//);
    expect(env.apiVersionPrefix).toBe('/api/v1');
  });

  it('never leaves a trailing slash on the base URL', () => {
    expect(env.apiBaseUrl.endsWith('/')).toBe(false);
  });

  it('builds versioned URLs with or without a leading slash', () => {
    expect(apiUrl('/health')).toBe(`${env.apiBaseUrl}/api/v1/health`);
    expect(apiUrl('health')).toBe(`${env.apiBaseUrl}/api/v1/health`);
  });
});
