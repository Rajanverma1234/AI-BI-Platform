/**
 * Distribution statistics for a numeric column.
 *
 * The buckets come back as data and are handed to the existing ChartRenderer,
 * so no chart-drawing logic is duplicated here.
 */

import { useState } from 'react';

import { getDistribution } from '@/api/analytics';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { formatValue } from '@/features/analytics/formatValue';
import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import type { ChartDataResponse, ColumnRole, DistributionResponse } from '@/types/api';

interface DistributionPanelProps {
  projectId: string;
  datasetId: string;
  versionId?: string;
  columns: ColumnRole[];
}

function toChart(result: DistributionResponse): ChartDataResponse {
  return {
    chart_type: 'histogram',
    title: null,
    x_axis: result.column,
    y_axis: 'frequency',
    labels: result.buckets.map((bucket) => bucket.label),
    series: [{ name: 'frequency', data: result.buckets.map((bucket) => bucket.count) }],
    points: [],
    boxes: [],
    metadata: {},
  };
}

export function DistributionPanel({
  projectId,
  datasetId,
  versionId,
  columns,
}: DistributionPanelProps) {
  const measures = columns.filter((column) => column.measure);

  const [column, setColumn] = useState(measures[0]?.name ?? '');
  const [bins, setBins] = useState(10);
  const [result, setResult] = useState<DistributionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const response = await getDistribution(projectId, datasetId, {
        column,
        bins,
        version_id: versionId ?? null,
      });
      setResult(response.result);
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  if (measures.length === 0) {
    return (
      <Card title="Distribution">
        <EmptyState
          title="No numeric columns"
          hint="Distribution analysis needs at least one numeric column."
          testId="distribution-none"
        />
      </Card>
    );
  }

  return (
    <div className="stack">
      <Card title="Distribution">
        <div className="row">
          <label className="field field--inline">
            <span className="muted small">Column</span>
            <select
              className="input"
              value={column}
              onChange={(event) => setColumn(event.target.value)}
              aria-label="Distribution column"
            >
              {measures.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field field--inline">
            <span className="muted small">Buckets</span>
            <input
              className="input"
              type="number"
              min={2}
              max={100}
              value={bins}
              onChange={(event) => setBins(Number(event.target.value))}
              aria-label="Bucket count"
            />
          </label>
        </div>
        <button type="button" className="button" onClick={() => void run()} disabled={busy}>
          {busy ? 'Calculating…' : 'Run analysis'}
        </button>
      </Card>

      {busy && <Spinner label="Calculating…" />}
      {error && <ErrorState error={error} />}

      {result && (
        <Card title={`Distribution of ${result.column}`}>
          <div className="kpi-grid">
            {[
              { label: 'Mean', value: result.mean },
              { label: 'Median', value: result.median },
              { label: 'Min', value: result.minimum },
              { label: 'Max', value: result.maximum },
              { label: 'Std dev', value: result.std_dev },
            ].map((item) => (
              <div key={item.label} className="kpi-card">
                <span className="kpi-card__name">{item.label}</span>
                <p className="kpi-card__value">{formatValue(item.value)}</p>
              </div>
            ))}
          </div>

          <p className="muted small" data-testid="percentiles">
            Percentiles:{' '}
            {Object.entries(result.percentiles)
              .map(([key, value]) => `${key} ${formatValue(value)}`)
              .join(' · ')}
          </p>

          {result.buckets.length > 0 ? (
            <ChartRenderer chart={toChart(result)} />
          ) : (
            <EmptyState
              title="No spread to plot"
              hint="Every value in this column is identical."
              testId="distribution-flat"
            />
          )}
        </Card>
      )}
    </div>
  );
}
