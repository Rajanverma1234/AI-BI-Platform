import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { createProject, listProjects } from '@/api/projects';
import { deleteWorkspace, getWorkspace, updateWorkspace } from '@/api/workspaces';
import { ResourceForm, type ResourcePayload } from '@/components/forms/ResourceForm';
import {
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Pagination,
  Spinner,
  SuccessMessage,
} from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { Paginated, Project, Workspace } from '@/types/api';

export default function WorkspaceDetailPage() {
  const { workspaceId = '' } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();

  const loadWorkspace = useCallback(
    (signal: AbortSignal) => getWorkspace(workspaceId, signal),
    [workspaceId],
  );
  const workspace = useAsync<Workspace>(loadWorkspace);

  const [page, setPage] = useState(1);
  const loadProjects = useCallback(
    (signal: AbortSignal) => listProjects(workspaceId, { page }, signal),
    [workspaceId, page],
  );
  const projects = useAsync<Paginated<Project>>(loadProjects);

  const [editing, setEditing] = useState(false);
  const [editError, setEditError] = useState<Error | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const [createError, setCreateError] = useState<Error | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<Error | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleUpdate(payload: ResourcePayload) {
    setEditError(null);
    setSaved(null);
    try {
      await updateWorkspace(workspaceId, payload);
      setEditing(false);
      setSaved('Workspace updated.');
      workspace.reload();
    } catch (cause) {
      setEditError(cause instanceof Error ? cause : new Error(String(cause)));
      throw cause;
    }
  }

  async function handleCreateProject(payload: ResourcePayload) {
    setCreateError(null);
    setCreated(null);
    try {
      const project = await createProject(workspaceId, payload);
      setCreated(`Project “${project.name}” created.`);
      if (page === 1) projects.reload();
      else setPage(1);
    } catch (cause) {
      setCreateError(cause instanceof Error ? cause : new Error(String(cause)));
      throw cause;
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteWorkspace(workspaceId);
      // Deleting cascades to the projects, so there is nothing left to show.
      navigate('/workspaces', { replace: true });
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause : new Error(String(cause)));
      setDeleting(false);
    }
  }

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to="/workspaces">← Workspaces</Link>
        </p>
        {workspace.isLoading && <Spinner label="Loading workspace…" />}
        {workspace.error && <ErrorState error={workspace.error} onRetry={workspace.reload} />}
        {workspace.data && (
          <>
            <h1>{workspace.data.name}</h1>
            <p className="muted">
              <code>{workspace.data.slug}</code>
              {workspace.data.description ? ` · ${workspace.data.description}` : ''}
            </p>
          </>
        )}
        {saved && <SuccessMessage message={saved} />}
      </div>

      {workspace.data && (
        <Card
          title="Workspace settings"
          actions={
            !editing && (
              <div className="row">
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => {
                    setSaved(null);
                    setEditing(true);
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="button button--danger"
                  onClick={() => setConfirmingDelete(true)}
                >
                  Delete
                </button>
              </div>
            )
          }
        >
          {editing ? (
            <ResourceForm
              idPrefix="workspace-edit"
              initialValues={{
                name: workspace.data.name,
                slug: workspace.data.slug,
                description: workspace.data.description ?? '',
              }}
              submitLabel="Save changes"
              error={editError}
              onSubmit={handleUpdate}
              onCancel={() => {
                setEditing(false);
                setEditError(null);
              }}
            />
          ) : (
            <dl className="details">
              <div>
                <dt>Slug</dt>
                <dd>{workspace.data.slug}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{new Date(workspace.data.created_at).toLocaleDateString()}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{new Date(workspace.data.updated_at).toLocaleDateString()}</dd>
              </div>
            </dl>
          )}
        </Card>
      )}

      <Card title="Projects">
        {projects.isLoading && <Spinner label="Loading projects…" />}
        {!projects.isLoading && projects.error && (
          <ErrorState error={projects.error} onRetry={projects.reload} />
        )}
        {!projects.isLoading && !projects.error && projects.data?.items.length === 0 && (
          <EmptyState
            title="No projects in this workspace yet"
            hint="Add one below."
            testId="projects-empty"
          />
        )}
        {!projects.isLoading && !projects.error && projects.data &&
          projects.data.items.length > 0 && (
            <>
              <ul className="list list--plain" data-testid="project-list">
                {projects.data.items.map((project) => (
                  <li key={project.id} className="row row--between">
                    <Link to={`/workspaces/${workspaceId}/projects/${project.id}`}>
                      {project.name}
                    </Link>
                    <span className="muted small">{project.slug}</span>
                  </li>
                ))}
              </ul>
              <Pagination
                page={projects.data.page}
                totalPages={projects.data.total_pages}
                total={projects.data.total}
                hasNext={projects.data.has_next}
                hasPrevious={projects.data.has_previous}
                onPageChange={setPage}
              />
            </>
          )}
      </Card>

      <Card title="New project">
        <ResourceForm
          idPrefix="project"
          submitLabel="Create project"
          busyLabel="Creating…"
          error={createError}
          successMessage={created}
          onSubmit={handleCreateProject}
          resetOnSuccess
        />
      </Card>

      {confirmingDelete && (
        <ConfirmDialog
          title="Delete this workspace?"
          message="Its projects are deleted with it. This cannot be undone."
          error={deleteError}
          busy={deleting}
          onConfirm={handleDelete}
          onCancel={() => {
            setConfirmingDelete(false);
            setDeleteError(null);
          }}
        />
      )}
    </div>
  );
}
