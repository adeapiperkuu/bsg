import type { CommunicationListItem } from "@/types/communications";

/**
 * Resolve display body for the workspace.
 * Prefer non-empty `body_approved`, otherwise fall back to `body_draft`.
 * Empty strings are treated as missing.
 */
export function resolveCommunicationBody(detail: {
  body_approved: string | null | undefined;
  body_draft: string | null | undefined;
}): string {
  const approved = detail.body_approved?.trim();
  if (approved) return approved;
  return detail.body_draft?.trim() ?? "";
}

export type InboxProjectGroup = {
  projectId: string;
  projectName: string;
  reports: CommunicationListItem[];
};

export type InboxClientGroup = {
  orgId: string;
  orgName: string;
  projects: InboxProjectGroup[];
  reportCount: number;
};

/** Group inbox rows as Client → Project → reports (preserves input order). */
export function groupReportsByClientAndProject(
  reports: CommunicationListItem[],
): InboxClientGroup[] {
  const clients: InboxClientGroup[] = [];
  const clientIndex = new Map<string, InboxClientGroup>();

  for (const report of reports) {
    const orgId = report.org_id || "unknown";
    const orgName = report.org_name?.trim() || "Unknown client";
    let client = clientIndex.get(orgId);
    if (!client) {
      client = { orgId, orgName, projects: [], reportCount: 0 };
      clientIndex.set(orgId, client);
      clients.push(client);
    }

    let project = client.projects.find((p) => p.projectId === report.project_id);
    if (!project) {
      project = {
        projectId: report.project_id,
        projectName: report.project_name,
        reports: [],
      };
      client.projects.push(project);
    }
    project.reports.push(report);
    client.reportCount += 1;
  }

  return clients;
}

/** Short display date for inbox / workspace chrome. */
export function formatReportDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** Prefer sent_at for sent reports; otherwise updated_at. */
export function reportListDate(item: {
  status: string;
  sent_at?: string | null;
  updated_at: string;
}): string {
  if (item.status === "sent" && item.sent_at) {
    return formatReportDate(item.sent_at);
  }
  return formatReportDate(item.updated_at);
}

export function userFacingReportsError(error: unknown, fallback: string): string {
  if (
    error &&
    typeof error === "object" &&
    "status" in error &&
    typeof (error as { status: unknown }).status === "number"
  ) {
    const status = (error as { status: number; message?: string }).status;
    if (status === 401 || status === 403) {
      return "You do not have permission to view these reports.";
    }
    if (status === 404) {
      return "This report is no longer available. It may have been deleted.";
    }
    if (typeof (error as { message?: string }).message === "string") {
      return (error as { message: string }).message;
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
