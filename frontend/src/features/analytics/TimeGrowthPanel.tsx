/** Time-series and period-over-period growth, sharing one set of controls. */

import { useState } from 'react';

import { getGrowth, getTimeSeries } from '@/api/analytics';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { changeTone, formatChange, formatValue } from '@/features/analytics/formatValue';
import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import type {
  ChartDataResponse,
  ColumnRole,
  GrowthResponse,
  MetricType,
  TimePeriod,
  TimeSeriesResponse,
} from '@/types/api';

interface TimeGrowthPanelProps {
  projectId: string;
  datasetId: string;
  versionId?: string;
  columns: ColumnRole[];
}

const PERIODS: TimePeriod[] = ['day', 'week', 'month', 'quarter', 'year'];
const METRICS: MetricType[] = ['sum', 'average', 'count', 'distinct_count', 'median', 'min', 'max'];

function toChart(series: TimeSeriesResponse, metricLabel: string): ChartDataResponse {
  return {
    chart_type: 'line',
    title: null,
    x_axis: series.date_column,
    y_axis: metricLabel,
    labels: series.labels,
    series: series.series.map((item) => ({
      name: item.name,
      data: item.points.map((point) => point.value),
    })),
    points: [],
    boxes: [],
    metadata: {},
  };
}

export function TimeGrowthPanel({
  projectId,
  datasetId,
  versionId,
  columns,
}: TimeGrowthPanelProps) {
  const temporal = columns.filter((column) => column.temporal);
  const dimensions = columns.filter((column) => column.categorical);

  const [dateColumn, setDateColumn] = useState(temporal[0]?.name ?? '');
  const [period, setPeriod] = useState<TimePeriod>('month');
  const [metric, setMetric] = useState<MetricType>('sum');
  const [column, setColumn] = useState(columns.find((c) => c.measure)?.name ?? '');
  const [groupBy, setGroupBy] = useState('');

  const [series, setSeries] = useState<TimeSeriesResponse | null>(null);
  const [growth, setGrowth] = useState<GrowthResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const needsColumn = metric !== 'count';

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const params = {
        date_column: dateColumn,
        period,
        metric,
        column: needsColumn ? column : null,
        version_id: versionId ?? null,
      };
      const [seriesResponse, growthResponse] = await Promise.all([
        getTimeSeries(projectId, datasetId, { ...params, group_by: groupBy || null }),
        getGrowth(projectId, datasetId, params),
      ]);
      setSeries(seriesResponse.result);
      setGrowth(growthResponse.result);
    } catch (cause) {
      setSeries(null);
      setGrowth(null);
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  if (temporal.length === 0) {
    return (
      <Card title="Time analysis">
        <EmptyState
          title="No date column available"
          hint="Time and growth analysis need a column recognised as dates."
          testId="time-no-date"
        />
      </Card>
    );
  }

  const metricLabel = needsColumn ? `${metric} of ${column}` : 'count';

  return (
    <div className="stack">
      <Card title="Time analysis">
        <div className="row">
          <label className="field field--inline">
            <span className="muted small">Date column</span>
            <select
              className="input"
              value={dateColumn}
              onChange={(event) => setDateColumn(event.target.value)}
              aria-label="Date column"
            >
              {temporal.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field field--inline">
            <span className="muted small">Period</span>
            <select
              className="input"
              value={period}
              onChange={(event) => setPeriod(event.target.value as TimePeriod)}
              aria-label="Time period"
            >
              {PERIODS.map((option) => (
                <option key={option} value={option}>
                  {option}
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
              aria-label="Time metric"
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
                aria-label="Time metric column"
              >
                <option value="">Select…</option>
                {columns.map((option) => (
                  <option key={option.name} value={option.name}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="field field--inline">
            <span className="muted small">Split by</span>
            <select
              className="input"
              value={groupBy}
              onChange={(event) => setGroupBy(event.target.value)}
              aria-label="Split by dimension"
            >
              <option value="">None</option>
              {dimensions.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="button"
          className="button"
          onClick={() => void run()}
          disabled={busy || !dateColumn || (needsColumn && !column)}
        >
          {busy ? 'Calculating…' : 'Run analysis'}
        </button>
      </Card>

      {busy && <Spinner label="Calculating…" />}
      {error && <ErrorState error={error} />}

      {series && (
        <Card title={`${metricLabel} per ${period}`}>
          {series.labels.length === 0 ? (
            <EmptyState title="No data in this period" testId="time-empty" />
          ) : (
            <ChartRenderer chart={toChart(series, metricLabel)} />
          )}
          {series.truncated && (
            <p className="muted small">Showing the most recent {series.labels.length} periods.</p>
          )}
        </Card>
      )}

      {growth && (
        <Card title="Growth">
          {growth.message ? (
            <EmptyState title="Not enough history" hint={growth.message} testId="growth-empty" />
          ) : (
            <>
              {growth.current && (
                <div className="kpi-grid">
                  <div className="kpi-card">
                    <span className="kpi-card__name">Current ({growth.current.label})</span>
                    <p className="kpi-card__value">{formatValue(growth.current.value)}</p>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-card__name">Previous</span>
                    <p className="kpi-card__value">
                      {formatValue(growth.current.previous_value)}
                    </p>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-card__name">Change</span>
                    <p
                      className={`kpi-card__value kpi-card__change--${changeTone(
                        growth.current.percentage_change,
                      )}`}
                    >
                      {formatChange(growth.current.percentage_change)}
                    </p>
                    <p className="muted small">
                      {formatValue(growth.current.absolute_change)} absolute
                    </p>
                  </div>
                </div>
              )}

              <div className="table-scroll">
                <table className="table" data-testid="growth-table">
                  <thead>
                    <tr>
                      <th scope="col">Period</th>
                      <th scope="col">Value</th>
                      <th scope="col">Previous</th>
                      <th scope="col">Change</th>
                      <th scope="col">Growth</th>
                    </tr>
                  </thead>
                  <tbody>
                    {growth.points.map((point) => (
                      <tr key={point.label}>
                        <td>{point.label}</td>
                        <td>{formatValue(point.value)}</td>
                        <td className="muted">{formatValue(point.previous_value)}</td>
                        <td className="muted">{formatValue(point.absolute_change)}</td>
                        <td className={`kpi-card__change--${changeTone(point.percentage_change)}`}>
                          {formatChange(point.percentage_change)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
