/**
 * Centralised API client.
 *
 * Every network call in the app goes through here so URL construction,
 * timeouts, JSON handling and error normalisation live in one place.
 */

import { apiUrl } from '@/config/env';
import type { ApiErrorBody } from '@/types/api';

export const DEFAULT_TIMEOUT_MS = 10_000;

/** Normalised failure - the UI never has to inspect raw fetch errors. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: { status?: number; code?: string; details?: unknown; requestId?: string | null } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status ?? 0;
    this.code = options.code ?? 'network_error';
    this.details = options.details ?? null;
    this.requestId = options.requestId ?? null;
  }

  /** True when the request never reached the backend. */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  timeoutMs?: number;
  /** Caller-supplied signal; composed with the internal timeout signal. */
  signal?: AbortSignal;
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof (value as ApiErrorBody).error?.message === 'string'
  );
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    return await response.text();
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** Perform a versioned API request and return the parsed JSON payload. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, timeoutMs = DEFAULT_TIMEOUT_MS, headers, signal, ...rest } = options;

  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), timeoutMs);
  const onAbort = () => timeoutController.abort();
  signal?.addEventListener('abort', onAbort);

  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...rest,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...headers,
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: timeoutController.signal,
    });
  } catch (cause) {
    const aborted = signal?.aborted === true;
    throw new ApiError(
      aborted ? 'Request cancelled.' : 'Could not reach the API. Is the backend running?',
      { code: aborted ? 'cancelled' : 'network_error', details: cause },
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }

  const payload = await parseBody(response);

  if (!response.ok) {
    if (isApiErrorBody(payload)) {
      throw new ApiError(payload.error.message, {
        status: response.status,
        code: payload.error.code,
        details: payload.error.details,
        requestId: payload.request_id ?? null,
      });
    }
    throw new ApiError(`Request failed with status ${response.status}.`, {
      status: response.status,
      code: 'http_error',
      details: payload,
    });
  }

  return payload as T;
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};
