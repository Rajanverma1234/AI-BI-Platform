import type { Insight, InsightSeverity } from '@/types/api';

const SEVERITY_TONE: Record<InsightSeverity, string> = {
  info: 'degraded',
  low: 'degraded',
  medium: 'degraded',
  high: 'error',
};

interface InsightCardProps {
  insight: Insight;
}

/** One deterministic finding, with the figures that produced it. */
export function InsightCard({ insight }: InsightCardProps) {
  return (
    <li className="insight" data-testid="insight-card">
      <div className="insight__header">
        <span className={`badge badge--${SEVERITY_TONE[insight.severity]}`}>
          {insight.severity}
        </span>
        <strong>{insight.title}</strong>
        <span className="muted small">{insight.category.replace('_', ' ')}</span>
      </div>

      <p className="muted">{insight.summary}</p>

      {insight.recommendation && (
        <p className="insight__recommendation small">
          <strong>Suggested action:</strong> {insight.recommendation}
        </p>
      )}

      {insight.confidence !== null && (
        <p className="muted small">
          Share of total: {(insight.confidence * 100).toFixed(1)}%
        </p>
      )}
    </li>
  );
}

export function InsightList({ insights }: { insights: Insight[] }) {
  return (
    <ul className="list list--plain" data-testid="insight-list">
      {insights.map((insight) => (
        <InsightCard key={insight.id} insight={insight} />
      ))}
    </ul>
  );
}
