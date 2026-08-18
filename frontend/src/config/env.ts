/**
 * Typed access to build-time environment configuration.
 *
 * Only variables prefixed with `VITE_` are exposed to the browser by Vite.
 * Never put secrets here - anything in this file ships to the client.
 */

interface AppEnv {
  apiBaseUrl: string;
  apiVersionPrefix: string;
  appName: string;
  isProduction: boolean;
  /** Per-request ceiling for ordinary JSON calls, in milliseconds. */
  apiTimeoutMs: number;
}

function readString(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replace(/\/+$/, '') : fallback;
}

function readPositiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value?.trim());
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

/**
 * Default request ceiling.
 *
 * Deliberately generous: a container that scales to zero when idle - Render's
 * free tier, Cloud Run with min-instances=0 - takes tens of seconds to answer
 * its first request, and a short timeout turns that cold start into
 * "Could not reach the API. Is the backend running?" on the user's very first
 * action. Override with VITE_API_TIMEOUT_MS when the API is always warm.
 */
const DEFAULT_API_TIMEOUT_MS = 45_000;

export const env: AppEnv = {
  apiBaseUrl: readString(import.meta.env.VITE_API_BASE_URL, 'http://localhost:8000'),
  apiVersionPrefix: readString(import.meta.env.VITE_API_VERSION_PREFIX, '/api/v1'),
  appName: import.meta.env.VITE_APP_NAME?.trim() || 'AI BI Platform',
  isProduction: import.meta.env.PROD,
  apiTimeoutMs: readPositiveInt(import.meta.env.VITE_API_TIMEOUT_MS, DEFAULT_API_TIMEOUT_MS),
};

/** Absolute URL for a versioned API path, e.g. `apiUrl('/health')`. */
export function apiUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${env.apiBaseUrl}${env.apiVersionPrefix}${suffix}`;
}
