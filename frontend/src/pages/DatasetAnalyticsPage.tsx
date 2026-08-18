import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { calculateKpis, getKpiCatalog } from '@/api/analytics';
import { getDataset } from '@/api/datasets';
import { listDatasetVersions } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { BreakdownPanel } from '@/features/analytics/BreakdownPanel';
import { DistributionPanel } from '@/features/analytics/DistributionPanel';
import { EntityPanel } from '@/features/analytics/EntityPanel';
import { KpiBuilder } from '@/features/analytics/KpiBuilder';
import { KpiCard } from '@/features/analytics/KpiCard';
import { TimeGrowthPanel } from '@/features/analytics/TimeGrowthPanel';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { useAsync } from '@/hooks/useAsync';
import type {
  Dataset,
  DatasetVersionListResponse,
  KpiCatalogResponse,
  KpiDefinition,
  KpiResult,
} from '@/types/api';

type Section = 'overview' | 'time' | 'breakdown' | 'entity' | 'distribution';

const SECTIONS: { id: Section; label: string }[] = [
  { id: 'overview', label: 'KPI overview' },
  { id: 'time', label: 'Time & growth' },
  { id: 'breakdown', label: 'Segmentation & ABC' },
  { id: 'entity', label: 'Entity analysis' },
  { id: 'distribution', label: 'Distribution' },
];

export default function DatasetAnalyticsPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();

  const [section, setSection] = useState<Section>('overview');
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

  const isReady = dataset.data?.status === 'ready';

  const loadCatalog = useCallback(
    (signal: AbortSignal) => getKpiCatalog(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );
  const catalog = useAsync<KpiCatalogResponse>(loadCatalog, { immediate: false });

  // The dataset resolves after the first render, so wait until it is READY.
  const catalogStatus = catalog.status;
  const reloadCatalog = catalog.reload;
  useEffect(() => {
    if (isReady && catalogStatus === 'idle') reloadCatalog();
  }, [isReady, catalogStatus, reloadCatalog]);

  const [definitions, setDefinitions] = useState<KpiDefinition[]>([]);
  const [results, setResults] = useState<KpiResult[]>([]);
  const [calculating, setCalculating] = useState(false);
  const [kpiError, setKpiError] = useState<Error | null>(null);

  const [preview, setPreview] = useState<KpiResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<Error | null>(null);

  const columns = catalog.data?.columns ?? [];

  /** Recalculate the dashboard whenever its definitions or source change. */
  const refresh = useCallback(
    async (next: KpiDefinition[]) => {
      if (next.length === 0) {
        setResults([]);
        return;
      }
      setCalculating(true);
      setKpiError(null);
      try {
        const response = await calculateKpis(projectId, datasetId, next, source);
        setResults(response.results);
      } catch (cause) {
        setKpiError(cause instanceof Error ? cause : new Error(String(cause)));
      } finally {
        setCalculating(false);
      }
    },
    [projectId, datasetId, source],
  );

  // Seed the dashboard with the suggestions the engine says are computable.
  const suggestions = catalog.data?.suggestions;
  useEffect(() => {
    if (!suggestions || definitions.length > 0) return;
    const seeded = suggestions.slice(0, 6).map((item) => item.definition);
    setDefinitions(seeded);
    void refresh(seeded);
    // Seeding runs once per catalogue load.
  }, [suggestions, definitions.length, refresh]);

  async function addKpi(definition: KpiDefinition) {
    const next = [...definitions, definition];
    setDefinitions(next);
    await refresh(next);
  }

  async function removeKpi(index: number) {
    const next = definitions.filter((_, position) => position !== index);
    setDefinitions(next);
    await refresh(next);
  }

  async function previewKpi(definition: KpiDefinition) {
    setPreviewing(true);
    setPreviewError(null);
    try {
      const response = await calculateKpis(projectId, datasetId, [definition], source);
      setPreview(response.results[0] ?? null);
    } catch (cause) {
      setPreview(null);
      setPreviewError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setPreviewing(false);
    }
  }

  if (dataset.isLoading) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={dataset.reload} />;

  const panelProps = { projectId, datasetId, versionId: source, columns };

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Analytics</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      {!isReady ? (
        <Card>
          <EmptyState
            title="This dataset is not ready yet"
            hint="Analytics become available once the file has been processed successfully."
            testId="analytics-not-ready"
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
                  setDefinitions([]);
                  setResults([]);
                  catalog.reload();
                }}
                aria-label="Analytics data source"
              >
                <option value="">Original dataset</option>
                {versions.data?.items.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} — {version.name}
                  </option>
                ))}
              </select>
            </label>
            {catalog.data && (
              <p className="muted small">
                {catalog.data.row_count.toLocaleString()} rows · {columns.length} columns
              </p>
            )}
          </Card>

          <nav className="layout__nav" aria-label="Analytics sections">
            {SECTIONS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={section === item.id ? 'navlink navlink--active' : 'navlink'}
                onClick={() => setSection(item.id)}
                aria-pressed={section === item.id}
              >
                {item.label}
              </button>
            ))}
          </nav>

          {catalog.isLoading && <Spinner label="Inspecting columns…" />}
          {catalog.error && <ErrorState error={catalog.error} onRetry={catalog.reload} />}

          {catalog.data && section === 'overview' && (
            <>
              <Card title="KPIs">
                {calculating && <Spinner label="Calculating KPIs…" />}
                {kpiError && <ErrorState error={kpiError} />}
                {!calculating && results.length === 0 && (
                  <EmptyState
                    title="No KPIs yet"
                    hint="Add one below, or pick from the suggestions."
                    testId="kpis-empty"
                  />
                )}
                {!calculating && results.length > 0 && (
                  <div className="kpi-grid" data-testid="kpi-grid">
                    {results.map((result, index) => (
                      <KpiCard
                        key={`${result.name}-${index}`}
                        kpi={result}
                        onRemove={() => void removeKpi(index)}
                      />
                    ))}
                  </div>
                )}
              </Card>

              {catalog.data.unavailable.length > 0 && (
                <Card title="Not available for this dataset">
                  <ul className="list" data-testid="kpis-unavailable">
                    {catalog.data.unavailable.map((item) => (
                      <li key={item.kpi}>
                        <strong>{item.kpi}</strong>{' '}
                        <span className="muted small">— {item.reason}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              <Card title="Suggested KPIs">
                <ul className="list list--plain" data-testid="kpi-suggestions">
                  {catalog.data.suggestions.map((item, index) => (
                    <li key={`${item.definition.name}-${index}`} className="row row--between">
                      <span>
                        <strong>{item.definition.name}</strong>{' '}
                        <span className="muted small">— {item.reason}</span>
                      </span>
                      <button
                        type="button"
                        className="button button--ghost"
                        onClick={() => void addKpi(item.definition)}
                      >
                        Add
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>

              <KpiBuilder
                columns={columns}
                preview={preview}
                previewing={previewing}
                error={previewError}
                onPreview={(definition) => void previewKpi(definition)}
                onAdd={(definition) => void addKpi(definition)}
              />
            </>
          )}

          {catalog.data && section === 'time' && <TimeGrowthPanel {...panelProps} />}
          {catalog.data && section === 'breakdown' && <BreakdownPanel {...panelProps} />}
          {catalog.data && section === 'entity' && <EntityPanel {...panelProps} />}
          {catalog.data && section === 'distribution' && <DistributionPanel {...panelProps} />}
        </>
      )}
    </div>
  );
}
