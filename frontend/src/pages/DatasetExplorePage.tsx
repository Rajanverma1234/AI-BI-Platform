import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getDataset } from '@/api/datasets';
import { listDatasetVersions } from '@/api/profiling';
import {
  buildChart,
  getChartSuggestions,
  getCorrelation,
  getEdaSummary,
  previewRows,
} from '@/api/visualization';
import { Card, EmptyState, ErrorState, Pagination, Spinner } from '@/components/ui';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { ChartBuilder } from '@/features/visualization/ChartBuilder';
import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import { CorrelationHeatmap } from '@/features/visualization/CorrelationHeatmap';
import { FilterBuilder } from '@/features/visualization/FilterBuilder';
import { useAsync } from '@/hooks/useAsync';
import { formatCount } from '@/lib/formatBytes';
import type {
  ChartConfig,
  ChartDataResponse,
  ChartSuggestionsResponse,
  CorrelationResponse,
  Dataset,
  DataPreviewResponse,
  DatasetVersionListResponse,
  EdaSummaryResponse,
  FilterSet,
} from '@/types/api';

type Section = 'preview' | 'charts' | 'eda' | 'correlation';

const SECTIONS: { id: Section; label: string }[] = [
  { id: 'preview', label: 'Data preview' },
  { id: 'charts', label: 'Chart builder' },
  { id: 'eda', label: 'Summary' },
  { id: 'correlation', label: 'Correlation' },
];

const DEFAULT_CONFIG: ChartConfig = {
  chart_type: 'bar',
  aggregation: 'count',
  bins: 10,
  max_categories: 25,
};

const EMPTY_FILTERS: FilterSet = { logic: 'and', conditions: [] };

export default function DatasetExplorePage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();

  const [section, setSection] = useState<Section>('preview');
  // Empty string means the original upload; otherwise a cleaned version id.
  const [versionId, setVersionId] = useState('');
  const [page, setPage] = useState(1);

  const loadDataset = useCallback(
    (signal: AbortSignal) => getDataset(projectId, datasetId, signal),
    [projectId, datasetId],
  );
  const loadVersions = useCallback(
    (signal: AbortSignal) => listDatasetVersions(projectId, datasetId, { page_size: 50 }, signal),
    [projectId, datasetId],
  );
  const dataset = useAsync<Dataset>(loadDataset);
  const versions = useAsync<DatasetVersionListResponse>(loadVersions);

  const isReady = dataset.data?.status === 'ready';
  const source = versionId || undefined;

  const loadPreview = useCallback(
    (signal: AbortSignal) =>
      previewRows(projectId, datasetId, { page, page_size: 25, version_id: source }, signal),
    [projectId, datasetId, page, source],
  );
  const preview = useAsync<DataPreviewResponse>(loadPreview, { immediate: false });

  // The dataset resolves after the first render, so the preview starts as soon
  // as it is known to be READY rather than firing a request that would 422.
  const previewStatus = preview.status;
  const reloadPreview = preview.reload;
  useEffect(() => {
    if (isReady && previewStatus === 'idle') reloadPreview();
  }, [isReady, previewStatus, reloadPreview]);

  const loadEda = useCallback(
    (signal: AbortSignal) => getEdaSummary(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );
  const eda = useAsync<EdaSummaryResponse>(loadEda, { immediate: false });

  const loadCorrelation = useCallback(
    (signal: AbortSignal) => getCorrelation(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );
  const correlation = useAsync<CorrelationResponse>(loadCorrelation, { immediate: false });

  const loadSuggestions = useCallback(
    (signal: AbortSignal) => getChartSuggestions(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );
  const suggestions = useAsync<ChartSuggestionsResponse>(loadSuggestions, { immediate: false });

  const [config, setConfig] = useState<ChartConfig>(DEFAULT_CONFIG);
  const [filters, setFilters] = useState<FilterSet>(EMPTY_FILTERS);
  const [chart, setChart] = useState<ChartDataResponse | null>(null);
  const [chartError, setChartError] = useState<Error | null>(null);
  const [rendering, setRendering] = useState(false);

  const columns = useMemo(() => preview.data?.columns ?? [], [preview.data]);

  function openSection(next: Section) {
    setSection(next);
    // Load on demand so opening Explore does not run every computation.
    if (next === 'eda' && eda.status === 'idle') eda.reload();
    if (next === 'correlation' && correlation.status === 'idle') correlation.reload();
    if (next === 'charts' && suggestions.status === 'idle') suggestions.reload();
  }

  async function renderChart(next: ChartConfig = config) {
    setRendering(true);
    setChartError(null);
    try {
      setChart(
        await buildChart(projectId, datasetId, {
          ...next,
          version_id: source ?? null,
          filters: filters.conditions.length > 0 ? filters : null,
        }),
      );
    } catch (cause) {
      setChart(null);
      setChartError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setRendering(false);
    }
  }

  if (dataset.isLoading) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={dataset.reload} />;

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Explore</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      {!isReady ? (
        <Card>
          <EmptyState
            title="This dataset is not ready yet"
            hint="Exploration becomes available once the file has been processed successfully."
            testId="explore-not-ready"
          />
        </Card>
      ) : (
        <>
          <Card title={dataset.data?.name ?? 'Dataset'}>
            <div className="row">
              <span className="muted small">
                {formatCount(dataset.data?.row_count ?? null)} rows ·{' '}
                {formatCount(dataset.data?.column_count ?? null)} columns ·{' '}
                {columns.length} available column(s)
              </span>
            </div>
            <label className="field field--inline">
              <span className="muted small">Data source</span>
              <select
                className="input"
                value={versionId}
                onChange={(event) => {
                  setVersionId(event.target.value);
                  setPage(1);
                  setChart(null);
                  // Recomputed sections must follow the new source.
                  eda.reload();
                  correlation.reload();
                  suggestions.reload();
                }}
                aria-label="Data source"
              >
                <option value="">Original dataset</option>
                {versions.data?.items.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} — {version.name}
                  </option>
                ))}
              </select>
            </label>
          </Card>

          <nav className="layout__nav" aria-label="Explore sections">
            {SECTIONS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={section === item.id ? 'navlink navlink--active' : 'navlink'}
                onClick={() => openSection(item.id)}
                aria-pressed={section === item.id}
              >
                {item.label}
              </button>
            ))}
          </nav>

          {section === 'preview' && (
            <Card title="Data preview">
              {preview.isLoading && <Spinner label="Loading rows…" />}
              {!preview.isLoading && preview.error && (
                <ErrorState error={preview.error} onRetry={preview.reload} />
              )}
              {!preview.isLoading && !preview.error && preview.data && (
                <>
                  <div className="table-scroll">
                    <table className="table" data-testid="preview-table">
                      <thead>
                        <tr>
                          {preview.data.columns.map((column) => (
                            <th key={column.name} scope="col">
                              {column.name}
                              <span className="muted small"> · {column.dtype}</span>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.data.rows.map((row, index) => (
                          <tr key={index}>
                            {preview.data!.columns.map((column) => {
                              const cell = row[column.name];
                              return (
                                <td key={column.name}>
                                  {cell === null || cell === undefined ? (
                                    <span className="cell--null">null</span>
                                  ) : (
                                    String(cell)
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination
                    page={preview.data.page}
                    totalPages={preview.data.total_pages}
                    total={preview.data.total_rows}
                    hasNext={preview.data.has_next}
                    hasPrevious={preview.data.has_previous}
                    onPageChange={setPage}
                  />
                </>
              )}
            </Card>
          )}

          {section === 'charts' && (
            <>
              <Card title="Suggested charts">
                {suggestions.isLoading && <Spinner />}
                {suggestions.data?.suggestions.length === 0 && (
                  <EmptyState
                    title="No suggestions available"
                    hint="Suggestions need at least one numeric or categorical column."
                    testId="suggestions-empty"
                  />
                )}
                {suggestions.data && suggestions.data.suggestions.length > 0 && (
                  <ul className="list list--plain" data-testid="chart-suggestions">
                    {suggestions.data.suggestions.map((suggestion, index) => (
                      <li key={`${suggestion.title}-${index}`} className="row row--between">
                        <span>
                          <strong>{suggestion.title}</strong>{' '}
                          <span className="muted small">— {suggestion.reason}</span>
                        </span>
                        <button
                          type="button"
                          className="button button--ghost"
                          onClick={() => {
                            setConfig(suggestion.config);
                            void renderChart(suggestion.config);
                          }}
                        >
                          Show
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card title="Filters">
                <FilterBuilder columns={columns} value={filters} onChange={setFilters} />
              </Card>

              <Card title="Chart builder">
                <ChartBuilder
                  columns={columns}
                  config={config}
                  onChange={setConfig}
                  onRender={() => void renderChart()}
                  busy={rendering}
                />
              </Card>

              <Card title={chart?.title ?? 'Chart'}>
                {rendering && <Spinner label="Building chart…" />}
                {!rendering && chartError && <ErrorState error={chartError} />}
                {!rendering && !chartError && !chart && (
                  <EmptyState
                    title="No chart yet"
                    hint="Pick a chart type and columns, then render."
                    testId="chart-placeholder"
                  />
                )}
                {!rendering && !chartError && chart && <ChartRenderer chart={chart} />}
              </Card>
            </>
          )}

          {section === 'eda' && (
            <Card title="Exploratory summary">
              {eda.isLoading && <Spinner label="Calculating…" />}
              {!eda.isLoading && eda.error && <ErrorState error={eda.error} onRetry={eda.reload} />}
              {!eda.isLoading && !eda.error && eda.data && (
                <div className="stack" data-testid="eda-summary">
                  <h3>Numeric columns</h3>
                  {eda.data.numeric.length === 0 ? (
                    <EmptyState title="No numeric columns" testId="eda-no-numeric" />
                  ) : (
                    <div className="table-scroll">
                      <table className="table">
                        <thead>
                          <tr>
                            <th scope="col">Column</th>
                            <th scope="col">Mean</th>
                            <th scope="col">Median</th>
                            <th scope="col">Min</th>
                            <th scope="col">Max</th>
                            <th scope="col">Std dev</th>
                          </tr>
                        </thead>
                        <tbody>
                          {eda.data.numeric.map((item) => (
                            <tr key={item.column}>
                              <td>{item.column}</td>
                              <td>{item.mean?.toFixed(2) ?? '—'}</td>
                              <td>{item.median?.toFixed(2) ?? '—'}</td>
                              <td>{item.minimum ?? '—'}</td>
                              <td>{item.maximum ?? '—'}</td>
                              <td>{item.std_dev?.toFixed(2) ?? '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <h3>Categorical columns</h3>
                  {eda.data.categorical.length === 0 ? (
                    <EmptyState title="No categorical columns" testId="eda-no-categorical" />
                  ) : (
                    <ul className="list list--plain">
                      {eda.data.categorical.map((item) => (
                        <li key={item.column}>
                          <strong>{item.column}</strong>{' '}
                          <span className="muted small">
                            {item.unique_count} unique ·{' '}
                            {item.top_values
                              .slice(0, 3)
                              .map((value) => `${value.value} (${value.count})`)
                              .join(', ')}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}

                  {eda.data.dates.length > 0 && (
                    <>
                      <h3>Date columns</h3>
                      <ul className="list list--plain">
                        {eda.data.dates.map((item) => (
                          <li key={item.column}>
                            <strong>{item.column}</strong>{' '}
                            <span className="muted small">
                              {item.minimum ? new Date(item.minimum).toLocaleDateString() : '—'} →{' '}
                              {item.maximum ? new Date(item.maximum).toLocaleDateString() : '—'}
                              {item.range_days !== null && ` (${item.range_days} days)`}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}
            </Card>
          )}

          {section === 'correlation' && (
            <Card title="Correlation">
              {correlation.isLoading && <Spinner label="Calculating correlations…" />}
              {!correlation.isLoading && correlation.error && (
                <ErrorState error={correlation.error} onRetry={correlation.reload} />
              )}
              {!correlation.isLoading && !correlation.error && correlation.data && (
                <div className="stack">
                  {correlation.data.columns.length === 0 ? (
                    <EmptyState
                      title="Correlation unavailable"
                      hint={correlation.data.message ?? undefined}
                      testId="correlation-empty"
                    />
                  ) : (
                    <>
                      <p className="muted small">
                        Pairwise {correlation.data.method} correlation across{' '}
                        {correlation.data.columns.length} numeric column(s).
                      </p>
                      <CorrelationHeatmap correlation={correlation.data} />
                    </>
                  )}
                  {correlation.data.excluded.length > 0 && (
                    <p className="muted small">
                      Excluded:{' '}
                      {correlation.data.excluded
                        .map((item) => `${item.column} (${item.reason})`)
                        .join(', ')}
                    </p>
                  )}
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
