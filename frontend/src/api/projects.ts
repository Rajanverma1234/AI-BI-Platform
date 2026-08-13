/** Project endpoints, always scoped to a workspace. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  Paginated,
  PaginationParams,
  Project,
  ProjectCreatePayload,
  ProjectUpdatePayload,
} from '@/types/api';

function basePath(workspaceId: string): string {
  return `/workspaces/${workspaceId}/projects`;
}

export function listProjects(
  workspaceId: string,
  params: PaginationParams = {},
  signal?: AbortSignal,
): Promise<Paginated<Project>> {
  return apiClient.get<Paginated<Project>>(
    withQuery(basePath(workspaceId), params),
    signal ? { signal } : {},
  );
}

export function getProject(
  workspaceId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<Project> {
  return apiClient.get<Project>(
    `${basePath(workspaceId)}/${projectId}`,
    signal ? { signal } : {},
  );
}

export function createProject(
  workspaceId: string,
  payload: ProjectCreatePayload,
): Promise<Project> {
  return apiClient.post<Project>(basePath(workspaceId), payload);
}

export function updateProject(
  workspaceId: string,
  projectId: string,
  payload: ProjectUpdatePayload,
): Promise<Project> {
  return apiClient.patch<Project>(`${basePath(workspaceId)}/${projectId}`, payload);
}

export function deleteProject(workspaceId: string, projectId: string): Promise<void> {
  return apiClient.delete<void>(`${basePath(workspaceId)}/${projectId}`);
}

/**
 * Look a project up by id alone.
 *
 * The dataset routes are addressed as /projects/:projectId/..., so the UI has
 * no workspace id to build the nested path from.
 */
export function getProjectById(projectId: string, signal?: AbortSignal): Promise<Project> {
  return apiClient.get<Project>(`/projects/${projectId}`, signal ? { signal } : {});
}
