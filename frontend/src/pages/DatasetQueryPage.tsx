import { useCallback, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getDataset } from '@/api/datasets';
import { askQuestion, getQueryHistory, getQuerySuggestions } from '@/api/nlq';
import { listDatasetVersions } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import { useAsync } from '@/hooks/useAsync';
import type {
  ChartDataResponse,
  Dataset,
  DatasetVersionListResponse,
  NlqResponse,
  QueryContextTurn,
  QueryHistoryResponse,
  QuerySuggestionsResponse,
} from '@/types/api';

/** Only the last few turns are replayed, keeping the context bounded. */
const MAX_CONTEXT_TURNS = 3;

/** Adapt a recommendation to the existing chart contract. */
function toChart(answer: NlqResponse): ChartDataResponse | null {
  if (!answer.chart) return null;
  return {
    chart_type: answer.chart.chart_type,
    title: null,
    x_axis: answer.chart.x_axis,
    y_axis: answer.chart.y_axis,
    labels: answer.chart.labels,
    series: answer.chart.series,
    points: [],
    boxes: [],
    metadata: {},
  };
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  }
  return String(value);
}

export default function DatasetQueryPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();

  const [versionId, setVersionId] = useState('');
  const source = versionId || undefined;

  const loadDataset = useCallback(
    (signal: AbortSignal) => getDataset(projectId, datasetId, signal),
    [projectId, datasetId],
  );
  const loadVersions = useCallback(
    (signal: AbortSignal) => listDatasetVersions(projectId, datasetId, { page_size: 50 }, signal),
    [projectId, datasetId],
  );
  const loadSuggestions = useCallback(
    (signal: AbortSignal) => getQuerySuggestions(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );
  const loadHistory = useCallback(
    (signal: AbortSignal) => getQueryHistory(projectId, datasetId, { page_size: 10 }, signal),
    [projectId, datasetId],
  );

  const dataset = useAsync<Dataset>(loadDataset);
  const versions = useAsync<DatasetVersionListResponse>(loadVersions);
  const suggestions = useAsync<QuerySuggestionsResponse>(loadSuggestions);
  const history = useAsync<QueryHistoryResponse>(loadHistory);

  const [question, setQuestion] = useState('');
  const [answers, setAnswers] = useState<NlqResponse[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const isReady = dataset.data?.status === 'ready';

  async function ask(text: string) {
    const trimmed = text.trim();
    if (trimmed.length === 0) return;

    setBusy(true);
    setError(null);
    try {
      // Send only the most recent turns so follow-ups keep their subject.
      const context: QueryContextTurn[] = answers
        .slice(0, MAX_CONTEXT_TURNS)
        .reverse()
        .map((item) => ({ question: item.question, plan: item.plan }));

      const answer = await askQuestion(projectId, datasetId, trimmed, {
        versionId: source,
        context,
      });
      setAnswers((current) => [answer, ...current]);
      setQuestion('');
      history.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  if (dataset.isLoading) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={dataset.reload} />;

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Ask your data</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      {!isReady ? (
        <Card>
          <EmptyState
            title="This dataset is not ready yet"
            hint="Questions can be asked once the file has been processed successfully."
            testId="nlq-not-ready"
          />
        </Card>
      ) : (
        <>
          <Card title={dataset.data?.name ?? 'Dataset'}>
            <label className="field field--inline">
              <span className="muted small">Data source</span>
              <select
                className="input"
                value={versionId}
                onChange={(event) => {
                  setVersionId(event.target.value);
                  setAnswers([]);
                  suggestions.reload();
                }}
                aria-label="Query data source"
              >
                <option value="">Original dataset</option>
                {versions.data?.items.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} — {version.name}
                  </option>
                ))}
              </select>
            </label>

            <form onSubmit={submit} className="stack" noValidate>
              <label className="field">
                <span className="muted small">Your question</span>
                <input
                  className="input"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="e.g. Which region generated the highest revenue?"
                  aria-label="Natural language question"
                  disabled={busy}
                />
              </label>
              <button
                type="submit"
                className="button"
                disabled={busy || question.trim().length === 0}
              >
                {busy ? 'Working…' : 'Ask'}
              </button>
            </form>

            {suggestions.data && suggestions.data.suggestions.length > 0 && (
              <div className="stack">
                <span className="muted small">Try one of these:</span>
                <div className="row" data-testid="nlq-suggestions">
                  {suggestions.data.suggestions.map((item) => (
                    <button
                      key={item.question}
                      type="button"
                      className="button button--ghost"
                      onClick={() => void ask(item.question)}
                      disabled={busy}
                      title={item.reason}
                    >
                      {item.question}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </Card>

          {busy && <Spinner label="Planning and running the query…" />}
          {error && <ErrorState error={error} />}

          {!busy && answers.length === 0 && (
            <Card>
              <EmptyState
                title="No questions asked yet"
                hint="Ask a question above, or pick one of the suggestions."
                testId="nlq-empty"
              />
            </Card>
          )}

          {answers.map((answer, index) => {
            const chart = toChart(answer);
            return (
              <Card key={`${answer.question}-${index}`} title={answer.question}>
                <div className="stack">
                  <p className={answer.success ? '' : 'field__error'}>{answer.answer}</p>

                  {answer.clarification_needed && answer.candidate_columns.length > 0 && (
                    <div className="row" data-testid="nlq-clarification">
                      {answer.candidate_columns.map((column) => (
                        <button
                          key={column}
                          type="button"
                          className="button button--ghost"
                          onClick={() => void ask(`${answer.question} using ${column}`)}
                          disabled={busy}
                        >
                          Use {column}
                        </button>
                      ))}
                    </div>
                  )}

                  {answer.contains_untraceable_numbers && (
                    <p className="field__error small" role="note">
                      The AI wording contained figures the result did not support, so the
                      computed answer is shown instead.
                    </p>
                  )}

                  {answer.result && answer.result.rows.length > 0 && (
                    <div className="table-scroll">
                      <table className="table" data-testid="nlq-result-table">
                        <thead>
                          <tr>
                            {answer.result.columns.map((column) => (
                              <th key={column.name} scope="col">
                                {column.name}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {answer.result.rows.slice(0, 50).map((row, rowIndex) => (
                            <tr key={rowIndex}>
                              {answer.result!.columns.map((column) => (
                                <td key={column.name}>{formatCell(row[column.name])}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {chart && (
                    <>
                      <ChartRenderer chart={chart} />
                      <p className="muted small">{answer.chart?.reason}</p>
                    </>
                  )}

                  {answer.calculation.length > 0 && (
                    <details>
                      <summary className="muted small">How this was calculated</summary>
                      <dl className="details details--grid" data-testid="nlq-calculation">
                        {answer.calculation.map((step) => (
                          <div key={step.label}>
                            <dt>{step.label}</dt>
                            <dd>{step.detail}</dd>
                          </div>
                        ))}
                      </dl>
                      <p className="muted small">
                        Plan built by {answer.plan_source === 'ai' ? 'the AI planner' : 'keyword rules'}
                        {answer.ai_status && answer.ai_status !== 'ok'
                          ? ` — ${answer.ai_status}`
                          : ''}
                        .
                      </p>
                    </details>
                  )}
                </div>
              </Card>
            );
          })}

          <Card title="Recent questions">
            {history.isLoading && <Spinner />}
            {history.data && history.data.items.length === 0 && (
              <EmptyState title="No history yet" testId="nlq-history-empty" />
            )}
            {history.data && history.data.items.length > 0 && (
              <ul className="list list--plain" data-testid="nlq-history">
                {history.data.items.map((entry) => (
                  <li key={entry.id} className="row row--between">
                    <button
                      type="button"
                      className="button button--ghost"
                      onClick={() => void ask(entry.question)}
                      disabled={busy}
                    >
                      {entry.question}
                    </button>
                    <span className="muted small">
                      {entry.status} · {new Date(entry.created_at).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
