/** Advanced analytics endpoints. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  AdvancedCapabilities,
  ChurnResponse,
  CohortResponse,
  ForecastMethod,
  ForecastResponse,
  MetricType,
  OutlierResponse,
  ParetoResponse,
  RfmResponse,
  SegmentationResponse,
  TimePeriod,
} from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}/analytics`;
}

/** Advanced analyses can take longer than the default client timeout. */
const OPTIONS = { timeoutMs: 120_000 };

export function getCapabilities(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<AdvancedCapabilities> {
  return apiClient.get<AdvancedCapabilities>(
    withQuery(`${basePath(projectId, datasetId)}/capabilities`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export function runRfm(
  projectId: string,
  datasetId: string,
  body: {
    version_id?: string | null;
    customer_column?: string | null;
    date_column?: string | null;
    monetary_column?: string | null;
    segment?: string | null;
  },
): Promise<RfmResponse> {
  return apiClient.post<RfmResponse>(`${basePath(projectId, datasetId)}/rfm`, body, OPTIONS);
}

export function runSegmentation(
  projectId: string,
  datasetId: string,
  body: {
    version_id?: string | null;
    feature_columns?: string[];
    entity_column?: string | null;
    clusters?: number;
    standardize?: boolean;
  },
): Promise<SegmentationResponse> {
  return apiClient.post<SegmentationResponse>(
    `${basePath(projectId, datasetId)}/segmentation`,
    body,
    OPTIONS,
  );
}

export function runCohort(
  projectId: string,
  datasetId: string,
  body: {
    version_id?: string | null;
    customer_column?: string | null;
    date_column?: string | null;
    period?: TimePeriod;
    max_periods?: number;
  },
): Promise<CohortResponse> {
  return apiClient.post<CohortResponse>(`${basePath(projectId, datasetId)}/cohort`, body, OPTIONS);
}

export function runChurn(
  projectId: string,
  datasetId: string,
  body: {
    version_id?: string | null;
    customer_column?: string | null;
    date_column?: string | null;
    churn_days?: number;
    at_risk_days?: number;
  },
): Promise<ChurnResponse> {
  return apiClient.post<ChurnResponse>(`${basePath(projectId, datasetId)}/churn`, body, OPTIONS);
}

export function runForecast(
  projectId: string,
  datasetId: string,
  body: {
    version_id?: string | null;
    date_column?: string | null;
    metric_column?: string | null;
    period?: TimePeriod;
    horizon?: number;
    method?: ForecastMethod;
  },
): Promise<ForecastResponse> {
  return apiClient.post<ForecastResponse>(
    `${basePath(projectId, datasetId)}/forecast`,
    body,
    OPTIONS,
  );
}

export function runOutliers(
  projectId: string,
  datasetId: string,
  body: { version_id?: string | null; column: string; method?: string; threshold?: number },
): Promise<OutlierResponse> {
  return apiClient.post<OutlierResponse>(
    `${basePath(projectId, datasetId)}/outliers`,
    body,
    OPTIONS,
  );
}

export function runPareto(
  projectId: string,
  datasetId: string,
  body: {
    version_id?: string | null;
    dimension: string;
    metric?: MetricType;
    column?: string | null;
    threshold?: number;
  },
): Promise<ParetoResponse> {
  return apiClient.post<ParetoResponse>(`${basePath(projectId, datasetId)}/pareto`, body, OPTIONS);
}
