import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

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

  const detectGapsMutation = useMutation({
    mutationFn: () => detectProjectCapabilityGaps(projectId!),
    onSuccess: (result) => {
      setActionError(null);
      setDetectMessage(
        `${result.created_count} new gap(s) created (${result.detected_count} detected)`,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectCapabilityGaps(projectId!),
      });
    },
    onError: (error: Error) => {
      setDetectMessage(null);
      setActionError(error.message);
    },
  });

  const generateRecommendationsMutation = useMutation({
    mutationFn: () => generateWorkforceRecommendations(projectId!),
    onSuccess: (result) => {
      setActionError(null);
      setRecommendMessage(`${result.recommendations_created} recommendation(s) created`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectRecommendations(projectId!),
      });
    },
    onError: (error: Error) => {
      setRecommendMessage(null);
      setActionError(error.message);
    },
  });

  const triggerDetectGaps = () => {
    setDetectMessage(null);
    setRecommendMessage(null);
    detectGapsMutation.mutate();
  };

  const triggerGenerateRecommendations = () => {
    setDetectMessage(null);
    setRecommendMessage(null);
    generateRecommendationsMutation.mutate();
  };

  const handleGapStatusUpdate = async (gapId: string, status: CapabilityGapStatus) => {
    setUpdatingGapId(gapId);
    setActionError(null);
    try {
      await updateCapabilityGap(gapId, { status });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projectCapabilityGaps(projectId!),
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Failed to update gap.");
    } finally {
      setUpdatingGapId(null);
    }
  };

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
