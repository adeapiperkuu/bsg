import type {
  KnowledgeChunkApi,
  KnowledgeDocumentApi,
  KnowledgeFolderKind,
  KnowledgeIndexingStatusApi,
  KnowledgeProcessingStatusApi,
  KnowledgeQualityScoreApi,
  KnowledgeSourceTypeApi,
  KnowledgeStatusApi,
  KnowledgeVisibilityApi,
  KnowledgeWorkflowState,
} from "@/types/knowledge";

export type FolderName = string;
export type SourceType =
  | "SOP"
  | "Guide"
  | "Training Document"
  | "Project Charter"
  | "Escalation Note"
  | "Lesson Learned";
export type Visibility = "Internal-only" | "Leadership-only" | "Client-safe";
export type DocumentStatus = "Draft" | "Approved" | "Archived";
export type WorkflowState = "Needs review" | "Approved" | "Expired" | "Needs re-index" | "Archived";

export type KnowledgeChunk = {
  id: string;
  chunkIndex: number;
  sectionTitle: string | null;
  pageNumber: number | null;
  chunkText: string;
  tokenCount: number | null;
};

export type KnowledgeDocument = {
  id: string;
  title: string;
  folderId: string;
  folder: FolderName;
  folderKind: KnowledgeFolderKind;
  sourceType: SourceType;
  version: string;
  visibility: Visibility;
  status: DocumentStatus;
  workflowState: WorkflowState;
  owner: string;
  effectiveDate: string;
  fileName: string;
  fileType: string;
  fileUrl?: string | null;
  indexed: boolean;
  indexing: boolean;
  processingStatus: KnowledgeProcessingStatusApi;
  processingLabel: string;
  processingError?: string | null;
  preview: string[];
  qualityScore: KnowledgeQualityScoreApi | null;
  chunkCount: number;
  citationCount: number;
  approvedByName: string | null;
  approvedAt: string | null;
  chunks: KnowledgeChunk[];
  semanticRelevance: number | null;
};

const seedFolderToApi: Record<string, KnowledgeFolderKind> = {
  SOPs: "sops",
  Guides: "guides",
  Histories: "histories",
};

const sourceToApi: Record<SourceType, KnowledgeSourceTypeApi> = {
  SOP: "sop",
  Guide: "guide",
  "Training Document": "training_document",
  "Project Charter": "project_charter",
  "Escalation Note": "escalation_note",
  "Lesson Learned": "lesson_learned",
};

const sourceFromApi: Record<KnowledgeSourceTypeApi, SourceType> = {
  sop: "SOP",
  guide: "Guide",
  training_document: "Training Document",
  project_charter: "Project Charter",
  escalation_note: "Escalation Note",
  lesson_learned: "Lesson Learned",
};

const visibilityToApi: Record<Visibility, KnowledgeVisibilityApi> = {
  "Internal-only": "internal_only",
  "Leadership-only": "leadership_only",
  "Client-safe": "client_safe",
};

const visibilityFromApi: Record<KnowledgeVisibilityApi, Visibility> = {
  internal_only: "Internal-only",
  leadership_only: "Leadership-only",
  client_safe: "Client-safe",
};

const statusToApi: Record<DocumentStatus, KnowledgeStatusApi> = {
  Draft: "draft",
  Approved: "approved",
  Archived: "archived",
};

const workflowFromApi: Record<KnowledgeWorkflowState, WorkflowState> = {
  needs_review: "Needs review",
  approved: "Approved",
  expired: "Expired",
  needs_reindex: "Needs re-index",
  archived: "Archived",
};

function chunkFromApi(chunk: KnowledgeChunkApi): KnowledgeChunk {
  return {
    id: chunk.id,
    chunkIndex: chunk.chunk_index,
    sectionTitle: chunk.section_title,
    pageNumber: chunk.page_number,
    chunkText: chunk.chunk_text,
    tokenCount: chunk.token_count,
  };
}

const statusFromApi: Record<KnowledgeStatusApi, DocumentStatus> = {
  draft: "Draft",
  approved: "Approved",
  archived: "Archived",
};

export function workflowStateLabel(state: WorkflowState): string {
  return state;
}

export function folderNameToApi(folder: FolderName): KnowledgeFolderKind {
  return seedFolderToApi[folder] ?? "custom";
}

export function folderKindFromApi(kind: KnowledgeFolderKind, name?: string): FolderName {
  if (kind === "sops") return "SOPs";
  if (kind === "guides") return "Guides";
  if (kind === "histories") return "Histories";
  return name ?? "Folder";
}

export function documentToApiPatch(patch: Partial<KnowledgeDocument>) {
  return {
    title: patch.title,
    folder_id: patch.folderId,
    folder_kind: patch.folderKind ? patch.folderKind : patch.folder ? folderNameToApi(patch.folder) : undefined,
    source_type: patch.sourceType ? sourceToApi[patch.sourceType] : undefined,
    version: patch.version,
    visibility: patch.visibility ? visibilityToApi[patch.visibility] : undefined,
    status: patch.status ? statusToApi[patch.status] : undefined,
    owner_approver: patch.owner,
    effective_date: patch.effectiveDate || undefined,
  };
}

export function documentFromApi(row: KnowledgeDocumentApi): KnowledgeDocument {
  const indexing = ["uploaded", "extracting", "extracted", "chunking", "chunked", "embedding"].includes(
    row.processing_status,
  );
  const indexed = row.processing_status === "ready" || row.indexing_status === "indexed";
  const fileType = row.file_name.split(".").pop()?.toUpperCase() ?? "DOC";
  return {
    id: row.id,
    title: row.title,
    folderId: row.folder_id,
    folder: row.folder_name,
    folderKind: row.folder_kind,
    sourceType: sourceFromApi[row.source_type],
    version: row.version,
    visibility: visibilityFromApi[row.visibility],
    status: statusFromApi[row.status],
    workflowState: workflowFromApi[row.workflow_state] ?? "Needs review",
    owner: row.owner_approver,
    effectiveDate: row.effective_date ?? "",
    fileName: row.file_name,
    fileType,
    fileUrl: row.file_url,
    indexed,
    indexing,
    processingStatus: row.processing_status,
    processingLabel: processingStatusLabel(row.processing_status),
    processingError: row.processing_error,
    preview: row.preview ?? [],
    qualityScore: row.quality_score ?? null,
    chunkCount: row.chunk_count ?? 0,
    citationCount: row.citation_count ?? 0,
    approvedByName: row.approved_by_name ?? null,
    approvedAt: row.approved_at ?? null,
    chunks: (row.chunks ?? []).map(chunkFromApi),
    semanticRelevance: row.semantic_relevance ?? null,
  };
}

export function uploadFormToApi(form: {
  title: string;
  folderId: string;
  sourceType: SourceType;
  version: string;
  visibility: Visibility;
  status: DocumentStatus;
  owner: string;
  effectiveDate: string;
}) {
  return {
    title: form.title,
    folder_id: form.folderId,
    source_type: sourceToApi[form.sourceType],
    version: form.version,
    visibility: visibilityToApi[form.visibility],
    status: statusToApi[form.status],
    owner_approver: form.owner,
    effective_date: form.effectiveDate || undefined,
  };
}

export function isRetrievalReady(doc: KnowledgeDocument): boolean {
  return doc.status === "Approved" && doc.processingStatus === "ready" && doc.indexed && !doc.indexing;
}

export function processingStatusLabel(status: KnowledgeProcessingStatusApi): string {
  switch (status) {
    case "uploaded":
      return "Uploaded";
    case "extracting":
      return "Extracting...";
    case "extracted":
      return "Extracted";
    case "chunking":
      return "Chunking...";
    case "chunked":
      return "Chunked";
    case "embedding":
      return "Generating Embeddings...";
    case "ready":
      return "Ready";
    case "failed":
      return "Failed";
    default:
      return status;
  }
}
