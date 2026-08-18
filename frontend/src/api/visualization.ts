/** Preview, query, chart and EDA endpoints for a dataset. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  ChartConfig,
  ChartDataResponse,
  ChartSuggestionsResponse,
  CorrelationResponse,
  DataPreviewResponse,
  EdaSummaryResponse,
  QueryRequest,
  QueryResponse,
} from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}`;
}

export function previewRows(
  projectId: string,
  datasetId: string,
  params: { page?: number; page_size?: number; version_id?: string } = {},
  signal?: AbortSignal,
): Promise<DataPreviewResponse> {
  return apiClient.get<DataPreviewResponse>(
    withQuery(`${basePath(projectId, datasetId)}/preview`, params),
    signal ? { signal } : {},
  );
}

export function runQuery(
  projectId: string,
  datasetId: string,
  request: QueryRequest,
): Promise<QueryResponse> {
  return apiClient.post<QueryResponse>(`${basePath(projectId, datasetId)}/query`, request);
}

export function buildChart(
  projectId: string,
  datasetId: string,
  config: ChartConfig,
): Promise<ChartDataResponse> {
  return apiClient.post<ChartDataResponse>(`${basePath(projectId, datasetId)}/chart`, config);
}

export function getEdaSummary(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<EdaSummaryResponse> {
  return apiClient.get<EdaSummaryResponse>(
    withQuery(`${basePath(projectId, datasetId)}/eda`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export function getCorrelation(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<CorrelationResponse> {
  return apiClient.get<CorrelationResponse>(
    withQuery(`${basePath(projectId, datasetId)}/correlation`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export function getChartSuggestions(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<ChartSuggestionsResponse> {
  return apiClient.get<ChartSuggestionsResponse>(
    withQuery(`${basePath(projectId, datasetId)}/chart-suggestions`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}
