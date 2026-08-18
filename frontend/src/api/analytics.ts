/** KPI and business-analytics endpoints for a dataset. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  AbcResponse,
  AnalyticsEnvelope,
  ContributionResponse,
  DistributionResponse,
  EntityResponse,
  FilterSet,
  GrowthResponse,
  KpiCalculateResponse,
  KpiCatalogResponse,
  KpiDefinition,
  MetricType,
  SegmentResponse,
  SortDirection,
  TimePeriod,
  TimeSeriesResponse,
} from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}/analytics`;
}

export function getKpiCatalog(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<KpiCatalogResponse> {
  return apiClient.get<KpiCatalogResponse>(
    withQuery(`${basePath(projectId, datasetId)}/kpis`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export function calculateKpis(
  projectId: string,
  datasetId: string,
  kpis: KpiDefinition[],
  versionId?: string,
): Promise<KpiCalculateResponse> {
  return apiClient.post<KpiCalculateResponse>(`${basePath(projectId, datasetId)}/kpis/calculate`, {
    kpis,
    version_id: versionId ?? null,
  });
}

export interface TimeSeriesParams {
  date_column: string;
  period: TimePeriod;
  metric: MetricType;
  column?: string | null;
  group_by?: string | null;
  filters?: FilterSet | null;
  version_id?: string | null;
}

export function getTimeSeries(
  projectId: string,
  datasetId: string,
  params: TimeSeriesParams,
): Promise<AnalyticsEnvelope<TimeSeriesResponse>> {
  return apiClient.post<AnalyticsEnvelope<TimeSeriesResponse>>(
    `${basePath(projectId, datasetId)}/time-series`,
    params,
  );
}

export function getGrowth(
  projectId: string,
  datasetId: string,
  params: Omit<TimeSeriesParams, 'group_by'>,
): Promise<AnalyticsEnvelope<GrowthResponse>> {
  return apiClient.post<AnalyticsEnvelope<GrowthResponse>>(
    `${basePath(projectId, datasetId)}/growth`,
    params,
  );
}

export interface SegmentParams {
  dimension: string;
  metric: MetricType;
  column?: string | null;
  sort?: SortDirection;
  limit?: number;
  filters?: FilterSet | null;
  version_id?: string | null;
}

export function getSegment(
  projectId: string,
  datasetId: string,
  params: SegmentParams,
): Promise<AnalyticsEnvelope<SegmentResponse>> {
  return apiClient.post<AnalyticsEnvelope<SegmentResponse>>(
    `${basePath(projectId, datasetId)}/segment`,
    params,
  );
}

export function getRanking(
  projectId: string,
  datasetId: string,
  params: SegmentParams,
): Promise<AnalyticsEnvelope<SegmentResponse>> {
  return apiClient.post<AnalyticsEnvelope<SegmentResponse>>(
    `${basePath(projectId, datasetId)}/ranking`,
    params,
  );
}

export function getContribution(
  projectId: string,
  datasetId: string,
  params: SegmentParams,
): Promise<AnalyticsEnvelope<ContributionResponse>> {
  return apiClient.post<AnalyticsEnvelope<ContributionResponse>>(
    `${basePath(projectId, datasetId)}/contribution`,
    params,
  );
}

export interface AbcParams extends SegmentParams {
  a_threshold?: number;
  b_threshold?: number;
}

export function getAbcAnalysis(
  projectId: string,
  datasetId: string,
  params: AbcParams,
): Promise<AnalyticsEnvelope<AbcResponse>> {
  return apiClient.post<AnalyticsEnvelope<AbcResponse>>(
    `${basePath(projectId, datasetId)}/abc-analysis`,
    params,
  );
}

export interface EntityParams {
  entity_column: string;
  value_column?: string | null;
  transaction_column?: string | null;
  limit?: number;
  filters?: FilterSet | null;
  version_id?: string | null;
}

export function getEntityAnalysis(
  projectId: string,
  datasetId: string,
  params: EntityParams,
): Promise<AnalyticsEnvelope<EntityResponse>> {
  return apiClient.post<AnalyticsEnvelope<EntityResponse>>(
    `${basePath(projectId, datasetId)}/entity-analysis`,
    params,
  );
}

export function getDistribution(
  projectId: string,
  datasetId: string,
  params: { column: string; bins?: number; filters?: FilterSet | null; version_id?: string | null },
): Promise<AnalyticsEnvelope<DistributionResponse>> {
  return apiClient.post<AnalyticsEnvelope<DistributionResponse>>(
    `${basePath(projectId, datasetId)}/distribution`,
    params,
  );
}
