/**
 * One finding, with its evidence one click away.
 *
 * The collapsed card carries the claim; the expanded view carries the figures
 * that produced it and the reason it was ranked where it was. That is the
 * "why am I seeing this?" contract - no insight is presented without a way to
 * check it.
 */

import { useState } from 'react';

import type {
  BusinessInsight,
  BusinessInsightSeverity,
  InsightPriority,
} from '@/types/api';

const SEVERITY_BADGE: Record<BusinessInsightSeverity, string> = {
  critical: 'badge badge--error',
  high: 'badge badge--error',
  medium: 'badge badge--degraded',
  low: 'badge',
  info: 'badge',
};

const PRIORITY_BADGE: Record<InsightPriority, string> = {
  critical: 'badge badge--error',
  high: 'badge badge--degraded',
  medium: 'badge',
  low: 'badge',
};

const PRIORITY_HINT: Record<InsightPriority, string> = {
  critical: 'Immediate attention',
  high: 'Important business action',
  medium: 'Worth investigating',
  low: 'Informational',
};

function formatCategory(value: string): string {
  return value.replace(/_/g, ' ');
}

export function InsightCard({ insight }: { insight: BusinessInsight }) {
  const [open, setOpen] = useState(false);

  return (
    <article className="insight" data-testid={`insight-${insight.id}`}>
      <header className="insight__header">
        <h4>{insight.title}</h4>
        <div className="row">
          <span className={SEVERITY_BADGE[insight.severity]}>{insight.severity}</span>
          <span
            className={PRIORITY_BADGE[insight.priority]}
            title={PRIORITY_HINT[insight.priority]}
          >
            {insight.priority} priority
          </span>
        </div>
      </header>

      <p className="muted small">{formatCategory(insight.category)} · {insight.source}</p>
      <p>{insight.summary}</p>

      {insight.why && (
        <p className="muted small">
          <strong>Why it matters:</strong> {insight.why}
        </p>
      )}

      {insight.action && (
        <p className="insight__recommendation">
          <strong>Suggested action:</strong> {insight.action}
        </p>
      )}

      <button
        type="button"
        className="button button--ghost"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? 'Hide evidence' : 'Why am I seeing this?'}
      </button>

      {open && (
        <div className="stack--narrow" data-testid={`evidence-${insight.id}`}>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col">Value</th>
                </tr>
              </thead>
              <tbody>
                {insight.evidence.map((item, index) => (
                  <tr key={`${item.label}-${index}`}>
                    <th scope="row">{item.label}</th>
                    <td>
                      {item.formatted}
                      {item.detail && <span className="muted small"> — {item.detail}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <dl className="details details--grid">
            {insight.affected_records !== null && (
              <>
                <dt>Records affected</dt>
                <dd>{insight.affected_records.toLocaleString()}</dd>
              </>
            )}
            {insight.confidence !== null && (
              <>
                <dt>Confidence</dt>
                <dd>{(insight.confidence * 100).toFixed(0)}%</dd>
              </>
            )}
            <dt>Ranked</dt>
            <dd className="muted small">
              {insight.priority_score} — {insight.priority_reason}
            </dd>
          </dl>
        </div>
      )}
    </article>
  );
}
