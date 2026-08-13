import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, getAuthToken, setAuthToken } from '@/lib/authToken';
import { authenticatedHandlers, errorBody, mockApi, TEST_USER } from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';

const TOKEN = 'a-valid-access-token';

describe('authentication state', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
  });

  it('treats a visitor with no token as unauthenticated', async () => {
    mockApi(authenticatedHandlers());

    renderApp('/');

    // The protected route sends them to the login screen.
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('restores a session from a stored token via /auth/me', async () => {
    setAuthToken(TOKEN);
    mockApi(authenticatedHandlers());

    renderApp('/');

    expect(await screen.findByTestId('current-user')).toHaveTextContent('Owner');
  });

  it('sends the token as a bearer header', async () => {
    setAuthToken(TOKEN);
    const fetchMock = mockApi(authenticatedHandlers());

    renderApp('/');
    await screen.findByTestId('current-user');

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it('discards a stored token the backend rejects', async () => {
    setAuthToken('an-expired-token');
    mockApi({
      ...authenticatedHandlers(),
      'GET /auth/me': { status: 401, body: errorBody('unauthorized', 'Token has expired.') },
    });

    renderApp('/');

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    await waitFor(() => expect(getAuthToken()).toBeNull());
  });

  it('logs out, clears the token and returns to the login screen', async () => {
    setAuthToken(TOKEN);
    mockApi(authenticatedHandlers());
    renderApp('/');
    await screen.findByTestId('current-user');

    await userEvent.click(screen.getByRole('button', { name: 'Log out' }));

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(getAuthToken()).toBeNull();
  });
});

describe('protected routes', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
  });

  it.each(['/', '/workspaces', '/system'])(
    'redirects an unauthenticated visitor away from %s',
    async (path) => {
      mockApi(authenticatedHandlers());

      renderApp(path);

      expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    },
  );

  it('lets an authenticated user reach a protected route', async () => {
    setAuthToken(TOKEN);
    mockApi(authenticatedHandlers());

    renderApp('/workspaces');

    expect(await screen.findByRole('heading', { name: 'Workspaces' })).toBeInTheDocument();
  });

  it('keeps a signed-in user off the login screen', async () => {
    setAuthToken(TOKEN);
    mockApi(authenticatedHandlers());

    renderApp('/login');

    expect(await screen.findByTestId('current-user')).toHaveTextContent(TEST_USER.display_name!);
  });
});
