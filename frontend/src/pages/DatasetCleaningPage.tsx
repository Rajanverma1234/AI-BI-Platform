import { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { applyCleaning, getDatasetProfile, getDatasetQuality, previewCleaning } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner, SuccessMessage } from '@/components/ui';
import { CleaningPreviewDialog } from '@/features/datasets/CleaningPreviewDialog';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { SeverityBadge } from '@/features/datasets/QualityBadge';
import {
  buildOperations,
  DEFAULT_SELECTION,
  type ColumnSelection,
  type MissingChoice,
  type OutlierChoice,
} from '@/features/datasets/buildOperations';
import { useAsync } from '@/hooks/useAsync';
import { formatCount } from '@/lib/formatBytes';
import type {
  CleaningPreviewResponse,
  ColumnProfile,
  ConvertibleType,
  DataQualitySummary,
  DatasetProfile,
} from '@/types/api';

const NUMERIC_TYPES = new Set(['integer', 'float']);

const CONVERT_OPTIONS: { value: ConvertibleType | ''; label: string }[] = [
  { value: '', label: 'Keep current' },
  { value: 'string', label: 'String' },
  { value: 'integer', label: 'Integer' },
  { value: 'float', label: 'Float' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'date', label: 'Date' },
  { value: 'datetime', label: 'Datetime' },
];

/** Strategies offered depend on the column's detected type. */
function missingOptions(column: ColumnProfile): { value: MissingChoice; label: string }[] {
  const base: { value: MissingChoice; label: string }[] = [{ value: 'keep', label: 'Keep' }];

  if (NUMERIC_TYPES.has(column.detected_data_type)) {
    base.push({ value: 'mean', label: 'Mean' }, { value: 'median', label: 'Median' });
  } else if (column.detected_data_type === 'datetime') {
    base.push(
      { value: 'forward_fill', label: 'Forward fill' },
      { value: 'backward_fill', label: 'Backward fill' },
    );
  } else {
    base.push({ value: 'mode', label: 'Mode' });
  }

  base.push(
    { value: 'custom', label: 'Custom value' },
    { value: 'remove_rows', label: 'Remove rows' },
  );
  return base;
}

export default function DatasetCleaningPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();
  const navigate = useNavigate();

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

  const [selections, setSelections] = useState<Record<string, ColumnSelection>>({});
  const [removeDuplicates, setRemoveDuplicates] = useState(false);
  const [convertErrorsToNull, setConvertErrorsToNull] = useState(false);

  const [preview, setPreview] = useState<CleaningPreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  function selectionFor(column: string): ColumnSelection {
    return selections[column] ?? DEFAULT_SELECTION;
  }

  function update(column: string, patch: Partial<ColumnSelection>) {
    setSelections((current) => ({
      ...current,
      [column]: { ...(current[column] ?? DEFAULT_SELECTION), ...patch },
    }));
  }

  const operations = useMemo(
    () => buildOperations({ selections, removeDuplicates, convertErrorsToNull }),
    [selections, removeDuplicates, convertErrorsToNull],
  );

  async function handlePreview() {
    setPreviewing(true);
    setError(null);
    setApplied(null);
    try {
      setPreview(await previewCleaning(projectId, datasetId, operations));
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setPreviewing(false);
    }
  }

  async function handleApply() {
    setApplying(true);
    setError(null);
    try {
      const result = await applyCleaning(projectId, datasetId, operations);
      setPreview(null);
      setApplied(`Created “${result.version.name}”.`);
      navigate(`/projects/${projectId}/datasets/${datasetId}/versions`);
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setApplying(false);
    }
  }

  const duplicateCount = profile.data?.duplicate_row_count ?? 0;

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Cleaning</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
        <p className="muted">
          Choose what to do with each issue. Nothing changes until you review and confirm — your
          original dataset is never modified.
        </p>
      </div>

      {profile.isLoading && <Spinner label="Loading dataset profile…" />}
      {profile.error && <ErrorState error={profile.error} onRetry={profile.reload} />}

      {quality.data && quality.data.issues.length > 0 && (
        <Card title="Detected issues">
          <ul className="list list--plain" data-testid="cleaning-issues">
            {quality.data.issues.map((issue, index) => (
              <li key={`${issue.issue_type}-${issue.column ?? 'dataset'}-${index}`} className="row">
                <SeverityBadge severity={issue.severity} />
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Duplicate rows">
        {duplicateCount === 0 ? (
          <EmptyState title="No duplicate rows found" testId="no-duplicates" />
        ) : (
          <div className="stack">
            <p className="muted">
              Duplicate rows: <strong>{formatCount(duplicateCount)}</strong> — removing them will
              drop that many rows.
            </p>
            <div className="row" role="group" aria-label="Duplicate handling">
              <button
                type="button"
                className={`button ${removeDuplicates ? 'button--ghost' : ''}`}
                onClick={() => setRemoveDuplicates(false)}
                aria-pressed={!removeDuplicates}
              >
                Keep
              </button>
              <button
                type="button"
                className={`button ${removeDuplicates ? '' : 'button--ghost'}`}
                onClick={() => setRemoveDuplicates(true)}
                aria-pressed={removeDuplicates}
              >
                Remove duplicates
              </button>
            </div>
          </div>
        )}
      </Card>

      {profile.data && (
        <Card title="Columns">
          <label className="row muted small">
            <input
              type="checkbox"
              checked={convertErrorsToNull}
              onChange={(event) => setConvertErrorsToNull(event.target.checked)}
            />
            Allow values that cannot be converted to become empty (otherwise the run is rejected)
          </label>

          <ul className="list list--plain" data-testid="cleaning-columns">
            {profile.data.columns.map((column) => {
              const selection = selectionFor(column.column_name);
              const isNumeric = NUMERIC_TYPES.has(column.detected_data_type);

              return (
                <li key={column.column_name} className="clean-column">
                  <div className="clean-column__header">
                    <strong>{column.column_name}</strong>
                    <span className="muted small">
                      {column.detected_data_type} · {formatCount(column.null_count)} missing (
                      {column.null_percentage}%)
                    </span>
                  </div>

                  <div className="clean-column__controls">
                    <label className="field field--inline">
                      <span className="muted small">Missing values</span>
                      <select
                        className="input"
                        value={selection.missing}
                        onChange={(event) =>
                          update(column.column_name, {
                            missing: event.target.value as MissingChoice,
                          })
                        }
                        aria-label={`Missing value strategy for ${column.column_name}`}
                      >
                        {missingOptions(column).map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    {selection.missing === 'custom' && (
                      <label className="field field--inline">
                        <span className="muted small">Custom value</span>
                        <input
                          className="input"
                          value={selection.customValue}
                          onChange={(event) =>
                            update(column.column_name, { customValue: event.target.value })
                          }
                          aria-label={`Custom fill value for ${column.column_name}`}
                        />
                      </label>
                    )}

                    <label className="field field--inline">
                      <span className="muted small">Convert to</span>
                      <select
                        className="input"
                        value={selection.convertTo}
                        onChange={(event) =>
                          update(column.column_name, {
                            convertTo: event.target.value as ConvertibleType | '',
                          })
                        }
                        aria-label={`Convert type for ${column.column_name}`}
                      >
                        {CONVERT_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    {isNumeric && (
                      <label className="field field--inline">
                        <span className="muted small">Outliers</span>
                        <select
                          className="input"
                          value={selection.outlier}
                          onChange={(event) =>
                            update(column.column_name, {
                              outlier: event.target.value as OutlierChoice,
                            })
                          }
                          aria-label={`Outlier handling for ${column.column_name}`}
                        >
                          <option value="keep">Keep</option>
                          <option value="remove">Remove (IQR)</option>
                          <option value="cap">Cap / winsorise</option>
                        </select>
                      </label>
                    )}

                    <label className="field field--inline">
                      <span className="muted small">Rename to</span>
                      <input
                        className="input"
                        value={selection.rename}
                        placeholder={column.column_name}
                        onChange={(event) =>
                          update(column.column_name, { rename: event.target.value })
                        }
                        aria-label={`Rename ${column.column_name}`}
                      />
                    </label>

                    <label className="row muted small">
                      <input
                        type="checkbox"
                        checked={selection.drop}
                        onChange={(event) =>
                          update(column.column_name, { drop: event.target.checked })
                        }
                        aria-label={`Remove column ${column.column_name}`}
                      />
                      Remove column
                    </label>
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      <Card title="Review">
        <div className="stack">
          <p className="muted small" data-testid="operation-count">
            {operations.length === 0
              ? 'No cleaning operations selected yet.'
              : `${operations.length} operation(s) will be applied, in order.`}
          </p>
          {error && <ErrorState error={error} />}
          {applied && <SuccessMessage message={applied} />}
          <button
            type="button"
            className="button"
            onClick={handlePreview}
            disabled={previewing || operations.length === 0}
          >
            {previewing ? 'Preparing preview…' : 'Preview changes'}
          </button>
        </div>
      </Card>

      {preview && (
        <CleaningPreviewDialog
          preview={preview}
          busy={applying}
          error={error}
          onConfirm={handleApply}
          onCancel={() => setPreview(null)}
        />
      )}
    </div>
  );
}
