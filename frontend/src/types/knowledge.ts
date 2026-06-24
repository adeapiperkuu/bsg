export type KnowledgeFolderKind = "sops" | "guides" | "histories";
export type KnowledgeSourceTypeApi =
  | "sop"
  | "guide"
  | "training_document"
  | "project_charter"
  | "escalation_note"
  | "lesson_learned";
export type KnowledgeVisibilityApi = "internal_only" | "leadership_only" | "client_safe";
export type KnowledgeStatusApi = "draft" | "approved" | "archived";
export type KnowledgeIndexingStatusApi = "not_indexed" | "indexing" | "indexed" | "failed";
export type KnowledgeProcessingStatusApi =
  | "uploaded"
  | "extracting"
  | "extracted"
  | "chunking"
  | "chunked"
  | "embedding"
  | "ready"
  | "failed";

export interface KnowledgeDocumentApi {
  id: string;
  folder_id: string;
  folder_name: string;
  folder_kind: KnowledgeFolderKind;
  title: string;
  source_type: KnowledgeSourceTypeApi;
  version: string;
  visibility: KnowledgeVisibilityApi;
  status: KnowledgeStatusApi;
  owner_approver: string;
  effective_date: string | null;
  file_name: string;
  file_mime_type: string;
  file_url: string | null;
  processing_status: KnowledgeProcessingStatusApi;
  processing_error: string | null;
  indexing_status: KnowledgeIndexingStatusApi;
  preview: string[];
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCitationApi {
  document_id: string;
  chunk_id: string | null;
  citation_label: string;
  title: string;
  source_type: string;
  version: string;
  folder_name: string;
  folder_kind: string;
  relevance_score: number;
  page_number: number | null;
  chunk_index: number | null;
}

export interface KnowledgeAskResponseApi {
  answer_text: string;
  next_step: string;
  confidence_score: number;
  citations: KnowledgeCitationApi[];
  query_id: string | null;
  model_used: string | null;
}
