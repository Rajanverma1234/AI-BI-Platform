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

// --- Visualization and EDA --------------------------------------------------

export type FilterOperator =
  | 'equals'
  | 'not_equals'
  | 'contains'
  | 'greater_than'
  | 'less_than'
  | 'greater_or_equal'
  | 'less_or_equal'
  | 'between'
  | 'is_null'
  | 'is_not_null';

export type FilterLogic = 'and' | 'or';
export type Aggregation = 'count' | 'sum' | 'mean' | 'median' | 'min' | 'max';

export type ChartType =
  | 'bar'
  | 'line'
  | 'area'
  | 'pie'
  | 'donut'
  | 'scatter'
  | 'histogram'
  | 'box';

export interface FilterCondition {
  column: string;
  operator: FilterOperator;
  value?: string | number | boolean | null;
  value_to?: string | number | null;
}

export interface FilterSet {
  logic: FilterLogic;
  conditions: FilterCondition[];
}

export interface PreviewColumn {
  name: string;
  dtype: DetectedType;
}

export interface DataPreviewResponse {
  dataset_id: string;
  version_id: string | null;
  columns: PreviewColumn[];
  rows: Record<string, unknown>[];
  total_rows: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface AggregationSpec {
  column: string;
  aggregation: Aggregation;
  alias?: string | null;
}

export interface QueryRequest {
  version_id?: string | null;
  filters?: FilterSet | null;
  group_by?: string[];
  aggregations?: AggregationSpec[];
  columns?: string[];
  sort_by?: string | null;
  sort_desc?: boolean;
  limit?: number;
}

export interface QueryResponse {
  dataset_id: string;
  version_id: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  total_matched: number;
  truncated: boolean;
}

/** Reusable chart definition; extensible for future dashboards. */
export interface ChartConfig {
  version_id?: string | null;
  chart_type: ChartType;
  x_column?: string | null;
  y_column?: string | null;
  group_by?: string | null;
  aggregation?: Aggregation;
  filters?: FilterSet | null;
  title?: string | null;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
  bins?: number;
  max_categories?: number;
}

export interface ChartSeries {
  name: string;
  data: (number | null)[];
}

export interface ScatterPoint {
  x: number;
  y: number;
}

export interface BoxPlotStats {
  label: string;
  minimum: number;
  q1: number;
  median: number;
  q3: number;
  maximum: number;
  outlier_count: number;
}

export interface ChartDataResponse {
  chart_type: ChartType;
  title: string | null;
  x_axis: string | null;
  y_axis: string | null;
  labels: string[];
  series: ChartSeries[];
  points: ScatterPoint[];
  boxes: BoxPlotStats[];
  metadata: Record<string, unknown>;
}

export interface NumericSummary {
  column: string;
  mean: number | null;
  median: number | null;
  minimum: number | null;
  maximum: number | null;
  std_dev: number | null;
}

export interface CategoricalSummary {
  column: string;
  unique_count: number;
  top_values: { value: string; count: number; percentage: number }[];
}

export interface DateSummary {
  column: string;
  minimum: string | null;
  maximum: string | null;
  range_days: number | null;
}

export interface EdaSummaryResponse {
  dataset_id: string;
  version_id: string | null;
  row_count: number;
  numeric: NumericSummary[];
  categorical: CategoricalSummary[];
  dates: DateSummary[];
}

export interface CorrelationResponse {
  dataset_id: string;
  version_id: string | null;
  method: string;
  columns: string[];
  matrix: (number | null)[][];
  excluded: { column: string; reason: string }[];
  message: string | null;
}

export interface ChartSuggestion {
  chart_type: ChartType;
  title: string;
  reason: string;
  config: ChartConfig;
}

export interface ChartSuggestionsResponse {
  dataset_id: string;
  version_id: string | null;
  suggestions: ChartSuggestion[];
}

// --- KPI and business analytics ---------------------------------------------

export type MetricType =
  | 'count'
  | 'distinct_count'
  | 'sum'
  | 'average'
  | 'median'
  | 'min'
  | 'max'
  | 'range'
  | 'std_dev';

export type TimePeriod = 'day' | 'week' | 'month' | 'quarter' | 'year';
export type SortDirection = 'asc' | 'desc';
export type ValueFormat = 'number' | 'integer' | 'currency' | 'percent';

export interface KpiFormat {
  style: ValueFormat;
  decimals: number;
  prefix?: string | null;
  suffix?: string | null;
}

/** Controlled formula tree — no strings are parsed or evaluated. */
export type FormulaNode =
  | { node: 'metric'; metric: MetricType; column?: string | null; filters?: FilterSet | null }
  | { node: 'constant'; value: number }
  | {
      node: 'binary';
      operator: 'add' | 'subtract' | 'multiply' | 'divide';
      left: FormulaNode;
      right: FormulaNode;
    };

export interface ComparisonSpec {
  date_column: string;
  period: TimePeriod;
}

export interface KpiDefinition {
  name: string;
  description?: string | null;
  metric?: MetricType | null;
  column?: string | null;
  filters?: FilterSet | null;
  group_by?: string | null;
  formula?: FormulaNode | null;
  format: KpiFormat;
  comparison?: ComparisonSpec | null;
}

export interface KpiComparison {
  period: TimePeriod;
  current_label: string | null;
  previous_label: string | null;
  previous_value: number | null;
  absolute_change: number | null;
  percentage_change: number | null;
}

export interface KpiResult {
  name: string;
  description: string | null;
  value: number | null;
  available: boolean;
  reason: string | null;
  metric: MetricType | null;
  column: string | null;
  format: KpiFormat;
  comparison: KpiComparison | null;
  groups: { group: string; value: number | null }[];
}

export interface KpiCalculateResponse {
  dataset_id: string;
  version_id: string | null;
  row_count: number;
  results: KpiResult[];
}

export interface ColumnRole {
  name: string;
  dtype: string;
  /** Numeric in type — an id column is numeric too, so prefer `measure`. */
  numeric: boolean;
  /** Numeric and not an identifier: totals and averages are meaningful. */
  measure: boolean;
  categorical: boolean;
  temporal: boolean;
  identifier: boolean;
}

export interface KpiSuggestion {
  definition: KpiDefinition;
  reason: string;
}

export interface KpiCatalogResponse {
  dataset_id: string;
  version_id: string | null;
  row_count: number;
  columns: ColumnRole[];
  suggestions: KpiSuggestion[];
  unavailable: { kpi: string; reason: string }[];
}

export interface AnalyticsMeta {
  dataset_id: string;
  version_id: string | null;
  row_count: number;
  filtered_row_count: number;
}

export interface TimeSeriesResponse {
  date_column: string;
  period: TimePeriod;
  metric: MetricType;
  column: string | null;
  labels: string[];
  series: { name: string; points: { label: string; value: number | null }[] }[];
  truncated: boolean;
}

export interface GrowthPoint {
  label: string;
  value: number | null;
  previous_value: number | null;
  absolute_change: number | null;
  percentage_change: number | null;
}

export interface GrowthResponse {
  date_column: string;
  period: TimePeriod;
  metric: MetricType;
  column: string | null;
  current: GrowthPoint | null;
  points: GrowthPoint[];
  message: string | null;
}

export interface SegmentRow {
  label: string;
  value: number | null;
  percentage: number | null;
}

export interface SegmentResponse {
  dimension: string;
  metric: MetricType;
  column: string | null;
  total: number | null;
  rows: SegmentRow[];
  group_count: number;
  truncated: boolean;
}

export interface ContributionRow extends SegmentRow {
  cumulative_percentage: number | null;
}

export interface ContributionResponse {
  dimension: string;
  metric: MetricType;
  column: string | null;
  total: number | null;
  rows: ContributionRow[];
  group_count: number;
}

export interface AbcRow {
  label: string;
  value: number;
  percentage: number;
  cumulative_percentage: number;
  abc_class: 'A' | 'B' | 'C';
}

export interface AbcResponse {
  dimension: string;
  metric: MetricType;
  column: string | null;
  total: number;
  a_threshold: number;
  b_threshold: number;
  rows: AbcRow[];
  summary: {
    abc_class: 'A' | 'B' | 'C';
    item_count: number;
    total_value: number;
    percentage_of_total: number;
    percentage_of_items: number;
  }[];
}

export interface EntityRow {
  entity: string;
  record_count: number;
  transaction_count: number | null;
  total_value: number | null;
  average_value: number | null;
}

export interface EntityResponse {
  entity_column: string;
  value_column: string | null;
  unique_entities: number;
  repeat_entities: number;
  one_time_entities: number;
  average_records_per_entity: number | null;
  average_value_per_entity: number | null;
  top_entities: EntityRow[];
}

export interface DistributionResponse {
  column: string;
  count: number;
  mean: number | null;
  median: number | null;
  minimum: number | null;
  maximum: number | null;
  std_dev: number | null;
  percentiles: Record<string, number | null>;
  buckets: { label: string; count: number; lower: number; upper: number }[];
}

/** Every analysis response carries the same meta envelope. */
export interface AnalyticsEnvelope<T> {
  meta: AnalyticsMeta;
  result: T;
}

// --- AI analyst -------------------------------------------------------------

export type InsightCategory =
  | 'kpi'
  | 'trend'
  | 'anomaly'
  | 'segment'
  | 'customer'
  | 'product'
  | 'region'
  | 'data_quality';

export type InsightSeverity = 'info' | 'low' | 'medium' | 'high';
export type TrendDirection = 'increasing' | 'decreasing' | 'stable' | 'insufficient_data';

export interface Insight {
  id: string;
  category: InsightCategory;
  title: string;
  summary: string;
  metric: string | null;
  value: number | null;
  comparison_value: number | null;
  percentage_change: number | null;
  dimension: string | null;
  dimension_value: string | null;
  severity: InsightSeverity;
  confidence: number | null;
  supporting_data: Record<string, unknown>;
  recommendation: string | null;
}

export interface TrendFinding {
  metric_column: string;
  date_column: string;
  period: TimePeriod;
  direction: TrendDirection;
  first_label: string | null;
  last_label: string | null;
  first_value: number | null;
  last_value: number | null;
  percentage_change: number | null;
  highest_label: string | null;
  highest_value: number | null;
  lowest_label: string | null;
  lowest_value: number | null;
  periods_observed: number;
  note: string | null;
}

export interface AnomalyFinding {
  metric_column: string;
  method: string;
  outlier_count: number;
  outlier_percentage: number;
  lower_bound: number | null;
  upper_bound: number | null;
  minimum_outlier: number | null;
  maximum_outlier: number | null;
  context: Record<string, unknown>;
  examples: Record<string, unknown>[];
}

export interface SegmentFinding {
  dimension: string;
  metric_column: string | null;
  metric: string;
  total: number | null;
  top: Record<string, unknown>[];
  bottom: Record<string, unknown>[];
  top_share_percentage: number | null;
  class_a_count: number | null;
  concentration_note: string | null;
}

export interface DataQualityNote {
  issue_type: string;
  severity: string;
  column: string | null;
  message: string;
  affected_rows: number;
}

export interface SemanticColumn {
  role: string;
  column: string;
  reason: string;
}

export interface AnalystKpi {
  name: string;
  metric: string;
  column: string | null;
  value: number | null;
  available: boolean;
  reason: string | null;
}

export interface AiNarrative {
  executive_summary: string | null;
  key_findings: string[];
  recommendations: string[];
  provider: string | null;
  model: string | null;
  contains_untraceable_numbers: boolean;
  untraceable_values: string[];
}

export interface AnalystReport {
  dataset_id: string;
  dataset_name: string;
  version_id: string | null;
  version_label: string | null;
  generated_at: string;
  row_count: number;
  column_count: number;
  summary: string;
  semantic_columns: SemanticColumn[];
  kpis: AnalystKpi[];
  insights: Insight[];
  trends: TrendFinding[];
  anomalies: AnomalyFinding[];
  segments: SegmentFinding[];
  recommendations: string[];
  data_quality: DataQualityNote[];
  ai_available: boolean;
  ai_status: string | null;
  ai: AiNarrative | null;
  cached: boolean;
}

export interface AnalystAnswer {
  question: string;
  answer: string;
  ai_available: boolean;
  ai_status: string | null;
  supporting_insight_ids: string[];
  contains_untraceable_numbers: boolean;
}

// --- Natural language query -------------------------------------------------

export type QueryIntent =
  | 'metric'
  | 'group'
  | 'rank'
  | 'timeseries'
  | 'comparison'
  | 'multi_metric';

export interface PlanMeasure {
  aggregation: MetricType;
  column: string | null;
  alias: string | null;
}

export interface PlanFilter {
  column: string;
  operator: FilterOperator;
  value?: unknown;
  value_to?: unknown;
}

export interface QueryPlan {
  intent: QueryIntent;
  measures: PlanMeasure[];
  dimensions: string[];
  date_column: string | null;
  date_period: TimePeriod | null;
  filters: PlanFilter[];
  filter_logic: FilterLogic;
  sort_by: string | null;
  sort_desc: boolean;
  limit: number;
  chart_type: ChartType | null;
}

export interface ResultColumn {
  name: string;
  role: string;
}

export interface NlqQueryResult {
  result_type: QueryIntent;
  columns: ResultColumn[];
  rows: Record<string, unknown>[];
  row_count: number;
  metric_label: string | null;
  metric_value: number | null;
  truncated: boolean;
}

export interface CalculationStep {
  label: string;
  detail: string;
}

export interface ChartRecommendation {
  chart_type: ChartType;
  reason: string;
  x_axis: string | null;
  y_axis: string | null;
  labels: string[];
  series: { name: string; data: (number | null)[] }[];
}

export interface QueryContextTurn {
  question: string;
  plan?: QueryPlan | null;
}

export interface NlqResponse {
  question: string;
  dataset_id: string;
  version_id: string | null;
  success: boolean;
  answer: string;
  plan: QueryPlan | null;
  result: NlqQueryResult | null;
  calculation: CalculationStep[];
  chart: ChartRecommendation | null;
  clarification_needed: boolean;
  clarification_question: string | null;
  candidate_columns: string[];
  ai_available: boolean;
  ai_status: string | null;
  plan_source: string;
  contains_untraceable_numbers: boolean;
  generated_at: string;
}

export interface QueryHistoryEntry {
  id: string;
  question: string;
  status: string;
  error_message: string | null;
  plan: Record<string, unknown> | null;
  dataset_version_id: string | null;
  created_at: string;
}

export type QueryHistoryResponse = Paginated<QueryHistoryEntry>;

export interface QuerySuggestion {
  question: string;
  reason: string;
}

export interface QuerySuggestionsResponse {
  dataset_id: string;
  version_id: string | null;
  suggestions: QuerySuggestion[];
}

// --- Advanced analytics -----------------------------------------------------

export interface AnalysisMeta {
  dataset_id: string;
  version_id: string | null;
  row_count: number;
  columns_used: Record<string, string>;
  warnings: string[];
}

export interface RequirementError {
  analysis: string;
  message: string;
  required_roles: string[];
  missing_roles: string[];
}

export interface AdvancedCapabilities {
  dataset_id: string;
  version_id: string | null;
  detected_columns: Record<string, string>;
  available: string[];
  unavailable: RequirementError[];
}

export interface RfmSegmentSummary {
  segment: string;
  customer_count: number;
  percentage: number;
  total_monetary: number;
  monetary_percentage: number;
  average_recency_days: number;
  average_frequency: number;
  average_monetary: number;
}

export interface RfmCustomer {
  customer: string;
  recency_days: number;
  frequency: number;
  monetary: number;
  r_score: number;
  f_score: number;
  m_score: number;
  rfm_score: string;
  segment: string;
}

export interface RfmResponse {
  meta: AnalysisMeta;
  reference_date: string;
  customer_count: number;
  total_monetary: number;
  segments: RfmSegmentSummary[];
  customers: RfmCustomer[];
  score_distribution: Record<string, Record<string, number>>;
}

export interface ClusterProfile {
  cluster: number;
  size: number;
  percentage: number;
  averages: Record<string, number>;
  distinguishing_features: { feature: string; z_score: number }[];
}

export interface ClusterPoint {
  label: string;
  cluster: number;
  x: number;
  y: number;
}

export interface SegmentationResponse {
  meta: AnalysisMeta;
  features: string[];
  clusters: number;
  standardized: boolean;
  explained_variance: number | null;
  iterations: number;
  profiles: ClusterProfile[];
  points: ClusterPoint[];
}

export interface CohortRow {
  cohort: string;
  cohort_size: number;
  values: (number | null)[];
  percentages: (number | null)[];
}

export interface CohortResponse {
  meta: AnalysisMeta;
  period: TimePeriod;
  period_labels: string[];
  rows: CohortRow[];
  average_retention: (number | null)[];
}

export type ChurnStatus = 'active' | 'at_risk' | 'churned';

export interface ChurnCustomer {
  customer: string;
  last_activity: string;
  days_since_activity: number;
  transactions: number;
  monetary: number | null;
  status: ChurnStatus;
}

export interface ChurnResponse {
  meta: AnalysisMeta;
  method: string;
  method_note: string;
  reference_date: string;
  churn_days: number;
  at_risk_days: number;
  total_customers: number;
  active_customers: number;
  at_risk_customers: number;
  churned_customers: number;
  churn_rate: number;
  revenue_at_risk: number | null;
  customers: ChurnCustomer[];
  trend: { period: string; active_customers: number }[];
}

export type ForecastMethod = 'holt' | 'ses' | 'moving_average';

export interface ForecastPoint {
  period: string;
  value: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
  is_forecast: boolean;
}

export interface ForecastResponse {
  meta: AnalysisMeta;
  method: ForecastMethod;
  period: TimePeriod;
  horizon: number;
  periods_observed: number;
  trend: string;
  mean_absolute_error: number | null;
  confidence_level: number;
  history: ForecastPoint[];
  forecast: ForecastPoint[];
}

export interface OutlierResponse {
  meta: AnalysisMeta;
  column: string;
  method: string;
  threshold: number;
  total_observations: number;
  outlier_count: number;
  outlier_percentage: number;
  lower_bound: number | null;
  upper_bound: number | null;
  minimum: number | null;
  q1: number | null;
  median: number | null;
  q3: number | null;
  maximum: number | null;
  outliers: { row: number; value: number }[];
}

export interface ParetoRow {
  label: string;
  value: number;
  percentage: number;
  cumulative_percentage: number;
  within_threshold: boolean;
}

export interface ParetoResponse {
  meta: AnalysisMeta;
  dimension: string;
  metric: MetricType;
  column: string | null;
  total: number;
  threshold: number;
  vital_few_count: number;
  vital_few_percentage_of_items: number;
  rows: ParetoRow[];
}

/* --- Reports ---------------------------------------------------------------- */

export type ReportTemplateName = 'executive' | 'sales' | 'customer' | 'full';
export type ReportFileFormat = 'pdf' | 'xlsx' | 'csv' | 'pptx';
export type ReportStatus = 'ready' | 'failed';

export type ReportSectionKey =
  | 'executive_summary'
  | 'business_health'
  | 'critical_insights'
  | 'opportunities'
  | 'risks'
  | 'dataset_overview'
  | 'data_quality'
  | 'kpis'
  | 'eda'
  | 'trends'
  | 'segmentation'
  | 'abc'
  | 'pareto'
  | 'rfm'
  | 'cohort'
  | 'churn'
  | 'correlation'
  | 'outliers'
  | 'forecast'
  | 'ai_insights'
  | 'recommendations';

/** A pre-formatted table cell. Numbers stay numeric for the XLSX export. */
export type ReportCell = string | number | null;

export interface ReportMetric {
  label: string;
  value: string;
  detail: string | null;
}

export interface ReportTable {
  title: string | null;
  columns: string[];
  rows: ReportCell[][];
  note: string | null;
}

export interface ReportSection {
  key: ReportSectionKey;
  title: string;
  narrative: string[];
  metrics: ReportMetric[];
  tables: ReportTable[];
  bullets: string[];
  unavailable_reason: string | null;
}

/**
 * The canonical report. The preview renders this object, and the PDF, XLSX,
 * CSV and PPTX exports are rendered from the very same structure server-side.
 */
export interface ReportData {
  title: string;
  subtitle: string | null;
  project_id: string;
  dataset_id: string;
  dataset_name: string;
  version_id: string | null;
  version_label: string;
  template: ReportTemplateName;
  generated_at: string;
  generated_by: string;
  row_count: number;
  column_count: number;
  sections: ReportSection[];
  ai_available: boolean;
  ai_status: string | null;
  skipped: { section: string; reason: string }[];
}

export interface SectionAvailability {
  key: ReportSectionKey;
  title: string;
  available: boolean;
  reason: string | null;
  required_roles: string[];
}

export interface ReportTemplateInfo {
  template: ReportTemplateName;
  name: string;
  description: string;
  sections: ReportSectionKey[];
  unavailable_sections: ReportSectionKey[];
}

export interface ReportOptions {
  dataset_id: string;
  version_id: string | null;
  templates: ReportTemplateInfo[];
  sections: SectionAvailability[];
  formats: ReportFileFormat[];
  detected_columns: Record<string, string>;
}

export interface Report {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string | null;
  name: string;
  template: ReportTemplateName;
  file_format: ReportFileFormat;
  sections: string[];
  status: ReportStatus;
  file_size: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export type ReportListResponse = Paginated<Report>;

/* --- AI Insights ------------------------------------------------------------- */

export type BusinessInsightCategory =
  | 'performance'
  | 'opportunity'
  | 'risk'
  | 'trend'
  | 'customer'
  | 'product'
  | 'region'
  | 'operations'
  | 'data_quality';

export type BusinessInsightSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';
export type InsightPriority = 'low' | 'medium' | 'high' | 'critical';
export type HealthRating = 'strong' | 'healthy' | 'mixed' | 'at_risk' | 'unknown';
export type FactorStatus = 'positive' | 'moderate' | 'negative' | 'not_measurable';
export type InsightRunStatus = 'ready' | 'failed';

/** One measured figure behind a finding. */
export interface Evidence {
  label: string;
  value: number | null;
  formatted: string;
  detail: string | null;
}

export interface BusinessInsight {
  id: string;
  category: BusinessInsightCategory;
  title: string;
  summary: string;
  severity: BusinessInsightSeverity;
  priority: InsightPriority;
  metric: string | null;
  metric_value: number | null;
  comparison_value: number | null;
  percentage_change: number | null;
  dimension: string | null;
  dimension_value: string | null;
  why: string | null;
  action: string | null;
  evidence: Evidence[];
  confidence: number | null;
  affected_records: number | null;
  recommendation: string | null;
  source: string;
  priority_score: number;
  priority_reason: string | null;
  created_at: string;
}

export interface InsightRecommendation {
  id: string;
  title: string;
  action: string;
  reason: string;
  supporting_insight_ids: string[];
  expected_impact: string;
  priority: InsightPriority;
  category: BusinessInsightCategory;
  source: string;
}

export interface HealthFactor {
  key: string;
  name: string;
  status: FactorStatus;
  score: number | null;
  weight: number;
  detail: string;
  evidence: Evidence[];
}

export interface BusinessHealth {
  score: number | null;
  rating: HealthRating;
  methodology: string;
  factors: HealthFactor[];
  excluded: { factor: string; reason: string }[];
}

/** Filter values derived from the dataset, never a hard-coded list. */
export interface InsightFilters {
  categories: BusinessInsightCategory[];
  severities: BusinessInsightSeverity[];
  priorities: InsightPriority[];
  products: string[];
  regions: string[];
  customer_segments: string[];
  periods: string[];
  product_column: string | null;
  region_column: string | null;
  date_column: string | null;
}

export interface AiInsightNarrative {
  headline: string | null;
  interpretation: string[];
  priorities: string[];
  provider: string | null;
  model: string | null;
  contains_untraceable_numbers: boolean;
  untraceable_values: string[];
}

export interface InsightReport {
  run_id: string | null;
  project_id: string;
  dataset_id: string;
  dataset_name: string;
  version_id: string | null;
  version_label: string;
  analysis_version: string;
  generated_at: string;
  generated_by: string;
  row_count: number;
  column_count: number;
  summary: string;
  health: BusinessHealth;
  insights: BusinessInsight[];
  recommendations: InsightRecommendation[];
  supporting_metrics: Evidence[];
  filters: InsightFilters;
  counts_by_category: Record<string, number>;
  counts_by_severity: Record<string, number>;
  counts_by_priority: Record<string, number>;
  ai_available: boolean;
  ai_status: string | null;
  ai: AiInsightNarrative | null;
  skipped: { analysis: string; reason: string }[];
  /** True when this run no longer matches the version or rules being viewed. */
  stale: boolean;
}

export interface InsightRun {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string | null;
  analysis_version: string;
  status: InsightRunStatus;
  health_score: number | null;
  health_rating: string | null;
  insight_count: number;
  recommendation_count: number;
  ai_available: boolean;
  ai_status: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface InsightRunDetail {
  run: InsightRun;
  report: InsightReport | null;
}

export type InsightRunListResponse = Paginated<InsightRun>;

/* --- Dashboards -------------------------------------------------------------- */

export type WidgetType =
  | 'kpi'
  | 'chart'
  | 'table'
  | 'ai_insight'
  | 'recommendation'
  | 'text'
  | 'nlq_result'
  | 'advanced';

export type WidgetStatus = 'ok' | 'error';

export type AdvancedAnalysis =
  | 'rfm'
  | 'cohort'
  | 'churn'
  | 'forecast'
  | 'pareto'
  | 'segmentation';

export interface WidgetPosition {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Widget configuration, discriminated on `widget_type`.
 *
 * These mirror the backend's validated models: a widget can name a column, a
 * metric, an aggregation and a filter, and nothing else.
 */
export interface KpiWidgetConfig {
  widget_type: 'kpi';
  definition: KpiDefinition;
}

export interface ChartWidgetConfig {
  widget_type: 'chart';
  chart_type: ChartType;
  x_column?: string | null;
  y_column?: string | null;
  group_by?: string | null;
  aggregation?: Aggregation;
  filters?: FilterSet | null;
  period?: TimePeriod | null;
  bins?: number;
  max_categories?: number;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
}

export interface TableWidgetConfig {
  widget_type: 'table';
  group_by?: string[];
  aggregations?: { column: string; aggregation: Aggregation; alias?: string | null }[];
  columns?: string[];
  filters?: FilterSet | null;
  sort_by?: string | null;
  sort_desc?: boolean;
  limit?: number;
}

export interface AiInsightWidgetConfig {
  widget_type: 'ai_insight';
  run_id?: string | null;
  categories?: string[];
  priorities?: string[];
  insight_ids?: string[];
  limit?: number;
  show_health?: boolean;
}

export interface RecommendationWidgetConfig {
  widget_type: 'recommendation';
  run_id?: string | null;
  priorities?: string[];
  limit?: number;
}

export interface TextWidgetConfig {
  widget_type: 'text';
  content: string;
}

export interface NlqWidgetConfig {
  widget_type: 'nlq_result';
  nlq_query_id: string;
  show_chart?: boolean;
}

export interface AdvancedWidgetConfig {
  widget_type: 'advanced';
  analysis: AdvancedAnalysis;
  dimension?: string | null;
  column?: string | null;
  metric?: MetricType;
  period?: TimePeriod;
  horizon?: number;
  clusters?: number;
  limit?: number;
  filters?: FilterSet | null;
}

export type WidgetConfig =
  | KpiWidgetConfig
  | ChartWidgetConfig
  | TableWidgetConfig
  | AiInsightWidgetConfig
  | RecommendationWidgetConfig
  | TextWidgetConfig
  | NlqWidgetConfig
  | AdvancedWidgetConfig;

export interface DashboardWidget {
  id: string;
  dashboard_id: string;
  widget_type: WidgetType;
  title: string;
  position: WidgetPosition;
  configuration: WidgetConfig;
  created_at: string;
  updated_at: string;
}

export interface Dashboard {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string | null;
  name: string;
  description: string | null;
  layout_columns: number;
  filters: FilterSet | null;
  widget_count: number;
  created_at: string;
  updated_at: string;
}

export interface DashboardDetail {
  dashboard: Dashboard;
  version_label: string;
  dataset_name: string;
  widgets: DashboardWidget[];
}

export type DashboardListResponse = Paginated<Dashboard>;

/* Resolved widget payloads. */

export interface KpiWidgetData {
  result: KpiResult;
}

export interface TableWidgetData {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
}

export interface InsightWidgetData {
  insights: BusinessInsight[];
  health_score: number | null;
  health_rating: string | null;
  run_id: string | null;
  generated_at: string | null;
  stale: boolean;
}

export interface RecommendationWidgetData {
  recommendations: InsightRecommendation[];
  run_id: string | null;
  generated_at: string | null;
}

export interface NlqWidgetData {
  question: string;
  answer: string;
  columns: string[];
  rows: Record<string, unknown>[];
  metric_label: string | null;
  metric_value: number | null;
  chart: ChartDataResponse | null;
}

export interface TextWidgetData {
  content: string;
}

export interface AdvancedWidgetData {
  analysis: AdvancedAnalysis;
  metrics: { label: string; value: number | string | null; suffix?: string }[];
  columns: string[];
  rows: Record<string, unknown>[];
  chart: ChartDataResponse | null;
  note: string | null;
}

export interface WidgetResult {
  widget_id: string;
  widget_type: WidgetType;
  title: string;
  position: WidgetPosition;
  status: WidgetStatus;
  error: string | null;
  kpi: KpiWidgetData | null;
  chart: ChartDataResponse | null;
  table: TableWidgetData | null;
  insight: InsightWidgetData | null;
  recommendation: RecommendationWidgetData | null;
  text: TextWidgetData | null;
  nlq: NlqWidgetData | null;
  advanced: AdvancedWidgetData | null;
}

export interface DashboardData {
  dashboard_id: string;
  name: string;
  description: string | null;
  dataset_id: string;
  dataset_name: string;
  version_id: string | null;
  version_label: string;
  layout_columns: number;
  row_count: number;
  refreshed_at: string;
  applied_filters: FilterSet | null;
  filtered_row_count: number;
  widgets: WidgetResult[];
}

export interface DashboardFilterField {
  column: string;
  kind: 'categorical' | 'numeric' | 'date';
  values: string[];
  minimum: string | number | null;
  maximum: string | number | null;
  role: string | null;
}

export interface DashboardFilterOptions {
  dataset_id: string;
  version_id: string | null;
  fields: DashboardFilterField[];
}

export interface TemplateWidget {
  title: string;
  position: WidgetPosition;
  configuration: WidgetConfig;
}

export interface DashboardTemplate {
  key: string;
  name: string;
  description: string;
  layout_columns: number;
  widgets: TemplateWidget[];
  unavailable: { widget: string; reason: string }[];
}

export interface DashboardTemplateList {
  dataset_id: string;
  version_id: string | null;
  templates: DashboardTemplate[];
  suggestions: TemplateWidget[];
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
