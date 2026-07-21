import { describe, expect, it } from "vitest";

import { deriveCommunicationCapabilities, canAccessPmReportsRoute } from "@/features/reports/reportPermissions";
import type { MeUser } from "@/types/auth";

function user(overrides: Partial<MeUser> & Pick<MeUser, "role" | "permissions">): MeUser {
  return {
    id: "u1",
    email: "t@example.com",
    full_name: "T",
    org_id: "o1",
    is_active: true,
    organisation: null,
    ...overrides,
  };
}

const approvePerms = {
  can_manage_projects: true,
  can_approve_communications: true,
  can_manage_metric_configurations: false,
  can_view_cross_client_portfolio: false,
  can_manage_users: false,
  can_manage_organisations: false,
};

const noApprovePerms = { ...approvePerms, can_approve_communications: false, can_manage_projects: false };

describe("reportPermissions", () => {
  it("gives DM full workflow capabilities via can_approve_communications", () => {
    const caps = deriveCommunicationCapabilities(
      user({ role: "delivery_manager", permissions: approvePerms }),
    );
    expect(caps.canGenerateCommunications).toBe(true);
    expect(caps.canReviewCommunications).toBe(true);
    expect(caps.canApproveCommunications).toBe(true);
    expect(caps.canRejectCommunications).toBe(true);
    expect(caps.canSendCommunications).toBe(true);
    expect(caps.canAccessReportsWorkflow).toBe(true);
    expect(caps.isReportsReadOnly).toBe(false);
  });

  it("treats leadership as read-only when approve capability is false", () => {
    const caps = deriveCommunicationCapabilities(
      user({ role: "bsg_leadership", permissions: noApprovePerms }),
    );
    expect(caps.canGenerateCommunications).toBe(false);
    expect(caps.canAccessReportsWorkflow).toBe(true);
    expect(caps.isReportsReadOnly).toBe(true);
  });

  it("denies client PM reports route access", () => {
    expect(canAccessPmReportsRoute("client")).toBe(false);
    expect(canAccessPmReportsRoute("delivery_manager")).toBe(true);
  });
});
