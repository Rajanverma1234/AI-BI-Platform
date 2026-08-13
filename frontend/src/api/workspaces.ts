/** Workspace endpoints. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  Paginated,
  PaginationParams,
  Workspace,
  WorkspaceCreatePayload,
  WorkspaceUpdatePayload,
} from '@/types/api';

export function listWorkspaces(
  params: PaginationParams = {},
  signal?: AbortSignal,
): Promise<Paginated<Workspace>> {
  return apiClient.get<Paginated<Workspace>>(
    withQuery('/workspaces', params),
    signal ? { signal } : {},
  );
}

export function getWorkspace(workspaceId: string, signal?: AbortSignal): Promise<Workspace> {
  return apiClient.get<Workspace>(`/workspaces/${workspaceId}`, signal ? { signal } : {});
}

export function createWorkspace(payload: WorkspaceCreatePayload): Promise<Workspace> {
  return apiClient.post<Workspace>('/workspaces', payload);
}

export function updateWorkspace(
  workspaceId: string,
  payload: WorkspaceUpdatePayload,
): Promise<Workspace> {
  return apiClient.patch<Workspace>(`/workspaces/${workspaceId}`, payload);
}

export function deleteWorkspace(workspaceId: string): Promise<void> {
  return apiClient.delete<void>(`/workspaces/${workspaceId}`);
}
