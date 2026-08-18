/** Report generation and export endpoints. */

import { apiClient, download, withQuery } from '@/lib/apiClient';
import type { DownloadedFile } from '@/lib/apiClient';
import type {
  Report,
  ReportData,
  ReportFileFormat,
  ReportListResponse,
  ReportOptions,
  ReportSectionKey,
  ReportTemplateName,
} from '@/types/api';

function basePath(projectId: string, datasetId: string): string {
  return `/projects/${projectId}/datasets/${datasetId}/reports`;
}

/** Building a report runs the full analysis pipeline, so allow generous time. */
const OPTIONS = { timeoutMs: 180_000 };

export function getReportOptions(
  projectId: string,
  datasetId: string,
  versionId?: string,
  signal?: AbortSignal,
): Promise<ReportOptions> {
  return apiClient.get<ReportOptions>(
    withQuery(`${basePath(projectId, datasetId)}/options`, { version_id: versionId }),
    signal ? { signal } : {},
  );
}

export interface ReportRequestBody {
  version_id?: string | null;
  template: ReportTemplateName;
  sections?: ReportSectionKey[] | null;
  title?: string | null;
  include_ai?: boolean;
}

export function previewReport(
  projectId: string,
  datasetId: string,
  body: ReportRequestBody,
): Promise<ReportData> {
  return apiClient.post<ReportData>(`${basePath(projectId, datasetId)}/preview`, body, OPTIONS);
}

export function generateReport(
  projectId: string,
  datasetId: string,
  body: ReportRequestBody & { file_format: ReportFileFormat; name?: string | null },
): Promise<Report> {
  return apiClient.post<Report>(basePath(projectId, datasetId), body, OPTIONS);
}

export function listReports(
  projectId: string,
  datasetId: string,
  params: { page?: number; page_size?: number } = {},
  signal?: AbortSignal,
): Promise<ReportListResponse> {
  return apiClient.get<ReportListResponse>(
    withQuery(basePath(projectId, datasetId), params),
    signal ? { signal } : {},
  );
}

/**
 * Fetch the rendered file as a blob.
 *
 * The download route needs the bearer token, so it cannot be a plain link -
 * the caller passes the result to `saveBlob`.
 */
export function downloadReport(
  projectId: string,
  datasetId: string,
  report: Pick<Report, 'id' | 'name' | 'file_format'>,
): Promise<DownloadedFile> {
  return download(
    `${basePath(projectId, datasetId)}/${report.id}/download`,
    `${report.name}.${report.file_format}`,
  );
}

export function deleteReport(
  projectId: string,
  datasetId: string,
  reportId: string,
): Promise<void> {
  return apiClient.delete<void>(`${basePath(projectId, datasetId)}/${reportId}`);
}
