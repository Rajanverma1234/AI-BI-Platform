import { useCallback, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { analyzeDataset } from '@/api/aiAnalyst';
import { getDataset } from '@/api/datasets';
import { listDatasetVersions } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { AskAnalyst } from '@/features/ai-analyst/AskAnalyst';
import { InsightList } from '@/features/ai-analyst/InsightCard';
import { formatValue } from '@/features/analytics/formatValue';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { useAsync } from '@/hooks/useAsync';
import type {
  AnalystReport,
  Dataset,
  DatasetVersionListResponse,
  InsightCategory,
} from '@/types/api';

export default function DatasetAiAnalystPage() {
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
  const dataset = useAsync<Dataset>(loadDataset);
  const versions = useAsync<DatasetVersionListResponse>(loadVersions);

  const [report, setReport] = useState<AnalystReport | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const isReady = dataset.data?.status === 'ready';

  async function analyse(refresh = false) {
    setAnalysing(true);
    setError(null);
    try {
      setReport(
        await analyzeDataset(projectId, datasetId, { versionId: source, refresh }),
      );
    } catch (cause) {
      setReport(null);
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setAnalysing(false);
    }
  }

  /** Group insights so each section shows only what belongs to it. */
  const byCategory = useMemo(() => {
    const groups: Partial<Record<InsightCategory, AnalystReport['insights']>> = {};
    for (const insight of report?.insights ?? []) {
      (groups[insight.category] ??= []).push(insight);
    }
    return groups;
  }, [report]);

  if (dataset.isLoading) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={dataset.reload} />;

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>AI analyst</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      {!isReady ? (
        <Card>
          <EmptyState
            title="This dataset is not ready yet"
            hint="Analysis becomes available once the file has been processed successfully."
            testId="analyst-not-ready"
          />
        </Card>
      ) : (
        <>
          <Card title={dataset.data?.name ?? 'Dataset'}>
            <div className="row">
              <label className="field field--inline">
                <span className="muted small">Data source</span>
                <select
                  className="input"
                  value={versionId}
                  onChange={(event) => {
                    setVersionId(event.target.value);
                    setReport(null);
                  }}
                  aria-label="Analysis data source"
                >
                  <option value="">Original dataset</option>
                  {versions.data?.items.map((version) => (
                    <option key={version.id} value={version.id}>
                      v{version.version_number} — {version.name}
                    </option>
                  ))}
                </select>
              </label>

              <button
                type="button"
                className="button"
                onClick={() => void analyse(false)}
                disabled={analysing}
              >
                {analysing ? 'Analysing…' : 'Analyze dataset'}
              </button>

              {report && (
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => void analyse(true)}
                  disabled={analysing}
                >
                  Re-run
                </button>
              )}
            </div>

            {report && (
              <p className="muted small" data-testid="analysis-status">
                Analysed {new Date(report.generated_at).toLocaleString()} ·{' '}
                {report.row_count.toLocaleString()} rows · {report.column_count} columns
                {report.cached && ' · from cache'}
                {report.ai_available
                  ? ` · AI interpretation by ${report.ai?.provider ?? 'provider'}`
                  : ' · deterministic analysis only'}
              </p>
            )}
          </Card>

          {analysing && <Spinner label="Running the analysis pipeline…" />}
          {error && <ErrorState error={error} onRetry={() => void analyse(true)} />}

          {!analysing && !error && !report && (
            <Card>
              <EmptyState
                title="No analysis yet"
                hint="Run “Analyze dataset” to generate insights from this data."
                testId="analyst-empty"
              />
            </Card>
          )}

          {report && !analysing && (
            <>
              <Card title="Executive summary">
                <p>{report.ai?.executive_summary ?? report.summary}</p>

                {report.ai?.executive_summary && (
                  <p className="muted small">
                    Computed summary: {report.summary}
                  </p>
                )}

                {!report.ai_available && report.ai_status && (
                  <p className="muted small" data-testid="ai-status">
                    {report.ai_status}
                  </p>
                )}

                {report.ai?.contains_untraceable_numbers && (
                  <p className="field__error small" role="note">
                    Some figures in the AI summary could not be matched to the computed
                    analysis ({report.ai.untraceable_values.join(', ')}). Trust the
                    deterministic insights below.
                  </p>
                )}
              </Card>

              <Card title="Key findings">
                {report.ai && report.ai.key_findings.length > 0 ? (
                  <ul className="list" data-testid="key-findings">
                    {report.ai.key_findings.map((finding) => (
                      <li key={finding}>{finding}</li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState
                    title="No AI findings"
                    hint="The deterministic insights below cover the same ground."
                    testId="findings-empty"
                  />
                )}
              </Card>

              <Card title="KPI insights">
                <div className="kpi-grid">
                  {report.kpis.map((kpi) => (
                    <div
                      key={kpi.name}
                      className={`kpi-card${kpi.available ? '' : ' kpi-card--unavailable'}`}
                    >
                      <span className="kpi-card__name">{kpi.name}</span>
                      {kpi.available ? (
                        <p className="kpi-card__value">{formatValue(kpi.value)}</p>
                      ) : (
                        <p className="muted small">Not available — {kpi.reason}</p>
                      )}
                    </div>
                  ))}
                </div>
              </Card>

              {(
                [
                  ['trend', 'Trend insights'],
                  ['anomaly', 'Anomaly insights'],
                  ['segment', 'Segment insights'],
                  ['kpi', 'Metric relationships'],
                  ['data_quality', 'Data quality notes'],
                ] as [InsightCategory, string][]
              ).map(([category, title]) => {
                const items = (byCategory[category] ?? []).filter(
                  // KPI cards are shown above; only relationships belong here.
                  (insight) => category !== 'kpi' || insight.metric === 'correlation',
                );
                if (items.length === 0) return null;
                return (
                  <Card key={category} title={title}>
                    <InsightList insights={items} />
                  </Card>
                );
              })}

              <Card title="Business recommendations">
                {(report.ai?.recommendations.length ?? 0) > 0 ||
                report.recommendations.length > 0 ? (
                  <ul className="list" data-testid="recommendations">
                    {(report.ai?.recommendations.length
                      ? report.ai.recommendations
                      : report.recommendations
                    ).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState
                    title="No recommendations"
                    hint="Nothing in this dataset warranted an action."
                    testId="recommendations-empty"
                  />
                )}
              </Card>

              <Card title="Detected business columns">
                <ul className="list list--plain" data-testid="semantic-columns">
                  {report.semantic_columns.map((item) => (
                    <li key={item.role} className="row row--between">
                      <span>
                        <strong>{item.role}</strong>{' '}
                        <span className="muted small">→ {item.column}</span>
                      </span>
                      <span className="muted small">{item.reason}</span>
                    </li>
                  ))}
                </ul>
              </Card>

              <AskAnalyst
                projectId={projectId}
                datasetId={datasetId}
                versionId={source}
                aiAvailable={report.ai_available}
                aiStatus={report.ai_status}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
