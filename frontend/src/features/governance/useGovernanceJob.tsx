import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelGovernanceJob,
  governanceJobQueryOptions,
  governanceJobsQueryOptions,
  retryGovernanceJob,
} from "@/lib/queries/governance";
import type { GovernanceJob, GovernanceJobStart } from "@/types/governance";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function useGovernanceJob({
  jobType,
  projectId,
  enabled = true,
  pollIntervalMs = 3000,
  onSucceeded,
}: {
  jobType: string;
  projectId?: string | null;
  enabled?: boolean;
  pollIntervalMs?: number;
  onSucceeded: (job: GovernanceJob) => void | Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const completedRef = useRef<string | null>(null);
  const onSucceededRef = useRef(onSucceeded);
  onSucceededRef.current = onSucceeded;

  useEffect(() => {
    setJobId(null);
    completedRef.current = null;
  }, [jobType, projectId]);

  const discoveryQuery = useQuery({
    ...governanceJobsQueryOptions({
      job_type: jobType,
      project_id: projectId || undefined,
      active_only: true,
      limit: 1,
    }),
    enabled: enabled && !jobId,
  });

  useEffect(() => {
    const discovered = discoveryQuery.data?.[0];
    if (discovered) setJobId(discovered.id);
  }, [discoveryQuery.data]);

  const jobQuery = useQuery({
    ...governanceJobQueryOptions(jobId ?? ""),
    enabled: enabled && Boolean(jobId),
    refetchInterval: (query) => {
      const job = query.state.data;
      return job && TERMINAL.has(job.status) ? false : pollIntervalMs;
    },
  });
  const job = jobQuery.data;

  useEffect(() => {
    if (job?.status !== "succeeded" || completedRef.current === job.id) return;
    completedRef.current = job.id;
    void onSucceededRef.current(job);
  }, [job]);

  const cancelMutation = useMutation({
    mutationFn: () => cancelGovernanceJob(jobId!),
    onSuccess: (updated) =>
      queryClient.setQueryData(governanceJobQueryOptions(updated.id).queryKey, updated),
  });
  const retryMutation = useMutation({
    mutationFn: () => retryGovernanceJob(jobId!),
    onSuccess: (updated) => {
      completedRef.current = null;
      queryClient.setQueryData(governanceJobQueryOptions(updated.id).queryKey, updated);
    },
  });

  const track = useCallback((started: GovernanceJobStart) => {
    completedRef.current = null;
    setJobId(started.job_id);
  }, []);
  const active =
    enabled && (discoveryQuery.isLoading || Boolean(jobId && (!job || !TERMINAL.has(job.status))));

  return {
    job,
    active,
    discovering: discoveryQuery.isLoading,
    track,
    cancel: () => cancelMutation.mutate(),
    retry: () => retryMutation.mutate(),
    controlBusy: cancelMutation.isPending || retryMutation.isPending,
  };
}
