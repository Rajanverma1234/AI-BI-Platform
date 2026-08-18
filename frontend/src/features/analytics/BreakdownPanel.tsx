/**
 * Segmentation, ranking, contribution and ABC share the same inputs
 * (dimension + metric), so one panel drives all four analyses and renders the
 * result with the existing chart components.
 */

import { useState } from 'react';

import {
  getAbcAnalysis,
  getContribution,
  getRanking,
  getSegment,
} from '@/api/analytics';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { formatValue } from '@/features/analytics/formatValue';
import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import type {
  AbcResponse,
  ChartDataResponse,
  ColumnRole,
  ContributionResponse,
  MetricType,
  SegmentResponse,
  SortDirection,
} from '@/types/api';

type Analysis = 'segment' | 'ranking' | 'contribution' | 'abc';

interface BreakdownPanelProps {
  projectId: string;
  datasetId: string;
  versionId?: string;
  columns: ColumnRole[];
}

const ANALYSES: { id: Analysis; label: string }[] = [
  { id: 'segment', label: 'Segmentation' },
  { id: 'ranking', label: 'Top / bottom' },
  { id: 'contribution', label: 'Contribution' },
  { id: 'abc', label: 'ABC analysis' },
];

const METRICS: MetricType[] = ['sum', 'average', 'count', 'distinct_count', 'median', 'min', 'max'];
/** These require a measure column; the rest accept any column. */
const NUMERIC_ONLY_METRICS: MetricType[] = ['sum', 'average', 'median'];

/** Build a bar chart from breakdown rows using the shared chart contract. */
function toChart(
  rows: { label: string; value: number | null }[],
  dimension: string,
  metricLabel: string,
): ChartDataResponse {
  return {
    chart_type: 'bar',
    title: null,
    x_axis: dimension,
    y_axis: metricLabel,
    labels: rows.map((row) => row.label),
    series: [{ name: metricLabel, data: rows.map((row) => row.value) }],
    points: [],
    boxes: [],
    metadata: {},
  };
}

export function BreakdownPanel({
  projectId,
  datasetId,
  versionId,
  columns,
}: BreakdownPanelProps) {
  const dimensions = columns.filter((column) => column.categorical || column.identifier);
  const measures = columns.filter((column) => column.measure);

  const [analysis, setAnalysis] = useState<Analysis>('segment');
  const [dimension, setDimension] = useState(dimensions[0]?.name ?? '');
  const [metric, setMetric] = useState<MetricType>(measures.length ? 'sum' : 'count');
  const [column, setColumn] = useState(measures[0]?.name ?? '');
  const [sort, setSort] = useState<SortDirection>('desc');
  const [limit, setLimit] = useState(10);
  const [aThreshold, setAThreshold] = useState(80);
  const [bThreshold, setBThreshold] = useState(95);

  const [segment, setSegmentResult] = useState<SegmentResponse | null>(null);
  const [contribution, setContributionResult] = useState<ContributionResponse | null>(null);
  const [abc, setAbcResult] = useState<AbcResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const needsColumn = metric !== 'count';

  async function run() {
    setBusy(true);
    setError(null);
    setSegmentResult(null);
    setContributionResult(null);
    setAbcResult(null);

    const params = {
      dimension,
      metric,
      column: needsColumn ? column : null,
      sort,
      limit,
      version_id: versionId ?? null,
    };

    try {
      if (analysis === 'abc') {
        const response = await getAbcAnalysis(projectId, datasetId, {
          ...params,
          a_threshold: aThreshold,
          b_threshold: bThreshold,
        });
        setAbcResult(response.result);
      } else if (analysis === 'contribution') {
        const response = await getContribution(projectId, datasetId, params);
        setContributionResult(response.result);
      } else {
        const call = analysis === 'ranking' ? getRanking : getSegment;
        const response = await call(projectId, datasetId, params);
        setSegmentResult(response.result);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  if (dimensions.length === 0) {
    return (
      <Card title="Breakdown">
        <EmptyState
          title="No dimensions available"
          hint="This dataset has no categorical column to group by."
          testId="breakdown-no-dimensions"
        />
      </Card>
    );
  }

  const metricLabel = needsColumn ? `${metric} of ${column}` : 'count';

  return (
    <div className="stack">
      <Card title="Breakdown">
        <div className="row">
          <label className="field field--inline">
            <span className="muted small">Analysis</span>
            <select
              className="input"
              value={analysis}
              onChange={(event) => setAnalysis(event.target.value as Analysis)}
              aria-label="Analysis type"
            >
              {ANALYSES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field field--inline">
            <span className="muted small">Dimension</span>
            <select
              className="input"
              value={dimension}
              onChange={(event) => setDimension(event.target.value)}
              aria-label="Dimension"
            >
              {dimensions.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field field--inline">
            <span className="muted small">Metric</span>
            <select
              className="input"
              value={metric}
              onChange={(event) => setMetric(event.target.value as MetricType)}
              aria-label="Breakdown metric"
            >
              {METRICS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          {needsColumn && (
            <label className="field field--inline">
              <span className="muted small">Of column</span>
              <select
                className="input"
                value={column}
                onChange={(event) => setColumn(event.target.value)}
                aria-label="Breakdown column"
              >
                <option value="">Select…</option>
                {/* Totals and averages apply to measures; counts to anything. */}
                {(NUMERIC_ONLY_METRICS.includes(metric) ? measures : columns).map((option) => (
                  <option key={option.name} value={option.name}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {(analysis === 'segment' || analysis === 'ranking') && (
            <label className="field field--inline">
              <span className="muted small">Order</span>
              <select
                className="input"
                value={sort}
                onChange={(event) => setSort(event.target.value as SortDirection)}
                aria-label="Sort direction"
              >
                <option value="desc">Top (highest first)</option>
                <option value="asc">Bottom (lowest first)</option>
              </select>
            </label>
          )}

          {analysis !== 'abc' && (
            <label className="field field--inline">
              <span className="muted small">Show</span>
              <input
                className="input"
                type="number"
                min={1}
                max={500}
                value={limit}
                onChange={(event) => setLimit(Number(event.target.value))}
                aria-label="Row limit"
              />
            </label>
          )}

          {analysis === 'abc' && (
            <>
              <label className="field field--inline">
                <span className="muted small">A up to %</span>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={99}
                  value={aThreshold}
                  onChange={(event) => setAThreshold(Number(event.target.value))}
                  aria-label="A threshold"
                />
              </label>
              <label className="field field--inline">
                <span className="muted small">B up to %</span>
                <input
                  className="input"
                  type="number"
                  min={2}
                  max={100}
                  value={bThreshold}
                  onChange={(event) => setBThreshold(Number(event.target.value))}
                  aria-label="B threshold"
                />
              </label>
            </>
          )}
        </div>

        <button
          type="button"
          className="button"
          onClick={() => void run()}
          disabled={busy || !dimension || (needsColumn && !column)}
        >
          {busy ? 'Calculating…' : 'Run analysis'}
        </button>
      </Card>

      {busy && <Spinner label="Calculating…" />}
      {error && <ErrorState error={error} />}

      {segment && (
        <Card title={`${metricLabel} by ${segment.dimension}`}>
          <ChartRenderer chart={toChart(segment.rows, segment.dimension, metricLabel)} />
          <div className="table-scroll">
            <table className="table" data-testid="segment-table">
              <thead>
                <tr>
                  <th scope="col">{segment.dimension}</th>
                  <th scope="col">Value</th>
                  <th scope="col">Share</th>
                </tr>
              </thead>
              <tbody>
                {segment.rows.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{formatValue(row.value)}</td>
                    <td className="muted">
                      {row.percentage === null ? '—' : `${row.percentage.toFixed(1)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {segment.truncated && (
            <p className="muted small">
              Showing {segment.rows.length} of {segment.group_count} groups.
            </p>
          )}
        </Card>
      )}

      {contribution && (
        <Card title={`Contribution by ${contribution.dimension}`}>
          <ChartRenderer
            chart={toChart(contribution.rows, contribution.dimension, metricLabel)}
          />
          <div className="table-scroll">
            <table className="table" data-testid="contribution-table">
              <thead>
                <tr>
                  <th scope="col">{contribution.dimension}</th>
                  <th scope="col">Value</th>
                  <th scope="col">Share</th>
                  <th scope="col">Cumulative</th>
                </tr>
              </thead>
              <tbody>
                {contribution.rows.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{formatValue(row.value)}</td>
                    <td className="muted">
                      {row.percentage === null ? '—' : `${row.percentage.toFixed(1)}%`}
                    </td>
                    <td className="muted">
                      {row.cumulative_percentage === null
                        ? '—'
                        : `${row.cumulative_percentage.toFixed(1)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {abc && (
        <Card title={`ABC analysis by ${abc.dimension}`}>
          <div className="kpi-grid">
            {abc.summary.map((item) => (
              <div key={item.abc_class} className="kpi-card">
                <span className="kpi-card__name">Class {item.abc_class}</span>
                <p className="kpi-card__value">{item.item_count}</p>
                <p className="muted small">
                  {item.percentage_of_total.toFixed(1)}% of value ·{' '}
                  {item.percentage_of_items.toFixed(1)}% of items
                </p>
              </div>
            ))}
          </div>
          <div className="table-scroll">
            <table className="table" data-testid="abc-table">
              <thead>
                <tr>
                  <th scope="col">{abc.dimension}</th>
                  <th scope="col">Value</th>
                  <th scope="col">Share</th>
                  <th scope="col">Cumulative</th>
                  <th scope="col">Class</th>
                </tr>
              </thead>
              <tbody>
                {abc.rows.slice(0, 100).map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{formatValue(row.value)}</td>
                    <td className="muted">{row.percentage.toFixed(1)}%</td>
                    <td className="muted">{row.cumulative_percentage.toFixed(1)}%</td>
                    <td>
                      <span className={`badge badge--abc-${row.abc_class.toLowerCase()}`}>
                        {row.abc_class}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
