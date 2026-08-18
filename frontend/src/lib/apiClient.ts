/**
 * Centralised API client.
 *
 * Every network call in the app goes through here so URL construction,
 * timeouts, JSON handling and error normalisation live in one place.
 */

import { apiUrl } from '@/config/env';
import { getAuthToken } from '@/lib/authToken';
import type { ApiErrorBody } from '@/types/api';

export const DEFAULT_TIMEOUT_MS = 10_000;

/**
 * Notified when the backend rejects a request that carried a token.
 *
 * A token can expire at any point in a session, not just on the /auth/me call
 * made at startup. Without this, the next request would fail with an opaque
 * error and leave the user on a page that can no longer load anything.
 * `AuthProvider` registers a handler that ends the session cleanly.
 */
type UnauthorizedHandler = () => void;

let onUnauthorized: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

/** Fires only when a token was actually sent - a plain 401 on login is normal. */
function reportUnauthorized(status: number, hadToken: boolean): void {
  if (status === 401 && hadToken) onUnauthorized?.();
}

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
  /** Set false for endpoints that must not carry the bearer token. */
  withAuth?: boolean;
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
  const {
    body,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    headers,
    signal,
    withAuth = true,
    ...rest
  } = options;

  const token = withAuth ? getAuthToken() : null;

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
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
    reportUnauthorized(response.status, Boolean(token));
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

export interface UploadOptions {
  /** Called with 0-100 as the request body is transmitted. */
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
  method?: 'POST' | 'PUT';
}

/**
 * Multipart upload with progress reporting.
 *
 * Uses XMLHttpRequest because `fetch` cannot report upload progress. Error
 * normalisation matches `request()`, so callers still receive an `ApiError`.
 * The browser sets the multipart Content-Type (including the boundary), so it
 * must not be set here.
 */
export function uploadFile<T>(
  path: string,
  body: FormData,
  { onProgress, signal, method = 'POST' }: UploadOptions = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, apiUrl(path));
    xhr.responseType = 'text';

    const token = getAuthToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('Accept', 'application/json');

    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
    }

    const onAbort = () => xhr.abort();
    signal?.addEventListener('abort', onAbort);

    const cleanup = () => signal?.removeEventListener('abort', onAbort);

    xhr.onload = () => {
      cleanup();
      let payload: unknown = null;
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        payload = null;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as T);
        return;
      }

      reportUnauthorized(xhr.status, Boolean(token));
      if (isApiErrorBody(payload)) {
        reject(
          new ApiError(payload.error.message, {
            status: xhr.status,
            code: payload.error.code,
            details: payload.error.details,
            requestId: payload.request_id ?? null,
          }),
        );
        return;
      }
      reject(
        new ApiError(`Upload failed with status ${xhr.status}.`, {
          status: xhr.status,
          code: 'http_error',
        }),
      );
    };

    xhr.onerror = () => {
      cleanup();
      reject(new ApiError('Could not reach the API. Is the backend running?'));
    };

    xhr.onabort = () => {
      cleanup();
      reject(new ApiError('Upload cancelled.', { code: 'cancelled' }));
    };

    xhr.send(body);
  });
}

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

/**
 * Fetch a binary response as a blob.
 *
 * A plain `<a download>` cannot carry the bearer token, so file downloads go
 * through `fetch` and the caller turns the blob into an object URL. The
 * filename comes from Content-Disposition, falling back to the caller's name.
 */
export async function download(
  path: string,
  fallbackFilename: string,
  options: { timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<DownloadedFile> {
  const { timeoutMs = 120_000, signal } = options;
  const token = getAuthToken();

  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), timeoutMs);
  const onAbort = () => timeoutController.abort();
  signal?.addEventListener('abort', onAbort);

  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: timeoutController.signal,
    });
  } catch (cause) {
    const aborted = signal?.aborted === true;
    throw new ApiError(aborted ? 'Download cancelled.' : 'Could not reach the API.', {
      code: aborted ? 'cancelled' : 'network_error',
      details: cause,
    });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }

  if (!response.ok) {
    reportUnauthorized(response.status, Boolean(token));
    // A failure still returns the standard JSON error envelope.
    const payload = await parseBody(response);
    if (isApiErrorBody(payload)) {
      throw new ApiError(payload.error.message, {
        status: response.status,
        code: payload.error.code,
        details: payload.error.details,
      });
    }
    throw new ApiError(`Download failed with status ${response.status}.`, {
      status: response.status,
      code: 'http_error',
    });
  }

  const disposition = response.headers.get('content-disposition') ?? '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);

  return { blob: await response.blob(), filename: match?.[1] ?? fallbackFilename };
}

/** Prompt the browser to save a downloaded blob, then release the object URL. */
export function saveBlob({ blob, filename }: DownloadedFile): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Append defined query parameters to a path, skipping undefined values. */
export function withQuery(path: string, params: object = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.append(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
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
