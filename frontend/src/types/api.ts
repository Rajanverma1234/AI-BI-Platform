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

// --- Authentication ---------------------------------------------------------

/** Public user shape. The backend never sends a password hash. */
export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  /** Seconds until expiry. */
  expires_in: number;
}

export interface RegisterPayload {
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

// --- Pagination -------------------------------------------------------------

/** Envelope returned by every paginated list endpoint. */
export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface PaginationParams {
  page?: number;
  page_size?: number;
}

// --- Workspaces and projects ------------------------------------------------

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  owner_id: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  workspace_id: string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceCreatePayload {
  name: string;
  slug?: string;
  description?: string;
}

/** PATCH accepts any subset; omitted fields are left unchanged. */
export type WorkspaceUpdatePayload = Partial<WorkspaceCreatePayload>;

export interface ProjectCreatePayload {
  name: string;
  slug?: string;
  description?: string;
}

export type ProjectUpdatePayload = Partial<ProjectCreatePayload>;

// --- Datasets ---------------------------------------------------------------

/** Lifecycle of an uploaded dataset, mirroring the backend enum. */
export type DatasetStatus = 'uploading' | 'processing' | 'ready' | 'failed';

export type DatasetFileType = 'csv' | 'xlsx';

/** One column detected while processing the file. */
export interface DatasetColumn {
  name: string;
  dtype: 'integer' | 'float' | 'boolean' | 'datetime' | 'string';
  nullable: boolean;
}

export interface Dataset {
  id: string;
  project_id: string;
  name: string;
  original_filename: string;
  file_type: DatasetFileType;
  file_size: number;
  status: DatasetStatus;
  row_count: number | null;
  column_count: number | null;
  columns: DatasetColumn[] | null;
  /** Safe, user-facing reason; present only when status is "failed". */
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/** Structural summary shown on the dataset detail screen. */
export interface DatasetMetadata {
  original_filename: string;
  file_type: DatasetFileType;
  file_size: number;
  row_count: number | null;
  column_count: number | null;
  columns: DatasetColumn[];
}

export type DatasetListResponse = Paginated<Dataset>;

/** The upload endpoint returns the created dataset with its final status. */
export type DatasetUploadResponse = Dataset;

// --- Profiling and data quality ---------------------------------------------

/** Normalised column type vocabulary shared by profiling and cleaning. */
export type DetectedType = 'integer' | 'float' | 'boolean' | 'datetime' | 'string' | 'empty';

export interface NumericStats {
  minimum: number | null;
  maximum: number | null;
  mean: number | null;
  median: number | null;
  std_dev: number | null;
  sum: number | null;
  percentile_25: number | null;
  percentile_50: number | null;
  percentile_75: number | null;
}

export interface ValueCount {
  value: string;
  count: number;
  percentage: number;
}

export interface CategoricalStats {
  unique_count: number;
  most_frequent_value: string | null;
  most_frequent_count: number | null;
  most_frequent_percentage: number | null;
  top_values: ValueCount[];
}

export interface DateTimeStats {
  minimum: string | null;
  maximum: string | null;
  unique_count: number;
  missing_count: number;
}

export interface ColumnProfile {
  column_name: string;
  detected_data_type: DetectedType;
  null_count: number;
  null_percentage: number;
  non_null_count: number;
  unique_count: number;
  unique_percentage: number;
  numeric: NumericStats | null;
  categorical: CategoricalStats | null;
  datetime_stats: DateTimeStats | null;
}

export interface DatasetProfile {
  dataset_id: string;
  version_id: string | null;
  row_count: number;
  column_count: number;
  duplicate_row_count: number;
  duplicate_row_percentage: number;
  missing_cell_count: number;
  missing_cell_percentage: number;
  columns: ColumnProfile[];
}

export type QualityStatus = 'good' | 'warning' | 'critical';
export type QualitySeverity = 'info' | 'warning' | 'critical';

export type QualityIssueType =
  | 'missing_values'
  | 'duplicate_rows'
  | 'empty_column'
  | 'high_missing'
  | 'constant_column'
  | 'mixed_types'
  | 'suspicious_values'
  | 'possible_wrong_type';

export interface DataQualityIssue {
  issue_type: QualityIssueType;
  severity: QualitySeverity;
  column: string | null;
  message: string;
  affected_rows: number;
  affected_percentage: number;
  suggested_operations: string[];
}

export interface DataQualitySummary {
  dataset_id: string;
  version_id: string | null;
  status: QualityStatus;
  score: number;
  total_issues: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  issues: DataQualityIssue[];
  rules: string[];
}

// --- Cleaning pipeline ------------------------------------------------------

export type MissingStrategy =
  | 'mean'
  | 'median'
  | 'mode'
  | 'forward_fill'
  | 'backward_fill'
  | 'custom';

export type OutlierMethod = 'iqr' | 'zscore';
export type OutlierAction = 'remove' | 'cap';
export type ConvertibleType = 'string' | 'integer' | 'float' | 'boolean' | 'date' | 'datetime';

/** Discriminated union mirroring the backend operation schemas. */
export type CleaningOperation =
  | { operation: 'fill_missing'; column: string; strategy: MissingStrategy; value?: string | number | boolean | null }
  | { operation: 'drop_missing_rows'; column?: string | null }
  | { operation: 'remove_duplicates'; subset?: string[] | null }
  | { operation: 'convert_type'; column: string; to_type: ConvertibleType; errors_to_null?: boolean }
  | { operation: 'rename_column'; column: string; new_name: string }
  | { operation: 'drop_column'; column: string }
  | { operation: 'reorder_columns'; order: string[] }
  | {
      operation: 'handle_outliers';
      column: string;
      method: OutlierMethod;
      action: OutlierAction;
      threshold: number;
    };

export interface TypeChange {
  column: string;
  before: DetectedType;
  after: DetectedType;
}

export interface OperationOutcome {
  index: number;
  operation: string;
  column: string | null;
  rows_affected: number;
  warning: string | null;
}

export interface CleaningPreviewResponse {
  dataset_id: string;
  source_version_id: string | null;
  original_row_count: number;
  cleaned_row_count: number;
  original_column_count: number;
  cleaned_column_count: number;
  missing_cells_before: number;
  missing_cells_after: number;
  duplicate_rows_before: number;
  duplicate_rows_after: number;
  rows_removed: number;
  affected_columns: string[];
  type_changes: TypeChange[];
  operations: OperationOutcome[];
  warnings: string[];
  sample_rows: Record<string, unknown>[];
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  source_version_id: string | null;
  version_number: number;
  name: string;
  file_size: number;
  row_count: number;
  column_count: number;
  columns: DatasetColumn[] | null;
  operations: CleaningOperation[];
  created_at: string;
  updated_at: string;
}

export type DatasetVersionListResponse = Paginated<DatasetVersion>;

export interface CleaningApplyResponse {
  version: DatasetVersion;
  preview: CleaningPreviewResponse;
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
