/** Response shapes mirrored from the backend Pydantic schemas. */

export type ServiceStatus = 'ok' | 'degraded' | 'error';

export interface HealthResponse {
  status: ServiceStatus;
  service: string;
  version: string;
  environment: string;
}

export interface DependencyStatus {
  name: string;
  status: ServiceStatus;
  detail?: string | null;
}

export interface ReadinessResponse extends HealthResponse {
  dependencies: DependencyStatus[];
}

/** Canonical error envelope produced by the backend error handlers. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
  request_id?: string | null;
}
