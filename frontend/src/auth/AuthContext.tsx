/**
 * Authentication state.
 *
 * Built on React context alone - the app has one small piece of shared state,
 * which does not justify another dependency.
 */

import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { fetchCurrentUser, login as loginRequest, register as registerRequest } from '@/api/auth';
import { setUnauthorizedHandler } from '@/lib/apiClient';
import { clearAuthToken, getAuthToken, setAuthToken } from '@/lib/authToken';
import type { LoginPayload, RegisterPayload, User } from '@/types/api';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  isAuthenticated: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Start in `loading` only when a stored token might still be valid.
  const [status, setStatus] = useState<AuthStatus>(() =>
    getAuthToken() ? 'loading' : 'unauthenticated',
  );

  const logout = useCallback(() => {
    clearAuthToken();
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  // End the session as soon as any request is rejected with a token attached,
  // rather than leaving the user on a page whose every request now fails.
  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  // Restore the session on first load: a stored token is only trusted once
  // the backend confirms it via /auth/me.
  useEffect(() => {
    if (!getAuthToken()) return;

    const controller = new AbortController();
    let active = true;

    fetchCurrentUser(controller.signal)
      .then((currentUser) => {
        if (!active) return;
        setUser(currentUser);
        setStatus('authenticated');
      })
      .catch(() => {
        if (!active || controller.signal.aborted) return;
        // Expired or revoked - drop it rather than keep a dead session.
        clearAuthToken();
        setUser(null);
        setStatus('unauthenticated');
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const login = useCallback(async (payload: LoginPayload) => {
    const token = await loginRequest(payload);
    setAuthToken(token.access_token);
    try {
      const currentUser = await fetchCurrentUser();
      setUser(currentUser);
      setStatus('authenticated');
    } catch (error) {
      clearAuthToken();
      setStatus('unauthenticated');
      throw error;
    }
  }, []);

  const register = useCallback(
    async (payload: RegisterPayload) => {
      await registerRequest(payload);
      // Registration does not return a token; sign in with the same details.
      await login({ email: payload.email, password: payload.password });
    },
    [login],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      isAuthenticated: status === 'authenticated',
      login,
      register,
      logout,
    }),
    [status, user, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
