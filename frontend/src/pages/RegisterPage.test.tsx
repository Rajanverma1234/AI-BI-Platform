import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, getAuthToken } from '@/lib/authToken';
import { authenticatedHandlers, errorBody, mockApi, TEST_USER } from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';

const TOKEN = 'issued-access-token';

const SUCCESS_HANDLERS = authenticatedHandlers({
  'POST /auth/register': { status: 201, body: TEST_USER },
  'POST /auth/login': {
    body: { access_token: TOKEN, token_type: 'bearer', expires_in: 3600 },
  },
});

async function fillAndSubmit(email: string, password: string, displayName?: string) {
  await userEvent.type(screen.getByLabelText('Email'), email);
  if (displayName) {
    await userEvent.type(screen.getByLabelText('Display name'), displayName);
  }
  await userEvent.type(screen.getByLabelText('Password'), password);
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
}

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
  });

  it('renders the registration form', async () => {
    mockApi(authenticatedHandlers());

    renderApp('/register');

    expect(await screen.findByRole('heading', { name: 'Create an account' })).toBeInTheDocument();
    expect(screen.getByLabelText('Display name')).toBeInTheDocument();
  });

  it('registers, signs in and enters the app', async () => {
    const fetchMock = mockApi(SUCCESS_HANDLERS);
    renderApp('/register');
    await screen.findByRole('heading', { name: 'Create an account' });

    await fillAndSubmit('owner@example.com', 'correct-horse-battery', 'Owner');

    expect(await screen.findByTestId('current-user')).toHaveTextContent('Owner');
    expect(getAuthToken()).toBe(TOKEN);
    const called = fetchMock.mock.calls.map(([url]) => String(url));
    expect(called.some((url) => url.endsWith('/auth/register'))).toBe(true);
    expect(called.some((url) => url.endsWith('/auth/login'))).toBe(true);
  });

  it('rejects a short password before calling the API', async () => {
    const fetchMock = mockApi(SUCCESS_HANDLERS);
    renderApp('/register');
    await screen.findByRole('heading', { name: 'Create an account' });
    fetchMock.mockClear();

    await fillAndSubmit('owner@example.com', 'short');

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least 8 characters/i);
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).endsWith('/auth/register')),
    ).toBe(false);
  });

  it('shows a duplicate-email conflict from the backend', async () => {
    mockApi(
      authenticatedHandlers({
        'POST /auth/register': {
          status: 409,
          body: errorBody('conflict', 'An account with this email already exists.'),
        },
      }),
    );
    renderApp('/register');
    await screen.findByRole('heading', { name: 'Create an account' });

    await fillAndSubmit('taken@example.com', 'correct-horse-battery');

    expect(await screen.findByRole('alert')).toHaveTextContent(/already exists/);
    expect(getAuthToken()).toBeNull();
  });
});
