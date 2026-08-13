import { Card } from '@/components/ui';
import { BackendStatus } from '@/features/health/BackendStatus';

export default function HomePage() {
  return (
    <div className="stack">
      <div>
        <h1>AI BI Platform</h1>
        <p className="muted">
          Foundation build. The dashboard arrives in a later task - for now this screen verifies
          the frontend can talk to the API.
        </p>
      </div>

      <BackendStatus />

      <Card title="What is wired up">
        <ul className="list">
          <li>Versioned FastAPI backend at /api/v1 with centralised errors and structured logs</li>
          <li>PostgreSQL via SQLAlchemy with Alembic migrations</li>
          <li>Users, workspaces and projects as the initial data model</li>
          <li>Pluggable AI provider layer (no credentials committed)</li>
        </ul>
      </Card>
    </div>
  );
}
