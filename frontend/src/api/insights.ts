/** AI insights and recommendations endpoints. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type { InsightReport, InsightRunDetail, InsightRunListResponse } from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}/insights`;
}

/** Generating insights runs the full analytics pipeline, so allow ample time. */
const OPTIONS = { timeoutMs: 180_000 };

export function generateInsights(
  projectId: string,
  datasetId: string,
  body: { version_id?: string | null; include_ai?: boolean; persist?: boolean } = {},
): Promise<InsightReport> {
  return apiClient.post<InsightReport>(basePath(projectId, datasetId), body, OPTIONS);
}

/**
 * The most recent stored run, or null if nothing has been generated.
 *
 * The report carries `stale` when it was produced for a different version or
 * by older detection rules, so the page can say so rather than mislead.
 */
export function getLatestInsights(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<InsightRunDetail | null> {
  return apiClient.get<InsightRunDetail | null>(
    withQuery(`${basePath(projectId, datasetId)}/latest`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export function listInsightRuns(
  projectId: string,
  datasetId: string,
  params: { page?: number; page_size?: number } = {},
  signal?: AbortSignal,
): Promise<InsightRunListResponse> {
  return apiClient.get<InsightRunListResponse>(
    withQuery(basePath(projectId, datasetId), params),
    signal ? { signal } : {},
  );
}

export function getInsightRun(runId: string, signal?: AbortSignal): Promise<InsightRunDetail> {
  return apiClient.get<InsightRunDetail>(`/insights/${runId}`, signal ? { signal } : {});
}

/** Re-runs the analysis and records a new run; the old one is kept. */
export function refreshInsightRun(
  runId: string,
  body: { include_ai?: boolean } = {},
): Promise<InsightRunDetail> {
  return apiClient.post<InsightRunDetail>(`/insights/${runId}/refresh`, body, OPTIONS);
}
