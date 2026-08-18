import { changeTone, formatChange, formatValue } from '@/features/analytics/formatValue';
import type { KpiResult } from '@/types/api';

interface KpiCardProps {
  kpi: KpiResult;
  onRemove?: () => void;
}

/**
 * A single KPI tile.
 *
 * An unavailable KPI shows the reason instead of a value — never a zero or a
 * placeholder that could be mistaken for real data.
 */
export function KpiCard({ kpi, onRemove }: KpiCardProps) {
  const tone = changeTone(kpi.comparison?.percentage_change ?? null);

  return (
    <div className={`kpi-card${kpi.available ? '' : ' kpi-card--unavailable'}`} data-testid="kpi-card">
      <div className="kpi-card__header">
        <span className="kpi-card__name">{kpi.name}</span>
        {onRemove && (
          <button
            type="button"
            className="kpi-card__remove"
            onClick={onRemove}
            aria-label={`Remove ${kpi.name}`}
          >
            ×
          </button>
        )}
      </div>

      {kpi.available ? (
        <>
          <p className="kpi-card__value">{formatValue(kpi.value, kpi.format)}</p>
          {kpi.comparison && kpi.comparison.previous_value !== null && (
            <p className={`kpi-card__change kpi-card__change--${tone}`}>
              {formatChange(kpi.comparison.percentage_change)}
              <span className="muted small">
                {' '}
                vs {kpi.comparison.previous_label ?? 'previous'} (
                {formatValue(kpi.comparison.previous_value, kpi.format)})
              </span>
            </p>
          )}
        </>
      ) : (
        <p className="kpi-card__unavailable muted small" role="note">
          Not available — {kpi.reason}
        </p>
      )}

      {kpi.description && <p className="muted small">{kpi.description}</p>}
    </div>
  );
}
