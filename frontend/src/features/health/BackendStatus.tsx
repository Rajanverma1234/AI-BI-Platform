/**
 * Confirms the browser can reach the backend health endpoint.
 * This is the connectivity smoke test for the whole stack.
 */

import { fetchHealth } from '@/api/health';
import { Card, ErrorState, Spinner, StatusBadge } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { HealthResponse } from '@/types/api';

export function BackendStatus() {
  const { data, error, isLoading, reload } = useAsync<HealthResponse>((signal) =>
    fetchHealth(signal),
  );

  return (
    <Card
      title="Backend connection"
      actions={
        <button type="button" className="button button--ghost" onClick={reload} disabled={isLoading}>
          Refresh
        </button>
      }
    >
      {isLoading && <Spinner label="Contacting the API…" />}

      {!isLoading && error && <ErrorState error={error} onRetry={reload} />}

      {!isLoading && !error && data && (
        <div data-testid="health-result">
          <p className="row">
            <StatusBadge status={data.status} />
            <span>
              Connected to <strong>{data.service}</strong>
            </span>
          </p>
          <dl className="details">
            <div>
              <dt>Version</dt>
              <dd>{data.version}</dd>
            </div>
            <div>
              <dt>Environment</dt>
              <dd>{data.environment}</dd>
            </div>
          </dl>
        </div>
      )}
    </Card>
  );
}
