import { describe, expect, it } from "vitest";

import {
  allowedActionsForStatus,
  canEditCommunication,
  COMMUNICATION_STATUS_LABELS,
  COMMUNICATION_TYPE_LABELS,
  isCommunicationReadOnly,
  statusLabel,
  statusPillFor,
  typeLabel,
} from "@/features/reports/report-status";
import type { CommunicationStatus } from "@/types/communications";

describe("report-status labels", () => {
  it("maps API statuses to UI labels", () => {
    expect(statusLabel("draft")).toBe("Draft");
    expect(statusLabel("in_review")).toBe("In review");
    expect(statusLabel("approved")).toBe("Approved");
    expect(statusLabel("sent")).toBe("Sent");
    expect(statusLabel("rejected")).toBe("Rejected");
    expect(COMMUNICATION_STATUS_LABELS.in_review).not.toBe("Pending");
    expect(COMMUNICATION_STATUS_LABELS.in_review).toBe("In review");
  });

  it("maps inbox filter Pending to API in_review", async () => {
    const { inboxFilterToApiStatus, COMMUNICATION_STATUS_FILTER_LABELS } = await import(
      "@/features/reports/report-status"
    );
    expect(COMMUNICATION_STATUS_FILTER_LABELS.in_review).toBe("Pending");
    expect(inboxFilterToApiStatus("in_review")).toBe("in_review");
    expect(inboxFilterToApiStatus("all")).toBeUndefined();
  });

  it("maps report types to UI labels", () => {
    expect(typeLabel("weekly_summary")).toBe("Weekly Status");
    expect(typeLabel("executive_summary")).toBe("Executive Summary");
    expect(typeLabel("ad_hoc")).toBe("Ad hoc Update");
    expect(COMMUNICATION_TYPE_LABELS.weekly_summary).toBe("Weekly Status");
  });

  it("maps statuses to StatusPill meanings", () => {
    expect(statusPillFor("draft")).toBe("In Progress");
    expect(statusPillFor("in_review")).toBe("Warning");
    expect(statusPillFor("approved")).toBe("On Track");
    expect(statusPillFor("sent")).toBe("On Track");
    expect(statusPillFor("rejected")).toBe("At Risk");
  });
});

describe("report-status allowed actions", () => {
  const cases: Array<{
    status: CommunicationStatus;
    expected: string[];
    readOnly: boolean;
  }> = [
    {
      status: "draft",
      expected: ["edit", "submit_review", "approve", "reject"],
      readOnly: false,
    },
    {
      status: "in_review",
      expected: ["edit", "submit_review", "approve", "reject"],
      readOnly: false,
    },
    {
      status: "approved",
      expected: ["send"],
      readOnly: false,
    },
    {
      status: "sent",
      expected: [],
      readOnly: true,
    },
    {
      status: "rejected",
      expected: ["generate_new"],
      readOnly: true,
    },
  ];

  it.each(cases)(
    "$status allows $expected and readOnly=$readOnly",
    ({ status, expected, readOnly }) => {
      expect([...allowedActionsForStatus(status)].sort()).toEqual([...expected].sort());
      expect(isCommunicationReadOnly(status)).toBe(readOnly);
      expect(canEditCommunication(status)).toBe(expected.includes("edit"));
    },
  );
});
