/**
 * Renders one resolved widget.
 *
 * Presentation only: it never fetches or aggregates. Charts go through the
 * existing `ChartRenderer` and KPI values through the existing `formatValue`,
 * so a dashboard tile and the analytics page show a number the same way.
 *
 * A widget that failed renders its own error with a retry, so one broken tile
 * never takes the dashboard down with it.
 */

import { formatValue } from '@/features/analytics/formatValue';
import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import type {
  AdvancedWidgetData,
  InsightWidgetData,
  NlqWidgetData,
  RecommendationWidgetData,
  TableWidgetData,
  WidgetResult,
} from '@/types/api';

interface DashboardWidgetCardProps {
  widget: WidgetResult;
  editing?: boolean;
  /** Height in grid rows, used to size the chart area. */
  onRetry?: () => void;
  onConfigure?: () => void;
  onRemove?: () => void;
  /** Called when a chart category is clicked, for cross-widget filtering. */
  onSelectCategory?: (column: string, value: string) => void;
}

function DataTable({ data }: { data: TableWidgetData }) {
  return (
    <div className="stack--narrow">
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, index) => (
              <tr key={index}>
                {data.columns.map((column) => {
                  const value = row[column];
                  return (
                    <td key={column} className={value === null ? 'cell--null' : undefined}>
                      {value === null || value === undefined
                        ? '—'
                        : typeof value === 'number'
                          ? formatValue(value)
                          : String(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.truncated && (
        <p className="muted small">
          Showing {data.rows.length.toLocaleString()} of {data.row_count.toLocaleString()} rows.
        </p>
      )}
    </div>
  );
}

function Insights({ data }: { data: InsightWidgetData }) {
  if (data.insights.length === 0 && data.health_score === null) {
    return <p className="muted">No findings match this widget’s filters.</p>;
  }
  return (
    <div className="stack--narrow">
      {data.stale && (
        <p className="muted small">
          Generated for a different dataset version — refresh insights to update.
        </p>
      )}
      {data.health_score !== null && (
        <div className="kpi-card">
          <span className="kpi-card__name">Business health</span>
          <p className="kpi-card__value">{data.health_score}/100</p>
          {data.health_rating && (
            <span className="muted small">{data.health_rating.replace(/_/g, ' ')}</span>
          )}
        </div>
      )}
      <ul className="list">
        {data.insights.map((insight) => (
          <li key={insight.id}>
            <strong>{insight.title}</strong>
            <span className="muted small"> · {insight.severity}</span>
            <br />
            <span className="muted small">{insight.summary}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Recommendations({ data }: { data: RecommendationWidgetData }) {
  if (data.recommendations.length === 0) {
    return <p className="muted">No recommendations match this widget’s filters.</p>;
  }
  return (
    <ul className="list">
      {data.recommendations.map((item) => (
        <li key={item.id}>
          <strong>{item.action}</strong>
          <br />
          <span className="muted small">{item.expected_impact}</span>
        </li>
      ))}
    </ul>
  );
}

function NlqResult({ data }: { data: NlqWidgetData }) {
  return (
    <div className="stack--narrow">
      <p className="muted small">{data.question}</p>
      <p>{data.answer}</p>
      {data.chart && <ChartRenderer chart={data.chart} height={200} />}
    </div>
  );
}

function Advanced({ data }: { data: AdvancedWidgetData }) {
  return (
    <div className="stack--narrow">
      {data.metrics.length > 0 && (
        <div className="kpi-grid">
          {data.metrics.map((metric) => (
            <div className="kpi-card" key={metric.label}>
              <span className="kpi-card__name">{metric.label}</span>
              <p className="kpi-card__value">
                {typeof metric.value === 'number' ? formatValue(metric.value) : (metric.value ?? '—')}
                {metric.suffix ?? ''}
              </p>
            </div>
          ))}
        </div>
      )}
      {data.chart && <ChartRenderer chart={data.chart} height={220} />}
      {data.rows.length > 0 && (
        <DataTable
          data={{
            columns: data.columns,
            rows: data.rows,
            row_count: data.rows.length,
            truncated: false,
          }}
        />
      )}
      {data.note && <p className="muted small">{data.note}</p>}
    </div>
  );
}

function WidgetBody({
  widget,
  onSelectCategory,
}: {
  widget: WidgetResult;
  onSelectCategory?: (column: string, value: string) => void;
}) {
  if (widget.kpi) {
    const result = widget.kpi.result;
    if (!result.available) {
      return (
        <div className="kpi-card kpi-card--unavailable">
          <span className="kpi-card__name">{result.name}</span>
          <p className="muted small">{result.reason ?? 'Not available for this dataset.'}</p>
        </div>
      );
    }
    return (
      <div className="kpi-card">
        <span className="kpi-card__name">{result.name}</span>
        <p className="kpi-card__value">{formatValue(result.value, result.format)}</p>
        {result.comparison?.percentage_change != null && (
          <span
            className={
              result.comparison.percentage_change >= 0
                ? 'kpi-card__change kpi-card__change--up'
                : 'kpi-card__change kpi-card__change--down'
            }
          >
            {result.comparison.percentage_change >= 0 ? '▲' : '▼'}{' '}
            {Math.abs(result.comparison.percentage_change).toFixed(1)}% vs{' '}
            {result.comparison.previous_label}
          </span>
        )}
      </div>
    );
  }

  if (widget.chart) {
    const chart = widget.chart;
    const height = Math.max(180, widget.position.height * 130);
    return (
      <div>
        <ChartRenderer chart={chart} height={height} />
        {onSelectCategory && chart.x_axis && chart.labels.length > 0 && (
          <div className="row" data-testid={`crossfilter-${widget.widget_id}`}>
            <span className="muted small">Filter by {chart.x_axis}:</span>
            {chart.labels.slice(0, 8).map((label) => (
              <button
                key={label}
                type="button"
                className="button button--ghost"
                onClick={() => onSelectCategory(chart.x_axis as string, label)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (widget.table) return <DataTable data={widget.table} />;
  if (widget.insight) return <Insights data={widget.insight} />;
  if (widget.recommendation) return <Recommendations data={widget.recommendation} />;
  if (widget.nlq) return <NlqResult data={widget.nlq} />;
  if (widget.advanced) return <Advanced data={widget.advanced} />;
  // Rendered as text, never as HTML.
  if (widget.text) return <p className="dashboard-text">{widget.text.content}</p>;

  return <p className="muted">This widget has nothing to show.</p>;
}

export function DashboardWidgetCard({
  widget,
  editing = false,
  onRetry,
  onConfigure,
  onRemove,
  onSelectCategory,
}: DashboardWidgetCardProps) {
  return (
    <section
      className="panel dashboard-widget"
      data-testid={`widget-${widget.widget_id}`}
      aria-label={widget.title}
    >
      <header className="panel__header">
        <h3>{widget.title}</h3>
        {editing && (
          <div className="row">
            {onConfigure && (
              <button type="button" className="button button--ghost" onClick={onConfigure}>
                Configure
              </button>
            )}
            {onRemove && (
              <button type="button" className="button button--ghost" onClick={onRemove}>
                Remove
              </button>
            )}
          </div>
        )}
      </header>

      {widget.status === 'error' ? (
        <div className="stack--narrow" data-testid={`widget-error-${widget.widget_id}`}>
          <p className="muted">Unable to load this widget.</p>
          <p className="muted small">{widget.error}</p>
          <div className="row">
            {onRetry && (
              <button type="button" className="button button--ghost" onClick={onRetry}>
                Retry
              </button>
            )}
            {onConfigure && (
              <button type="button" className="button button--ghost" onClick={onConfigure}>
                Configure
              </button>
            )}
          </div>
        </div>
      ) : (
        <WidgetBody widget={widget} onSelectCategory={onSelectCategory} />
      )}
    </section>
  );
}
