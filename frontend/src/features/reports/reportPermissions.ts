import type { AppRole, MeUser } from "@/types/auth";
import type { CommunicationCapabilities } from "@/types/communications";

/**
 * Derive PM reports capabilities from `/me`.
 *
 * `/me` currently exposes `can_approve_communications` for delivery_manager /
 * super_admin. Backend mutations for generate/edit/review/approve/reject/send
 * all use the same role gate, so this flag covers the full PM workflow.
 * Leadership may read the inbox without action capabilities.
 */
export function deriveCommunicationCapabilities(
  user: MeUser | null | undefined,
): CommunicationCapabilities {
  const role = user?.role;
  const canApprove = user?.permissions.can_approve_communications ?? false;
  const isWorkflowRole = role === "delivery_manager" || role === "super_admin";
  const isLeadership = role === "bsg_leadership";

  return {
    canGenerateCommunications: canApprove,
    canReviewCommunications: canApprove,
    canApproveCommunications: canApprove,
    canRejectCommunications: canApprove,
    canSendCommunications: canApprove,
    canAccessReportsWorkflow: isWorkflowRole || isLeadership || canApprove,
    isReportsReadOnly: isLeadership && !canApprove,
  };
}

export function canAccessPmReportsRoute(role: AppRole | undefined): boolean {
  if (!role) return false;
  return role === "delivery_manager" || role === "super_admin" || role === "bsg_leadership";
}
