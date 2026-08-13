import { render, screen } from '@testing-library/react';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { routes } from '@/routes';
import { mockJsonFetch } from '@/test/mockFetch';

function renderAt(path: string) {
  return render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

describe('routing', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    mockJsonFetch({
      status: 'ok',
      service: 'AI BI Platform',
      version: '0.1.0',
      environment: 'test',
      dependencies: [],
    });
  });

  it('renders the overview page at /', async () => {
    renderAt('/');

    expect(await screen.findByRole('heading', { name: 'AI BI Platform' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
  });

  it('renders the system page at /system', async () => {
    renderAt('/system');

    expect(await screen.findByRole('heading', { name: 'System' })).toBeInTheDocument();
  });

  it('renders the not-found page for an unknown route', async () => {
    renderAt('/nope');

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});
