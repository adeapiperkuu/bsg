/**
 * Client communication (PM reports) domain types.
 * Aligned with backend `CommunicationStatus` / `CommunicationType` and
 * `CommunicationRead` / draft-review-approve request schemas.
 *
 * Product boundary:
 * - `/reports` — PM workflow console (all statuses, lifecycle actions)
 * - `/client/reports` — client published archive (sent only, read-only)
 */

import type { MePermissions } from "@/types/auth";

/** Backend `communication_status` enum values. */
export type CommunicationStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "sent"
  | "rejected";

/** Backend `communication_type` enum values. */
export type CommunicationType = "weekly_summary" | "executive_summary" | "ad_hoc";

/** Evidence row attached to a communication (matches `EvidenceLinkRead`). */
export interface CommunicationEvidenceLink {
  id?: string | null;
  source_table: string;
  source_row_id: string;
  description: string;
  created_at?: string | null;
}

/**
 * List-row shape for the PM inbox (`GET /communications`).
 * Extends the API list item; Phase 3 wires this from the org-scoped endpoint.
 */
export interface CommunicationListItem {
  id: string;
  project_id: string;
  project_name: string;
  org_id: string;
  org_name: string;
  comm_type: CommunicationType;
  subject: string;
  status: CommunicationStatus;
  created_at: string;
  updated_at: string;
  sent_at?: string | null;
  evidence_link_count: number;
}

/** Full communication detail (`CommunicationRead`). */
export interface CommunicationDetail {
  id: string;
  project_id: string;
  comm_type: CommunicationType;
  subject: string;
  body_draft: string;
  body_approved: string | null;
  status: CommunicationStatus;
  drafted_by_agent: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
  evidence_links: CommunicationEvidenceLink[];
  /** Display-only helper for the workspace chrome. */
  project_name?: string;
  /** `ai` when LLM succeeded; `fallback` when evidence-backed placeholder was used. */
  generation_mode?: "ai" | "fallback" | string | null;
  /** User-facing notice when generation used fallback (or other soft warnings). */
  generation_warning?: string | null;
}

/** `POST /projects/{project_id}/communications/draft` body. */
export interface CommunicationDraftRequest {
  comm_type: CommunicationType;
  subject: string;
  instructions?: string | null;
}

/** `PATCH /communications/{id}` — save edits without status change. */
export interface CommunicationContentUpdateRequest {
  subject?: string;
  body?: string;
}

/** `PATCH /communications/{communication_id}/review` body. */
export interface CommunicationReviewRequest {
  body_approved: string;
  status?: CommunicationStatus;
}

/** `POST /communications/{communication_id}/approve` body. */
export interface CommunicationApproveRequest {
  body_approved?: string | null;
}

/** Response envelope for reject (same as approve/send — returns updated communication). */
export interface CommunicationRejectResponse {
  data: CommunicationDetail;
}

/** Response envelope for send. */
export interface CommunicationSendResponse {
  data: CommunicationDetail;
}

/** Metadata captured when a draft is generated (Phase 2+). */
export interface CommunicationGenerationMetadata {
  drafted_by_agent: string;
  generated_at: string;
  instructions?: string | null;
  evidence_count: number;
  /** True when body came from LLM; false for placeholder fallback. */
  generated_by_ai: boolean;
}

/**
 * Permissions relevant to communications.
 *
 * Backend `/me` exposes `can_approve_communications` for delivery_manager /
 * super_admin. All PM lifecycle mutations (generate, edit, review, approve,
 * reject, send) share that same backend role gate, so the flag legitimately
 * covers the full workflow until finer-grained `/me` fields exist.
 * Leadership remains read-only.
 */
export type CommunicationCapabilities = {
  canGenerateCommunications: boolean;
  canReviewCommunications: boolean;
  canApproveCommunications: boolean;
  canRejectCommunications: boolean;
  canSendCommunications: boolean;
  /** Access to the PM `/reports` console (DM, SA, leadership). */
  canAccessReportsWorkflow: boolean;
  /** Leadership without approve capability — view only. */
  isReportsReadOnly: boolean;
};

export type ListCommunicationsParams = {
  status?: CommunicationStatus;
  project_id?: string;
  limit?: number;
  offset?: number;
};

export type ListCommunicationsPagination = {
  limit: number;
  offset: number;
  total?: number | null;
  items?: number | null;
  has_more?: boolean;
  next_cursor?: string | null;
};

export type ListCommunicationsResult = {
  data: CommunicationListItem[];
  pagination: ListCommunicationsPagination;
};

/** @deprecated Prefer CommunicationCapabilities from reportPermissions. */
export type CommunicationPermissions = Pick<MePermissions, "can_approve_communications"> & {
  can_manage_communications: boolean;
  can_view_sent_only: boolean;
};

/** Workspace actions driven by status (+ permissions in Phase 2). */
export type ReportWorkspaceAction =
  | "edit"
  | "submit_review"
  | "approve"
  | "reject"
  | "send"
  | "generate_new";
