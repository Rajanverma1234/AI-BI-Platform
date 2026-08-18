import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { deleteProject, getProject, updateProject } from '@/api/projects';
import { ResourceForm, type ResourcePayload } from '@/components/forms/ResourceForm';
import {
  Card,
  ConfirmDialog,
  ErrorState,
  Spinner,
  SuccessMessage,
} from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { Project } from '@/types/api';

export default function ProjectDetailPage() {
  const { workspaceId = '', projectId = '' } = useParams<{
    workspaceId: string;
    projectId: string;
  }>();
  const navigate = useNavigate();

  const load = useCallback(
    (signal: AbortSignal) => getProject(workspaceId, projectId, signal),
    [workspaceId, projectId],
  );
  const project = useAsync<Project>(load);

  const [editing, setEditing] = useState(false);
  const [editError, setEditError] = useState<Error | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<Error | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleUpdate(payload: ResourcePayload) {
    setEditError(null);
    setSaved(null);
    try {
      await updateProject(workspaceId, projectId, payload);
      setEditing(false);
      setSaved('Project updated.');
      project.reload();
    } catch (cause) {
      setEditError(cause instanceof Error ? cause : new Error(String(cause)));
      throw cause;
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteProject(workspaceId, projectId);
      navigate(`/workspaces/${workspaceId}`, { replace: true });
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause : new Error(String(cause)));
      setDeleting(false);
    }
  }

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/workspaces/${workspaceId}`}>← Back to workspace</Link>
        </p>
        {project.isLoading && <Spinner label="Loading project…" />}
        {project.error && <ErrorState error={project.error} onRetry={project.reload} />}
        {project.data && <h1>{project.data.name}</h1>}
        {saved && <SuccessMessage message={saved} />}
      </div>

      {project.data && (
        <Card
          title="Project details"
          actions={
            !editing && (
              <div className="row">
                <Link
                  className="button button--ghost"
                  to={`/workspaces/${workspaceId}/projects/${projectId}/dashboards`}
                >
                  Dashboards
                </Link>
                <Link className="button button--ghost" to={`/projects/${projectId}/datasets`}>
                  Datasets
                </Link>
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
              idPrefix="project-edit"
              initialValues={{
                name: project.data.name,
                slug: project.data.slug,
                description: project.data.description ?? '',
              }}
              submitLabel="Save changes"
              slugHint="Unique within this workspace."
              error={editError}
              onSubmit={handleUpdate}
              onCancel={() => {
                setEditing(false);
                setEditError(null);
              }}
            />
          ) : (
            <>
              <p className="muted">{project.data.description || 'No description yet.'}</p>
              <dl className="details">
                <div>
                  <dt>Slug</dt>
                  <dd>{project.data.slug}</dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{new Date(project.data.created_at).toLocaleDateString()}</dd>
                </div>
                <div>
                  <dt>Updated</dt>
                  <dd>{new Date(project.data.updated_at).toLocaleDateString()}</dd>
                </div>
              </dl>
            </>
          )}
        </Card>
      )}

      {confirmingDelete && (
        <ConfirmDialog
          title="Delete this project?"
          message="This cannot be undone."
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
