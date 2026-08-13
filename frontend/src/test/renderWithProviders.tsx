import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement } from 'react';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';

import { AuthProvider } from '@/auth/AuthContext';
import { routes } from '@/routes';

/** Render the real route table at a given path, inside the auth provider. */
export function renderApp(initialPath = '/'): RenderResult {
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  );
}

/** Render an isolated element with routing and auth available. */
export function renderWithProviders(ui: ReactElement, initialPath = '/'): RenderResult {
  const router = createMemoryRouter([{ path: '*', element: ui }], {
    initialEntries: [initialPath],
  });
  return render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  );
}
