/**
 * Route-aware fetch stub.
 *
 * Tests declare handlers per "METHOD /path" so a screen that makes several
 * calls does not need a hand-rolled fetch mock each time.
 */

import { vi } from 'vitest';

import type { Project, User, Workspace } from '@/types/api';

export interface MockResponse {
  status?: number;
  body?: unknown;
}

export type Handlers = Record<string, MockResponse | (() => MockResponse)>;

export const TEST_USER: User = {
  id: '11111111-1111-4111-8111-111111111111',
  email: 'owner@example.com',
  display_name: 'Owner',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

export const TEST_WORKSPACE: Workspace = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Analytics',
  slug: 'analytics',
  description: null,
  owner_id: TEST_USER.id,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

export const TEST_PROJECT: Project = {
  id: '33333333-3333-4333-8333-333333333333',
  name: 'Sales',
  slug: 'sales',
  description: null,
  workspace_id: TEST_WORKSPACE.id,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

/** Wrap items in the backend's pagination envelope. */
export function page<T>(
  items: T[],
  overrides: { total?: number; page?: number; page_size?: number } = {},
) {
  const total = overrides.total ?? items.length;
  const pageNumber = overrides.page ?? 1;
  const pageSize = overrides.page_size ?? 20;
  const totalPages = total === 0 ? 0 : Math.ceil(total / pageSize);
  return {
    items,
    total,
    page: pageNumber,
    page_size: pageSize,
    total_pages: totalPages,
    has_next: pageNumber < totalPages,
    has_previous: pageNumber > 1 && total > 0,
  };
}

export function errorBody(code: string, message: string) {
  return { error: { code, message, details: null }, request_id: 'test-request' };
}

/** Install a fetch stub driven by `handlers`; unmatched routes 404. */
export function mockApi(handlers: Handlers) {
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = (init?.method ?? 'GET').toUpperCase();
    // Match on the path only; the base URL is environment-dependent.
    const path = new URL(url).pathname.replace('/api/v1', '');
    const key = `${method} ${path}`;

    const handler = handlers[key];
    if (handler === undefined) {
      return new Response(JSON.stringify(errorBody('not_found', `No handler for ${key}`)), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      });
    }

    const { status = 200, body = null } = typeof handler === 'function' ? handler() : handler;
    return new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  });

  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Handlers for a signed-in session with no workspaces. */
export function authenticatedHandlers(extra: Handlers = {}): Handlers {
  return {
    'GET /auth/me': { body: TEST_USER },
    'GET /health': {
      body: { status: 'ok', service: 'AI BI Platform', version: '0.1.0', environment: 'test' },
    },
    'GET /workspaces': { body: page([]) },
    ...extra,
  };
}
