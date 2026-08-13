import { RouterProvider, createBrowserRouter } from 'react-router-dom';

import { AuthProvider } from '@/auth/AuthContext';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { routes } from '@/routes';

const router = createBrowserRouter(routes);

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ErrorBoundary>
  );
}
