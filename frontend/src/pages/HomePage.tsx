import { Link } from 'react-router-dom';

import { useAuth } from '@/auth/useAuth';
import { Card } from '@/components/ui';
import { BackendStatus } from '@/features/health/BackendStatus';

export default function HomePage() {
  const { user } = useAuth();

  return (
    <div className="stack">
      <div>
        <h1>AI BI Platform</h1>
        <p className="muted">
          Signed in as {user?.display_name || user?.email}. The dashboard arrives in a later task —
          for now, set up your workspaces and projects.
        </p>
      </div>

      <BackendStatus />

      <Card title="Get started">
        <ul className="list">
          <li>
            <Link to="/workspaces">Workspaces</Link> — create a workspace and add projects to it
          </li>
          <li>
            <Link to="/system">System</Link> — check the backend dependencies
          </li>
        </ul>
      </Card>
    </div>
  );
}
