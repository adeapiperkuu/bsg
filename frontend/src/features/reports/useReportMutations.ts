/**
 * Mutation hooks for PM communication lifecycle (Phases 4–5).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  approveCommunication as approveCommunicationApi,
  createCommunicationDraft,
  rejectCommunication as rejectCommunicationApi,
  reviewCommunication as reviewCommunicationApi,
  sendCommunication as sendCommunicationApi,
  updateCommunication as updateCommunicationApi,
} from "@/lib/api";
import { reportQueryKeys } from "@/features/reports/useReportsQueries";
import type {
  CommunicationApproveRequest,
  CommunicationContentUpdateRequest,
  CommunicationDetail,
  CommunicationDraftRequest,
  CommunicationListItem,
  CommunicationReviewRequest,
  ListCommunicationsResult,
} from "@/types/communications";

function toListItem(
  detail: CommunicationDetail,
  extras?: {
    projectName?: string | null;
    orgId?: string | null;
    orgName?: string | null;
  },
): CommunicationListItem {
  return {
    id: detail.id,
    project_id: detail.project_id,
    project_name: extras?.projectName || detail.project_name || "Project",
    org_id: extras?.orgId || "",
    org_name: extras?.orgName || "",
    comm_type: detail.comm_type,
    subject: detail.subject,
    status: detail.status,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
    sent_at: detail.sent_at,
    evidence_link_count: detail.evidence_links?.length ?? 0,
  };
}

function applyDetailToCaches(
  queryClient: ReturnType<typeof useQueryClient>,
  response: CommunicationDetail,
  extras?: {
    projectName?: string | null;
    orgId?: string | null;
    orgName?: string | null;
  },
) {
  const enriched = {
    ...response,
    project_name: extras?.projectName ?? response.project_name,
  };
  queryClient.setQueryData(reportQueryKeys.detail(response.id), enriched);

  const listItem = toListItem(response, extras);
  queryClient.setQueriesData<ListCommunicationsResult>(
    { queryKey: reportQueryKeys.lists() },
    (previous) => {
      if (!previous) return previous;
      const idx = previous.data.findIndex((row) => row.id === listItem.id);
      if (idx === -1) {
        return {
          ...previous,
          data: [listItem, ...previous.data],
        };
      }
      const existing = previous.data[idx];
      const next = [...previous.data];
      next[idx] = {
        ...existing,
        ...listItem,
        org_id: listItem.org_id || existing.org_id,
        org_name: listItem.org_name || existing.org_name,
        project_name: listItem.project_name || existing.project_name,
      };
      return { ...previous, data: next };
    },
  );

  void queryClient.invalidateQueries({ queryKey: reportQueryKeys.lists() });
}

export type DraftCommunicationArgs = {
  projectId: string;
  payload: CommunicationDraftRequest;
  projectName?: string;
  orgId?: string;
  orgName?: string;
};

export function useDraftCommunicationMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      projectId,
      payload,
    }: DraftCommunicationArgs): Promise<CommunicationDetail> =>
      createCommunicationDraft(projectId, payload),
    onSuccess: (response, variables) => {
      applyDetailToCaches(queryClient, response, {
        projectName: variables.projectName,
        orgId: variables.orgId,
        orgName: variables.orgName,
      });
      toast.success("Draft generated.");
    },
  });
}

export async function draftCommunication(
  mutateAsync: ReturnType<typeof useDraftCommunicationMutation>["mutateAsync"],
  projectId: string,
  payload: CommunicationDraftRequest,
  projectName?: string,
  org?: { orgId?: string; orgName?: string },
): Promise<CommunicationDetail> {
  return mutateAsync({
    projectId,
    payload,
    projectName,
    orgId: org?.orgId,
    orgName: org?.orgName,
  });
}

export function useUpdateReportMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      communicationId: string;
      payload: CommunicationContentUpdateRequest;
      projectName?: string | null;
    }): Promise<CommunicationDetail> =>
      updateCommunicationApi(args.communicationId, args.payload),
    onSuccess: (data, variables) => {
      applyDetailToCaches(queryClient, data, { projectName: variables.projectName });
      toast.success("Report saved.");
    },
  });
}

export function useReviewReportMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      communicationId: string;
      payload: CommunicationReviewRequest;
      projectName?: string | null;
    }): Promise<CommunicationDetail> =>
      reviewCommunicationApi(args.communicationId, args.payload),
    onSuccess: (data, variables) => {
      applyDetailToCaches(queryClient, data, { projectName: variables.projectName });
      toast.success("Submitted for review.");
    },
  });
}

export function useApproveReportMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      communicationId: string;
      payload?: CommunicationApproveRequest;
      projectName?: string | null;
    }): Promise<CommunicationDetail> =>
      approveCommunicationApi(args.communicationId, args.payload),
    onSuccess: (data, variables) => {
      applyDetailToCaches(queryClient, data, { projectName: variables.projectName });
      toast.success("Report approved. Send it separately to publish to the client.");
    },
  });
}

export function useRejectReportMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      communicationId: string;
      projectName?: string | null;
    }): Promise<CommunicationDetail> => rejectCommunicationApi(args.communicationId),
    onSuccess: (data, variables) => {
      applyDetailToCaches(queryClient, data, { projectName: variables.projectName });
      toast.success("Report rejected.");
    },
  });
}

export function useSendReportMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      communicationId: string;
      projectName?: string | null;
    }): Promise<CommunicationDetail> => sendCommunicationApi(args.communicationId),
    onSuccess: (data, variables) => {
      applyDetailToCaches(queryClient, data, { projectName: variables.projectName });
      toast.success("Report sent to the client.");
    },
  });
}

/** Named helpers matching the Phase 5 contract. */
export async function reviewCommunication(
  mutateAsync: ReturnType<typeof useReviewReportMutation>["mutateAsync"],
  id: string,
  payload: CommunicationReviewRequest,
  projectName?: string | null,
): Promise<CommunicationDetail> {
  return mutateAsync({ communicationId: id, payload, projectName });
}

export async function approveCommunication(
  mutateAsync: ReturnType<typeof useApproveReportMutation>["mutateAsync"],
  id: string,
  payload?: CommunicationApproveRequest,
  projectName?: string | null,
): Promise<CommunicationDetail> {
  return mutateAsync({ communicationId: id, payload, projectName });
}

export async function rejectCommunication(
  mutateAsync: ReturnType<typeof useRejectReportMutation>["mutateAsync"],
  id: string,
  _payload?: unknown,
  projectName?: string | null,
): Promise<CommunicationDetail> {
  return mutateAsync({ communicationId: id, projectName });
}

export async function sendCommunication(
  mutateAsync: ReturnType<typeof useSendReportMutation>["mutateAsync"],
  id: string,
  projectName?: string | null,
): Promise<CommunicationDetail> {
  return mutateAsync({ communicationId: id, projectName });
}

/** Convenience bundle for ReportsPage / workspace wiring. */
export function useReportMutations(_projectId: string | null = null) {
  return {
    draftCommunication: useDraftCommunicationMutation(),
    update: useUpdateReportMutation(),
    review: useReviewReportMutation(),
    approve: useApproveReportMutation(),
    reject: useRejectReportMutation(),
    send: useSendReportMutation(),
  };
}
