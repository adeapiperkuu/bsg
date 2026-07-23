export type ClientProjectOverview = {
  project_id: string;
  project_name: string;
  description: string | null;
  current_status: string;
  overall_health: "green" | "amber" | "red" | "insufficient";
  delivery_confidence: number | null;
  delivery_confidence_label: string;
  current_phase: string;
  completion_percentage: number;
  start_date: string;
  target_end_date: string;
};

export type ClientMilestone = {
  id: string;
  name: string;
  description: string | null;
  planned_date: string;
  actual_date: string | null;
  status: string;
  progress_percentage: number;
};

export type ClientRisk = {
  id: string;
  title: string;
  severity: string;
  impact: string | null;
  mitigation: string | null;
  status: string;
  updated_at: string;
};

export type ClientAction = {
  id: string;
  title: string;
  description: string | null;
  action_type: "approval" | "information_request" | "client_action";
  due_date: string | null;
  status: string;
  is_overdue: boolean;
};

export type ClientPortalReport = {
  id: string;
  title: string;
  report_type: string;
  executive_summary: string;
  published_at: string;
  pdf_download_url: string;
  csv_download_url: string;
};

export type ClientAiSummary = {
  title: string;
  summary: string;
  current_progress: string[];
  risks: string[];
  upcoming_work: string[];
  generated_at: string | null;
};

export type ClientDocument = {
  id: string;
  title: string;
  document_type: string;
  version: string;
  description: string | null;
  file_name: string;
  file_url: string | null;
  shared_at: string;
};

export type ClientDeliverable = {
  id: string;
  title: string;
  description: string | null;
  status: "completed" | "in_progress" | "planned";
  due_date: string | null;
  completed_at: string | null;
  file_name: string | null;
  file_url: string | null;
};

export type ClientChangeRequestStatus =
  | "submitted"
  | "under_review"
  | "approved"
  | "rejected"
  | "implemented";

export type ClientChangeRequest = {
  id: string;
  project_id: string;
  title: string;
  description: string;
  business_justification: string | null;
  priority: "low" | "medium" | "high" | "critical";
  status: ClientChangeRequestStatus;
  decision_notes: string | null;
  implemented_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ClientChangeRequestCreate = {
  title: string;
  description: string;
  business_justification?: string | null;
  priority: "low" | "medium" | "high" | "critical";
};

export type ClientMeetingActionItem = {
  title: string;
  owner: string | null;
  due_date: string | null;
  status: string;
};

export type ClientMeeting = {
  id: string;
  title: string;
  starts_at: string;
  duration_minutes: number;
  meeting_url: string | null;
  agenda: string | null;
  minutes: string | null;
  action_items: ClientMeetingActionItem[];
  status: "scheduled" | "completed" | "cancelled";
};

export type ClientNotification = {
  id: string;
  notification_type:
    | "report_published"
    | "milestone_completed"
    | "risk_updated"
    | "document_shared"
    | "meeting_scheduled";
  title: string;
  detail: string | null;
  occurred_at: string;
  href: string | null;
};

export type ClientProjectDashboard = {
  overview: ClientProjectOverview;
  milestones: ClientMilestone[];
  risks: ClientRisk[];
  client_actions: ClientAction[];
  reports: ClientPortalReport[];
  ai_summary: ClientAiSummary;
  documents: ClientDocument[];
  deliverables: ClientDeliverable[];
  change_requests: ClientChangeRequest[];
  meetings: ClientMeeting[];
  notifications: ClientNotification[];
  generated_at: string;
};
