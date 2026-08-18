/**
 * Chart configuration form.
 *
 * Which inputs appear, and which columns each offers, depends on the chart
 * type — so an invalid combination (SUM over a text column, a scatter plot of
 * two categories) cannot be assembled here. The backend validates again.
 */

import type {
  Aggregation,
  ChartConfig,
  ChartType,
  DetectedType,
  PreviewColumn,
} from '@/types/api';

interface ChartBuilderProps {
  columns: PreviewColumn[];
  config: ChartConfig;
  onChange: (config: ChartConfig) => void;
  onRender: () => void;
  busy: boolean;
}

const NUMERIC: DetectedType[] = ['integer', 'float'];

const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: 'bar', label: 'Bar' },
  { value: 'line', label: 'Line' },
  { value: 'area', label: 'Area' },
  { value: 'pie', label: 'Pie' },
  { value: 'donut', label: 'Donut' },
  { value: 'scatter', label: 'Scatter' },
  { value: 'histogram', label: 'Histogram' },
  { value: 'box', label: 'Box plot' },
];

/** COUNT works on any column; the rest need numbers. */
const AGGREGATIONS: { value: Aggregation; label: string; numericOnly: boolean }[] = [
  { value: 'count', label: 'Count', numericOnly: false },
  { value: 'sum', label: 'Sum', numericOnly: true },
  { value: 'mean', label: 'Mean', numericOnly: true },
  { value: 'median', label: 'Median', numericOnly: true },
  { value: 'min', label: 'Min', numericOnly: true },
  { value: 'max', label: 'Max', numericOnly: true },
];

const CATEGORY_CHARTS: ChartType[] = ['bar', 'line', 'area', 'pie', 'donut'];

export function ChartBuilder({ columns, config, onChange, onRender, busy }: ChartBuilderProps) {
  const numericColumns = columns.filter((column) => NUMERIC.includes(column.dtype));
  const categoryColumns = columns.filter((column) => !NUMERIC.includes(column.dtype));

  const isCategoryChart = CATEGORY_CHARTS.includes(config.chart_type);
  const isScatter = config.chart_type === 'scatter';
  const isHistogram = config.chart_type === 'histogram';
  const isBox = config.chart_type === 'box';
  const countOnly = config.aggregation === 'count';

  function update(patch: Partial<ChartConfig>) {
    onChange({ ...config, ...patch });
  }

  const noNumeric = numericColumns.length === 0;
  const blocked =
    ((isScatter || isHistogram || isBox) && noNumeric) ||
    (isScatter && numericColumns.length < 2);

  return (
    <div className="stack" data-testid="chart-builder">
      <div className="row">
        <label className="field field--inline">
          <span className="muted small">Chart type</span>
          <select
            className="input"
            value={config.chart_type}
            onChange={(event) => update({ chart_type: event.target.value as ChartType })}
            aria-label="Chart type"
          >
            {CHART_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </label>

        {isCategoryChart && (
          <label className="field field--inline">
            <span className="muted small">Category (X)</span>
            <select
              className="input"
              value={config.x_column ?? ''}
              onChange={(event) => update({ x_column: event.target.value || null })}
              aria-label="Category column"
            >
              <option value="">Select…</option>
              {columns.map((column) => (
                <option key={column.name} value={column.name}>
                  {column.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {isCategoryChart && (
          <label className="field field--inline">
            <span className="muted small">Aggregation</span>
            <select
              className="input"
              value={config.aggregation ?? 'sum'}
              onChange={(event) => update({ aggregation: event.target.value as Aggregation })}
              aria-label="Aggregation"
            >
              {AGGREGATIONS.map((option) => (
                <option
                  key={option.value}
                  value={option.value}
                  // Numeric aggregations are unusable without a numeric column.
                  disabled={option.numericOnly && noNumeric}
                >
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {isCategoryChart && !countOnly && (
          <label className="field field--inline">
            <span className="muted small">Value (Y)</span>
            <select
              className="input"
              value={config.y_column ?? ''}
              onChange={(event) => update({ y_column: event.target.value || null })}
              aria-label="Value column"
            >
              <option value="">Select…</option>
              {numericColumns.map((column) => (
                <option key={column.name} value={column.name}>
                  {column.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {isScatter && (
          <>
            <label className="field field--inline">
              <span className="muted small">X (numeric)</span>
              <select
                className="input"
                value={config.x_column ?? ''}
                onChange={(event) => update({ x_column: event.target.value || null })}
                aria-label="Scatter X column"
              >
                <option value="">Select…</option>
                {numericColumns.map((column) => (
                  <option key={column.name} value={column.name}>
                    {column.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span className="muted small">Y (numeric)</span>
              <select
                className="input"
                value={config.y_column ?? ''}
                onChange={(event) => update({ y_column: event.target.value || null })}
                aria-label="Scatter Y column"
              >
                <option value="">Select…</option>
                {numericColumns.map((column) => (
                  <option key={column.name} value={column.name}>
                    {column.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}

        {isHistogram && (
          <>
            <label className="field field--inline">
              <span className="muted small">Numeric column</span>
              <select
                className="input"
                value={config.x_column ?? ''}
                onChange={(event) => update({ x_column: event.target.value || null })}
                aria-label="Histogram column"
              >
                <option value="">Select…</option>
                {numericColumns.map((column) => (
                  <option key={column.name} value={column.name}>
                    {column.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span className="muted small">Bins</span>
              <input
                className="input"
                type="number"
                min={2}
                max={100}
                value={config.bins ?? 10}
                onChange={(event) => update({ bins: Number(event.target.value) })}
                aria-label="Histogram bins"
              />
            </label>
          </>
        )}

        {isBox && (
          <>
            <label className="field field--inline">
              <span className="muted small">Numeric column</span>
              <select
                className="input"
                value={config.y_column ?? ''}
                onChange={(event) => update({ y_column: event.target.value || null })}
                aria-label="Box plot column"
              >
                <option value="">Select…</option>
                {numericColumns.map((column) => (
                  <option key={column.name} value={column.name}>
                    {column.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span className="muted small">Group by (optional)</span>
              <select
                className="input"
                value={config.group_by ?? ''}
                onChange={(event) => update({ group_by: event.target.value || null })}
                aria-label="Box plot grouping"
              >
                <option value="">None</option>
                {categoryColumns.map((column) => (
                  <option key={column.name} value={column.name}>
                    {column.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
      </div>

      {blocked && (
        <p className="field__error" role="alert">
          {isScatter
            ? 'A scatter plot needs at least two numeric columns.'
            : 'This chart type needs at least one numeric column.'}
        </p>
      )}

      <div className="row">
        <button type="button" className="button" onClick={onRender} disabled={busy || blocked}>
          {busy ? 'Building…' : 'Render chart'}
        </button>
      </div>
    </div>
  );
}
