import { fetchReadiness } from '@/api/health';
import { Card, ErrorState, Spinner, StatusBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { ReadinessResponse } from '@/types/api';

export default function SystemPage() {
  const { data, error, isLoading, reload } = useAsync<ReadinessResponse>((signal) =>
    fetchReadiness(signal),
  );

  return (
    <div className="stack">
      <div>
        <h1>System</h1>
        <p className="muted">Readiness of each dependency the backend needs to serve traffic.</p>
      </div>

      <Card
        title="Dependencies"
        actions={
          <button
            type="button"
            className="button button--ghost"
            onClick={reload}
            disabled={isLoading}
          >
            Refresh
          </button>
        }
      >
        {isLoading && <Spinner />}
        {!isLoading && error && <ErrorState error={error} onRetry={reload} />}
        {!isLoading && !error && data && (
          <ul className="list list--plain">
            {data.dependencies.map((dependency) => (
              <li key={dependency.name} className="row">
                <StatusBadge status={dependency.status} />
                <span>{dependency.name}</span>
                {dependency.detail && <span className="muted small">{dependency.detail}</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
