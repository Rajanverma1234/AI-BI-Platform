import { beforeEach, describe, expect, it, vi } from 'vitest';

import { env } from '@/config/env';
import { ApiError, apiClient } from '@/lib/apiClient';
import { mockJsonFetch, mockNetworkFailure } from '@/test/mockFetch';

describe('apiClient', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('builds versioned absolute URLs', async () => {
    const fetchMock = mockJsonFetch({ status: 'ok' });

    await apiClient.get('/health');

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = vi.mocked(fetchMock).mock.calls[0] as unknown as [string];
    expect(url).toBe(`${env.apiBaseUrl}${env.apiVersionPrefix}/health`);
  });

  it('returns the parsed JSON payload', async () => {
    mockJsonFetch({ status: 'ok', service: 'AI BI Platform' });

    await expect(apiClient.get('/health')).resolves.toMatchObject({ status: 'ok' });
  });

  it('normalises the backend error envelope into an ApiError', async () => {
    mockJsonFetch(
      { error: { code: 'not_found', message: 'Nope.', details: null }, request_id: 'r-1' },
      404,
    );

    const error = await apiClient.get('/missing').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: 'not_found',
      message: 'Nope.',
      requestId: 'r-1',
    });
  });

  it('reports an unreachable backend as a network error', async () => {
    mockNetworkFailure();

    const error = (await apiClient.get('/health').catch((e: unknown) => e)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.isNetworkError).toBe(true);
    expect(error.message).toMatch(/Could not reach the API/);
  });

  it('handles a non-JSON error response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('upstream exploded', { status: 502 })),
    );

    const error = (await apiClient.get('/health').catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(502);
    expect(error.code).toBe('http_error');
  });

  it('serialises the request body as JSON', async () => {
    const fetchMock = mockJsonFetch({ ok: true });

    await apiClient.post('/things', { name: 'x' });

    const [, init] = vi.mocked(fetchMock).mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe('POST');
    expect(init.body).toBe(JSON.stringify({ name: 'x' }));
  });
});
