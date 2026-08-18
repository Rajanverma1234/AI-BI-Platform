/** Per-identifier analysis. The identifier column is always user-selected. */

import { useState } from 'react';

import { getEntityAnalysis } from '@/api/analytics';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { formatValue } from '@/features/analytics/formatValue';
import type { ColumnRole, EntityResponse } from '@/types/api';

interface EntityPanelProps {
  projectId: string;
  datasetId: string;
  versionId?: string;
  columns: ColumnRole[];
}

export function EntityPanel({ projectId, datasetId, versionId, columns }: EntityPanelProps) {
  const candidates = columns.filter((column) => column.identifier || column.categorical);
  const measures = columns.filter((column) => column.measure);

  const [entityColumn, setEntityColumn] = useState(candidates[0]?.name ?? '');
  const [valueColumn, setValueColumn] = useState('');
  const [transactionColumn, setTransactionColumn] = useState('');

  const [result, setResult] = useState<EntityResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const response = await getEntityAnalysis(projectId, datasetId, {
        entity_column: entityColumn,
        value_column: valueColumn || null,
        transaction_column: transactionColumn || null,
        version_id: versionId ?? null,
        limit: 20,
      });
      setResult(response.result);
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  if (candidates.length === 0) {
    return (
      <Card title="Entity analysis">
        <EmptyState
          title="No identifier column available"
          hint="Entity analysis needs a column that identifies a customer, product or similar."
          testId="entity-none"
        />
      </Card>
    );
  }

  return (
    <div className="stack">
      <Card title="Entity analysis">
        <div className="row">
          <label className="field field--inline">
            <span className="muted small">Identifier column</span>
            <select
              className="input"
              value={entityColumn}
              onChange={(event) => setEntityColumn(event.target.value)}
              aria-label="Entity column"
            >
              {candidates.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field field--inline">
            <span className="muted small">Value column</span>
            <select
              className="input"
              value={valueColumn}
              onChange={(event) => setValueColumn(event.target.value)}
              aria-label="Entity value column"
            >
              <option value="">None</option>
              {measures.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field field--inline">
            <span className="muted small">Transaction column</span>
            <select
              className="input"
              value={transactionColumn}
              onChange={(event) => setTransactionColumn(event.target.value)}
              aria-label="Transaction column"
            >
              <option value="">None</option>
              {columns.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="button"
          className="button"
          onClick={() => void run()}
          disabled={busy || !entityColumn}
        >
          {busy ? 'Calculating…' : 'Run analysis'}
        </button>
      </Card>

      {busy && <Spinner label="Calculating…" />}
      {error && <ErrorState error={error} />}

      {result && (
        <Card title={`Entities by ${result.entity_column}`}>
          <div className="kpi-grid">
            <div className="kpi-card">
              <span className="kpi-card__name">Unique</span>
              <p className="kpi-card__value">{result.unique_entities.toLocaleString()}</p>
            </div>
            <div className="kpi-card">
              <span className="kpi-card__name">Repeat</span>
              <p className="kpi-card__value">{result.repeat_entities.toLocaleString()}</p>
            </div>
            <div className="kpi-card">
              <span className="kpi-card__name">One-time</span>
              <p className="kpi-card__value">{result.one_time_entities.toLocaleString()}</p>
            </div>
            <div className="kpi-card">
              <span className="kpi-card__name">Avg records / entity</span>
              <p className="kpi-card__value">
                {formatValue(result.average_records_per_entity)}
              </p>
            </div>
            {result.average_value_per_entity !== null && (
              <div className="kpi-card">
                <span className="kpi-card__name">Avg value / entity</span>
                <p className="kpi-card__value">
                  {formatValue(result.average_value_per_entity)}
                </p>
              </div>
            )}
          </div>

          <div className="table-scroll">
            <table className="table" data-testid="entity-table">
              <thead>
                <tr>
                  <th scope="col">{result.entity_column}</th>
                  <th scope="col">Records</th>
                  {result.top_entities.some((row) => row.transaction_count !== null) && (
                    <th scope="col">Transactions</th>
                  )}
                  {result.value_column && <th scope="col">Total {result.value_column}</th>}
                  {result.value_column && <th scope="col">Average</th>}
                </tr>
              </thead>
              <tbody>
                {result.top_entities.map((row) => (
                  <tr key={row.entity}>
                    <td>{row.entity}</td>
                    <td>{row.record_count.toLocaleString()}</td>
                    {result.top_entities.some((item) => item.transaction_count !== null) && (
                      <td className="muted">
                        {row.transaction_count === null ? '—' : row.transaction_count}
                      </td>
                    )}
                    {result.value_column && <td>{formatValue(row.total_value)}</td>}
                    {result.value_column && (
                      <td className="muted">{formatValue(row.average_value)}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
