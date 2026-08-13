/**
 * Access token storage.
 *
 * The token is held in a module variable and mirrored into localStorage so a
 * page reload keeps the session. localStorage is readable by any script on the
 * origin, so this trades some XSS exposure for a simple stateless backend; the
 * safer alternative (an httpOnly refresh cookie) needs server-side session
 * endpoints that do not exist yet. Keeping every read and write in this one
 * module means that swap only touches this file.
 */

const STORAGE_KEY = 'aibi.access_token';

let inMemoryToken: string | null = null;

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    // Private-mode or a non-browser environment.
    return null;
  }
}

export function getAuthToken(): string | null {
  if (inMemoryToken !== null) return inMemoryToken;
  inMemoryToken = safeStorage()?.getItem(STORAGE_KEY) ?? null;
  return inMemoryToken;
}

export function setAuthToken(token: string): void {
  inMemoryToken = token;
  safeStorage()?.setItem(STORAGE_KEY, token);
}

export function clearAuthToken(): void {
  inMemoryToken = null;
  safeStorage()?.removeItem(STORAGE_KEY);
}
