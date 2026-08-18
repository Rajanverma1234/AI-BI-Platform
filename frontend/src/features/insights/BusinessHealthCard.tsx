/**
 * Business health, with its working shown.
 *
 * The score is never presented on its own: the contributing signals, their
 * weights and the signals that could not be measured are all one click away,
 * because a number a user cannot interrogate is a number they cannot act on.
 */

import { useState } from 'react';

import type { BusinessHealth, FactorStatus, HealthRating } from '@/types/api';

const RATING_LABELS: Record<HealthRating, string> = {
  strong: 'Strong',
  healthy: 'Healthy',
  mixed: 'Mixed',
  at_risk: 'At risk',
  unknown: 'Not measurable',
};

const STATUS_LABELS: Record<FactorStatus, string> = {
  positive: 'Positive',
  moderate: 'Moderate',
  negative: 'Negative',
  not_measurable: 'Not measurable',
};

/** Ratings map onto the existing badge palette rather than new colours. */
const RATING_BADGE: Record<HealthRating, string> = {
  strong: 'badge badge--ok',
  healthy: 'badge badge--ok',
  mixed: 'badge badge--degraded',
  at_risk: 'badge badge--error',
  unknown: 'badge',
};

const STATUS_BADGE: Record<FactorStatus, string> = {
  positive: 'badge badge--ok',
  moderate: 'badge badge--degraded',
  negative: 'badge badge--error',
  not_measurable: 'badge',
};

export function BusinessHealthCard({ health }: { health: BusinessHealth }) {
  const [showMethod, setShowMethod] = useState(false);

  return (
    <div className="stack--narrow" data-testid="business-health">
      <div className="row row--between">
        <div>
          <p className="kpi-card__name">Overall business health</p>
          <p className="kpi-card__value" data-testid="health-score">
            {health.score === null ? 'Not measurable' : `${health.score}/100`}
          </p>
        </div>
        <span className={RATING_BADGE[health.rating]}>{RATING_LABELS[health.rating]}</span>
      </div>

      <button
        type="button"
        className="button button--ghost"
        onClick={() => setShowMethod((open) => !open)}
        aria-expanded={showMethod}
      >
        {showMethod ? 'Hide calculation' : 'How is this calculated?'}
      </button>

      {showMethod && (
        <p className="muted small" data-testid="health-methodology">
          {health.methodology}
        </p>
      )}

      {health.factors.length > 0 && (
        <div className="table-scroll">
          <table className="table" data-testid="health-factors">
            <thead>
              <tr>
                <th scope="col">Signal</th>
                <th scope="col">Status</th>
                <th scope="col">Score</th>
                <th scope="col">Weight</th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {health.factors.map((factor) => (
                <tr key={factor.key}>
                  <th scope="row">{factor.name}</th>
                  <td>
                    <span className={STATUS_BADGE[factor.status]}>
                      {STATUS_LABELS[factor.status]}
                    </span>
                  </td>
                  <td>{factor.score === null ? '—' : `${Math.round(factor.score)}/100`}</td>
                  <td className="muted">{Math.round(factor.weight * 100)}%</td>
                  <td className="muted small">{factor.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {health.excluded.length > 0 && (
        <details data-testid="health-excluded">
          <summary className="muted small">
            {health.excluded.length} signal(s) could not be measured
          </summary>
          <ul className="list">
            {health.excluded.map((item) => (
              <li key={item.factor}>
                <strong>{item.factor}</strong> — {item.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
