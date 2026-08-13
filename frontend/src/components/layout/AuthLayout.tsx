/** Minimal centred shell for the sign-in and sign-up screens. */

import { Outlet } from 'react-router-dom';

import { env } from '@/config/env';

export function AuthLayout() {
  return (
    <div className="layout layout--auth">
      <header className="layout__header">
        <div className="layout__brand">
          <span className="layout__logo" aria-hidden="true" />
          <span>{env.appName}</span>
        </div>
      </header>
      <main className="layout__main layout__main--narrow">
        <Outlet />
      </main>
    </div>
  );
}
