import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, setAuthToken } from '@/lib/authToken';
import { authenticatedHandlers, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';

describe('routing', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    // Routes below the app shell now require a session.
    setAuthToken('a-valid-access-token');
    mockApi(authenticatedHandlers());
  });

  it('renders the overview page at /', async () => {
    renderApp('/');

    expect(await screen.findByRole('heading', { name: 'AI BI Platform' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
  });

  it('renders the workspaces page at /workspaces', async () => {
    renderApp('/workspaces');

    expect(await screen.findByRole('heading', { name: 'Workspaces' })).toBeInTheDocument();
  });

  it('renders the system page at /system', async () => {
    renderApp('/system');

    expect(await screen.findByRole('heading', { name: 'System' })).toBeInTheDocument();
  });

  it('renders the not-found page for an unknown route', async () => {
    renderApp('/nope');

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});
