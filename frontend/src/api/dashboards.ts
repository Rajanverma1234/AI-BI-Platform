/** Dashboard builder endpoints. */

import { apiClient, withQuery } from '@/lib/apiClient';
import type {
  DashboardData,
  DashboardDetail,
  DashboardFilterOptions,
  DashboardListResponse,
  DashboardTemplateList,
  DashboardWidget,
  FilterSet,
  Report,
  ReportFileFormat,
  WidgetConfig,
  WidgetPosition,
} from '@/types/api';

function projectPath(projectId: string): string {
  return `/projects/${projectId}/dashboards`;
}

/** Refreshing resolves every widget, so allow more than the default timeout. */
const OPTIONS = { timeoutMs: 120_000 };

export function listDashboards(
  projectId: string,
  params: { page?: number; page_size?: number } = {},
  signal?: AbortSignal,
): Promise<DashboardListResponse> {
  return apiClient.get<DashboardListResponse>(
    withQuery(projectPath(projectId), params),
    signal ? { signal } : {},
  );
}

export function getDashboardTemplates(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<DashboardTemplateList> {
  return apiClient.get<DashboardTemplateList>(
    withQuery(`${projectPath(projectId)}/templates`, {
      dataset_id: datasetId,
      version_id: versionId,
    }),
    signal ? { signal } : {},
  );
}

export function createDashboard(
  projectId: string,
  body: {
    name: string;
    description?: string | null;
    dataset_id: string;
    dataset_version_id?: string | null;
    layout_columns?: number;
    template?: string | null;
  },
): Promise<DashboardDetail> {
  return apiClient.post<DashboardDetail>(projectPath(projectId), body, OPTIONS);
}

export function getDashboard(
  dashboardId: string,
  signal?: AbortSignal,
): Promise<DashboardDetail> {
  return apiClient.get<DashboardDetail>(
    `/dashboards/${dashboardId}`,
    signal ? { signal } : {},
  );
}

export interface DashboardPatch {
  name?: string;
  description?: string | null;
  layout_columns?: number;
  filters?: FilterSet | null;
  /** Moving version is always explicit; it never happens implicitly. */
  dataset_version_id?: string | null;
  clear_version?: boolean;
  layout?: { widget_id: string; position: WidgetPosition }[];
}

export function updateDashboard(
  dashboardId: string,
  body: DashboardPatch,
): Promise<DashboardDetail> {
  return apiClient.patch<DashboardDetail>(`/dashboards/${dashboardId}`, body);
}

export function duplicateDashboard(
  dashboardId: string,
  name?: string,
): Promise<DashboardDetail> {
  return apiClient.post<DashboardDetail>(`/dashboards/${dashboardId}/duplicate`, { name });
}

export function deleteDashboard(dashboardId: string): Promise<void> {
  return apiClient.delete<void>(`/dashboards/${dashboardId}`);
}

export function getDashboardFilters(
  dashboardId: string,
  signal?: AbortSignal,
): Promise<DashboardFilterOptions> {
  return apiClient.get<DashboardFilterOptions>(
    `/dashboards/${dashboardId}/filters`,
    signal ? { signal } : {},
  );
}

/**
 * Resolve widgets against the pinned dataset version.
 *
 * `filters` layers ad-hoc conditions over the saved ones without changing
 * them - that is how a chart click filters the rest of the dashboard.
 * `widget_ids` narrows the refresh to a single widget.
 */
export function refreshDashboard(
  dashboardId: string,
  body: { filters?: FilterSet | null; widget_ids?: string[] } = {},
): Promise<DashboardData> {
  return apiClient.post<DashboardData>(`/dashboards/${dashboardId}/refresh`, body, OPTIONS);
}

export function addWidget(
  dashboardId: string,
  body: { title: string; position?: WidgetPosition; configuration: WidgetConfig },
): Promise<DashboardWidget> {
  return apiClient.post<DashboardWidget>(`/dashboards/${dashboardId}/widgets`, body);
}

export function updateWidget(
  dashboardId: string,
  widgetId: string,
  body: { title?: string; position?: WidgetPosition; configuration?: WidgetConfig },
): Promise<DashboardWidget> {
  return apiClient.patch<DashboardWidget>(
    `/dashboards/${dashboardId}/widgets/${widgetId}`,
    body,
  );
}

export function deleteWidget(dashboardId: string, widgetId: string): Promise<void> {
  return apiClient.delete<void>(`/dashboards/${dashboardId}/widgets/${widgetId}`);
}

/** Exports through the existing report engine; download via the reports route. */
export function exportDashboard(
  dashboardId: string,
  fileFormat: ReportFileFormat,
): Promise<Report> {
  return apiClient.post<Report>(
    withQuery(`/dashboards/${dashboardId}/export`, { file_format: fileFormat }),
    {},
    OPTIONS,
  );
}
