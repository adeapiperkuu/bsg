import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import {
  detectProjectCapabilityGaps,
  generateWorkforceRecommendations,
  updateCapabilityGap,
} from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import type { CapabilityGapStatus } from "@/types/workforce";

export function useWorkforceCapabilityGapActions(projectId: string | null) {
  const queryClient = useQueryClient();
  const [detectMessage, setDetectMessage] = useState<string | null>(null);
  const [recommendMessage, setRecommendMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [updatingGapId, setUpdatingGapId] = useState<string | null>(null);
  const actionInFlightRef = useRef(false);

  const invalidateDashboard = useCallback(() => {
    if (!projectId) return;
    void queryClient.invalidateQueries({
      queryKey: queryKeys.projectWorkforceDashboard(projectId),
      exact: true,
    });
  }, [projectId, queryClient]);

  const detectGapsMutation = useMutation({
    mutationFn: () => detectProjectCapabilityGaps(projectId!),
    onSuccess: (result) => {
      setActionError(null);
      setDetectMessage(
        `${result.created_count} new gap(s) created (${result.detected_count} detected)`,
      );
      if (!projectId) return;
      invalidateDashboard();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectCapabilityGaps(projectId),
        exact: true,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
        exact: true,
      });
    },
    onError: (error: Error) => {
      setDetectMessage(null);
      setActionError(error.message);
    },
    onSettled: () => {
      actionInFlightRef.current = false;
    },
  });

  const generateRecommendationsMutation = useMutation({
    mutationFn: () => generateWorkforceRecommendations(projectId!),
    onSuccess: (result) => {
      setActionError(null);
      setRecommendMessage(`${result.recommendations_created} recommendation(s) created`);
      if (!projectId) return;
      invalidateDashboard();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectRecommendations(projectId),
        exact: true,
      });
    },
    onError: (error: Error) => {
      setRecommendMessage(null);
      setActionError(error.message);
    },
    onSettled: () => {
      actionInFlightRef.current = false;
    },
  });

  const triggerDetectGaps = useCallback(() => {
    if (!projectId || actionInFlightRef.current) return;
    actionInFlightRef.current = true;
    setDetectMessage(null);
    setRecommendMessage(null);
    detectGapsMutation.mutate();
  }, [projectId, detectGapsMutation]);

  const triggerGenerateRecommendations = useCallback(() => {
    if (!projectId || actionInFlightRef.current) return;
    actionInFlightRef.current = true;
    setDetectMessage(null);
    setRecommendMessage(null);
    generateRecommendationsMutation.mutate();
  }, [projectId, generateRecommendationsMutation]);

  const handleGapStatusUpdate = useCallback(
    async (gapId: string, status: CapabilityGapStatus) => {
      if (!projectId || updatingGapId) return;
      setUpdatingGapId(gapId);
      setActionError(null);
      try {
        await updateCapabilityGap(gapId, { status });
        invalidateDashboard();
        void queryClient.invalidateQueries({
          queryKey: queryKeys.projectCapabilityGaps(projectId),
          exact: true,
        });
      } catch (error) {
        setActionError(error instanceof Error ? error.message : "Failed to update gap.");
      } finally {
        setUpdatingGapId(null);
      }
    },
    [invalidateDashboard, projectId, queryClient, updatingGapId],
  );

  return {
    detectMessage,
    recommendMessage,
    actionError,
    updatingGapId,
    detectGapsMutation,
    generateRecommendationsMutation,
    triggerDetectGaps,
    triggerGenerateRecommendations,
    handleGapStatusUpdate,
  };
}
