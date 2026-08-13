/** Profiling, data-quality and cleaning endpoints for a dataset. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  CleaningApplyResponse,
  CleaningOperation,
  CleaningPreviewResponse,
  DataQualitySummary,
  DatasetProfile,
  DatasetVersionListResponse,
  PaginationParams,
} from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}`;
}

export function getDatasetProfile(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<DatasetProfile> {
  return apiClient.get<DatasetProfile>(
    withQuery(`${basePath(projectId, datasetId)}/profile`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export function getDatasetQuality(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<DataQualitySummary> {
  return apiClient.get<DataQualitySummary>(
    withQuery(`${basePath(projectId, datasetId)}/quality`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export function previewCleaning(
  projectId: string,
  datasetId: string,
  operations: CleaningOperation[],
  sourceVersionId?: string,
): Promise<CleaningPreviewResponse> {
  return apiClient.post<CleaningPreviewResponse>(`${basePath(projectId, datasetId)}/clean/preview`, {
    operations,
    source_version_id: sourceVersionId ?? null,
  });
}

export function applyCleaning(
  projectId: string,
  datasetId: string,
  operations: CleaningOperation[],
  options: { name?: string; sourceVersionId?: string } = {},
): Promise<CleaningApplyResponse> {
  return apiClient.post<CleaningApplyResponse>(`${basePath(projectId, datasetId)}/clean`, {
    operations,
    source_version_id: options.sourceVersionId ?? null,
    name: options.name ?? null,
  });
}

export function listDatasetVersions(
  projectId: string,
  datasetId: string,
  params: PaginationParams = {},
  signal?: AbortSignal,
): Promise<DatasetVersionListResponse> {
  return apiClient.get<DatasetVersionListResponse>(
    withQuery(`${basePath(projectId, datasetId)}/versions`, params),
    signal ? { signal } : {},
  );
}
