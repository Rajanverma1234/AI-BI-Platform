import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  addWidget,
  deleteWidget,
  exportDashboard,
  getDashboard,
  getDashboardFilters,
  refreshDashboard,
  updateDashboard,
} from '@/api/dashboards';
import { listDatasetVersions } from '@/api/profiling';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { AddWidgetDialog } from '@/features/dashboards/AddWidgetDialog';
import { DashboardGrid } from '@/features/dashboards/DashboardGrid';
import { useAsync } from '@/hooks/useAsync';
import type {
  DashboardData,
  DashboardDetail,
  DashboardFilterOptions,
  DatasetVersionListResponse,
  FilterCondition,
  TemplateWidget,
  WidgetPosition,
} from '@/types/api';

export default function DashboardDetailPage() {
  const { workspaceId = '', projectId = '', dashboardId = '' } = useParams<{
    workspaceId: string;
    projectId: string;
    dashboardId: string;
  }>();

  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /** Ad-hoc filters from the filter bar or a chart click. Never persisted. */
  const [adHoc, setAdHoc] = useState<FilterCondition[]>([]);

  const loadDetail = useCallback(
    (signal: AbortSignal) => getDashboard(dashboardId, signal),
    [dashboardId],
  );
  const loadFilters = useCallback(
    (signal: AbortSignal) => getDashboardFilters(dashboardId, signal),
    [dashboardId],
  );
  const detail = useAsync<DashboardDetail>(loadDetail);
  const filters = useAsync<DashboardFilterOptions>(loadFilters);

  const datasetId = detail.data?.dashboard.dataset_id;
  const versionsLoader = useCallback(
    (signal: AbortSignal) =>
      datasetId
        ? listDatasetVersions(projectId, datasetId, { page_size: 50 }, signal)
        : Promise.resolve(null),
    [projectId, datasetId],
  );
  const versions = useAsync<DatasetVersionListResponse | null>(versionsLoader);

  const [data, setData] = useState<DashboardData | null>(null);

  const filterSet = useMemo(
    () => (adHoc.length > 0 ? { logic: 'and' as const, conditions: adHoc } : null),
    [adHoc],
  );

  const refresh = useCallback(
    async (widgetIds?: string[]) => {
      setBusy(widgetIds ? 'widget' : 'dashboard');
      setError(null);
      try {
        const next = await refreshDashboard(dashboardId, {
          filters: filterSet,
          ...(widgetIds ? { widget_ids: widgetIds } : {}),
        });
        // A single-widget refresh replaces only that widget's result.
        setData((current) =>
          current && widgetIds
            ? {
                ...current,
                widgets: current.widgets.map(
                  (widget) =>
                    next.widgets.find((item) => item.widget_id === widget.widget_id) ?? widget,
                ),
              }
            : next,
        );
      } catch (cause) {
        setError(cause instanceof Error ? cause : new Error(String(cause)));
      } finally {
        setBusy(null);
      }
    },
    [dashboardId, filterSet],
  );

  // Resolve once the dashboard's definition is known, and again whenever the
  // ad-hoc filters change (refresh is memoised on the filter set).
  const definitionLoaded = detail.status === 'success';
  useEffect(() => {
    if (definitionLoaded) void refresh();
  }, [definitionLoaded, refresh]);

  async function handleAddWidget(widget: {
    title: string;
    position: WidgetPosition;
    configuration: TemplateWidget['configuration'];
  }) {
    setBusy('add');
    setError(null);
    try {
      await addWidget(dashboardId, widget);
      setAdding(false);
      detail.reload();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  async function handleRemoveWidget(widgetId: string) {
    setBusy(widgetId);
    try {
      await deleteWidget(dashboardId, widgetId);
      detail.reload();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  async function saveLayout(layout: { widget_id: string; position: WidgetPosition }[]) {
    setBusy('layout');
    try {
      await updateDashboard(dashboardId, { layout });
      detail.reload();
      await refresh();
      setNotice('Layout saved.');
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  function handleReorder(orderedIds: string[]) {
    if (!data) return;
    const columns = data.layout_columns;
    let x = 0;
    let y = 0;
    const layout = orderedIds.map((widgetId) => {
      const widget = data.widgets.find((item) => item.widget_id === widgetId)!;
      const width = Math.min(widget.position.width, columns);
      if (x + width > columns) {
        x = 0;
        y += 1;
      }
      const position = { ...widget.position, x, y, width };
      x += width;
      return { widget_id: widgetId, position };
    });
    void saveLayout(layout);
  }

  async function handleExport() {
    setBusy('export');
    setNotice(null);
    try {
      const report = await exportDashboard(dashboardId, 'pdf');
      setNotice(
        report.status === 'ready'
          ? `"${report.name}" is ready in this dataset's report history.`
          : (report.error_message ?? 'The export could not be produced.'),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  async function handleVersionChange(versionId: string) {
    setBusy('version');
    try {
      await updateDashboard(dashboardId, {
        ...(versionId ? { dataset_version_id: versionId } : { clear_version: true }),
      });
      detail.reload();
      filters.reload();
      await refresh();
      setNotice('Dashboard moved to the selected version.');
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  if (detail.isLoading) return <Spinner label="Loading dashboard…" />;
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;

  const dashboard = detail.data?.dashboard;
  const categorical = (filters.data?.fields ?? []).filter((f) => f.kind === 'categorical');

  return (
    <div className="stack">
      <div className="dashboard-header">
        <div>
          <p className="muted small">
            <Link to={`/workspaces/${workspaceId}/projects/${projectId}/dashboards`}>
              ← Dashboards
            </Link>
          </p>
          <h1>{dashboard?.name}</h1>
          {dashboard?.description && <p className="muted">{dashboard.description}</p>}
          <p className="muted small" data-testid="dashboard-source">
            {detail.data?.dataset_name} · {detail.data?.version_label}
            {data ? ` · ${data.filtered_row_count.toLocaleString()} rows` : ''}
          </p>
        </div>

        <div className="row">
          <button
            type="button"
            className="button button--ghost"
            onClick={() => setEditing((value) => !value)}
          >
            {editing ? 'Done editing' : 'Edit dashboard'}
          </button>
          {editing && (
            <button type="button" className="button" onClick={() => setAdding(true)}>
              Add widget
            </button>
          )}
          <button
            type="button"
            className="button button--ghost"
            onClick={() => void refresh()}
            disabled={busy !== null}
          >
            {busy === 'dashboard' ? 'Refreshing…' : 'Refresh'}
          </button>
          <button
            type="button"
            className="button button--ghost"
            onClick={() => void handleExport()}
            disabled={busy !== null}
          >
            {busy === 'export' ? 'Exporting…' : 'Export PDF'}
          </button>
        </div>
      </div>

      {error && <ErrorState error={error} />}
      {notice && (
        <p className="notice notice--success" data-testid="dashboard-notice">
          {notice}
        </p>
      )}

      {editing && (
        <Card title="Data source">
          <label className="field field--inline">
            <span className="muted small">Dataset version</span>
            <select
              className="input"
              value={dashboard?.dataset_version_id ?? ''}
              onChange={(event) => void handleVersionChange(event.target.value)}
              aria-label="Dataset version"
              disabled={busy !== null}
            >
              <option value="">Original dataset</option>
              {versions.data?.items.map((version) => (
                <option key={version.id} value={version.id}>
                  v{version.version_number} — {version.name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted small">
            A dashboard stays on the version it was built for until you move it here.
          </p>
        </Card>
      )}

      {categorical.length > 0 && (
        <Card title="Filters">
          <div className="row" data-testid="dashboard-filters">
            {categorical.slice(0, 6).map((field) => (
              <label className="field field--inline" key={field.column}>
                <span className="muted small">{field.column}</span>
                <select
                  className="input"
                  value={
                    adHoc.find((condition) => condition.column === field.column)?.value as
                      | string
                      | undefined ?? ''
                  }
                  onChange={(event) => {
                    const value = event.target.value;
                    setAdHoc((current) => [
                      ...current.filter((condition) => condition.column !== field.column),
                      ...(value
                        ? [{ column: field.column, operator: 'equals' as const, value }]
                        : []),
                    ]);
                  }}
                  aria-label={field.column}
                >
                  <option value="">All</option>
                  {field.values.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            {adHoc.length > 0 && (
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setAdHoc([])}
              >
                Clear filters
              </button>
            )}
          </div>
          <p className="muted small">
            Filters narrow every compatible widget. They are not saved to the dashboard.
          </p>
        </Card>
      )}

      {busy === 'dashboard' && <Spinner label="Resolving widgets…" />}

      {data && data.widgets.length === 0 ? (
        <Card>
          <EmptyState
            title="Your dashboard is empty."
            hint="Add your first widget to start building."
            testId="empty-dashboard"
          />
          <div className="row">
            <button type="button" className="button" onClick={() => setAdding(true)}>
              Add your first widget
            </button>
          </div>
        </Card>
      ) : (
        data && (
          <DashboardGrid
            widgets={data.widgets}
            columns={data.layout_columns}
            editing={editing}
            onRetryWidget={(widgetId) => void refresh([widgetId])}
            onRemoveWidget={editing ? (id) => void handleRemoveWidget(id) : undefined}
            onResizeWidget={
              editing
                ? (widgetId, position) => void saveLayout([{ widget_id: widgetId, position }])
                : undefined
            }
            onReorder={editing ? handleReorder : undefined}
            onSelectCategory={(column, value) =>
              setAdHoc((current) => [
                ...current.filter((condition) => condition.column !== column),
                { column, operator: 'equals', value },
              ])
            }
          />
        )
      )}

      {adding && (
        <AddWidgetDialog
          filters={filters.data}
          layoutColumns={dashboard?.layout_columns ?? 2}
          busy={busy === 'add'}
          error={error}
          onCancel={() => setAdding(false)}
          onAdd={(widget) => void handleAddWidget(widget)}
        />
      )}
    </div>
  );
}
