/** Application shell: header, primary navigation and routed content area. */

import { NavLink, Outlet, useNavigate } from 'react-router-dom';

import { useAuth } from '@/auth/useAuth';
import { env } from '@/config/env';

const NAV_ITEMS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/workspaces', label: 'Workspaces' },
  { to: '/system', label: 'System' },
];

export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="layout">
      <header className="layout__header">
        <div className="layout__brand">
          <span className="layout__logo" aria-hidden="true" />
          <span>{env.appName}</span>
        </div>
        <nav className="layout__nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? 'navlink navlink--active' : 'navlink')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="layout__account">
          {user && (
            <span className="muted small" data-testid="current-user">
              {user.display_name || user.email}
            </span>
          )}
          <button type="button" className="button button--ghost" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      <main className="layout__main">
        <Outlet />
      </main>

      <footer className="layout__footer muted small">
        API: {env.apiBaseUrl}
        {env.apiVersionPrefix}
      </footer>
    </div>
  );
}
