/** Application shell: header, primary navigation and routed content area. */

import { NavLink, Outlet } from 'react-router-dom';

import { env } from '@/config/env';

const NAV_ITEMS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/system', label: 'System' },
];

export function AppLayout() {
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
