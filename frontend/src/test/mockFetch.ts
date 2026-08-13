import { vi } from 'vitest';

/** Install a `fetch` stub returning `body` with the given status. */
export function mockJsonFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Install a `fetch` stub that rejects, simulating an unreachable backend. */
export function mockNetworkFailure() {
  const fetchMock = vi.fn(async () => {
    throw new TypeError('Failed to fetch');
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
