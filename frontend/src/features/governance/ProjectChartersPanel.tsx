import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Archive, BookOpen, Download, FileText, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { AiBadge, Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useGovernanceJob } from "@/features/governance/useGovernanceJob";
import { formatDate } from "@/lib/governance-utils";
import { queryKeys } from "@/lib/queries/keys";
import {
  approveProjectCharter,
  archiveProjectCharter,
  exportProjectCharter,
  generateProjectCharter,
  getProjectCharter,
  governanceProjectChartersPanelQueryOptions,
  listProjectCharterPublicationVersions,
  publishProjectCharter,
  republishProjectCharter,
  retryProjectCharterPublication,
  unpublishProjectCharter,
  updateProjectCharter,
} from "@/lib/queries/governance";
import type {
  GovernanceCharterPublicationStatus,
  KnowledgeVisibility,
  ProjectCharter,
  ProjectChartersPanelData,
} from "@/types/governance";

const PROJECT_CHARTER_PAGE_SIZE = 5;

type ProjectOption = {
  value: string;
  label: string;
};

type ProjectChartersPanelProps = {
  projects: ProjectOption[];
  canWrite: boolean;
  canPublish?: boolean;
  isClient: boolean;
  isReadOnly: boolean;
  loadCharters?: boolean;
};

function formatCharterStatus(status: ProjectCharter["status"]): string {
  if (status === "approved") return "Approved";
  if (status === "archived") return "Archived";
  return "Draft";
}

function formatPublicationStatus(status: GovernanceCharterPublicationStatus | undefined): string {
  switch (status) {
    case "published":
      return "Published";
    case "publishing":
      return "Publishing";
    case "failed":
      return "Failed";
    case "superseded":
      return "Superseded";
    default:
      return "Not Published";
  }
}

function formatVisibility(value: KnowledgeVisibility): string {
  if (value === "client_safe") return "Client Safe";
  if (value === "leadership_only") return "Leadership Only";
  return "Internal Only";
}

function pickCurrentCharter(charters: ProjectCharter[]): ProjectCharter | null {
  return (
    charters.find((charter) => charter.status === "approved") ??
    charters.find((charter) => charter.status === "draft") ??
    charters[0] ??
    null
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function filenameFor(charter: ProjectCharter, format: "pdf" | "docx"): string {
  const project = (charter.project_name ?? "project")
    .replace(/[^a-z0-9]+/gi, "_")
    .replace(/^_+|_+$/g, "");
  return `${project || "project"}_charter_${charter.version}.${format}`;
}

export function ProjectChartersPanel({
  projects,
  canWrite,
  canPublish = false,
  isClient,
  isReadOnly,
  loadCharters = true,
}: ProjectChartersPanelProps) {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [activeCharterId, setActiveCharterId] = useState<string | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftVisibility, setDraftVisibility] = useState<KnowledgeVisibility>("internal_only");
  const [downloading, setDownloading] = useState<"pdf" | "docx" | null>(null);
  const [charterLimit, setCharterLimit] = useState(PROJECT_CHARTER_PAGE_SIZE);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      setSelectedProjectId(projects[0].value);
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    setActiveCharterId(null);
    setReviewOpen(false);
    setCharterLimit(PROJECT_CHARTER_PAGE_SIZE);
  }, [selectedProjectId]);

  const charterListParams = useMemo(
    () => ({
      projectId: selectedProjectId,
      selectedCharterId: activeCharterId,
      limit: charterLimit,
      offset: 0,
    }),
    [activeCharterId, charterLimit, selectedProjectId],
  );

  const panelQuery = useQuery({
    ...governanceProjectChartersPanelQueryOptions(charterListParams),
    enabled: Boolean(selectedProjectId) && loadCharters,
    placeholderData: keepPreviousData,
  });

  const hydrateGeneratedCharter = async (charterId: string) => {
    const charter = await getProjectCharter(charterId);
    setActiveCharterId(charter.id);
    queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
    queryClient.setQueriesData<ProjectChartersPanelData>(
      { queryKey: ["governance", "project-charters-panel"] },
      (existing) => {
        if (!existing) {
          return {
            charters: [
              {
                ...charter,
                generated_text: "",
                evidence_links: [],
              },
            ],
            selected_charter: charter,
            limit: PROJECT_CHARTER_PAGE_SIZE,
            offset: 0,
            has_more: false,
          };
        }
        const nextListRow = { ...charter, generated_text: "", evidence_links: [] };
        const charters = existing.charters.some((row) => row.id === charter.id)
          ? existing.charters.map((row) => (row.id === charter.id ? nextListRow : row))
          : [nextListRow, ...existing.charters];
        return {
          ...existing,
          charters,
          selected_charter: charter,
        };
      },
    );
    await queryClient.invalidateQueries({
      queryKey: ["governance", "project-charters"],
      refetchType: "inactive",
    });
  };

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["governance", "project-charters"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["governance", "project-charters-panel"],
      }),
    ]);
  };

  const refreshCharter = async (charterId?: string) => {
    const invalidations = [
      queryClient.invalidateQueries({
        queryKey: ["governance", "project-charters"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["governance", "project-charters-panel"],
      }),
    ];
    if (charterId) {
      invalidations.push(
        queryClient.invalidateQueries({
          queryKey: queryKeys.governanceProjectCharter(charterId),
        }),
      );
      invalidations.push(
        queryClient.invalidateQueries({
          queryKey: queryKeys.governanceProjectCharterVersions(charterId),
        }),
      );
    }
    await Promise.all(invalidations);
  };

  const generationJob = useGovernanceJob({
    jobType: "project_charter_generate",
    projectId: selectedProjectId,
    enabled: canWrite && Boolean(selectedProjectId) && loadCharters,
    onSucceeded: async (job) => {
      if (job.result_record_id) {
        await hydrateGeneratedCharter(job.result_record_id);
      } else {
        await refresh();
      }
      toast.success("Project charter draft generated for review.");
    },
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      generateProjectCharter({
        project_id: selectedProjectId,
        visibility: "internal_only",
      }),
    onSuccess: (started) => {
      generationJob.track(started);
      toast.message(
        started.deduplicated ? "Charter generation already active." : "Charter generation queued.",
      );
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to generate charter.");
    },
  });

  const saveMutation = useMutation({
    mutationFn: (payload: {
      id: string;
      generated_text: string;
      visibility: KnowledgeVisibility;
    }) =>
      updateProjectCharter(payload.id, {
        generated_text: payload.generated_text,
        visibility: payload.visibility,
      }),
    onSuccess: async (charter) => {
      toast.success("Charter draft saved.");
      setActiveCharterId(charter.id);
      queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
      await refreshCharter(charter.id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to save charter.");
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveProjectCharter(id),
    onSuccess: async (charter) => {
      toast.success("Project charter approved.");
      setActiveCharterId(charter.id);
      queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
      setApproveOpen(false);
      setReviewOpen(false);
      await refreshCharter(charter.id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to approve charter.");
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (id: string) => archiveProjectCharter(id),
    onSuccess: async (charter) => {
      toast.success("Project charter archived.");
      setActiveCharterId(charter.id);
      queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
      setArchiveOpen(false);
      setReviewOpen(false);
      await refreshCharter(charter.id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to archive charter.");
    },
  });

  const publishMutation = useMutation({
    mutationFn: (id: string) => publishProjectCharter(id),
    onSuccess: async (charter) => {
      toast.success("Charter published to Knowledge.");
      setActiveCharterId(charter.id);
      queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
      await refreshCharter(charter.id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to publish charter.");
    },
  });

  const retryPublishMutation = useMutation({
    mutationFn: (id: string) => retryProjectCharterPublication(id),
    onSuccess: async (charter) => {
      toast.success("Publication retry succeeded.");
      setActiveCharterId(charter.id);
      queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
      await refreshCharter(charter.id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to retry publication.");
    },
  });

  const republishMutation = useMutation({
    mutationFn: (id: string) => republishProjectCharter(id),
    onSuccess: async (charter) => {
      toast.success("Charter republished to Knowledge.");
      setActiveCharterId(charter.id);
      queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
      await refreshCharter(charter.id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to republish charter.");
    },
  });

  const unpublishMutation = useMutation({
    mutationFn: (id: string) => unpublishProjectCharter(id),
    onSuccess: async (charter) => {
      toast.success("Charter unpublished from Knowledge.");
      setActiveCharterId(charter.id);
      queryClient.setQueryData(queryKeys.governanceProjectCharter(charter.id), charter);
      await refreshCharter(charter.id);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to unpublish charter.");
    },
  });

  const charters = useMemo(() => panelQuery.data?.charters ?? [], [panelQuery.data?.charters]);
  const currentCharter = pickCurrentCharter(charters);
  const detailCharter = panelQuery.data?.selected_charter ?? null;
  const selectedListCharter =
    charters.find((charter) => charter.id === (activeCharterId ?? detailCharter?.id)) ??
    currentCharter;
  const selectedCharterId = activeCharterId ?? detailCharter?.id ?? selectedListCharter?.id ?? null;

  useEffect(() => {
    if (charters.length === 0) {
      setActiveCharterId(null);
      return;
    }
    if (!selectedCharterId || !charters.some((charter) => charter.id === selectedCharterId)) {
      setActiveCharterId(currentCharter?.id ?? null);
    }
  }, [charters, currentCharter?.id, selectedCharterId]);

  const displayCharter = detailCharter ?? selectedListCharter;
  const detailLoading = Boolean(selectedProjectId) && panelQuery.isLoading;

  useEffect(() => {
    setHistoryOpen(false);
  }, [displayCharter?.id]);

  const versionsQuery = useQuery({
    queryKey: queryKeys.governanceProjectCharterVersions(displayCharter?.id),
    queryFn: () => listProjectCharterPublicationVersions(displayCharter!.id),
    enabled: Boolean(displayCharter?.id) && loadCharters && historyOpen,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });

  const publicationStatus = displayCharter?.publication_status ?? "not_published";
  const showKnowledgePanel = Boolean(displayCharter && displayCharter.status !== "draft");
  const publishBusy =
    publishMutation.isPending ||
    retryPublishMutation.isPending ||
    republishMutation.isPending ||
    unpublishMutation.isPending;
  const canEditActive = canWrite && detailCharter?.status === "draft";
  const selectedVersionId = selectedCharterId ?? "";
  const canLoadOlderCharters = Boolean(panelQuery.data?.has_more);

  const openReview = (charter: ProjectCharter) => {
    setActiveCharterId(charter.id);
    setDraftText(charter.generated_text);
    setDraftVisibility(charter.visibility);
    setReviewOpen(true);
  };

  const download = async (charter: ProjectCharter, format: "pdf" | "docx") => {
    setDownloading(format);
    try {
      const blob = await exportProjectCharter(charter.id, format);
      downloadBlob(blob, filenameFor(charter, format));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Failed to export ${format.toUpperCase()}.`);
    } finally {
      setDownloading(null);
    }
  };

  if (projects.length === 0) {
    return null;
  }

  return (
    <>
      <Card className="flex h-[640px] flex-col overflow-hidden">
        <SectionHeader
          title="Project Charters"
          sub="AI-generated drafts, approval workflow, version history, and exports"
          right={
            <div className="flex min-w-48 flex-wrap items-center justify-end gap-2">
              <Select value={selectedProjectId} onValueChange={setSelectedProjectId}>
                <SelectTrigger className="h-8 w-56 text-xs">
                  <SelectValue placeholder="Select project" />
                </SelectTrigger>
                <SelectContent data-governance-select-content>
                  {projects.map((project) => (
                    <SelectItem key={project.value} value={project.value}>
                      {project.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={selectedVersionId}
                onValueChange={(charterId) => {
                  setActiveCharterId(charterId);
                }}
                disabled={charters.length === 0}
              >
                <SelectTrigger className="h-8 w-40 text-xs">
                  <SelectValue placeholder="Version history" />
                </SelectTrigger>
                <SelectContent data-governance-select-content>
                  {charters.map((charter) => (
                    <SelectItem key={charter.id} value={charter.id}>
                      {charter.version} · {formatCharterStatus(charter.status)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          }
        />

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 flex-col rounded-md border border-border bg-elevated p-3">
            {panelQuery.isLoading ? (
              <div
                role="status"
                aria-label="Loading project charters"
                className="flex flex-1 items-center justify-center text-muted-foreground"
              >
                <Loader2 className="h-4 w-4 animate-spin" />
              </div>
            ) : displayCharter ? (
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <StatusPill status={formatCharterStatus(displayCharter.status)} />
                  {displayCharter.generated_by_ai && <AiBadge label="AI Generated" />}
                  <span className="text-[10px] text-muted-foreground">
                    {displayCharter.version} generated {formatDate(displayCharter.created_at)}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    {formatVisibility(displayCharter.visibility)}
                  </span>
                </div>
                {displayCharter.approved_at && (
                  <p className="mb-2 text-[10px] text-muted-foreground">
                    Approved {formatDate(displayCharter.approved_at)}
                    {displayCharter.approved_by_name
                      ? ` by ${displayCharter.approved_by_name}`
                      : ""}
                  </p>
                )}
                {showKnowledgePanel && (
                  <div className="mb-2 rounded-lg border border-border bg-background/70 px-2.5 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="text-xs font-medium">Knowledge publication</span>
                      </div>
                      <StatusPill status={formatPublicationStatus(publicationStatus)} />
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                      <p>
                        Status: {formatPublicationStatus(publicationStatus)}
                        {displayCharter.knowledge_version_id
                          ? ` · Knowledge version ${displayCharter.version}`
                          : ""}
                      </p>
                      {displayCharter.published_at && (
                        <p>
                          Published {formatDate(displayCharter.published_at)}
                          {displayCharter.published_by_name
                            ? ` by ${displayCharter.published_by_name}`
                            : ""}
                        </p>
                      )}
                      {displayCharter.publication_error && (
                        <p className="text-destructive">{displayCharter.publication_error}</p>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {displayCharter.knowledge_document_id && (
                        <Button
                          asChild
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-6 px-2 text-[10px] shadow-none"
                        >
                          <a
                            href={
                              displayCharter.knowledge_url ??
                              `/knowledge?documentId=${displayCharter.knowledge_document_id}`
                            }
                          >
                            View Knowledge
                          </a>
                        </Button>
                      )}
                      {canPublish &&
                        displayCharter.status === "approved" &&
                        (publicationStatus === "not_published" ||
                          publicationStatus === "failed") && (
                          <Button
                            type="button"
                            size="sm"
                            className="h-6 px-2 text-[10px] shadow-none"
                            disabled={publishBusy}
                            onClick={() =>
                              publicationStatus === "failed"
                                ? retryPublishMutation.mutate(displayCharter.id)
                                : publishMutation.mutate(displayCharter.id)
                            }
                          >
                            {publishBusy ? (
                              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                            ) : (
                              <BookOpen className="mr-1 h-3 w-3" />
                            )}
                            {publicationStatus === "failed" ? "Retry" : "Publish"}
                          </Button>
                        )}
                      {canPublish && publicationStatus === "published" && (
                        <>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-[10px] shadow-none"
                            disabled={publishBusy}
                            onClick={() => republishMutation.mutate(displayCharter.id)}
                          >
                            {republishMutation.isPending ? (
                              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                            ) : (
                              <RefreshCw className="mr-1 h-3 w-3" />
                            )}
                            Republish
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-[10px] shadow-none"
                            disabled={publishBusy}
                            onClick={() => unpublishMutation.mutate(displayCharter.id)}
                          >
                            {unpublishMutation.isPending ? (
                              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                            ) : (
                              <BookOpen className="mr-1 h-3 w-3" />
                            )}
                            Unpublish
                          </Button>
                        </>
                      )}
                    </div>
                    <div className="mt-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-5 px-0 text-[10px] text-muted-foreground hover:text-foreground"
                        aria-expanded={historyOpen}
                        onClick={() => setHistoryOpen((open) => !open)}
                      >
                        {historyOpen ? "Hide version history" : "Show version history"}
                      </Button>
                    </div>
                    {historyOpen && (
                      <div className="mt-3 border-t border-border pt-2">
                        <p className="mb-1 text-[10px] font-medium text-muted-foreground">
                          Version history
                        </p>
                        {versionsQuery.isLoading ? (
                          <p className="text-[10px] text-muted-foreground">Loading history...</p>
                        ) : versionsQuery.isError ? (
                          <div className="flex items-center gap-2">
                            <p className="text-[10px] text-destructive">Could not load history.</p>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-6 text-[10px]"
                              onClick={() => void versionsQuery.refetch()}
                            >
                              Retry
                            </Button>
                          </div>
                        ) : (versionsQuery.data?.length ?? 0) > 0 ? (
                          <ul className="space-y-1 text-[10px] text-muted-foreground">
                            {versionsQuery.data?.map((version) => (
                              <li key={version.charter_id} className="flex flex-wrap gap-x-2">
                                <span>
                                  {version.charter_version} ·{" "}
                                  {formatPublicationStatus(version.publication_status)}
                                </span>
                                {version.knowledge_url && version.knowledge_document_id && (
                                  <a href={version.knowledge_url} className="underline">
                                    Open
                                  </a>
                                )}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-[10px] text-muted-foreground">
                            No publication history yet.
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {detailLoading ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading charter details...
                    </div>
                  ) : panelQuery.isError ? (
                    <div className="space-y-2 text-sm text-muted-foreground">
                      <p>Could not load charter details.</p>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 text-[11px]"
                        onClick={() => void panelQuery.refetch()}
                      >
                        Retry
                      </Button>
                    </div>
                  ) : (
                    <DeliveryMarkdown content={detailCharter?.generated_text ?? ""} />
                  )}
                </div>
                <div className="mt-3 flex shrink-0 flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    disabled={!detailCharter}
                    onClick={() => detailCharter && openReview(detailCharter)}
                  >
                    <FileText className="mr-1 h-3 w-3" />
                    Review draft
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    disabled={downloading === "pdf"}
                    onClick={() => void download(displayCharter, "pdf")}
                  >
                    <Download className="mr-1 h-3 w-3" />
                    PDF
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    disabled={downloading === "docx"}
                    onClick={() => void download(displayCharter, "docx")}
                  >
                    <Download className="mr-1 h-3 w-3" />
                    DOCX
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-1 items-center text-sm text-muted-foreground">
                No project charter exists for this project yet.
              </div>
            )}

            <div className="mt-3 flex shrink-0 flex-wrap gap-2">
              {canWrite && (
                <Button
                  type="button"
                  size="sm"
                  disabled={
                    !selectedProjectId || generateMutation.isPending || generationJob.active
                  }
                  onClick={() => generateMutation.mutate()}
                >
                  {generateMutation.isPending || generationJob.active ? (
                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Sparkles className="mr-1 h-3.5 w-3.5" />
                  )}
                  Generate charter
                </Button>
              )}
              {isReadOnly && (
                <span className="self-center text-[10px] text-muted-foreground">
                  Approved charters only. Drafts are hidden from leadership.
                </span>
              )}
              {isClient && (
                <span className="self-center text-[10px] text-muted-foreground">
                  Client-safe approved charters only.
                </span>
              )}
              {canLoadOlderCharters && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11px]"
                  disabled={panelQuery.isFetching}
                  onClick={() => setCharterLimit((limit) => limit + PROJECT_CHARTER_PAGE_SIZE)}
                >
                  Load older versions
                </Button>
              )}
            </div>
          </div>
        </div>
      </Card>

      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent className="governance-no-shadow max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Review project charter</DialogTitle>
          </DialogHeader>
          {detailCharter && (
            <div className="space-y-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill status={formatCharterStatus(detailCharter.status)} />
                <span className="text-muted-foreground">{detailCharter.version}</span>
                {detailCharter.generated_by_ai && <AiBadge label="AI Generated" />}
              </div>
              {canEditActive ? (
                <>
                  <div className="max-w-xs">
                    <Label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
                      Visibility
                    </Label>
                    <Select
                      value={draftVisibility}
                      onValueChange={(value) => setDraftVisibility(value as KnowledgeVisibility)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent data-governance-select-content>
                        <SelectItem value="internal_only">Internal Only</SelectItem>
                        <SelectItem value="client_safe">Client Safe</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <Textarea
                    rows={20}
                    value={draftText}
                    onChange={(event) => setDraftText(event.target.value)}
                    className="font-mono text-xs"
                  />
                </>
              ) : (
                <DeliveryMarkdown
                  content={detailCharter.generated_text}
                  className="rounded border border-border bg-elevated p-3"
                />
              )}

              {detailCharter.evidence_links.length > 0 && (
                <div className="rounded border border-border p-3">
                  <div className="mb-2 font-semibold">Evidence</div>
                  <ul className="max-h-40 space-y-1 overflow-y-auto text-muted-foreground">
                    {detailCharter.evidence_links.map((link) => (
                      <li key={link.id}>
                        {link.label ?? link.source_id}
                        {link.project_name ? ` - ${link.project_name}` : ""}
                        {link.detail ? ` - ${link.detail}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setReviewOpen(false)}>
              Close
            </Button>
            {detailCharter && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  disabled={downloading === "pdf"}
                  onClick={() => void download(detailCharter, "pdf")}
                >
                  PDF
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={downloading === "docx"}
                  onClick={() => void download(detailCharter, "docx")}
                >
                  DOCX
                </Button>
              </>
            )}
            {canWrite && detailCharter?.status !== "archived" && (
              <Button type="button" variant="outline" onClick={() => setArchiveOpen(true)}>
                <Archive className="mr-1 h-3.5 w-3.5" />
                Archive
              </Button>
            )}
            {canEditActive && detailCharter && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  disabled={saveMutation.isPending || !draftText.trim()}
                  onClick={() =>
                    saveMutation.mutate({
                      id: detailCharter.id,
                      generated_text: draftText.trim(),
                      visibility: draftVisibility,
                    })
                  }
                >
                  {saveMutation.isPending ? "Saving..." : "Save draft"}
                </Button>
                <Button type="button" onClick={() => setApproveOpen(true)}>
                  Approve
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={approveOpen} onOpenChange={setApproveOpen}>
        <AlertDialogContent className="governance-no-shadow">
          <AlertDialogHeader>
            <AlertDialogTitle>Approve project charter?</AlertDialogTitle>
            <AlertDialogDescription>
              Approved charters become official and read-only. A future regeneration creates a new
              draft version instead of overwriting this one.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={approveMutation.isPending || !detailCharter}
              onClick={() => detailCharter && approveMutation.mutate(detailCharter.id)}
            >
              {approveMutation.isPending ? "Approving..." : "Approve"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={archiveOpen} onOpenChange={setArchiveOpen}>
        <AlertDialogContent className="governance-no-shadow">
          <AlertDialogHeader>
            <AlertDialogTitle>Archive charter version?</AlertDialogTitle>
            <AlertDialogDescription>
              The version stays in history but is marked archived.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={archiveMutation.isPending || !detailCharter}
              onClick={() => detailCharter && archiveMutation.mutate(detailCharter.id)}
            >
              {archiveMutation.isPending ? "Archiving..." : "Archive"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
