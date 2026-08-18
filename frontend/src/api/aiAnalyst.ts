/** AI analyst endpoints. */

import { apiClient } from '@/lib/apiClient';
import type { AnalystAnswer, AnalystReport } from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}/ai-analyst`;
}

export function analyzeDataset(
  projectId: string,
  datasetId: string,
  options: { versionId?: string; includeAi?: boolean; refresh?: boolean } = {},
): Promise<AnalystReport> {
  return apiClient.post<AnalystReport>(
    `${basePath(projectId, datasetId)}/analyze`,
    {
      version_id: options.versionId ?? null,
      include_ai: options.includeAi ?? true,
      refresh: options.refresh ?? false,
    },
    // Analysis runs the full pipeline, so allow more than the default timeout.
    { timeoutMs: 120_000 },
  );
}

export function askAnalyst(
  projectId: string,
  datasetId: string,
  question: string,
  versionId?: string,
): Promise<AnalystAnswer> {
  return apiClient.post<AnalystAnswer>(
    `${basePath(projectId, datasetId)}/ask`,
    { question, version_id: versionId ?? null },
    { timeoutMs: 120_000 },
  );
}
