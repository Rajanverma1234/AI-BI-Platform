/**
 * The prioritised action plan.
 *
 * Each row states the action, the finding that justifies it and the impact it
 * could have - always phrased as a possibility, because the backend never
 * claims a guaranteed outcome and neither should the UI.
 */

import type { InsightPriority, InsightRecommendation } from '@/types/api';

const PRIORITY_BADGE: Record<InsightPriority, string> = {
  critical: 'badge badge--error',
  high: 'badge badge--degraded',
  medium: 'badge',
  low: 'badge',
};

/** Highest priority first, matching the order the backend ranked them in. */
const ORDER: Record<InsightPriority, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

interface RecommendationListProps {
  recommendations: InsightRecommendation[];
  onShowInsight?: (insightId: string) => void;
}

export function RecommendationList({
  recommendations,
  onShowInsight,
}: RecommendationListProps) {
  const ranked = [...recommendations].sort(
    (left, right) => ORDER[left.priority] - ORDER[right.priority],
  );

  return (
    <div className="stack--narrow" data-testid="recommendations">
      {ranked.map((item) => (
        <article className="insight" key={item.id}>
          <header className="insight__header">
            <h4>{item.action}</h4>
            <span className={PRIORITY_BADGE[item.priority]}>{item.priority}</span>
          </header>

          <p className="muted small">
            <strong>Why:</strong> {item.reason}
          </p>
          <p className="insight__recommendation">{item.expected_impact}</p>

          <p className="muted small">
            {item.source === 'deterministic'
              ? 'Derived from measured findings'
              : `Suggested by ${item.source}`}
            {item.supporting_insight_ids.length > 0 && onShowInsight && (
              <>
                {' · '}
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => onShowInsight(item.supporting_insight_ids[0])}
                >
                  See the finding
                </button>
              </>
            )}
          </p>
        </article>
      ))}
    </div>
  );
}
