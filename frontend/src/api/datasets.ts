/** Dataset endpoints, scoped to a project. */

import { apiClient, uploadFile, withQuery } from '@/lib/apiClient';
import type {
  Dataset,
  DatasetListResponse,
  DatasetUploadResponse,
  PaginationParams,
} from '@/types/api';

function basePath(projectId: string): string {
  return `/projects/${projectId}/datasets`;
}

export function listDatasets(
  projectId: string,
  params: PaginationParams = {},
  signal?: AbortSignal,
): Promise<DatasetListResponse> {
  return apiClient.get<DatasetListResponse>(
    withQuery(basePath(projectId), params),
    signal ? { signal } : {},
  );
}

export function getDataset(
  projectId: string,
  datasetId: string,
  signal?: AbortSignal,
): Promise<Dataset> {
  return apiClient.get<Dataset>(
    `${basePath(projectId)}/${datasetId}`,
    signal ? { signal } : {},
  );
}

export interface UploadOptions {
  /** 0-100; reported while the request body is being sent. */
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}

export function uploadDataset(
  projectId: string,
  file: File,
  name?: string,
  options: UploadOptions = {},
): Promise<DatasetUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  if (name?.trim()) form.append('name', name.trim());

  return uploadFile<DatasetUploadResponse>(basePath(projectId), form, options);
}

/** Re-upload: replaces the stored file, keeping the dataset id and name. */
export function replaceDatasetFile(
  projectId: string,
  datasetId: string,
  file: File,
  options: UploadOptions = {},
): Promise<Dataset> {
  const form = new FormData();
  form.append('file', file);

  return uploadFile<Dataset>(`${basePath(projectId)}/${datasetId}`, form, {
    ...options,
    method: 'PUT',
  });
}

export function deleteDataset(projectId: string, datasetId: string): Promise<void> {
  return apiClient.delete<void>(`${basePath(projectId)}/${datasetId}`);
}
