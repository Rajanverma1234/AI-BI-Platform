/**
 * Configure a new widget from the analytics the platform already offers.
 *
 * Every column list here comes from the dashboard's own filter metadata, which
 * the backend derives from the dataset - there is no hard-coded column name in
 * this component. The configuration it emits is exactly the validated shape
 * the API accepts, so the form cannot construct something the backend rejects.
 */

import { useEffect, useMemo, useState } from 'react';

import type {
  AdvancedAnalysis,
  Aggregation,
  ChartType,
  DashboardFilterOptions,
  WidgetConfig,
  WidgetPosition,
  WidgetType,
} from '@/types/api';

const WIDGET_KINDS: { id: WidgetType; label: string; blurb: string }[] = [
  { id: 'kpi', label: 'KPI', blurb: 'A single headline figure.' },
  { id: 'chart', label: 'Chart', blurb: 'Line, bar, pie, donut, area or scatter.' },
  { id: 'table', label: 'Table', blurb: 'A grouped, aggregated table.' },
  { id: 'ai_insight', label: 'AI insight', blurb: 'Findings from a generated insight run.' },
  { id: 'recommendation', label: 'Recommendation', blurb: 'Actions from an insight run.' },
  { id: 'advanced', label: 'Advanced analytics', blurb: 'RFM, cohort, churn, forecast, Pareto.' },
  { id: 'text', label: 'Text', blurb: 'A note or description.' },
];

const CHART_TYPES: ChartType[] = ['bar', 'line', 'area', 'pie', 'donut', 'scatter', 'histogram'];
const AGGREGATIONS: Aggregation[] = ['sum', 'mean', 'count', 'median', 'min', 'max'];
const ANALYSES: AdvancedAnalysis[] = [
  'rfm',
  'cohort',
  'churn',
  'forecast',
  'pareto',
  'segmentation',
];

interface AddWidgetDialogProps {
  filters: DashboardFilterOptions | null;
  layoutColumns: number;
  busy?: boolean;
  error?: Error | null;
  onCancel: () => void;
  onAdd: (widget: {
    title: string;
    position: WidgetPosition;
    configuration: WidgetConfig;
  }) => void;
}

export function AddWidgetDialog({
  filters,
  layoutColumns,
  busy = false,
  error,
  onCancel,
  onAdd,
}: AddWidgetDialogProps) {
  const [kind, setKind] = useState<WidgetType>('kpi');
  const [title, setTitle] = useState('');
  const [width, setWidth] = useState(1);
  const [height, setHeight] = useState(1);

  const fields = filters?.fields ?? [];
  const numeric = useMemo(() => fields.filter((f) => f.kind === 'numeric'), [fields]);
  const categorical = useMemo(() => fields.filter((f) => f.kind === 'categorical'), [fields]);
  const dates = useMemo(() => fields.filter((f) => f.kind === 'date'), [fields]);

  const [metric, setMetric] = useState<Aggregation>('sum');
  const [valueColumn, setValueColumn] = useState('');
  const [dimension, setDimension] = useState('');
  const [chartType, setChartType] = useState<ChartType>('bar');
  const [useDateAxis, setUseDateAxis] = useState(false);
  const [analysis, setAnalysis] = useState<AdvancedAnalysis>('rfm');
  const [content, setContent] = useState('');

  // Default the column pickers to something real once metadata arrives.
  useEffect(() => {
    if (!valueColumn && numeric.length > 0) setValueColumn(numeric[0].column);
    if (!dimension && categorical.length > 0) setDimension(categorical[0].column);
  }, [numeric, categorical, valueColumn, dimension]);

  function buildConfiguration(): WidgetConfig | null {
    switch (kind) {
      case 'kpi':
        return {
          widget_type: 'kpi',
          definition: {
            name: title || `${metric} ${valueColumn}`.trim(),
            metric: metric === 'mean' ? 'average' : (metric as never),
            column: metric === 'count' ? null : valueColumn || null,
            format: { style: 'number', decimals: 2 },
          },
        } as WidgetConfig;
      case 'chart':
        return {
          widget_type: 'chart',
          chart_type: chartType,
          x_column: useDateAxis ? (dates[0]?.column ?? null) : dimension || null,
          y_column: valueColumn || null,
          aggregation: metric,
          period: useDateAxis ? 'month' : null,
        };
      case 'table':
        return {
          widget_type: 'table',
          group_by: dimension ? [dimension] : [],
          aggregations: valueColumn
            ? [{ column: valueColumn, aggregation: metric, alias: valueColumn }]
            : [],
          sort_by: valueColumn || null,
          sort_desc: true,
          limit: 10,
        };
      case 'ai_insight':
        return { widget_type: 'ai_insight', limit: 5, show_health: true };
      case 'recommendation':
        return { widget_type: 'recommendation', limit: 5 };
      case 'advanced':
        return { widget_type: 'advanced', analysis };
      case 'text':
        return { widget_type: 'text', content };
      default:
        return null;
    }
  }

  function submit() {
    const configuration = buildConfiguration();
    if (!configuration) return;
    onAdd({
      title: title.trim() || WIDGET_KINDS.find((item) => item.id === kind)!.label,
      position: { x: 0, y: 0, width: Math.min(width, layoutColumns), height },
      configuration,
    });
  }

  const needsValue = kind === 'kpi' || kind === 'chart' || kind === 'table';
  const needsDimension = (kind === 'chart' && !useDateAxis) || kind === 'table';

  return (
    <div className="modal__backdrop">
      <div
        className="modal modal--wide panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-widget-title"
        data-testid="add-widget-dialog"
      >
        <h2 id="add-widget-title">Add a widget</h2>

        <label className="field">
          <span className="muted small">Widget type</span>
          <select
            className="input"
            value={kind}
            onChange={(event) => setKind(event.target.value as WidgetType)}
            aria-label="Widget type"
          >
            {WIDGET_KINDS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <p className="muted small">
          {WIDGET_KINDS.find((item) => item.id === kind)?.blurb}
        </p>

        <label className="field">
          <span className="muted small">Title</span>
          <input
            className="input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Optional"
            maxLength={200}
          />
        </label>

        {kind === 'chart' && (
          <>
            <label className="field">
              <span className="muted small">Chart type</span>
              <select
                className="input"
                value={chartType}
                onChange={(event) => setChartType(event.target.value as ChartType)}
                aria-label="Chart type"
              >
                {CHART_TYPES.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            {dates.length > 0 && (
              <label className="field field--inline">
                <input
                  type="checkbox"
                  checked={useDateAxis}
                  onChange={(event) => setUseDateAxis(event.target.checked)}
                />
                <span>Plot over time ({dates[0].column}, monthly)</span>
              </label>
            )}
          </>
        )}

        {kind === 'advanced' && (
          <label className="field">
            <span className="muted small">Analysis</span>
            <select
              className="input"
              value={analysis}
              onChange={(event) => setAnalysis(event.target.value as AdvancedAnalysis)}
              aria-label="Analysis"
            >
              {ANALYSES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        )}

        {kind === 'text' && (
          <label className="field">
            <span className="muted small">Content</span>
            <textarea
              className="input"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={4}
              maxLength={5000}
              aria-label="Content"
            />
          </label>
        )}

        {needsValue && (
          <div className="row">
            <label className="field field--inline">
              <span className="muted small">Aggregation</span>
              <select
                className="input"
                value={metric}
                onChange={(event) => setMetric(event.target.value as Aggregation)}
                aria-label="Aggregation"
              >
                {AGGREGATIONS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            {metric !== 'count' && (
              <label className="field field--inline">
                <span className="muted small">Value column</span>
                <select
                  className="input"
                  value={valueColumn}
                  onChange={(event) => setValueColumn(event.target.value)}
                  aria-label="Value column"
                >
                  {numeric.map((field) => (
                    <option key={field.column} value={field.column}>
                      {field.column}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        )}

        {needsDimension && (
          <label className="field field--inline">
            <span className="muted small">Group by</span>
            <select
              className="input"
              value={dimension}
              onChange={(event) => setDimension(event.target.value)}
              aria-label="Group by"
            >
              {categorical.map((field) => (
                <option key={field.column} value={field.column}>
                  {field.column}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="row">
          <label className="field field--inline">
            <span className="muted small">Width</span>
            <select
              className="input"
              value={width}
              onChange={(event) => setWidth(Number(event.target.value))}
              aria-label="Width"
            >
              {Array.from({ length: layoutColumns }, (_, index) => index + 1).map((value) => (
                <option key={value} value={value}>
                  {value} column{value > 1 ? 's' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="field field--inline">
            <span className="muted small">Height</span>
            <select
              className="input"
              value={height}
              onChange={(event) => setHeight(Number(event.target.value))}
              aria-label="Height"
            >
              {[1, 2, 3, 4].map((value) => (
                <option key={value} value={value}>
                  {value} row{value > 1 ? 's' : ''}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error && <p className="field__error">{error.message}</p>}

        <div className="modal__actions">
          <button type="button" className="button button--ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="button" onClick={submit} disabled={busy}>
            {busy ? 'Adding…' : 'Add widget'}
          </button>
        </div>
      </div>
    </div>
  );
}
