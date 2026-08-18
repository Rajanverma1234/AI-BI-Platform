import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import {
  createDashboard,
  deleteDashboard,
  duplicateDashboard,
  getDashboardTemplates,
  listDashboards,
} from '@/api/dashboards';
import { listDatasets } from '@/api/datasets';
import { Card, ConfirmDialog, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type {
  Dashboard,
  DashboardListResponse,
  DashboardTemplateList,
  DatasetListResponse,
} from '@/types/api';

export default function DashboardsPage() {
  const { workspaceId = '', projectId = '' } = useParams<{
    workspaceId: string;
    projectId: string;
  }>();
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [datasetId, setDatasetId] = useState('');
  const [template, setTemplate] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Dashboard | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadDashboards = useCallback(
    (signal: AbortSignal) => listDashboards(projectId, { page_size: 50 }, signal),
    [projectId],
  );
  const loadDatasets = useCallback(
    (signal: AbortSignal) => listDatasets(projectId, { page_size: 50 }, signal),
    [projectId],
  );

  const dashboards = useAsync<DashboardListResponse>(loadDashboards);
  const datasets = useAsync<DatasetListResponse>(loadDatasets);

  const ready = (datasets.data?.items ?? []).filter((item) => item.status === 'ready');

  useEffect(() => {
    if (!datasetId && ready.length > 0) setDatasetId(ready[0].id);
  }, [ready, datasetId]);

  const loadTemplates = useCallback(
    (signal: AbortSignal) =>
      datasetId
        ? getDashboardTemplates(projectId, datasetId, undefined, signal)
        : Promise.resolve(null),
    [projectId, datasetId],
  );
  const templates = useAsync<DashboardTemplateList | null>(loadTemplates);

  // Templates describe one dataset's columns, so they are refetched when the
  // dataset changes. The empty initial id would only fetch nothing, so it is
  // skipped rather than firing a request that resolves to null.
  const reloadTemplates = templates.reload;
  useEffect(() => {
    if (datasetId) reloadTemplates();
  }, [datasetId, reloadTemplates]);

  async function handleCreate() {
    if (!name.trim() || !datasetId) return;
    setCreating(true);
    setError(null);
    try {
      const detail = await createDashboard(projectId, {
        name: name.trim(),
        description: description.trim() || null,
        dataset_id: datasetId,
        template: template || null,
      });
      navigate(
        `/workspaces/${workspaceId}/projects/${projectId}/dashboards/${detail.dashboard.id}`,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setCreating(false);
    }
  }

  async function handleDuplicate(dashboard: Dashboard) {
    setBusyId(dashboard.id);
    setError(null);
    try {
      await duplicateDashboard(dashboard.id);
      dashboards.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(dashboard: Dashboard) {
    setBusyId(dashboard.id);
    try {
      await deleteDashboard(dashboard.id);
      dashboards.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusyId(null);
      setPendingDelete(null);
    }
  }

  if (dashboards.isLoading) return <Spinner label="Loading dashboards…" />;

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/workspaces/${workspaceId}/projects/${projectId}`}>← Project</Link>
        </p>
        <h1>Dashboards</h1>
      </div>

      {dashboards.error && <ErrorState error={dashboards.error} onRetry={dashboards.reload} />}

      <Card title="Create a dashboard">
        {ready.length === 0 ? (
          <EmptyState
            title="No datasets are ready yet"
            hint="Upload and process a dataset before building a dashboard."
            testId="no-datasets"
          />
        ) : (
          <div className="stack--narrow">
            <label className="field">
              <span className="muted small">Name</span>
              <input
                className="input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Sales performance dashboard"
                maxLength={200}
              />
            </label>
            <label className="field">
              <span className="muted small">Description</span>
              <input
                className="input"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Optional"
                maxLength={1000}
              />
            </label>
            <label className="field field--inline">
              <span className="muted small">Dataset</span>
              <select
                className="input"
                value={datasetId}
                onChange={(event) => setDatasetId(event.target.value)}
                aria-label="Dataset"
              >
                {ready.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span className="muted small">Start from</span>
              <select
                className="input"
                value={template}
                onChange={(event) => setTemplate(event.target.value)}
                aria-label="Start from"
              >
                <option value="">Empty dashboard</option>
                {templates.data?.templates.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.name} ({item.widgets.length} widgets)
                  </option>
                ))}
              </select>
            </label>

            {template && templates.data && (
              <TemplateNote
                templates={templates.data}
                selected={template}
              />
            )}

            <button
              type="button"
              className="button"
              onClick={() => void handleCreate()}
              disabled={creating || !name.trim() || !datasetId}
            >
              {creating ? 'Creating…' : 'Create dashboard'}
            </button>
            {error && <ErrorState error={error} />}
          </div>
        )}
      </Card>

      <Card title="Your dashboards">
        {(dashboards.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No dashboards yet"
            hint="Create one above to pin the analytics you care about."
            testId="no-dashboards"
          />
        ) : (
          <div className="table-scroll">
            <table className="table" data-testid="dashboard-list">
              <thead>
                <tr>
                  <th scope="col">Dashboard</th>
                  <th scope="col">Widgets</th>
                  <th scope="col">Created</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {dashboards.data?.items.map((dashboard) => (
                  <tr key={dashboard.id}>
                    <td>
                      <Link
                        to={`/workspaces/${workspaceId}/projects/${projectId}/dashboards/${dashboard.id}`}
                      >
                        {dashboard.name}
                      </Link>
                      {dashboard.description && (
                        <p className="muted small">{dashboard.description}</p>
                      )}
                    </td>
                    <td className="muted">{dashboard.widget_count}</td>
                    <td className="muted">
                      {new Date(dashboard.created_at).toLocaleDateString()}
                    </td>
                    <td>
                      <div className="row">
                        <button
                          type="button"
                          className="button button--ghost"
                          onClick={() => void handleDuplicate(dashboard)}
                          disabled={busyId === dashboard.id}
                        >
                          Duplicate
                        </button>
                        <button
                          type="button"
                          className="button button--ghost"
                          onClick={() => setPendingDelete(dashboard)}
                          disabled={busyId === dashboard.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pendingDelete && (
        <ConfirmDialog
          title="Delete this dashboard?"
          message={`"${pendingDelete.name}" and all of its widgets will be removed. This cannot be undone.`}
          confirmLabel="Delete"
          onConfirm={() => void handleDelete(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}

/** Says which of a template's widgets this dataset cannot support, and why. */
function TemplateNote({
  templates,
  selected,
}: {
  templates: DashboardTemplateList;
  selected: string;
}) {
  const template = templates.templates.find((item) => item.key === selected);
  if (!template) return null;

  return (
    <div className="stack--narrow" data-testid="template-note">
      <p className="muted small">{template.description}</p>
      {template.unavailable.length > 0 && (
        <details>
          <summary className="muted small">
            {template.unavailable.length} widget(s) unavailable for this dataset
          </summary>
          <ul className="list">
            {template.unavailable.map((item) => (
              <li key={item.widget}>
                <strong>{item.widget}</strong> — {item.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
