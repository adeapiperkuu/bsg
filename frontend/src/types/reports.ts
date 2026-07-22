/** Phase 18.3 Cross-Agent Reporting Framework types. */

export type ReportFormat = "pdf" | "docx" | "json" | "csv";
export type ReportAudience =
  | "client"
  | "delivery_manager"
  | "bsg_leadership"
  | "executive"
  | "internal";
export type ReportDomain =
  | "delivery"
  | "governance"
  | "quality"
  | "workforce"
  | "client"
  | "executive"
  | "cross_agent";
export type ReportInstanceStatus =
  | "queued"
  | "generating"
  | "draft"
  | "in_review"
  | "approved"
  | "rejected"
  | "distributed"
  | "failed"
  | "cancelled";

export type ReportSectionConfig = {
  key: string;
  options?: Record<string, unknown>;
};

export type ReportTemplate = {
  id: string;
  org_id: string | null;
  template_key: string;
  name: string;
  description: string | null;
  audience: ReportAudience | string;
  domain: ReportDomain | string;
  version: string;
  status: "draft" | "active" | "archived";
  section_config: ReportSectionConfig[];
  export_formats: ReportFormat[];
  requires_approval: boolean;
  allowed_roles: string[];
  is_client_visible: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type ReportInstanceListItem = {
  id: string;
  org_id: string;
  project_id: string | null;
  template_key: string;
  template_version: string;
  audience: string;
  domain: string;
  status: ReportInstanceStatus | string;
  title: string;
  period_start: string | null;
  period_end: string | null;
  has_ai_sections: boolean;
  evidence_fingerprint: string | null;
  created_at: string;
  updated_at: string;
};

export type ReportInstance = ReportInstanceListItem & {
  template_id: string;
  body_markdown: string | null;
  content_payload: Record<string, unknown>;
  provenance: Record<string, unknown>;
  limitations: unknown[];
  generation_mode: string;
  generated_by_user_id: string | null;
  generated_by_job_id: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  distributed_at: string | null;
};

export type ReportGenerateRequest = {
  template_key: string;
  template_version?: string;
  project_id?: string;
  period_start?: string;
  period_end?: string;
  title?: string;
  section_options?: Record<string, Record<string, unknown>>;
  idempotency_key?: string;
  generation_mode?: string;
};

export type ReportJobStart = {
  id: string;
  job_type: string;
  status: string;
  report_instance_id: string | null;
  idempotency_key: string;
  requested_at: string;
};

export type ReportExport = {
  id: string;
  report_instance_id: string;
  format: ReportFormat | string;
  storage_backend: string;
  storage_path: string;
  file_name: string;
  content_type: string;
  size_bytes: number | null;
  checksum_sha256: string | null;
  content_hash: string | null;
  generated_at: string;
};

export type ReportApprovalEvent = {
  id: string;
  report_instance_id: string;
  actor_user_id: string | null;
  from_status: string | null;
  to_status: string;
  action: string;
  note: string | null;
  event_metadata: Record<string, unknown>;
  created_at: string;
};

export type ReportSchedule = {
  id: string;
  org_id: string;
  project_id: string | null;
  template_id: string;
  interval: "daily" | "weekly" | "monthly" | "quarterly";
  is_enabled: boolean;
  create_as_status: "draft";
  audience: string;
  config: Record<string, unknown>;
  next_run_at: string | null;
  last_run_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type ReportScheduleCreate = {
  project_id?: string | null;
  template_id: string;
  interval: "daily" | "weekly" | "monthly" | "quarterly";
  is_enabled?: boolean;
  audience: string;
  config?: Record<string, unknown>;
  next_run_at?: string | null;
  create_as_status?: "draft";
};

export type ReportSectionPayload = {
  key: string;
  title: string;
  payload: Record<string, unknown>;
  markdown: string;
  limitations: string[];
  has_ai: boolean;
  requires_approval: boolean;
};

export type ReportPreview = {
  template: ReportTemplate;
  title: string;
  body_markdown: string;
  sections: ReportSectionPayload[];
  limitations: string[];
  evidence_fingerprint: string | null;
  has_ai_sections: boolean;
  requires_approval: boolean;
};
