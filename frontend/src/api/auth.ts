/** Authentication endpoints. */

import { apiClient } from '@/lib/apiClient';
import type { LoginPayload, RegisterPayload, TokenResponse, User } from '@/types/api';

export function register(payload: RegisterPayload): Promise<User> {
  // No token exists yet, and sending a stale one would be misleading.
  return apiClient.post<User>('/auth/register', payload, { withAuth: false });
}

export function login(payload: LoginPayload): Promise<TokenResponse> {
  return apiClient.post<TokenResponse>('/auth/login', payload, { withAuth: false });
}

export function fetchCurrentUser(signal?: AbortSignal): Promise<User> {
  return apiClient.get<User>('/auth/me', signal ? { signal } : {});
}
