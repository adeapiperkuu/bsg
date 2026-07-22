/** Phase 18.2 Platform Time-Series Engine types. */

export type TimeSeriesInterval = "hour" | "day" | "week" | "month" | "quarter" | "on_demand";
export type CompareMode = "period" | "baseline" | "project" | "department" | "portfolio";

export type KpiObservation = {
  id: string;
  org_id: string;
  project_id: string | null;
  kpi_key: string;
  version: string;
  definition_version: string | null;
  calculator_key: string | null;
  calculator_version: string | null;
  observed_at: string;
  evaluated_at: string | null;
  numeric_value: number | string | null;
  text_value: string | null;
  normalized_value: number | string | null;
  confidence: number | string | null;
  value_type: string;
  status: string;
  department_key: string | null;
  agent_key: string | null;
  source_type: string;
  bucket_interval: string | null;
  bucket_start: string | null;
  bucket_end: string | null;
  evidence_refs: unknown[];
  lineage_refs: Record<string, unknown>;
  explainability: Record<string, unknown> | null;
  idempotency_fingerprint: string | null;
  supersedes_observation_id: string | null;
};

export type KpiTrendSummary = {
  kpi_key: string;
  latest: KpiObservation | null;
  previous: KpiObservation | null;
  absolute_change: number | string | null;
  percentage_change: number | string | null;
  raw_direction: "up" | "down" | "flat" | "unknown";
  semantic_favorability:
    | "improving"
    | "declining"
    | "stable"
    | "on_target"
    | "off_target"
    | "unknown";
  trend_direction_policy: string;
  observation_count: number;
  rolling_average: number | string | null;
  min_value: number | string | null;
  max_value: number | string | null;
  average_value: number | string | null;
  median_value: number | string | null;
};

export type KpiSeriesPoint = {
  bucket_start: string;
  bucket_end: string | null;
  numeric_value: number | string | null;
  text_value: string | null;
  observation_count: number;
  min_value: number | string | null;
  max_value: number | string | null;
  avg_value: number | string | null;
  median_value: number | string | null;
};

export type KpiSeries = {
  kpi_key: string;
  interval: TimeSeriesInterval;
  points: KpiSeriesPoint[];
  source: "observations" | "rollups";
};

export type KpiComparisonSeries = {
  label: string;
  scope_key: string;
  project_id: string | null;
  department_key: string | null;
  points: KpiSeriesPoint[];
  latest_value: number | string | null;
};

export type KpiCompare = {
  kpi_key: string;
  mode: CompareMode;
  interval: TimeSeriesInterval;
  baseline_label: string | null;
  series: KpiComparisonSeries[];
  absolute_deltas: Record<string, number | string | null>;
  percentage_deltas: Record<string, number | string | null>;
};

export type KpiForecastPoint = {
  forecast_at: string;
  value: number | string;
  lower_bound: number | string | null;
  upper_bound: number | string | null;
};

export type KpiForecast = {
  kpi_key: string;
  status: "ok" | "insufficient_data";
  method: string | null;
  model_version: string | null;
  horizon: number | null;
  training_window_start: string | null;
  training_window_end: string | null;
  sample_count: number;
  assumptions: string[];
  points: KpiForecastPoint[];
  message: string | null;
};

export type TimeSeriesDimensions = {
  kpi_keys: string[];
  agents: string[];
  departments: string[];
  intervals: string[];
  min_observed_at: string | null;
  max_observed_at: string | null;
};

export type RecommendationTimelineEvent = {
  id: string;
  org_id: string;
  project_id: string | null;
  domain: string;
  subject_table: string;
  subject_id: string;
  event_type: string;
  actor_user_id: string | null;
  source_agent: string | null;
  recommendation_type: string | null;
  severity: string | null;
  confidence: number | string | null;
  affected_kpi_keys: unknown[];
  status_snapshot: string | null;
  related_table: string | null;
  related_id: string | null;
  conversion_target: string | null;
  resolution_outcome: string | null;
  strategy_version: string | null;
  evidence_fingerprint: string | null;
  event_timestamp: string;
  payload: Record<string, unknown>;
};

export type RecommendationSubjectSummary = {
  domain: string;
  subject_table: string;
  subject_id: string;
  project_id: string | null;
  source_agent: string | null;
  recommendation_type: string | null;
  severity: string | null;
  status_snapshot: string | null;
  last_event_type: string;
  last_event_at: string;
  event_count: number;
};

export type TimeSeriesScopeParams = {
  org_id?: string;
  project_id?: string;
  department_key?: string;
  agent_key?: string;
  definition_version?: string;
  calculator_version?: string;
  date_from?: string;
  date_to?: string;
  interval?: TimeSeriesInterval;
  limit?: number;
  offset?: number;
  horizon?: number;
  rolling_window?: number;
  mode?: CompareMode;
  compare_project_id?: string;
};
