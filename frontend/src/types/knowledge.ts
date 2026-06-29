export type KnowledgeFolderKind = "sops" | "guides" | "histories" | "custom";
export type KnowledgeWorkflowState =
  | "needs_review"
  | "approved"
  | "expired"
  | "needs_reindex"
  | "archived";
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

export interface KnowledgeQualityCriterionApi {
  key: string;
  label: string;
  passed: boolean;
}

export interface KnowledgeQualityScoreApi {
  score: number;
  max_score: number;
  criteria: KnowledgeQualityCriterionApi[];
}

export interface KnowledgeChunkApi {
  id: string;
  chunk_index: number;
  section_title: string | null;
  page_number: number | null;
  chunk_text: string;
  token_count: number | null;
}

export interface KnowledgeFolderApi {
  id: string;
  name: string;
  folder_kind: KnowledgeFolderKind;
  display_order: number;
}

export interface KnowledgeBootstrapApi {
  folders: KnowledgeFolderApi[];
  documents: KnowledgeDocumentApi[];
  library_health: KnowledgeLibraryHealthApi;
}

export interface KnowledgeGapTodoApi {
  id: string;
  query_text: string;
  message: string;
  suggested_title: string | null;
  suggested_source_type: string | null;
  suggested_folder_kind: string | null;
  agent_query_id: string | null;
  created_at: string;
}

export interface KnowledgeLibraryHealthApi {
  ready_count: number;
  needs_review_count: number;
  expired_count: number;
  needs_reindex_count: number;
  indexing_count: number;
  draft_count: number;
  archived_count: number;
  open_gaps: KnowledgeGapTodoApi[];
}

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
  workflow_state: KnowledgeWorkflowState;
  quality_score: KnowledgeQualityScoreApi | null;
  quality_warnings: string[];
  chunk_count: number;
  citation_count: number;
  approved_by_name: string | null;
  approved_at: string | null;
  chunks: KnowledgeChunkApi[];
  semantic_relevance: number | null;
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
  chunk_preview: string;
  section_title: string | null;
}

export interface KnowledgeStructuredAnswerApi {
  policy: string;
  steps: string;
  owner: string;
  evidence: string;
  next_action: string;
}

export type KnowledgeConversationRoleApi = "user" | "assistant";

export interface KnowledgeConversationTurnApi {
  role: KnowledgeConversationRoleApi;
  content: string;
}

export interface KnowledgeGapApi {
  message: string;
  suggested_title: string | null;
  suggested_source_type: string | null;
  suggested_folder_kind: string | null;
}

export interface KnowledgeAskResponseApi {
  answer_text: string;
  next_step: string;
  confidence_score: number;
  confidence_reasons: string[];
  structured_answer: KnowledgeStructuredAnswerApi | null;
  knowledge_gap: KnowledgeGapApi | null;
  citations: KnowledgeCitationApi[];
  query_id: string | null;
  model_used: string | null;
  retrieval_debug?: KnowledgeRetrievalDebugApi | null;
}

export type KnowledgeAnswerModeApi = "internal" | "client_safe";

export interface KnowledgeRetrievalDebugSourceApi {
  document_id: string;
  chunk_id: string;
  title: string;
  relevance_score: number;
  vector_score: number;
  keyword_score: number;
}

export interface KnowledgeRetrievalDebugApi {
  query_text?: string;
  retrieval_query?: string;
  answer_mode?: KnowledgeAnswerModeApi | string;
  include_histories?: boolean;
  max_sources?: number;
  min_relevance_score?: number;
  project?: string | null;
  department?: string | null;
  eligible_doc_count?: number;
  has_embeddings?: boolean;
  confidence_score?: number;
  sources?: KnowledgeRetrievalDebugSourceApi[];
}

export interface KnowledgeDocumentVersionApi {
  id: string;
  version: string;
  is_active: boolean;
  uploaded_at: string;
  uploaded_by_name: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  checksum_sha256: string | null;
  chunk_count: number;
}

export interface KnowledgeVersionCompareApi {
  left_version: string;
  right_version: string;
  left_approved_by: string | null;
  right_approved_by: string | null;
  summary: string;
  added_sections: string[];
  removed_sections: string[];
}

export interface KnowledgeRetrievalSettingsApi {
  only_approved: boolean;
  include_histories: boolean;
  min_confidence: number;
  max_sources: number;
  project: string | null;
  department: string | null;
}

export type KnowledgeFeedbackRatingApi = "up" | "down";

export interface KnowledgeFeedbackRequestApi {
  query_id: string;
  rating: KnowledgeFeedbackRatingApi;
  comment?: string | null;
}

export interface KnowledgeFeedbackResponseApi {
  id: string;
  query_id: string;
  rating: KnowledgeFeedbackRatingApi;
  comment: string | null;
  created_at: string;
}

export interface AgentQueryApi {
  id: string;
  agent_name: string;
  project_id: string | null;
  query_text: string;
  answer_text: string;
  model_used: string | null;
  latency_ms: number | null;
  created_at: string;
  retrieval_params?: Record<string, unknown> | null;
}

export interface KnowledgeEvalQuestionApi {
  id: string;
  question_text: string;
  expected_document_ids: string[];
  expected_answer_notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeEvalMetricsApi {
  days: number;
  total_queries: number;
  empty_answer_rate: number;
  latency_p95_ms: number | null;
  downvote_rate: number;
  eval_question_count: number;
  eval_run_count: number;
  citation_hit_rate: number;
}

export interface KnowledgeEvalRunItemApi {
  id: string;
  eval_question_id: string;
  query_id: string | null;
  citation_hit: boolean;
  empty_answer: boolean;
  latency_ms: number | null;
  observed_document_ids: string[];
  created_at: string;
}

export interface KnowledgeEvalRunApi {
  run_count: number;
  citation_hit_rate: number;
  empty_answer_rate: number;
  latency_p95_ms: number | null;
  results: KnowledgeEvalRunItemApi[];
}

export interface KnowledgeDocumentFilters {
  sourceType?: string;
  owner?: string;
  visibility?: string;
  ready?: boolean;
  workflowState?: string;
  effectiveDateFrom?: string;
  effectiveDateTo?: string;
  semanticQuery?: string;
}
