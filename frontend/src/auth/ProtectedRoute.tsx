/** Route guards for authenticated and guest-only areas. */

import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { Spinner } from '@/components/ui';
import { useAuth } from '@/auth/useAuth';

/** Renders child routes only for a signed-in user. */
export function ProtectedRoute() {
  const { status } = useAuth();
  const location = useLocation();

  // Wait for the session check; redirecting first would bounce a valid user.
  if (status === 'loading') {
    return <Spinner label="Checking your session…" />;
  }

  if (status === 'unauthenticated') {
    // `from` lets the login page return the user where they were headed.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

/** Keeps signed-in users away from the login and register screens. */
export function GuestOnlyRoute() {
  const { status } = useAuth();

  if (status === 'loading') {
    return <Spinner label="Checking your session…" />;
  }

  if (status === 'authenticated') {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
