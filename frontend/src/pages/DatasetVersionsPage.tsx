import { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getDataset } from '@/api/datasets';
import { listDatasetVersions } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Pagination, Spinner } from '@/components/ui';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { useAsync } from '@/hooks/useAsync';
import { formatBytes, formatCount } from '@/lib/formatBytes';
import type { Dataset, DatasetVersionListResponse } from '@/types/api';

/** Renders a stored pipeline as a short, readable list. */
function describeOperations(operations: Record<string, unknown>[]): string {
  if (operations.length === 0) return 'No operations recorded';
  return operations
    .map((operation) => {
      const name = String(operation.operation ?? 'operation');
      const column = operation.column ? ` (${String(operation.column)})` : '';
      return `${name.replace(/_/g, ' ')}${column}`;
    })
    .join(', ');
}

export default function DatasetVersionsPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();
  const [page, setPage] = useState(1);

  const loadDataset = useCallback(
    (signal: AbortSignal) => getDataset(projectId, datasetId, signal),
    [projectId, datasetId],
  );
  const loadVersions = useCallback(
    (signal: AbortSignal) => listDatasetVersions(projectId, datasetId, { page }, signal),
    [projectId, datasetId, page],
  );

  const dataset = useAsync<Dataset>(loadDataset);
  const versions = useAsync<DatasetVersionListResponse>(loadVersions);

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Versions</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      <Card title="Original dataset">
        {dataset.isLoading && <Spinner />}
        {dataset.error && <ErrorState error={dataset.error} onRetry={dataset.reload} />}
        {dataset.data && (
          <div className="stack" data-testid="original-dataset">
            <p className="row">
              <span className="badge badge--ok">Original</span>
              <strong>{dataset.data.name}</strong>
              <span className="muted small">{dataset.data.original_filename}</span>
            </p>
            <p className="muted small">
              {formatCount(dataset.data.row_count)} rows ·{' '}
              {formatCount(dataset.data.column_count)} columns ·{' '}
              {formatBytes(dataset.data.file_size)} · never modified by cleaning
            </p>
          </div>
        )}
      </Card>

      <Card
        title="Cleaned versions"
        actions={
          <Link
            className="button button--ghost"
            to={`/projects/${projectId}/datasets/${datasetId}/clean`}
          >
            New cleaning run
          </Link>
        }
      >
        {versions.isLoading && <Spinner label="Loading versions…" />}
        {!versions.isLoading && versions.error && (
          <ErrorState error={versions.error} onRetry={versions.reload} />
        )}
        {!versions.isLoading && !versions.error && versions.data?.items.length === 0 && (
          <EmptyState
            title="No cleaned versions yet"
            hint="Run a cleaning pipeline to create the first version."
            testId="versions-empty"
          />
        )}
        {!versions.isLoading && !versions.error && versions.data &&
          versions.data.items.length > 0 && (
            <>
              <ul className="list list--plain" data-testid="version-list">
                {versions.data.items.map((version) => (
                  <li key={version.id} className="clean-column">
                    <div className="clean-column__header">
                      <span className="row">
                        <span className="badge badge--degraded">v{version.version_number}</span>
                        <strong>{version.name}</strong>
                      </span>
                      <span className="muted small">
                        {new Date(version.created_at).toLocaleString()}
                      </span>
                    </div>
                    <p className="muted small">
                      {formatCount(version.row_count)} rows ·{' '}
                      {formatCount(version.column_count)} columns ·{' '}
                      {formatBytes(version.file_size)} · derived from{' '}
                      {version.source_version_id ? 'an earlier version' : 'the original dataset'}
                    </p>
                    <p className="muted small">
                      Operations:{' '}
                      {describeOperations(
                        version.operations as unknown as Record<string, unknown>[],
                      )}
                    </p>
                  </li>
                ))}
              </ul>
              <Pagination
                page={versions.data.page}
                totalPages={versions.data.total_pages}
                total={versions.data.total}
                hasNext={versions.data.has_next}
                hasPrevious={versions.data.has_previous}
                onPageChange={setPage}
              />
            </>
          )}
      </Card>
    </div>
  );
}
