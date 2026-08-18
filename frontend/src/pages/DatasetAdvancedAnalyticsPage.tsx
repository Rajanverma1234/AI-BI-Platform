import { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  getCapabilities,
  runChurn,
  runCohort,
  runForecast,
  runOutliers,
  runPareto,
  runRfm,
  runSegmentation,
} from '@/api/advancedAnalytics';
import { getDataset } from '@/api/datasets';
import { listDatasetVersions } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { formatValue } from '@/features/analytics/formatValue';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { BoxPlot } from '@/features/visualization/BoxPlot';
import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import { useAsync } from '@/hooks/useAsync';
import type {
  AdvancedCapabilities,
  ChartDataResponse,
  ChurnResponse,
  CohortResponse,
  Dataset,
  DatasetVersionListResponse,
  ForecastResponse,
  OutlierResponse,
  ParetoResponse,
  RfmResponse,
  SegmentationResponse,
} from '@/types/api';

type Analysis =
  | 'rfm'
  | 'segmentation'
  | 'cohort'
  | 'churn'
  | 'pareto'
  | 'outliers'
  | 'forecast';

const TABS: { id: Analysis; label: string; blurb: string }[] = [
  { id: 'rfm', label: 'RFM', blurb: 'Ranks customers by how recently, how often and how much they buy.' },
  { id: 'segmentation', label: 'Segmentation', blurb: 'Groups similar records together using K-Means clustering.' },
  { id: 'cohort', label: 'Cohort', blurb: 'Tracks how many customers keep coming back after their first purchase.' },
  { id: 'churn', label: 'Churn', blurb: 'Flags customers who have gone quiet, using an inactivity rule.' },
  { id: 'pareto', label: 'Pareto / ABC', blurb: 'Finds the few entities that drive most of the result.' },
  { id: 'outliers', label: 'Outliers', blurb: 'Identifies unusually high or low values. Nothing is removed.' },
  { id: 'forecast', label: 'Forecast', blurb: 'Projects a metric forward using exponential smoothing.' },
];

/** Retention percentage → heatmap cell colour. */
function heatColour(value: number | null): string {
  if (value === null) return 'transparent';
  return `rgba(91, 140, 255, ${Math.min(value / 100, 1) * 0.8})`;
}

export default function DatasetAdvancedAnalyticsPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();

  const [versionId, setVersionId] = useState('');
  const source = versionId || undefined;
  const [tab, setTab] = useState<Analysis>('rfm');

  const loadDataset = useCallback(
    (signal: AbortSignal) => getDataset(projectId, datasetId, signal),
    [projectId, datasetId],
  );
  const loadVersions = useCallback(
    (signal: AbortSignal) => listDatasetVersions(projectId, datasetId, { page_size: 50 }, signal),
    [projectId, datasetId],
  );
  const loadCapabilities = useCallback(
    (signal: AbortSignal) => getCapabilities(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );

  const dataset = useAsync<Dataset>(loadDataset);
  const versions = useAsync<DatasetVersionListResponse>(loadVersions);
  const capabilities = useAsync<AdvancedCapabilities>(loadCapabilities);

  const [rfm, setRfm] = useState<RfmResponse | null>(null);
  const [clusters, setClusters] = useState<SegmentationResponse | null>(null);
  const [cohort, setCohort] = useState<CohortResponse | null>(null);
  const [churn, setChurn] = useState<ChurnResponse | null>(null);
  const [pareto, setPareto] = useState<ParetoResponse | null>(null);
  const [outliers, setOutliers] = useState<OutlierResponse | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const detected = capabilities.data?.detected_columns ?? {};
  const blocked = capabilities.data?.unavailable.find((item) => item.analysis === tab);

  async function run() {
    setBusy(true);
    setError(null);
    const version_id = source ?? null;
    try {
      if (tab === 'rfm') setRfm(await runRfm(projectId, datasetId, { version_id }));
      if (tab === 'segmentation')
        setClusters(await runSegmentation(projectId, datasetId, { version_id, clusters: 4 }));
      if (tab === 'cohort') setCohort(await runCohort(projectId, datasetId, { version_id }));
      if (tab === 'churn') setChurn(await runChurn(projectId, datasetId, { version_id }));
      if (tab === 'pareto')
        setPareto(
          await runPareto(projectId, datasetId, {
            version_id,
            dimension: detected.dimension ?? '',
            column: detected.revenue ?? null,
          }),
        );
      if (tab === 'outliers')
        setOutliers(
          await runOutliers(projectId, datasetId, {
            version_id,
            column: detected.revenue ?? detected.measure ?? '',
          }),
        );
      if (tab === 'forecast') setForecast(await runForecast(projectId, datasetId, { version_id }));
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  function barChart(labels: string[], data: (number | null)[], x: string, y: string): ChartDataResponse {
    return {
      chart_type: 'bar',
      title: null,
      x_axis: x,
      y_axis: y,
      labels,
      series: [{ name: y, data }],
      points: [],
      boxes: [],
      metadata: {},
    };
  }

  if (dataset.isLoading) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={dataset.reload} />;

  const isReady = dataset.data?.status === 'ready';
  const active = TABS.find((item) => item.id === tab);

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Advanced analytics</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      {!isReady ? (
        <Card>
          <EmptyState
            title="This dataset is not ready yet"
            hint="Advanced analytics become available once processing succeeds."
            testId="advanced-not-ready"
          />
        </Card>
      ) : (
        <>
          <Card title={dataset.data?.name ?? 'Dataset'}>
            <label className="field field--inline">
              <span className="muted small">Data source</span>
              <select
                className="input"
                value={versionId}
                onChange={(event) => {
                  setVersionId(event.target.value);
                  setRfm(null);
                  setClusters(null);
                  setCohort(null);
                  setChurn(null);
                  setPareto(null);
                  setOutliers(null);
                  setForecast(null);
                  capabilities.reload();
                }}
                aria-label="Advanced analytics data source"
              >
                <option value="">Original dataset</option>
                {versions.data?.items.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} — {version.name}
                  </option>
                ))}
              </select>
            </label>
            {capabilities.data && (
              <p className="muted small" data-testid="detected-columns">
                Detected:{' '}
                {Object.entries(detected)
                  .map(([role, column]) => `${role} → ${column}`)
                  .join(' · ') || 'none'}
              </p>
            )}
          </Card>

          <nav className="layout__nav" aria-label="Advanced analyses">
            {TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? 'navlink navlink--active' : 'navlink'}
                onClick={() => setTab(item.id)}
                aria-pressed={tab === item.id}
              >
                {item.label}
              </button>
            ))}
          </nav>

          <Card title={active?.label}>
            <p className="muted">{active?.blurb}</p>
            {blocked ? (
              <EmptyState
                title="Not available for this dataset"
                hint={blocked.message}
                testId="analysis-blocked"
              />
            ) : (
              <button type="button" className="button" onClick={() => void run()} disabled={busy}>
                {busy ? 'Calculating…' : 'Run analysis'}
              </button>
            )}
            {capabilities.error && <ErrorState error={capabilities.error} />}
          </Card>

          {busy && <Spinner label="Calculating…" />}
          {error && <ErrorState error={error} />}

          {tab === 'rfm' && rfm && (
            <Card title={`RFM — ${rfm.customer_count.toLocaleString()} customers`}>
              <p className="muted small">
                Scored against the latest activity in the data ({rfm.reference_date}).
              </p>
              <ChartRenderer
                chart={barChart(
                  rfm.segments.map((item) => item.segment),
                  rfm.segments.map((item) => item.customer_count),
                  'segment',
                  'customers',
                )}
              />
              <div className="table-scroll">
                <table className="table" data-testid="rfm-segments">
                  <thead>
                    <tr>
                      <th scope="col">Segment</th>
                      <th scope="col">Customers</th>
                      <th scope="col">Share</th>
                      <th scope="col">Value</th>
                      <th scope="col">Value share</th>
                      <th scope="col">Avg recency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rfm.segments.map((item) => (
                      <tr key={item.segment}>
                        <td>{item.segment}</td>
                        <td>{item.customer_count.toLocaleString()}</td>
                        <td className="muted">{item.percentage}%</td>
                        <td>{formatValue(item.total_monetary)}</td>
                        <td className="muted">{item.monetary_percentage}%</td>
                        <td className="muted">{item.average_recency_days} days</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'segmentation' && clusters && (
            <Card title={`${clusters.clusters} clusters on ${clusters.features.join(', ')}`}>
              {clusters.meta.warnings.map((warning) => (
                <p key={warning} className="muted small">
                  {warning}
                </p>
              ))}
              <ChartRenderer
                chart={barChart(
                  clusters.profiles.map((item) => `Cluster ${item.cluster}`),
                  clusters.profiles.map((item) => item.size),
                  'cluster',
                  'records',
                )}
              />
              <div className="table-scroll">
                <table className="table" data-testid="cluster-profiles">
                  <thead>
                    <tr>
                      <th scope="col">Cluster</th>
                      <th scope="col">Size</th>
                      <th scope="col">Share</th>
                      <th scope="col">Distinguishing features</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clusters.profiles.map((item) => (
                      <tr key={item.cluster}>
                        <td>Cluster {item.cluster}</td>
                        <td>{item.size.toLocaleString()}</td>
                        <td className="muted">{item.percentage}%</td>
                        <td className="muted">
                          {item.distinguishing_features
                            .map((f) => `${f.feature} (${f.z_score > 0 ? '+' : ''}${f.z_score}σ)`)
                            .join(', ')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'cohort' && cohort && (
            <Card title="Cohort retention">
              <div className="table-scroll">
                <table className="table heatmap" data-testid="cohort-matrix">
                  <thead>
                    <tr>
                      <th scope="col">Cohort</th>
                      <th scope="col">Size</th>
                      {cohort.period_labels.map((label) => (
                        <th key={label} scope="col">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cohort.rows.slice(0, 24).map((row) => (
                      <tr key={row.cohort}>
                        <th scope="row">{row.cohort}</th>
                        <td>{row.cohort_size}</td>
                        {row.percentages.map((value, index) => (
                          <td
                            key={index}
                            className="heatmap__cell"
                            style={{ background: heatColour(value) }}
                          >
                            {value === null ? '—' : `${value}%`}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'churn' && churn && (
            <Card title="Churn (rule-based)">
              <p className="muted small">{churn.method_note}</p>
              <div className="kpi-grid">
                {[
                  { label: 'Active', value: churn.active_customers },
                  { label: 'At risk', value: churn.at_risk_customers },
                  { label: 'Churned', value: churn.churned_customers },
                  { label: 'Churn rate', value: `${churn.churn_rate}%` },
                ].map((item) => (
                  <div key={item.label} className="kpi-card">
                    <span className="kpi-card__name">{item.label}</span>
                    <p className="kpi-card__value">{item.value.toLocaleString?.() ?? item.value}</p>
                  </div>
                ))}
              </div>
              <ChartRenderer
                chart={{
                  chart_type: 'line',
                  title: null,
                  x_axis: 'period',
                  y_axis: 'active customers',
                  labels: churn.trend.map((point) => point.period),
                  series: [
                    {
                      name: 'active customers',
                      data: churn.trend.map((point) => point.active_customers),
                    },
                  ],
                  points: [],
                  boxes: [],
                  metadata: {},
                }}
              />
            </Card>
          )}

          {tab === 'pareto' && pareto && (
            <Card title={`Pareto — ${pareto.dimension}`}>
              <p className="muted">
                {pareto.vital_few_count} of {pareto.rows.length} groups (
                {pareto.vital_few_percentage_of_items}% of entities) drive {pareto.threshold}% of
                the total.
              </p>
              <ChartRenderer
                chart={barChart(
                  pareto.rows.map((row) => row.label),
                  pareto.rows.map((row) => row.value),
                  pareto.dimension,
                  'value',
                )}
              />
              <div className="table-scroll">
                <table className="table" data-testid="pareto-table">
                  <thead>
                    <tr>
                      <th scope="col">{pareto.dimension}</th>
                      <th scope="col">Value</th>
                      <th scope="col">Share</th>
                      <th scope="col">Cumulative</th>
                      <th scope="col">Vital few</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pareto.rows.map((row) => (
                      <tr key={row.label}>
                        <td>{row.label}</td>
                        <td>{formatValue(row.value)}</td>
                        <td className="muted">{row.percentage}%</td>
                        <td className="muted">{row.cumulative_percentage}%</td>
                        <td>{row.within_threshold ? 'Yes' : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {tab === 'outliers' && outliers && (
            <Card title={`Outliers in ${outliers.column}`}>
              <p className="muted">
                {outliers.outlier_count.toLocaleString()} of{' '}
                {outliers.total_observations.toLocaleString()} values (
                {outliers.outlier_percentage}%) fall outside {formatValue(outliers.lower_bound)} to{' '}
                {formatValue(outliers.upper_bound)} using the {outliers.method.toUpperCase()}{' '}
                method. Nothing has been removed.
              </p>
              {outliers.minimum !== null && (
                <BoxPlot
                  boxes={[
                    {
                      label: outliers.column,
                      minimum: outliers.minimum,
                      q1: outliers.q1 ?? 0,
                      median: outliers.median ?? 0,
                      q3: outliers.q3 ?? 0,
                      maximum: outliers.maximum ?? 0,
                      outlier_count: outliers.outlier_count,
                    },
                  ]}
                />
              )}
            </Card>
          )}

          {tab === 'forecast' && forecast && (
            <Card title={`Forecast — ${forecast.method}`}>
              <p className="muted small">
                {forecast.periods_observed} historical {forecast.period} periods · trend{' '}
                {forecast.trend} · in-sample MAE {formatValue(forecast.mean_absolute_error)}.
                Intervals are {Math.round(forecast.confidence_level * 100)}% prediction bounds.
              </p>
              <ChartRenderer
                chart={{
                  chart_type: 'line',
                  title: null,
                  x_axis: 'period',
                  y_axis: 'value',
                  labels: [
                    ...forecast.history.map((point) => point.period),
                    ...forecast.forecast.map((point) => point.period),
                  ],
                  series: [
                    {
                      name: 'history',
                      data: [
                        ...forecast.history.map((point) => point.value),
                        ...forecast.forecast.map(() => null),
                      ],
                    },
                    {
                      name: 'forecast',
                      data: [
                        ...forecast.history.map(() => null),
                        ...forecast.forecast.map((point) => point.value),
                      ],
                    },
                  ],
                  points: [],
                  boxes: [],
                  metadata: {},
                }}
              />
              <div className="table-scroll">
                <table className="table" data-testid="forecast-table">
                  <thead>
                    <tr>
                      <th scope="col">Period</th>
                      <th scope="col">Forecast</th>
                      <th scope="col">Lower</th>
                      <th scope="col">Upper</th>
                    </tr>
                  </thead>
                  <tbody>
                    {forecast.forecast.map((point) => (
                      <tr key={point.period}>
                        <td>{point.period}</td>
                        <td>{formatValue(point.value)}</td>
                        <td className="muted">{formatValue(point.lower_bound)}</td>
                        <td className="muted">{formatValue(point.upper_bound)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
