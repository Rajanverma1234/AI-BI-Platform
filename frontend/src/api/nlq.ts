/** Natural-language query endpoints. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  NlqResponse,
  PaginationParams,
  QueryContextTurn,
  QueryHistoryResponse,
  QuerySuggestionsResponse,
} from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}/nlq`;
}

export function askQuestion(
  projectId: string,
  datasetId: string,
  question: string,
  options: { versionId?: string; context?: QueryContextTurn[] } = {},
): Promise<NlqResponse> {
  return apiClient.post<NlqResponse>(
    basePath(projectId, datasetId),
    {
      question,
      version_id: options.versionId ?? null,
      context: options.context ?? [],
    },
    // Planning plus execution can take longer than the default timeout.
    { timeoutMs: 120_000 },
  );
}

export function getQueryHistory(
  projectId: string,
  datasetId: string,
  params: PaginationParams = {},
  signal?: AbortSignal,
): Promise<QueryHistoryResponse> {
  return apiClient.get<QueryHistoryResponse>(
    withQuery(`${basePath(projectId, datasetId)}/history`, params),
    signal ? { signal } : {},
  );
}

export function getQuerySuggestions(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<QuerySuggestionsResponse> {
  return apiClient.get<QuerySuggestionsResponse>(
    withQuery(`${basePath(projectId, datasetId)}/suggestions`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}
