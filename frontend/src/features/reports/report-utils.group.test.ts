import { describe, expect, it } from "vitest";

import { groupReportsByClientAndProject } from "@/features/reports/report-utils";
import type { CommunicationListItem } from "@/types/communications";

function item(
  overrides: Partial<CommunicationListItem> & Pick<CommunicationListItem, "id">,
): CommunicationListItem {
  return {
    project_id: "proj-1",
    project_name: "Annotation Sprint 13",
    org_id: "org1",
    org_name: "Northwind Analytics",
    comm_type: "weekly_summary",
    subject: "Weekly",
    status: "draft",
    created_at: "2026-07-16T10:00:00Z",
    updated_at: "2026-07-16T12:00:00Z",
    sent_at: null,
    evidence_link_count: 0,
    ...overrides,
  };
}

describe("groupReportsByClientAndProject", () => {
  it("groups reports under client then project", () => {
    const groups = groupReportsByClientAndProject([
      item({ id: "a", project_id: "p1", project_name: "Sprint 13" }),
      item({ id: "b", project_id: "p2", project_name: "Ops 39" }),
      item({
        id: "c",
        project_id: "p1",
        project_name: "Sprint 13",
        subject: "Second",
      }),
      item({
        id: "d",
        org_id: "org2",
        org_name: "Helix Mobility",
        project_id: "p3",
        project_name: "Helios",
      }),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({
      orgId: "org1",
      orgName: "Northwind Analytics",
      reportCount: 3,
    });
    expect(groups[0].projects).toHaveLength(2);
    expect(groups[0].projects[0].reports.map((r) => r.id)).toEqual(["a", "c"]);
    expect(groups[0].projects[1].reports.map((r) => r.id)).toEqual(["b"]);
    expect(groups[1].orgName).toBe("Helix Mobility");
  });
});
