import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { listKnowledgeDocuments } from "@/lib/api";
import type { KnowledgeDocumentApi } from "@/types/knowledge";
import type {
  GovernanceAction,
  GovernanceBootstrap,
  GovernanceEscalation,
  GovernanceEscalationSeverity,
  GovernanceEscalationSourceType,
  ProjectDependency,
  ProjectScopeState,
} from "@/types/governance";

export type WorkflowDialogState =
  | { kind: "dependency"; mode: "create" | "edit"; projectId?: string; id?: string }
  | { kind: "action"; mode: "create" | "edit"; projectId?: string; id?: string }
  | { kind: "escalation"; mode: "create" | "edit"; projectId?: string; id?: string }
  | { kind: "scope"; mode: "edit"; projectId: string }
  | null;

type Option = { value: string; label: string };

type GovernanceWorkflowDialogsProps = {
  dialog: WorkflowDialogState;
  onClose: () => void;
  data: GovernanceBootstrap;
  projects: Option[];
  users: Option[];
  canWrite: boolean;
  onSaveDependency: (payload: {
    projectId: string;
    id?: string;
    values: Record<string, string | null>;
  }) => Promise<void>;
  onSaveAction: (payload: {
    projectId: string;
    id?: string;
    values: Record<string, string | null>;
  }) => Promise<void>;
  onSaveEscalation: (payload: {
    projectId: string;
    id?: string;
    values: Record<string, string | null>;
  }) => Promise<void>;
  onSaveScope: (payload: {
    projectId: string;
    values: Record<string, string | null>;
  }) => Promise<void>;
};

function approvedDocs(
  docs: KnowledgeDocumentApi[],
  sourceTypes?: string[],
): KnowledgeDocumentApi[] {
  return docs.filter(
    (doc) =>
      doc.workflow_state === "approved" &&
      doc.status === "approved" &&
      (!sourceTypes || sourceTypes.includes(doc.source_type)),
  );
}

function docLabel(doc: KnowledgeDocumentApi): string {
  return `${doc.title} (${doc.version})`;
}

export function GovernanceWorkflowDialogs({
  dialog,
  onClose,
  data,
  projects,
  users,
  canWrite,
  onSaveDependency,
  onSaveAction,
  onSaveEscalation,
  onSaveScope,
}: GovernanceWorkflowDialogsProps) {
  const [saving, setSaving] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [assignedTo, setAssignedTo] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [status, setStatus] = useState("");
  const [dependencyType, setDependencyType] = useState("internal");
  const [severity, setSeverity] = useState<GovernanceEscalationSeverity>("medium");
  const [scopeStatus, setScopeStatus] = useState("approved");
  const [versionLabel, setVersionLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [linkedDocId, setLinkedDocId] = useState("");
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDocumentApi[]>([]);

  useEffect(() => {
    if (!dialog || !canWrite) return;
    void listKnowledgeDocuments({ workflowState: "approved" })
      .then(setKnowledgeDocs)
      .catch(() => setKnowledgeDocs([]));
  }, [dialog, canWrite]);

  useEffect(() => {
    if (!dialog) return;

    const reset = () => {
      setTitle("");
      setDescription("");
      setProjectId(dialog.kind !== "scope" ? (dialog.projectId ?? "") : dialog.projectId);
      setOwnerId("");
      setAssignedTo("");
      setDueDate("");
      setStatus("");
      setDependencyType("internal");
      setSeverity("medium");
      setScopeStatus("approved");
      setVersionLabel("");
      setNotes("");
      setLinkedDocId("");
    };

    if (dialog.mode === "create") {
      reset();
      if (dialog.kind === "dependency") setStatus("open");
      if (dialog.kind === "action") setStatus("open");
      if (dialog.kind === "escalation") setStatus("open");
      return;
    }

    if (dialog.kind === "dependency" && dialog.id) {
      const dep = data.dependencies.find((d) => d.id === dialog.id);
      if (!dep) return;
      fillDependency(dep);
      return;
    }
    if (dialog.kind === "action" && dialog.id) {
      const action = data.actions.find((a) => a.id === dialog.id);
      if (!action) return;
      fillAction(action);
      return;
    }
    if (dialog.kind === "escalation" && dialog.id) {
      const esc = data.escalations.find((e) => e.id === dialog.id);
      if (!esc) return;
      fillEscalation(esc);
      return;
    }
    if (dialog.kind === "scope") {
      const scope = data.scope_states.find((s) => s.project_id === dialog.projectId);
      if (!scope) {
        reset();
        return;
      }
      fillScope(scope);
    }

    function fillDependency(dep: ProjectDependency) {
      setTitle(dep.title);
      setDescription(dep.description ?? "");
      setProjectId(dep.project_id);
      setOwnerId(dep.owner_id ?? "");
      setDueDate(dep.due_date ?? "");
      setStatus(dep.status);
      setDependencyType(dep.dependency_type);
    }

    function fillAction(action: GovernanceAction) {
      setTitle(action.title);
      setDescription(action.description ?? "");
      setProjectId(action.project_id);
      setOwnerId(action.owner_id ?? "");
      setDueDate(action.due_date ?? "");
      setStatus(action.status);
      setLinkedDocId(action.linked_knowledge_document_id ?? "");
    }

    function fillEscalation(esc: GovernanceEscalation) {
      setTitle(esc.title);
      setDescription(esc.description ?? "");
      setProjectId(esc.project_id);
      setAssignedTo(esc.assigned_to ?? "");
      setStatus(esc.status);
      setSeverity(esc.severity);
      if (esc.source_type === "knowledge_document" && esc.source_id) {
        setLinkedDocId(esc.source_id);
      }
    }

    function fillScope(scope: ProjectScopeState) {
      setProjectId(scope.project_id);
      setScopeStatus(scope.scope_status);
      setVersionLabel(scope.version_label);
      setNotes(scope.notes ?? "");
      setLinkedDocId(scope.linked_charter_document_id ?? "");
    }
  }, [dialog, data]);

  if (!dialog || !canWrite) return null;

  const charterDocs = approvedDocs(knowledgeDocs, ["project_charter"]);
  const escalationNoteDocs = approvedDocs(knowledgeDocs, ["escalation_note"]);
  const pmNoteDocs = approvedDocs(knowledgeDocs, ["guide", "sop", "training_document"]);

  const handleSave = async () => {
    if (dialog.kind !== "scope" && !title.trim()) {
      toast.error("Title is required.");
      return;
    }
    if (!projectId) {
      toast.error("Project is required.");
      return;
    }
    if (dialog.kind === "dependency" && !dueDate) {
      toast.error("Due date is required for dependencies.");
      return;
    }
    if (dialog.kind === "action") {
      if (!dueDate) {
        toast.error("Due date is required for actions.");
        return;
      }
      if (!ownerId) {
        toast.error("Owner is required for actions.");
        return;
      }
    }
    if (dialog.kind === "escalation" && !severity) {
      toast.error("Severity is required for escalations.");
      return;
    }

    setSaving(true);
    try {
      if (dialog.kind === "dependency") {
        await onSaveDependency({
          projectId,
          id: dialog.mode === "edit" ? dialog.id : undefined,
          values: {
            title: title.trim(),
            description: description || null,
            dependency_type: dependencyType,
            owner_id: ownerId || null,
            due_date: dueDate,
            status,
          },
        });
      } else if (dialog.kind === "action") {
        await onSaveAction({
          projectId,
          id: dialog.mode === "edit" ? dialog.id : undefined,
          values: {
            title: title.trim(),
            description: description || null,
            owner_id: ownerId,
            due_date: dueDate,
            status,
            linked_knowledge_document_id: linkedDocId || null,
          },
        });
      } else if (dialog.kind === "escalation") {
        const existing = dialog.id ? data.escalations.find((e) => e.id === dialog.id) : undefined;
        const sourceType: GovernanceEscalationSourceType | null =
          existing?.source_type === "delivery_risk"
            ? "delivery_risk"
            : linkedDocId
              ? "knowledge_document"
              : null;
        const sourceId =
          existing?.source_type === "delivery_risk"
            ? (existing.source_id ?? null)
            : linkedDocId || null;

        await onSaveEscalation({
          projectId,
          id: dialog.mode === "edit" ? dialog.id : undefined,
          values: {
            title: title.trim(),
            description: description || null,
            severity,
            status,
            assigned_to: assignedTo || null,
            source_type: sourceType,
            source_id: sourceId,
          },
        });
      } else if (dialog.kind === "scope") {
        await onSaveScope({
          projectId,
          values: {
            scope_status: scopeStatus,
            version_label: versionLabel,
            notes: notes || null,
            linked_charter_document_id: linkedDocId || null,
          },
        });
      }
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const titles: Record<string, string> = {
    dependency: dialog.mode === "create" ? "Create dependency" : "Edit dependency",
    action: dialog.mode === "create" ? "Create action" : "Edit action",
    escalation: dialog.mode === "create" ? "Create escalation" : "Edit escalation",
    scope: "Update scope",
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="governance-no-shadow max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{titles[dialog.kind]}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {dialog.kind !== "scope" && (
            <>
              <div>
                <Label>Title *</Label>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} />
              </div>
              <div>
                <Label>Description</Label>
                <Textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
            </>
          )}

          {dialog.kind !== "scope" && (
            <div>
              <Label>Project *</Label>
              <Select
                value={projectId}
                onValueChange={setProjectId}
                disabled={dialog.mode === "edit"}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select project" />
                </SelectTrigger>
                <SelectContent data-governance-select-content>
                  {projects.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {dialog.kind === "dependency" && (
            <>
              <div>
                <Label>Type</Label>
                <Select value={dependencyType} onValueChange={setDependencyType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="client_action">Client Action</SelectItem>
                    <SelectItem value="internal">Internal</SelectItem>
                    <SelectItem value="external">External</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Owner</Label>
                <Select
                  value={ownerId || "none"}
                  onValueChange={(v) => setOwnerId(v === "none" ? "" : v)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Unassigned" />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="none">Unassigned</SelectItem>
                    {users.map((u) => (
                      <SelectItem key={u.value} value={u.value}>
                        {u.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Due date *</Label>
                <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </div>
              <div>
                <Label>Status</Label>
                <Select value={status} onValueChange={setStatus}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="open">Open</SelectItem>
                    <SelectItem value="blocking">Blocking</SelectItem>
                    <SelectItem value="resolved">Resolved</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {dialog.kind === "action" && (
            <>
              <div>
                <Label>Owner *</Label>
                <Select value={ownerId} onValueChange={setOwnerId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select owner" />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    {users.map((u) => (
                      <SelectItem key={u.value} value={u.value}>
                        {u.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Due date *</Label>
                <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </div>
              <div>
                <Label>Status</Label>
                <Select value={status} onValueChange={setStatus}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="open">Open</SelectItem>
                    <SelectItem value="in_progress">In Progress</SelectItem>
                    <SelectItem value="completed">Completed</SelectItem>
                    <SelectItem value="overdue">Overdue</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Linked PM note (approved)</Label>
                <Select
                  value={linkedDocId || "none"}
                  onValueChange={(v) => setLinkedDocId(v === "none" ? "" : v)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="none">None</SelectItem>
                    {pmNoteDocs.map((doc) => (
                      <SelectItem key={doc.id} value={doc.id}>
                        {docLabel(doc)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {dialog.kind === "escalation" && (
            <>
              <div>
                <Label>Severity *</Label>
                <Select
                  value={severity}
                  onValueChange={(v) => setSeverity(v as GovernanceEscalationSeverity)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="critical">Critical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Status</Label>
                <Select value={status} onValueChange={setStatus}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="open">Open</SelectItem>
                    <SelectItem value="in_progress">In Progress</SelectItem>
                    <SelectItem value="resolved">Resolved</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Assigned to</Label>
                <Select
                  value={assignedTo || "none"}
                  onValueChange={(v) => setAssignedTo(v === "none" ? "" : v)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Unassigned" />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="none">Unassigned</SelectItem>
                    {users.map((u) => (
                      <SelectItem key={u.value} value={u.value}>
                        {u.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {!(
                dialog.mode === "edit" &&
                data.escalations.find((e) => e.id === dialog.id)?.source_type === "delivery_risk"
              ) && (
                <div>
                  <Label>Linked escalation note (approved)</Label>
                  <Select
                    value={linkedDocId || "none"}
                    onValueChange={(v) => setLinkedDocId(v === "none" ? "" : v)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="None" />
                    </SelectTrigger>
                    <SelectContent data-governance-select-content>
                      <SelectItem value="none">None</SelectItem>
                      {escalationNoteDocs.map((doc) => (
                        <SelectItem key={doc.id} value={doc.id}>
                          {docLabel(doc)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </>
          )}

          {dialog.kind === "scope" && (
            <>
              <div>
                <Label>Scope status</Label>
                <Select value={scopeStatus} onValueChange={setScopeStatus}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="approved">Approved</SelectItem>
                    <SelectItem value="pending_revision">Pending Revision</SelectItem>
                    <SelectItem value="locked">Locked</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Version label</Label>
                <Input value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} />
              </div>
              <div>
                <Label>Notes</Label>
                <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
              </div>
              <div>
                <Label>Linked charter (approved)</Label>
                <Select
                  value={linkedDocId || "none"}
                  onValueChange={(v) => setLinkedDocId(v === "none" ? "" : v)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent data-governance-select-content>
                    <SelectItem value="none">None</SelectItem>
                    {charterDocs.map((doc) => (
                      <SelectItem key={doc.id} value={doc.id}>
                        {docLabel(doc)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleSave()} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
