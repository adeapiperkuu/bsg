import type {
  KnowledgeExtractionScoreBreakdownApi,
  KnowledgeLibraryAnalyticsApi,
  KnowledgeChunkApi,
  KnowledgeDocumentApi,
  KnowledgeDocumentSummaryApi,
  KnowledgeFolderKind,
  KnowledgeIndexingStatusApi,
  KnowledgeProcessingStatusApi,
  KnowledgeQualityScoreApi,
  KnowledgeRetrievalActionApi,
  KnowledgeRetrievalReadinessReasonApi,
  KnowledgeSourceTypeApi,
  KnowledgeStatusApi,
  KnowledgeVisibilityApi,
  KnowledgeWorkflowState,
} from "@/types/knowledge";

export type SourceType =
  | "SOP"
  | "Guide"
  | "Training Document"
  | "Project Charter"
  | "Escalation Note"
  | "Lesson Learned";
export type Visibility = "Internal-only" | "Leadership-only" | "Restricted" | "Client-safe";
export type DocumentStatus =
  | "Draft"
  | "Submitted for review"
  | "Approved"
  | "Rejected"
  | "Needs re-index"
  | "Expired"
  | "Archived";
export type WorkflowState = "Needs review" | "Approved" | "Expired" | "Needs re-index" | "Archived";
export type RetrievalReadinessReason = KnowledgeRetrievalReadinessReasonApi | string;
export type RetrievalAction = KnowledgeRetrievalActionApi;

export type KnowledgeChunk = {
  id: string;
  documentId: string;
  chunkIndex: number;
  totalChunks: number | null;
  previousChunkId: string | null;
  nextChunkId: string | null;
  sectionTitle: string | null;
  sectionPath: string | null;
  headingLevel: number | null;
  pageNumber: number | null;
  chunkText: string;
  tokenCount: number | null;
  chunkSummary: string | null;
  chunkType: string;
  isTable: boolean;
  containsProcedure: boolean;
  containsWarning: boolean;
  containsDecision: boolean;
  containsChecklist: boolean;
  containsTable: boolean;
  containsRoles: boolean;
  containsDates: boolean;
  sourceType: string | null;
  folderName: string | null;
  project: string | null;
  department: string | null;
  effectiveDate: string | null;
  ownerApprover: string | null;
};

export type KnowledgeExtractionScoreBreakdown = {
  headingCoverage: number;
  ocrConfidence: number;
  metadataCompleteness: number;
  tableQuality: number;
  sectionBalance: number;
  duplicatePenalty: number;
  emptyPageRatio: number;
  imageRatio: number;
  operationalKeywordDensity: number;
  overall: number;
};

export type KnowledgeLibraryAnalytics = {
  averageChunkTokens: number;
  largestChunkTokens: number;
  smallestChunkTokens: number;
  headingCount: number;
  tableCount: number;
  warningCount: number;
  entityCount: number;
  estimatedRetrievalQuality: number;
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
  retrievalReady: boolean;
  retrievalReadinessReason: RetrievalReadinessReason;
  retrievalAction: RetrievalAction | null;
  owner: string;
  effectiveDate: string;
  expiryDate: string;
  submittedAt: string | null;
  reviewedAt: string | null;
  rejectionReason: string | null;
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
  qualityWarnings: string[];
  extractionQualityScore: number | null;
  extractionScoreBreakdown: KnowledgeExtractionScoreBreakdown | null;
  libraryAnalytics: KnowledgeLibraryAnalytics | null;
  ocrNeeded: boolean;
  reindexRecommended: boolean;
  chunkCount: number;
  citationCount: number;
  approvedByName: string | null;
  approvedAt: string | null;
  executiveSummary: string | null;
  keyProcedures: string[];
  importantWarnings: string[];
  affectedDepartments: string[];
  relatedDocumentIds: string[];
  summaryGeneratedAt: string | null;
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
  Restricted: "restricted",
  "Client-safe": "client_safe",
};

const visibilityFromApi: Record<KnowledgeVisibilityApi, Visibility> = {
  internal_only: "Internal-only",
  leadership_only: "Leadership-only",
  restricted: "Restricted",
  client_safe: "Client-safe",
};

const statusToApi: Record<DocumentStatus, KnowledgeStatusApi> = {
  Draft: "draft",
  "Submitted for review": "submitted_for_review",
  Approved: "approved",
  Rejected: "rejected",
  "Needs re-index": "needs_reindex",
  Expired: "expired",
  Archived: "archived",
};

const workflowFromApi: Record<KnowledgeWorkflowState, WorkflowState> = {
  needs_review: "Needs review",
  approved: "Approved",
  expired: "Expired",
  needs_reindex: "Needs re-index",
  archived: "Archived",
};

export const workflowToApi: Record<WorkflowState, KnowledgeWorkflowState> = {
  "Needs review": "needs_review",
  Approved: "approved",
  Expired: "expired",
  "Needs re-index": "needs_reindex",
  Archived: "archived",
};

function scoreBreakdownFromApi(
  row: KnowledgeExtractionScoreBreakdownApi | null | undefined,
): KnowledgeExtractionScoreBreakdown | null {
  if (!row) return null;
  return {
    headingCoverage: row.heading_coverage,
    ocrConfidence: row.ocr_confidence,
    metadataCompleteness: row.metadata_completeness,
    tableQuality: row.table_quality,
    sectionBalance: row.section_balance,
    duplicatePenalty: row.duplicate_penalty,
    emptyPageRatio: row.empty_page_ratio,
    imageRatio: row.image_ratio,
    operationalKeywordDensity: row.operational_keyword_density,
    overall: row.overall,
  };
}

function libraryAnalyticsFromApi(
  row: KnowledgeLibraryAnalyticsApi | null | undefined,
): KnowledgeLibraryAnalytics | null {
  if (!row) return null;
  return {
    averageChunkTokens: row.average_chunk_tokens,
    largestChunkTokens: row.largest_chunk_tokens,
    smallestChunkTokens: row.smallest_chunk_tokens,
    headingCount: row.heading_count,
    tableCount: row.table_count,
    warningCount: row.warning_count,
    entityCount: row.entity_count,
    estimatedRetrievalQuality: row.estimated_retrieval_quality,
  };
}

function chunkFromApi(chunk: KnowledgeChunkApi): KnowledgeChunk {
  return {
    id: chunk.id,
    documentId: chunk.document_id,
    chunkIndex: chunk.chunk_index,
    totalChunks: chunk.total_chunks ?? null,
    previousChunkId: chunk.previous_chunk_id ?? null,
    nextChunkId: chunk.next_chunk_id ?? null,
    sectionTitle: chunk.section_title,
    sectionPath: chunk.section_path ?? null,
    headingLevel: chunk.heading_level ?? null,
    pageNumber: chunk.page_number,
    chunkText: chunk.chunk_text,
    tokenCount: chunk.token_count,
    chunkSummary: chunk.chunk_summary ?? null,
    chunkType: chunk.chunk_type ?? "text",
    isTable: chunk.is_table ?? chunk.chunk_type === "table",
    containsProcedure: chunk.contains_procedure ?? false,
    containsWarning: chunk.contains_warning ?? false,
    containsDecision: chunk.contains_decision ?? false,
    containsChecklist: chunk.contains_checklist ?? false,
    containsTable: chunk.contains_table ?? false,
    containsRoles: chunk.contains_roles ?? false,
    containsDates: chunk.contains_dates ?? false,
    sourceType: chunk.source_type ?? null,
    folderName: chunk.folder_name ?? null,
    project: chunk.project ?? null,
    department: chunk.department ?? null,
    effectiveDate: chunk.effective_date ?? null,
    ownerApprover: chunk.owner_approver ?? null,
  };
}

const statusFromApi: Record<KnowledgeStatusApi, DocumentStatus> = {
  draft: "Draft",
  submitted_for_review: "Submitted for review",
  approved: "Approved",
  rejected: "Rejected",
  needs_reindex: "Needs re-index",
  expired: "Expired",
  archived: "Archived",
};

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
    owner_approver: patch.owner,
    effective_date: patch.effectiveDate || undefined,
    expiry_date: patch.expiryDate || undefined,
  };
}

export function documentSummaryFromApi(row: KnowledgeDocumentSummaryApi): KnowledgeDocument {
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
    retrievalReady: row.retrieval_ready ?? false,
    retrievalReadinessReason: row.retrieval_readiness_reason ?? "Needs approval",
    retrievalAction: row.retrieval_action ?? null,
    owner: row.owner_approver,
    effectiveDate: row.effective_date ?? "",
    expiryDate: row.expiry_date ?? "",
    submittedAt: row.submitted_at ?? null,
    reviewedAt: row.reviewed_at ?? null,
    rejectionReason: row.rejection_reason ?? null,
    fileName: row.file_name,
    fileType,
    fileUrl: null,
    indexed,
    indexing,
    processingStatus: row.processing_status,
    processingLabel: processingStatusLabel(row.processing_status),
    processingError: row.processing_error,
    preview: [],
    qualityScore: null,
    qualityWarnings: [],
    extractionQualityScore: null,
    extractionScoreBreakdown: null,
    libraryAnalytics: null,
    ocrNeeded: false,
    reindexRecommended: false,
    chunkCount: 0,
    citationCount: 0,
    approvedByName: null,
    approvedAt: null,
    executiveSummary: null,
    keyProcedures: [],
    importantWarnings: [],
    affectedDepartments: [],
    relatedDocumentIds: [],
    summaryGeneratedAt: null,
    chunks: [],
    semanticRelevance: null,
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
    retrievalReady: row.retrieval_ready ?? false,
    retrievalReadinessReason: row.retrieval_readiness_reason ?? "Needs approval",
    retrievalAction: row.retrieval_action ?? null,
    owner: row.owner_approver,
    effectiveDate: row.effective_date ?? "",
    expiryDate: row.expiry_date ?? "",
    submittedAt: row.submitted_at ?? null,
    reviewedAt: row.reviewed_at ?? null,
    rejectionReason: row.rejection_reason ?? null,
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
    qualityWarnings: row.quality_warnings ?? [],
    extractionQualityScore: row.extraction_quality_score ?? null,
    extractionScoreBreakdown: scoreBreakdownFromApi(row.extraction_score_breakdown),
    libraryAnalytics: libraryAnalyticsFromApi(row.library_analytics),
    ocrNeeded: row.ocr_needed ?? false,
    reindexRecommended: row.reindex_recommended ?? false,
    chunkCount: row.chunk_count ?? 0,
    citationCount: row.citation_count ?? 0,
    approvedByName: row.approved_by_name ?? null,
    approvedAt: row.approved_at ?? null,
    executiveSummary: row.executive_summary ?? null,
    keyProcedures: row.key_procedures ?? [],
    importantWarnings: row.important_warnings ?? [],
    affectedDepartments: row.affected_departments ?? [],
    relatedDocumentIds: row.related_document_ids ?? [],
    summaryGeneratedAt: row.summary_generated_at ?? null,
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
  owner: string;
  effectiveDate: string;
}) {
  return {
    title: form.title,
    folder_id: form.folderId,
    source_type: sourceToApi[form.sourceType],
    version: form.version,
    visibility: visibilityToApi[form.visibility],
    status: "draft" as const,
    owner_approver: form.owner,
    effective_date: form.effectiveDate || undefined,
  };
}

export function isRetrievalReady(doc: KnowledgeDocument): boolean {
  if (typeof doc.retrievalReady === "boolean") {
    return doc.retrievalReady;
  }
  return doc.status === "Approved" && doc.processingStatus === "ready" && doc.indexed && !doc.indexing;
}

export function retrievalActionLabel(action: RetrievalAction | null | undefined): string | null {
  switch (action) {
    case "approve":
      return "Approve document";
    case "reindex":
      return "Re-index document";
    case "edit_metadata":
      return "Edit metadata";
    case "retry_processing":
      return "Retry processing";
    default:
      return null;
  }
}

export function readinessBadgeTone(
  reason: RetrievalReadinessReason,
): "success" | "danger" | "info" | "warning" {
  if (reason === "Ready") return "success";
  if (reason === "Processing failed" || reason === "Expired") return "danger";
  if (reason === "Needs re-index") return "info";
  return "warning";
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
