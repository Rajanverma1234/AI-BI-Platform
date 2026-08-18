/**
 * Build a KPI definition.
 *
 * Supports a plain metric or a two-operand ratio formula (the common
 * business case: AOV, margin, conversion rate). The formula is assembled as a
 * structured tree — the user never types an expression.
 */

import { useState } from 'react';

import { Card, ErrorState, FormField, Spinner } from '@/components/ui';
import { KpiCard } from '@/features/analytics/KpiCard';
import type {
  ColumnRole,
  KpiDefinition,
  KpiResult,
  MetricType,
  TimePeriod,
  ValueFormat,
} from '@/types/api';

interface KpiBuilderProps {
  columns: ColumnRole[];
  preview: KpiResult | null;
  previewing: boolean;
  error: Error | null;
  onPreview: (definition: KpiDefinition) => void;
  onAdd: (definition: KpiDefinition) => void;
}

const METRICS: { value: MetricType; label: string; numericOnly: boolean }[] = [
  { value: 'count', label: 'Count', numericOnly: false },
  { value: 'distinct_count', label: 'Distinct count', numericOnly: false },
  { value: 'sum', label: 'Sum', numericOnly: true },
  { value: 'average', label: 'Average', numericOnly: true },
  { value: 'median', label: 'Median', numericOnly: true },
  { value: 'min', label: 'Min', numericOnly: false },
  { value: 'max', label: 'Max', numericOnly: false },
  { value: 'range', label: 'Range', numericOnly: true },
  { value: 'std_dev', label: 'Std deviation', numericOnly: true },
];

const FORMATS: ValueFormat[] = ['number', 'integer', 'currency', 'percent'];
const PERIODS: TimePeriod[] = ['day', 'week', 'month', 'quarter', 'year'];

type Mode = 'metric' | 'ratio';

export function KpiBuilder({
  columns,
  preview,
  previewing,
  error,
  onPreview,
  onAdd,
}: KpiBuilderProps) {
  const measures = columns.filter((column) => column.measure);
  const temporal = columns.filter((column) => column.temporal);

  const [mode, setMode] = useState<Mode>('metric');
  const [name, setName] = useState('');
  const [metric, setMetric] = useState<MetricType>('sum');
  const [column, setColumn] = useState('');
  const [style, setStyle] = useState<ValueFormat>('number');

  // Ratio (formula) inputs.
  const [numeratorMetric, setNumeratorMetric] = useState<MetricType>('sum');
  const [numeratorColumn, setNumeratorColumn] = useState('');
  const [denominatorMetric, setDenominatorMetric] = useState<MetricType>('distinct_count');
  const [denominatorColumn, setDenominatorColumn] = useState('');
  const [asPercentage, setAsPercentage] = useState(false);

  const [compareColumn, setCompareColumn] = useState('');
  const [comparePeriod, setComparePeriod] = useState<TimePeriod>('month');

  function build(): KpiDefinition {
    const base: KpiDefinition = {
      name: name.trim() || 'Untitled KPI',
      format: { style, decimals: style === 'integer' ? 0 : 2 },
      ...(compareColumn
        ? { comparison: { date_column: compareColumn, period: comparePeriod } }
        : {}),
    };

    if (mode === 'metric') {
      return {
        ...base,
        metric,
        column: metric === 'count' && !column ? null : column || null,
      };
    }

    const ratio: KpiDefinition['formula'] = {
      node: 'binary',
      operator: 'divide',
      left: { node: 'metric', metric: numeratorMetric, column: numeratorColumn || null },
      right: { node: 'metric', metric: denominatorMetric, column: denominatorColumn || null },
    };

    return {
      ...base,
      // Multiplying by 100 turns the ratio into a percentage.
      formula: asPercentage
        ? { node: 'binary', operator: 'multiply', left: ratio, right: { node: 'constant', value: 100 } }
        : ratio,
      format: { style: asPercentage ? 'percent' : style, decimals: 2 },
    };
  }

  const needsColumn = mode === 'metric' && metric !== 'count';
  const incomplete =
    mode === 'metric'
      ? needsColumn && !column
      : !numeratorColumn && numeratorMetric !== 'count';

  return (
    <Card title="Create a KPI">
      <div className="stack">
        <div className="row">
          <label className="field field--inline">
            <span className="muted small">Type</span>
            <select
              className="input"
              value={mode}
              onChange={(event) => setMode(event.target.value as Mode)}
              aria-label="KPI type"
            >
              <option value="metric">Single metric</option>
              <option value="ratio">Ratio / formula</option>
            </select>
          </label>

          <FormField
            id="kpi-name"
            label="KPI name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Average order value"
          />
        </div>

        {mode === 'metric' ? (
          <div className="row">
            <label className="field field--inline">
              <span className="muted small">Metric</span>
              <select
                className="input"
                value={metric}
                onChange={(event) => setMetric(event.target.value as MetricType)}
                aria-label="Metric"
              >
                {METRICS.map((option) => (
                  <option
                    key={option.value}
                    value={option.value}
                    disabled={option.numericOnly && measures.length === 0}
                  >
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field field--inline">
              <span className="muted small">Column</span>
              <select
                className="input"
                value={column}
                onChange={(event) => setColumn(event.target.value)}
                aria-label="Metric column"
              >
                <option value="">{metric === 'count' ? 'All rows' : 'Select…'}</option>
                {/* Sum/average only make sense over measures, never over ids. */}
                {(METRICS.find((m) => m.value === metric)?.numericOnly ? measures : columns).map(
                  (option) => (
                    <option key={option.name} value={option.name}>
                      {option.name}
                    </option>
                  ),
                )}
              </select>
            </label>
          </div>
        ) : (
          <>
            <div className="row">
              <label className="field field--inline">
                <span className="muted small">Numerator</span>
                <select
                  className="input"
                  value={numeratorMetric}
                  onChange={(event) => setNumeratorMetric(event.target.value as MetricType)}
                  aria-label="Numerator metric"
                >
                  {METRICS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field--inline">
                <span className="muted small">of</span>
                <select
                  className="input"
                  value={numeratorColumn}
                  onChange={(event) => setNumeratorColumn(event.target.value)}
                  aria-label="Numerator column"
                >
                  <option value="">Select…</option>
                  {columns.map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="row">
              <label className="field field--inline">
                <span className="muted small">Denominator</span>
                <select
                  className="input"
                  value={denominatorMetric}
                  onChange={(event) => setDenominatorMetric(event.target.value as MetricType)}
                  aria-label="Denominator metric"
                >
                  {METRICS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field--inline">
                <span className="muted small">of</span>
                <select
                  className="input"
                  value={denominatorColumn}
                  onChange={(event) => setDenominatorColumn(event.target.value)}
                  aria-label="Denominator column"
                >
                  <option value="">All rows</option>
                  {columns.map((option) => (
                    <option key={option.name} value={option.name}>
                      {option.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="row muted small">
                <input
                  type="checkbox"
                  checked={asPercentage}
                  onChange={(event) => setAsPercentage(event.target.checked)}
                />
                Show as percentage (× 100)
              </label>
            </div>
          </>
        )}

        <div className="row">
          <label className="field field--inline">
            <span className="muted small">Format</span>
            <select
              className="input"
              value={style}
              onChange={(event) => setStyle(event.target.value as ValueFormat)}
              aria-label="Value format"
            >
              {FORMATS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="field field--inline">
            <span className="muted small">Compare over time</span>
            <select
              className="input"
              value={compareColumn}
              onChange={(event) => setCompareColumn(event.target.value)}
              aria-label="Comparison date column"
              disabled={temporal.length === 0}
            >
              <option value="">No comparison</option>
              {temporal.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>

          {compareColumn && (
            <label className="field field--inline">
              <span className="muted small">Period</span>
              <select
                className="input"
                value={comparePeriod}
                onChange={(event) => setComparePeriod(event.target.value as TimePeriod)}
                aria-label="Comparison period"
              >
                {PERIODS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        {temporal.length === 0 && (
          <p className="muted small">
            Time comparison is unavailable: this dataset has no recognisable date column.
          </p>
        )}

        <div className="row">
          <button
            type="button"
            className="button button--ghost"
            onClick={() => onPreview(build())}
            disabled={previewing || incomplete}
          >
            {previewing ? 'Calculating…' : 'Preview'}
          </button>
          <button
            type="button"
            className="button"
            onClick={() => onAdd(build())}
            disabled={incomplete}
          >
            Add to dashboard
          </button>
        </div>

        {previewing && <Spinner label="Calculating KPI…" />}
        {error && <ErrorState error={error} />}
        {preview && !previewing && (
          <div className="kpi-grid" data-testid="kpi-preview">
            <KpiCard kpi={preview} />
          </div>
        )}
      </div>
    </Card>
  );
}
