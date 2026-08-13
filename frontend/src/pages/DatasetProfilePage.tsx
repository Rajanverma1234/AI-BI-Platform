import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getDatasetProfile, getDatasetQuality } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { QualityBadge, SeverityBadge } from '@/features/datasets/QualityBadge';
import { useAsync } from '@/hooks/useAsync';
import { formatCount } from '@/lib/formatBytes';
import type { ColumnProfile, DataQualitySummary, DatasetProfile } from '@/types/api';

function summariseStats(column: ColumnProfile): string {
  if (column.numeric) {
    const { minimum, maximum, mean } = column.numeric;
    if (minimum === null || maximum === null) return '—';
    return `min ${minimum} · max ${maximum} · mean ${mean?.toFixed(2) ?? '—'}`;
  }
  if (column.categorical?.most_frequent_value) {
    const { most_frequent_value, most_frequent_count } = column.categorical;
    return `top: ${most_frequent_value} (${most_frequent_count})`;
  }
  if (column.datetime_stats?.minimum) {
    const { minimum, maximum } = column.datetime_stats;
    return `${new Date(minimum).toLocaleDateString()} → ${
      maximum ? new Date(maximum).toLocaleDateString() : '—'
    }`;
  }
  return '—';
}

export default function DatasetProfilePage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();

  const loadProfile = useCallback(
    (signal: AbortSignal) => getDatasetProfile(projectId, datasetId, undefined, signal),
    [projectId, datasetId],
  );
  const loadQuality = useCallback(
    (signal: AbortSignal) => getDatasetQuality(projectId, datasetId, undefined, signal),
    [projectId, datasetId],
  );

  const profile = useAsync<DatasetProfile>(loadProfile);
  const quality = useAsync<DataQualitySummary>(loadQuality);

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Profile &amp; quality</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      <Card title="Dataset summary">
        {profile.isLoading && <Spinner label="Profiling dataset…" />}
        {!profile.isLoading && profile.error && (
          <ErrorState error={profile.error} onRetry={profile.reload} />
        )}
        {!profile.isLoading && !profile.error && profile.data && (
          <dl className="details details--grid" data-testid="profile-summary">
            <div>
              <dt>Rows</dt>
              <dd>{formatCount(profile.data.row_count)}</dd>
            </div>
            <div>
              <dt>Columns</dt>
              <dd>{formatCount(profile.data.column_count)}</dd>
            </div>
            <div>
              <dt>Missing cells</dt>
              <dd>
                {formatCount(profile.data.missing_cell_count)}{' '}
                <span className="muted small">({profile.data.missing_cell_percentage}%)</span>
              </dd>
            </div>
            <div>
              <dt>Duplicate rows</dt>
              <dd>
                {formatCount(profile.data.duplicate_row_count)}{' '}
                <span className="muted small">({profile.data.duplicate_row_percentage}%)</span>
              </dd>
            </div>
            <div>
              <dt>Quality</dt>
              <dd>
                {quality.data ? <QualityBadge status={quality.data.status} /> : <span>—</span>}
              </dd>
            </div>
          </dl>
        )}
      </Card>

      <Card title="Column profile">
        {profile.isLoading && <Spinner />}
        {!profile.isLoading && !profile.error && profile.data && (
          <div className="table-scroll">
            <table className="table" data-testid="column-profile-table">
              <thead>
                <tr>
                  <th scope="col">Column</th>
                  <th scope="col">Type</th>
                  <th scope="col">Missing</th>
                  <th scope="col">Missing %</th>
                  <th scope="col">Unique</th>
                  <th scope="col">Unique %</th>
                  <th scope="col">Statistics</th>
                </tr>
              </thead>
              <tbody>
                {profile.data.columns.map((column) => (
                  <tr key={column.column_name}>
                    <td>{column.column_name}</td>
                    <td className="muted">{column.detected_data_type}</td>
                    <td>{formatCount(column.null_count)}</td>
                    <td className="muted">{column.null_percentage}%</td>
                    <td>{formatCount(column.unique_count)}</td>
                    <td className="muted">{column.unique_percentage}%</td>
                    <td className="muted">{summariseStats(column)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Data quality"
        actions={
          <Link className="button button--ghost" to={`/projects/${projectId}/datasets/${datasetId}/clean`}>
            Clean this dataset
          </Link>
        }
      >
        {quality.isLoading && <Spinner label="Checking quality…" />}
        {!quality.isLoading && quality.error && (
          <ErrorState error={quality.error} onRetry={quality.reload} />
        )}
        {!quality.isLoading && !quality.error && quality.data && (
          <div className="stack">
            <p className="row">
              <QualityBadge status={quality.data.status} />
              <span className="muted small">
                Score {quality.data.score}/100 · {quality.data.total_issues} issue(s):{' '}
                {quality.data.critical_count} critical, {quality.data.warning_count} warning,{' '}
                {quality.data.info_count} info
              </span>
            </p>

            {quality.data.issues.length === 0 ? (
              <EmptyState
                title="No issues detected"
                hint="This dataset passed every quality rule."
                testId="quality-empty"
              />
            ) : (
              <ul className="list list--plain" data-testid="quality-issues">
                {quality.data.issues.map((issue, index) => (
                  <li key={`${issue.issue_type}-${issue.column ?? 'dataset'}-${index}`} className="row">
                    <SeverityBadge severity={issue.severity} />
                    <span>{issue.message}</span>
                  </li>
                ))}
              </ul>
            )}

            <details className="muted small">
              <summary>Rules used for this assessment</summary>
              <ul className="list">
                {quality.data.rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </Card>
    </div>
  );
}
