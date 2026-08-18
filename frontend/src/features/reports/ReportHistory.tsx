/**
 * Previously generated reports for this dataset.
 *
 * A failed report is kept and shown with its reason rather than hidden, so a
 * user who clicked Generate and got nothing can see what happened.
 */

import { useState } from 'react';

import { deleteReport, downloadReport } from '@/api/reports';
import { ConfirmDialog, EmptyState, ErrorState } from '@/components/ui';
import { saveBlob } from '@/lib/apiClient';
import type { Report } from '@/types/api';

const FORMAT_LABELS: Record<Report['file_format'], string> = {
  pdf: 'PDF',
  xlsx: 'Excel',
  csv: 'CSV',
  pptx: 'PowerPoint',
};

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface ReportHistoryProps {
  projectId: string;
  datasetId: string;
  reports: Report[];
  onChanged: () => void;
}

export function ReportHistory({ projectId, datasetId, reports, onChanged }: ReportHistoryProps) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Report | null>(null);
  const [error, setError] = useState<Error | null>(null);

  async function handleDownload(report: Report) {
    setBusyId(report.id);
    setError(null);
    try {
      saveBlob(await downloadReport(projectId, datasetId, report));
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(report: Report) {
    setBusyId(report.id);
    setError(null);
    try {
      await deleteReport(projectId, datasetId, report.id);
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusyId(null);
      setPendingDelete(null);
    }
  }

  if (reports.length === 0) {
    return (
      <EmptyState
        title="No reports yet"
        hint="Generated reports appear here, ready to download again."
        testId="no-reports"
      />
    );
  }

  return (
    <div className="stack--narrow">
      {error && <ErrorState error={error} />}
      <div className="table-scroll">
        <table className="table" data-testid="report-history">
          <thead>
            <tr>
              <th scope="col">Report</th>
              <th scope="col">Format</th>
              <th scope="col">Sections</th>
              <th scope="col">Size</th>
              <th scope="col">Created</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {reports.map((report) => (
              <tr key={report.id}>
                <td>
                  {report.name}
                  {report.status === 'failed' && (
                    <p className="muted small">{report.error_message ?? 'Generation failed.'}</p>
                  )}
                </td>
                <td>{FORMAT_LABELS[report.file_format]}</td>
                <td className="muted">{report.sections.length}</td>
                <td className="muted">
                  {report.status === 'ready' ? fileSize(report.file_size) : '—'}
                </td>
                <td className="muted">{new Date(report.created_at).toLocaleString()}</td>
                <td>
                  <div className="row">
                    {report.status === 'ready' && (
                      <button
                        type="button"
                        className="button button--ghost"
                        onClick={() => void handleDownload(report)}
                        disabled={busyId === report.id}
                      >
                        {busyId === report.id ? 'Downloading…' : 'Download'}
                      </button>
                    )}
                    <button
                      type="button"
                      className="button button--ghost"
                      onClick={() => setPendingDelete(report)}
                      disabled={busyId === report.id}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pendingDelete && (
        <ConfirmDialog
          title="Delete this report?"
          message={`"${pendingDelete.name}" and its stored file will be removed. This cannot be undone.`}
          confirmLabel="Delete"
          onConfirm={() => void handleDelete(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
