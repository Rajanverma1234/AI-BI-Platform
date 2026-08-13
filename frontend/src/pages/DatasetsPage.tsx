import { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { listDatasets, uploadDataset } from '@/api/datasets';
import { getProjectById } from '@/api/projects';
import {
  Card,
  EmptyState,
  ErrorState,
  Pagination,
  Spinner,
} from '@/components/ui';
import { DatasetStatusBadge } from '@/features/datasets/DatasetStatusBadge';
import { DatasetUpload } from '@/features/datasets/DatasetUpload';
import { useAsync } from '@/hooks/useAsync';
import { formatBytes, formatCount } from '@/lib/formatBytes';
import type { DatasetListResponse, Project } from '@/types/api';

export default function DatasetsPage() {
  const { projectId = '' } = useParams<{ projectId: string }>();

  const [page, setPage] = useState(1);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<Error | null>(null);
  const [uploaded, setUploaded] = useState<string | null>(null);

  const loadProject = useCallback(
    (signal: AbortSignal) => getProjectById(projectId, signal),
    [projectId],
  );
  const project = useAsync<Project>(loadProject);

  const loadDatasets = useCallback(
    (signal: AbortSignal) => listDatasets(projectId, { page }, signal),
    [projectId, page],
  );
  const datasets = useAsync<DatasetListResponse>(loadDatasets);

  async function handleUpload(file: File) {
    setUploading(true);
    setProgress(0);
    setUploadError(null);
    setUploaded(null);
    try {
      const dataset = await uploadDataset(projectId, file, undefined, {
        onProgress: setProgress,
      });
      setUploaded(
        dataset.status === 'failed'
          ? `“${dataset.name}” was uploaded but could not be processed.`
          : `“${dataset.name}” uploaded successfully.`,
      );
      if (page === 1) datasets.reload();
      else setPage(1);
    } catch (cause) {
      setUploadError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setUploading(false);
      setProgress(null);
    }
  }

  return (
    <div className="stack">
      <div>
        {project.data && (
          <p className="muted small">
            <Link to={`/workspaces/${project.data.workspace_id}/projects/${projectId}`}>
              ← {project.data.name}
            </Link>
          </p>
        )}
        <h1>Datasets</h1>
        <p className="muted">Upload CSV or Excel files to use in this project.</p>
        {project.error && <ErrorState error={project.error} onRetry={project.reload} />}
      </div>

      <Card title="Upload a dataset">
        <DatasetUpload
          onUpload={handleUpload}
          busy={uploading}
          progress={progress}
          error={uploadError}
          successMessage={uploaded}
        />
      </Card>

      <Card title="Your datasets">
        {datasets.isLoading && <Spinner label="Loading datasets…" />}
        {!datasets.isLoading && datasets.error && (
          <ErrorState error={datasets.error} onRetry={datasets.reload} />
        )}
        {!datasets.isLoading && !datasets.error && datasets.data?.items.length === 0 && (
          <EmptyState
            title="No datasets yet"
            hint="Upload a CSV or XLSX file above to get started."
            testId="datasets-empty"
          />
        )}
        {!datasets.isLoading && !datasets.error && datasets.data &&
          datasets.data.items.length > 0 && (
            <>
              <ul className="list list--plain" data-testid="dataset-list">
                {datasets.data.items.map((dataset) => (
                  <li key={dataset.id} className="dataset-row">
                    <div className="dataset-row__main">
                      <Link to={`/projects/${projectId}/datasets/${dataset.id}`}>
                        {dataset.name}
                      </Link>
                      <span className="muted small">{dataset.original_filename}</span>
                    </div>
                    <div className="dataset-row__meta muted small">
                      <span>{dataset.file_type.toUpperCase()}</span>
                      <span>{formatBytes(dataset.file_size)}</span>
                      <span>{formatCount(dataset.row_count)} rows</span>
                      <span>{formatCount(dataset.column_count)} cols</span>
                      <span>{new Date(dataset.created_at).toLocaleDateString()}</span>
                    </div>
                    <DatasetStatusBadge status={dataset.status} />
                  </li>
                ))}
              </ul>
              <Pagination
                page={datasets.data.page}
                totalPages={datasets.data.total_pages}
                total={datasets.data.total}
                hasNext={datasets.data.has_next}
                hasPrevious={datasets.data.has_previous}
                onPageChange={setPage}
              />
            </>
          )}
      </Card>
    </div>
  );
}
