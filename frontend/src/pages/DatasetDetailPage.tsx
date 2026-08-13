import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { deleteDataset, getDataset, replaceDatasetFile } from '@/api/datasets';
import {
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Spinner,
} from '@/components/ui';
import { DatasetStatusBadge } from '@/features/datasets/DatasetStatusBadge';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { DatasetUpload } from '@/features/datasets/DatasetUpload';
import { useAsync } from '@/hooks/useAsync';
import { formatBytes, formatCount } from '@/lib/formatBytes';
import type { Dataset } from '@/types/api';

export default function DatasetDetailPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();
  const navigate = useNavigate();

  const load = useCallback(
    (signal: AbortSignal) => getDataset(projectId, datasetId, signal),
    [projectId, datasetId],
  );
  const dataset = useAsync<Dataset>(load);

  const [replacing, setReplacing] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [replaceError, setReplaceError] = useState<Error | null>(null);
  const [replaced, setReplaced] = useState<string | null>(null);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<Error | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleReplace(file: File) {
    setReplacing(true);
    setProgress(0);
    setReplaceError(null);
    setReplaced(null);
    try {
      const updated = await replaceDatasetFile(projectId, datasetId, file, {
        onProgress: setProgress,
      });
      setReplaced(
        updated.status === 'failed'
          ? 'File replaced, but it could not be processed.'
          : 'File replaced and reprocessed.',
      );
      dataset.reload();
    } catch (cause) {
      setReplaceError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setReplacing(false);
      setProgress(null);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteDataset(projectId, datasetId);
      navigate(`/projects/${projectId}/datasets`, { replace: true });
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause : new Error(String(cause)));
      setDeleting(false);
    }
  }

  const data = dataset.data;

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets`}>← Datasets</Link>
        </p>
        {dataset.isLoading && <Spinner label="Loading dataset…" />}
        {dataset.error && <ErrorState error={dataset.error} onRetry={dataset.reload} />}
        {data && (
          <>
            <div className="row">
              <h1>{data.name}</h1>
              <DatasetStatusBadge status={data.status} />
            </div>
            {/* Profiling and cleaning need a successfully processed file. */}
            {data.status === 'ready' && (
              <DatasetTabs projectId={projectId} datasetId={datasetId} />
            )}
          </>
        )}
      </div>

      {data?.status === 'failed' && data.error_message && (
        <div className="panel panel--error" role="alert">
          <h3>Processing failed</h3>
          <p className="muted">{data.error_message}</p>
          <p className="muted small">Upload a corrected file below to try again.</p>
        </div>
      )}

      {data && (
        <Card
          title="Details"
          actions={
            <button
              type="button"
              className="button button--danger"
              onClick={() => setConfirmingDelete(true)}
            >
              Delete
            </button>
          }
        >
          <dl className="details details--grid">
            <div>
              <dt>Original filename</dt>
              <dd>{data.original_filename}</dd>
            </div>
            <div>
              <dt>File type</dt>
              <dd>{data.file_type.toUpperCase()}</dd>
            </div>
            <div>
              <dt>File size</dt>
              <dd>{formatBytes(data.file_size)}</dd>
            </div>
            <div>
              <dt>Rows</dt>
              <dd>{formatCount(data.row_count)}</dd>
            </div>
            <div>
              <dt>Columns</dt>
              <dd>{formatCount(data.column_count)}</dd>
            </div>
            <div>
              <dt>Uploaded</dt>
              <dd>{new Date(data.created_at).toLocaleString()}</dd>
            </div>
          </dl>
        </Card>
      )}

      {data && (
        <Card title="Columns">
          {data.columns && data.columns.length > 0 ? (
            <div className="table-scroll">
              <table className="table" data-testid="dataset-columns">
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Detected type</th>
                    <th scope="col">Nullable</th>
                  </tr>
                </thead>
                <tbody>
                  {data.columns.map((column) => (
                    <tr key={column.name}>
                      <td>{column.name}</td>
                      <td className="muted">{column.dtype}</td>
                      <td className="muted">{column.nullable ? 'Yes' : 'No'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="No column metadata"
              hint={
                data.status === 'ready'
                  ? 'This dataset reported no columns.'
                  : 'Metadata appears once processing succeeds.'
              }
              testId="columns-empty"
            />
          )}
        </Card>
      )}

      {data && (
        <Card title="Replace file">
          <p className="muted small">
            Upload a new file to replace the stored one. The dataset keeps its id and name.
          </p>
          <DatasetUpload
            onUpload={handleReplace}
            busy={replacing}
            progress={progress}
            error={replaceError}
            successMessage={replaced}
            label="Drag a replacement CSV or XLSX file here"
          />
        </Card>
      )}

      {confirmingDelete && (
        <ConfirmDialog
          title="Delete this dataset?"
          message="The uploaded file is removed as well. This cannot be undone."
          error={deleteError}
          busy={deleting}
          onConfirm={handleDelete}
          onCancel={() => {
            setConfirmingDelete(false);
            setDeleteError(null);
          }}
        />
      )}
    </div>
  );
}
