/**
 * Single source of truth for PM report status / type presentation and lifecycle UI rules.
 *
 * Lifecycle (backend-enforced):
 *   draft → in_review → approved → sent
 *        ↘ rejected   ↗ (approve may skip in_review)
 *   draft → approved → sent
 *
 * Verified contracts (`backend/app/services/communications.py`):
 * - `PATCH /communications/{id}` — edit subject/body for draft | in_review only
 * - `PATCH .../review` — submit/re-save into `in_review` (writes `body_approved`)
 * - `POST .../approve` — draft | in_review → approved (does not send)
 * - `POST .../reject` — draft | in_review → rejected
 * - `POST .../send` — approved → sent (idempotent if already sent)
 */

import type {
  CommunicationStatus,
  CommunicationType,
  ReportWorkspaceAction,
} from "@/types/communications";

/** StatusPill `status` prop values used for communication pills. */
export type ReportStatusPillStatus =
  | "In Progress"
  | "Warning"
  | "On Track"
  | "At Risk";

export const COMMUNICATION_STATUSES: readonly CommunicationStatus[] = [
  "draft",
  "in_review",
  "approved",
  "sent",
  "rejected",
] as const;

export const COMMUNICATION_TYPES: readonly CommunicationType[] = [
  "weekly_summary",
  "executive_summary",
  "ad_hoc",
] as const;

export const COMMUNICATION_STATUS_ORDER: Record<CommunicationStatus, number> = {
  draft: 0,
  in_review: 1,
  approved: 2,
  sent: 3,
  rejected: 4,
};

export const COMMUNICATION_STATUS_LABELS: Record<CommunicationStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  approved: "Approved",
  sent: "Sent",
  rejected: "Rejected",
};

/** Filter chip labels for the PM inbox. UI "Pending" maps to API `in_review`. */
export const COMMUNICATION_STATUS_FILTER_LABELS: Record<"all" | CommunicationStatus, string> =
  {
    all: "All",
    draft: "Draft",
    in_review: "Pending",
    approved: "Approved",
    sent: "Sent",
    rejected: "Rejected",
  };

export const COMMUNICATION_STATUS_PILL: Record<CommunicationStatus, ReportStatusPillStatus> = {
  draft: "In Progress",
  in_review: "Warning",
  approved: "On Track",
  sent: "On Track",
  rejected: "At Risk",
};

export const COMMUNICATION_TYPE_LABELS: Record<CommunicationType, string> = {
  weekly_summary: "Weekly Status",
  executive_summary: "Executive Summary",
  ad_hoc: "Ad hoc Update",
};

export const COMMUNICATION_SUBJECT_SUGGESTIONS: Record<CommunicationType, string[]> = {
  weekly_summary: ["Weekly Status — W{week}", "Weekly Delivery Update"],
  executive_summary: ["Executive Summary", "Executive Brief"],
  ad_hoc: ["Ad hoc Update", "Client Update"],
};

/**
 * Status-driven UI actions (permissions applied separately).
 *
 * - edit: draft | in_review
 * - submit_review: draft | in_review (submit or re-save into review)
 * - approve: draft | in_review
 * - reject: draft | in_review
 * - send: approved only
 * - generate_new: rejected
 */
export function allowedActionsForStatus(
  status: CommunicationStatus,
): ReadonlySet<ReportWorkspaceAction> {
  switch (status) {
    case "draft":
      return new Set(["edit", "submit_review", "approve", "reject"]);
    case "in_review":
      return new Set(["edit", "submit_review", "approve", "reject"]);
    case "approved":
      return new Set(["send"]);
    case "sent":
      return new Set();
    case "rejected":
      return new Set(["generate_new"]);
    default: {
      const _exhaustive: never = status;
      return _exhaustive;
    }
  }
}

export function canEditCommunication(status: CommunicationStatus): boolean {
  return allowedActionsForStatus(status).has("edit");
}

export function isCommunicationReadOnly(status: CommunicationStatus): boolean {
  return status === "sent" || status === "rejected";
}

export function statusLabel(status: CommunicationStatus): string {
  return COMMUNICATION_STATUS_LABELS[status];
}

export function typeLabel(commType: CommunicationType): string {
  return COMMUNICATION_TYPE_LABELS[commType];
}

export function statusPillFor(status: CommunicationStatus): ReportStatusPillStatus {
  return COMMUNICATION_STATUS_PILL[status];
}

export const REPORT_INBOX_FILTERS = [
  "all",
  "draft",
  "in_review",
  "approved",
  "sent",
  "rejected",
] as const;
export type ReportInboxFilter = (typeof REPORT_INBOX_FILTERS)[number];

export function inboxFilterToApiStatus(
  filter: ReportInboxFilter,
): CommunicationStatus | undefined {
  if (filter === "all") return undefined;
  return filter;
}

export function parseInboxFilter(value: unknown): ReportInboxFilter {
  if (typeof value === "string" && (REPORT_INBOX_FILTERS as readonly string[]).includes(value)) {
    return value as ReportInboxFilter;
  }
  return "all";
}
