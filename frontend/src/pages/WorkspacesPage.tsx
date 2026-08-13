import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';

import { createWorkspace, listWorkspaces } from '@/api/workspaces';
import { ResourceForm, type ResourcePayload } from '@/components/forms/ResourceForm';
import { Card, EmptyState, ErrorState, Pagination, Spinner } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { Paginated, Workspace } from '@/types/api';

export default function WorkspacesPage() {
  const [page, setPage] = useState(1);
  const [createError, setCreateError] = useState<Error | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const load = useCallback(
    (signal: AbortSignal) => listWorkspaces({ page }, signal),
    [page],
  );
  const { data, error, isLoading, reload } = useAsync<Paginated<Workspace>>(load);

  async function handleCreate(payload: ResourcePayload) {
    setCreateError(null);
    setCreated(null);
    try {
      const workspace = await createWorkspace(payload);
      setCreated(`Workspace “${workspace.name}” created.`);
      // Newest first, so the new row is on page 1.
      if (page === 1) reload();
      else setPage(1);
    } catch (cause) {
      setCreateError(cause instanceof Error ? cause : new Error(String(cause)));
      throw cause;
    }
  }

  return (
    <div className="stack">
      <div>
        <h1>Workspaces</h1>
        <p className="muted">Each workspace holds its own projects.</p>
      </div>

      <Card title="Your workspaces">
        {isLoading && <Spinner label="Loading workspaces…" />}
        {!isLoading && error && <ErrorState error={error} onRetry={reload} />}
        {!isLoading && !error && data?.items.length === 0 && (
          <EmptyState
            title="No workspaces yet"
            hint="Create your first one below to start adding projects."
            testId="workspaces-empty"
          />
        )}
        {!isLoading && !error && data && data.items.length > 0 && (
          <>
            <ul className="list list--plain" data-testid="workspace-list">
              {data.items.map((workspace) => (
                <li key={workspace.id} className="row row--between">
                  <Link to={`/workspaces/${workspace.id}`}>{workspace.name}</Link>
                  <span className="muted small">{workspace.slug}</span>
                </li>
              ))}
            </ul>
            <Pagination
              page={data.page}
              totalPages={data.total_pages}
              total={data.total}
              hasNext={data.has_next}
              hasPrevious={data.has_previous}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>

      <Card title="New workspace">
        <ResourceForm
          idPrefix="workspace"
          submitLabel="Create workspace"
          busyLabel="Creating…"
          error={createError}
          successMessage={created}
          onSubmit={handleCreate}
          resetOnSuccess
        />
      </Card>
    </div>
  );
}
