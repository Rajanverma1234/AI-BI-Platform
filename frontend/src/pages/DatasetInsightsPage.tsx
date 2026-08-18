import { useCallback, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getDataset } from '@/api/datasets';
import { generateInsights, getLatestInsights, refreshInsightRun } from '@/api/insights';
import { listDatasetVersions } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { BusinessHealthCard } from '@/features/insights/BusinessHealthCard';
import { InsightCard } from '@/features/insights/InsightCard';
import {
  applyFilters,
  EMPTY_FILTERS,
  InsightFilterBar,
  type InsightFilterState,
} from '@/features/insights/InsightFilterBar';
import { RecommendationList } from '@/features/insights/RecommendationList';
import { useAsync } from '@/hooks/useAsync';
import type {
  BusinessInsight,
  Dataset,
  DatasetVersionListResponse,
  InsightReport,
  InsightRunDetail,
} from '@/types/api';

/** Groups shown on the page, in the order a business owner would read them. */
const GROUPS: { id: string; title: string; blurb: string; match: (i: BusinessInsight) => boolean }[] =
  [
    {
      id: 'critical',
      title: 'Critical alerts',
      blurb: 'Findings that need attention first, ranked by measured impact.',
      match: (insight) => insight.priority === 'critical' || insight.priority === 'high',
    },
    {
      id: 'opportunities',
      title: 'Opportunities',
      blurb: 'Areas already performing well where there may be room to do more.',
      match: (insight) => insight.category === 'opportunity',
    },
    {
      id: 'risks',
      title: 'Risks',
      blurb: 'Potential risks detected in the data. Each one is a prompt to investigate.',
      match: (insight) => insight.category === 'risk',
    },
    {
      id: 'positive',
      title: 'Positive findings',
      blurb: 'Where the numbers are moving the right way.',
      match: (insight) =>
        insight.severity === 'info' &&
        (insight.category === 'performance' ||
          insight.category === 'customer' ||
          insight.category === 'operations'),
    },
    {
      id: 'trends',
      title: 'Trends',
      blurb: 'Patterns over the dataset’s own time axis.',
      match: (insight) => insight.category === 'trend' || insight.category === 'performance',
    },
    {
      id: 'quality',
      title: 'Data quality',
      blurb: 'Issues that limit how far the figures above can be trusted.',
      match: (insight) => insight.category === 'data_quality',
    },
  ];

export default function DatasetInsightsPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();

  const [versionId, setVersionId] = useState('');
  const source = versionId || undefined;

  const [report, setReport] = useState<InsightReport | null>(null);
  const [busy, setBusy] = useState<'generate' | 'refresh' | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [filters, setFilters] = useState<InsightFilterState>(EMPTY_FILTERS);

  const loadDataset = useCallback(
    (signal: AbortSignal) => getDataset(projectId, datasetId, signal),
    [projectId, datasetId],
  );
  const loadVersions = useCallback(
    (signal: AbortSignal) => listDatasetVersions(projectId, datasetId, { page_size: 50 }, signal),
    [projectId, datasetId],
  );
  const loadLatest = useCallback(
    (signal: AbortSignal) => getLatestInsights(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );

  const dataset = useAsync<Dataset>(loadDataset);
  const versions = useAsync<DatasetVersionListResponse>(loadVersions);
  const latest = useAsync<InsightRunDetail | null>(loadLatest);

  // A freshly generated report wins; otherwise fall back to the stored run.
  const active = report ?? latest.data?.report ?? null;

  const visible = useMemo(
    () => (active ? applyFilters(active.insights, filters, active.filters) : []),
    [active, filters],
  );

  /**
   * Each finding belongs to exactly one group - the first it matches.
   *
   * A critical risk would otherwise appear under Critical alerts, Risks and
   * Trends at once, which reads as three separate problems rather than one.
   */
  const grouped = useMemo(() => {
    const claimed = new Set<string>();
    return GROUPS.map((group) => {
      const items = visible.filter(
        (insight) => !claimed.has(insight.id) && group.match(insight),
      );
      items.forEach((insight) => claimed.add(insight.id));
      return { group, items };
    });
  }, [visible]);

  async function run(kind: 'generate' | 'refresh') {
    setBusy(kind);
    setError(null);
    try {
      if (kind === 'refresh' && active?.run_id) {
        const detail = await refreshInsightRun(active.run_id, { include_ai: true });
        setReport(detail.report);
      } else {
        setReport(
          await generateInsights(projectId, datasetId, {
            version_id: source ?? null,
            include_ai: true,
          }),
        );
      }
      setFilters(EMPTY_FILTERS);
      latest.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  if (dataset.isLoading) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={dataset.reload} />;

  const isReady = dataset.data?.status === 'ready';

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>AI insights</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      {!isReady ? (
        <Card>
          <EmptyState
            title="This dataset is not ready yet"
            hint="Insights become available once processing succeeds."
            testId="insights-not-ready"
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
                  // Insights belong to the version they were generated from.
                  setReport(null);
                  setFilters(EMPTY_FILTERS);
                  latest.reload();
                }}
                aria-label="Insights data source"
              >
                <option value="">Original dataset</option>
                {versions.data?.items.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} — {version.name}
                  </option>
                ))}
              </select>
            </label>

            <div className="row">
              <button
                type="button"
                className="button"
                onClick={() => void run('generate')}
                disabled={busy !== null}
              >
                {busy === 'generate' ? 'Analysing…' : 'Generate insights'}
              </button>
              {active?.run_id && (
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => void run('refresh')}
                  disabled={busy !== null}
                >
                  {busy === 'refresh' ? 'Refreshing…' : 'Refresh insights'}
                </button>
              )}
            </div>

            {error && <ErrorState error={error} />}
          </Card>

          {busy && <Spinner label="Analysing the dataset…" />}

          {!active && !busy && (
            <Card>
              <EmptyState
                title="No insights yet"
                hint="Generate insights to see what this dataset says about the business."
                testId="no-insights"
              />
            </Card>
          )}

          {active && (
            <>
              {active.stale && (
                <Card>
                  <p className="notice" data-testid="stale-notice">
                    These insights were generated for a different dataset version or by an
                    earlier version of the analysis. Refresh to bring them up to date.
                  </p>
                </Card>
              )}

              <Card title="What you should know">
                <p>{active.summary}</p>
                <p className="muted small">
                  {active.dataset_name} · {active.version_label} ·{' '}
                  {active.row_count.toLocaleString()} rows · generated{' '}
                  {new Date(active.generated_at).toLocaleString()} by {active.generated_by}
                </p>
                {!active.ai_available && (
                  <p className="muted small" data-testid="ai-status">
                    AI interpretation unavailable. Showing data-driven insights.
                    {active.ai_status ? ` (${active.ai_status})` : ''}
                  </p>
                )}
                {active.ai?.headline && (
                  <div className="stack--narrow" data-testid="ai-narrative">
                    <h3>{active.ai.headline}</h3>
                    {active.ai.interpretation.map((line, index) => (
                      <p key={index}>{line}</p>
                    ))}
                    {active.ai.priorities.length > 0 && (
                      <ul className="list">
                        {active.ai.priorities.map((line, index) => (
                          <li key={index}>{line}</li>
                        ))}
                      </ul>
                    )}
                    {active.ai.contains_untraceable_numbers && (
                      <p className="muted small">
                        Some figures in this narrative could not be traced back to the
                        computed evidence. Rely on the findings below.
                      </p>
                    )}
                  </div>
                )}
              </Card>

              <Card title="Business health">
                <BusinessHealthCard health={active.health} />
              </Card>

              {active.supporting_metrics.length > 0 && (
                <Card title="Supporting metrics">
                  <div className="kpi-grid" data-testid="supporting-metrics">
                    {active.supporting_metrics.slice(0, 12).map((metric, index) => (
                      <div className="kpi-card" key={`${metric.label}-${index}`}>
                        <span className="kpi-card__name">{metric.label}</span>
                        <p className="kpi-card__value">{metric.formatted}</p>
                        {metric.detail && <span className="muted small">{metric.detail}</span>}
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              <Card title="Findings">
                <InsightFilterBar
                  filters={active.filters}
                  state={filters}
                  onChange={setFilters}
                  resultCount={visible.length}
                  totalCount={active.insights.length}
                />
              </Card>

              {grouped.map(({ group, items }) =>
                items.length === 0 ? null : (
                  <Card title={group.title} key={group.id}>
                    <p className="muted small">{group.blurb}</p>
                    <div className="stack--narrow" data-testid={`group-${group.id}`}>
                      {items.map((insight) => (
                        <InsightCard key={insight.id} insight={insight} />
                      ))}
                    </div>
                  </Card>
                ),
              )}

              {visible.length === 0 && (
                <Card>
                  <EmptyState
                    title="No findings match these filters"
                    hint="Clear the filters to see everything this run detected."
                    testId="no-matching-insights"
                  />
                </Card>
              )}

              {active.recommendations.length > 0 && (
                <Card title="Recommendations">
                  <p className="muted small">
                    Each action points back at the finding that justifies it. No financial
                    outcome is guaranteed.
                  </p>
                  <RecommendationList recommendations={active.recommendations} />
                </Card>
              )}

              {active.skipped.length > 0 && (
                <Card title="Analyses that could not run">
                  <ul className="list" data-testid="insights-skipped">
                    {active.skipped.map((item) => (
                      <li key={item.analysis}>
                        <strong>{item.analysis}</strong> — {item.reason}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
