import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, getAuthToken } from '@/lib/authToken';
import { authenticatedHandlers, errorBody, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';

const TOKEN = 'issued-access-token';

async function fillAndSubmit(email: string, password: string) {
  await userEvent.type(screen.getByLabelText('Email'), email);
  await userEvent.type(screen.getByLabelText('Password'), password);
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
  });

  it('renders the sign-in form', async () => {
    mockApi(authenticatedHandlers());

    renderApp('/login');

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('stores the token and enters the app on success', async () => {
    mockApi(
      authenticatedHandlers({
        'POST /auth/login': {
          body: { access_token: TOKEN, token_type: 'bearer', expires_in: 3600 },
        },
      }),
    );
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Sign in' });

    await fillAndSubmit('owner@example.com', 'correct-horse-battery');

    expect(await screen.findByTestId('current-user')).toHaveTextContent('Owner');
    expect(getAuthToken()).toBe(TOKEN);
  });

  it('shows the backend error and stays put on bad credentials', async () => {
    mockApi(
      authenticatedHandlers({
        'POST /auth/login': {
          status: 401,
          body: errorBody('unauthorized', 'Incorrect email or password.'),
        },
      }),
    );
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Sign in' });

    await fillAndSubmit('owner@example.com', 'wrong-password');

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.');
    expect(getAuthToken()).toBeNull();
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('surfaces an unreachable backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Sign in' });

    await fillAndSubmit('owner@example.com', 'correct-horse-battery');

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not reach the API/);
  });

  it('offers a link to registration', async () => {
    mockApi(authenticatedHandlers());

    renderApp('/login');

    expect(await screen.findByRole('link', { name: 'Create one' })).toHaveAttribute(
      'href',
      '/register',
    );
  });
});
