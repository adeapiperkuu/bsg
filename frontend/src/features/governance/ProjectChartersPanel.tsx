import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Archive, Download, FileText, Loader2, Sparkles } from "lucide-react";
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
import { formatDate } from "@/lib/governance-utils";
import {
  approveProjectCharter,
  archiveProjectCharter,
  exportProjectCharter,
  generateProjectCharter,
  listProjectCharters,
  updateProjectCharter,
} from "@/lib/queries/governance";
import type { KnowledgeVisibility, ProjectCharter } from "@/types/governance";

type ProjectOption = {
  value: string;
  label: string;
};

type ProjectChartersPanelProps = {
  projects: ProjectOption[];
  canWrite: boolean;
  isClient: boolean;
  isReadOnly: boolean;
  loadCharters?: boolean;
};

function formatCharterStatus(status: ProjectCharter["status"]): string {
  if (status === "approved") return "Approved";
  if (status === "archived") return "Archived";
  return "Draft";
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
  isClient,
  isReadOnly,
  loadCharters = true,
}: ProjectChartersPanelProps) {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [activeCharter, setActiveCharter] = useState<ProjectCharter | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftVisibility, setDraftVisibility] = useState<KnowledgeVisibility>("internal_only");
  const [downloading, setDownloading] = useState<"pdf" | "docx" | null>(null);

  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      setSelectedProjectId(projects[0].value);
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    setActiveCharter(null);
    setReviewOpen(false);
  }, [selectedProjectId]);

  const chartersQuery = useQuery({
    queryKey: ["governance", "project-charters", selectedProjectId],
    queryFn: () => listProjectCharters(selectedProjectId),
    enabled: Boolean(selectedProjectId) && loadCharters,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["governance", "project-charters", selectedProjectId],
    });
  };

  const generateMutation = useMutation({
    mutationFn: () =>
      generateProjectCharter({
        project_id: selectedProjectId,
        visibility: "internal_only",
      }),
    onSuccess: async (charter) => {
      toast.success("Project charter draft generated.");
      setActiveCharter(charter);
      setDraftText(charter.generated_text);
      setDraftVisibility(charter.visibility);
      setReviewOpen(true);
      await refresh();
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
      setActiveCharter(charter);
      await refresh();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to save charter.");
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveProjectCharter(id),
    onSuccess: async (charter) => {
      toast.success("Project charter approved.");
      setActiveCharter(charter);
      setApproveOpen(false);
      setReviewOpen(false);
      await refresh();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to approve charter.");
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (id: string) => archiveProjectCharter(id),
    onSuccess: async () => {
      toast.success("Project charter archived.");
      setArchiveOpen(false);
      setReviewOpen(false);
      await refresh();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to archive charter.");
    },
  });

  const charters = useMemo(() => chartersQuery.data ?? [], [chartersQuery.data]);
  const currentCharter = pickCurrentCharter(charters);
  const displayCharter = activeCharter ?? currentCharter;
  const canEditActive = canWrite && activeCharter?.status === "draft";
  const selectedVersionId = displayCharter?.id ?? "";

  const openReview = (charter: ProjectCharter) => {
    setActiveCharter(charter);
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
      <Card>
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
                  const charter = charters.find((item) => item.id === charterId);
                  setActiveCharter(charter ?? null);
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

        <div>
          <div className="rounded-md border border-border bg-elevated p-3">
            {chartersQuery.isLoading ? (
              <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading charters...
              </div>
            ) : displayCharter ? (
              <>
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
                <div className="max-h-72 overflow-y-auto">
                  <DeliveryMarkdown content={displayCharter.generated_text} />
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    onClick={() => openReview(displayCharter)}
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
              </>
            ) : (
              <div className="py-8 text-sm text-muted-foreground">
                No project charter exists for this project yet.
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              {canWrite && (
                <Button
                  type="button"
                  size="sm"
                  disabled={!selectedProjectId || generateMutation.isPending}
                  onClick={() => generateMutation.mutate()}
                >
                  {generateMutation.isPending ? (
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
            </div>
          </div>
        </div>
      </Card>

      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent className="governance-no-shadow max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Review project charter</DialogTitle>
          </DialogHeader>
          {activeCharter && (
            <div className="space-y-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill status={formatCharterStatus(activeCharter.status)} />
                <span className="text-muted-foreground">{activeCharter.version}</span>
                {activeCharter.generated_by_ai && <AiBadge label="AI Generated" />}
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
                  content={activeCharter.generated_text}
                  className="rounded border border-border bg-elevated p-3"
                />
              )}

              {activeCharter.evidence_links.length > 0 && (
                <div className="rounded border border-border p-3">
                  <div className="mb-2 font-semibold">Evidence</div>
                  <ul className="max-h-40 space-y-1 overflow-y-auto text-muted-foreground">
                    {activeCharter.evidence_links.map((link) => (
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
            {activeCharter && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  disabled={downloading === "pdf"}
                  onClick={() => void download(activeCharter, "pdf")}
                >
                  PDF
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={downloading === "docx"}
                  onClick={() => void download(activeCharter, "docx")}
                >
                  DOCX
                </Button>
              </>
            )}
            {canWrite && activeCharter?.status !== "archived" && (
              <Button type="button" variant="outline" onClick={() => setArchiveOpen(true)}>
                <Archive className="mr-1 h-3.5 w-3.5" />
                Archive
              </Button>
            )}
            {canEditActive && activeCharter && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  disabled={saveMutation.isPending || !draftText.trim()}
                  onClick={() =>
                    saveMutation.mutate({
                      id: activeCharter.id,
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
              disabled={approveMutation.isPending || !activeCharter}
              onClick={() => activeCharter && approveMutation.mutate(activeCharter.id)}
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
              disabled={archiveMutation.isPending || !activeCharter}
              onClick={() => activeCharter && archiveMutation.mutate(activeCharter.id)}
            >
              {archiveMutation.isPending ? "Archiving..." : "Archive"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
