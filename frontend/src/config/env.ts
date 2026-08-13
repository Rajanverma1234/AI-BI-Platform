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
}

function readString(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replace(/\/+$/, '') : fallback;
}

export const env: AppEnv = {
  apiBaseUrl: readString(import.meta.env.VITE_API_BASE_URL, 'http://localhost:8000'),
  apiVersionPrefix: readString(import.meta.env.VITE_API_VERSION_PREFIX, '/api/v1'),
  appName: import.meta.env.VITE_APP_NAME?.trim() || 'AI BI Platform',
  isProduction: import.meta.env.PROD,
};

/** Absolute URL for a versioned API path, e.g. `apiUrl('/health')`. */
export function apiUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${env.apiBaseUrl}${env.apiVersionPrefix}${suffix}`;
}
