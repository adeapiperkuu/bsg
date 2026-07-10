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
export type KnowledgeVisibilityApi = "internal_only" | "leadership_only" | "restricted" | "client_safe";
export type KnowledgeStatusApi =
  | "draft"
  | "submitted_for_review"
  | "approved"
  | "rejected"
  | "needs_reindex"
  | "expired"
  | "archived";
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

export type KnowledgeRetrievalReadinessReasonApi =
  | "Ready"
  | "Needs approval"
  | "Needs re-index"
  | "Processing failed"
  | "Expired"
  | "Missing owner"
  | "Missing effective date";

export type KnowledgeRetrievalActionApi = "approve" | "reindex" | "edit_metadata" | "retry_processing";

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

export interface KnowledgeExtractionScoreBreakdownApi {
  heading_coverage: number;
  ocr_confidence: number;
  metadata_completeness: number;
  table_quality: number;
  section_balance: number;
  duplicate_penalty: number;
  empty_page_ratio: number;
  image_ratio: number;
  operational_keyword_density: number;
  overall: number;
}

export interface KnowledgeLibraryAnalyticsApi {
  average_chunk_tokens: number;
  largest_chunk_tokens: number;
  smallest_chunk_tokens: number;
  heading_count: number;
  table_count: number;
  warning_count: number;
  entity_count: number;
  estimated_retrieval_quality: number;
}

export interface KnowledgeChunkApi {
  id: string;
  document_id: string;
  chunk_index: number;
  total_chunks?: number | null;
  previous_chunk_id?: string | null;
  next_chunk_id?: string | null;
  section_title: string | null;
  section_path?: string | null;
  heading_level?: number | null;
  page_number: number | null;
  chunk_text: string;
  token_count: number | null;
  chunk_summary?: string | null;
  chunk_type?: string;
  is_table?: boolean;
  contains_procedure?: boolean;
  contains_warning?: boolean;
  contains_decision?: boolean;
  contains_checklist?: boolean;
  contains_table?: boolean;
  contains_roles?: boolean;
  contains_dates?: boolean;
  source_type?: string | null;
  folder_name?: string | null;
  project?: string | null;
  department?: string | null;
  effective_date?: string | null;
  owner_approver?: string | null;
}

export interface KnowledgeFolderApi {
  id: string;
  name: string;
  folder_kind: KnowledgeFolderKind;
  display_order: number;
}

export interface KnowledgeDocumentSummaryApi {
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
  expiry_date?: string | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  approved_at?: string | null;
  rejection_reason?: string | null;
  file_name: string;
  processing_status: KnowledgeProcessingStatusApi;
  processing_error: string | null;
  indexing_status: KnowledgeIndexingStatusApi;
  workflow_state: KnowledgeWorkflowState;
  retrieval_ready: boolean;
  retrieval_readiness_reason: KnowledgeRetrievalReadinessReasonApi | string;
  retrieval_action: KnowledgeRetrievalActionApi | null;
  updated_at: string;
}

export interface KnowledgeFolderTreeNodeApi {
  id: string;
  name: string;
  folder_kind: KnowledgeFolderKind;
  display_order: number;
  document_count: number;
}

export interface KnowledgeDocumentCountsApi {
  total: number;
  by_folder_id: Record<string, number>;
}

export interface KnowledgePermissionsApi {
  can_upload: boolean;
  can_manage_eval: boolean;
  can_adjust_retrieval_scope: boolean;
  can_review_approvals?: boolean;
}

export interface KnowledgeLibraryHealthCountsApi {
  ready_count: number;
  ready_for_retrieval_count: number;
  approved_and_indexed_count: number;
  needs_review_count: number;
  expired_count: number;
  needs_reindex_count: number;
  failed_processing_count: number;
  missing_metadata_count: number;
  indexing_count: number;
  draft_count: number;
  archived_count: number;
  approaching_expiry_count: number;
  outdated_count: number;
}

export interface KnowledgeBootstrapApi {
  folders: KnowledgeFolderApi[];
  folder_tree: KnowledgeFolderTreeNodeApi[];
  recent_documents: KnowledgeDocumentSummaryApi[];
  document_counts: KnowledgeDocumentCountsApi;
  permissions: KnowledgePermissionsApi;
  library_health: KnowledgeLibraryHealthCountsApi;
}

export interface KnowledgeLibraryHealthApi {
  ready_count: number;
  ready_for_retrieval_count: number;
  approved_and_indexed_count: number;
  needs_review_count: number;
  expired_count: number;
  needs_reindex_count: number;
  failed_processing_count: number;
  missing_metadata_count: number;
  indexing_count: number;
  draft_count: number;
  archived_count: number;
  approaching_expiry_count: number;
  outdated_count: number;
  health_score?: number | null;
  health_band?: string | null;
  health_recommendations?: string[];
}

export interface KnowledgeDocumentApi {
  id: string;
  folder_id: string;
  active_version_id?: string | null;
  folder_name: string;
  folder_kind: KnowledgeFolderKind;
  title: string;
  source_type: KnowledgeSourceTypeApi;
  version: string;
  visibility: KnowledgeVisibilityApi;
  status: KnowledgeStatusApi;
  owner_approver: string;
  effective_date: string | null;
  expiry_date?: string | null;
  created_by?: string | null;
  submitted_by?: string | null;
  submitted_at?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  rejection_reason?: string | null;
  file_name: string;
  file_mime_type: string;
  file_url: string | null;
  processing_status: KnowledgeProcessingStatusApi;
  processing_error: string | null;
  indexing_status: KnowledgeIndexingStatusApi;
  preview: string[];
  workflow_state: KnowledgeWorkflowState;
  retrieval_ready: boolean;
  retrieval_readiness_reason: KnowledgeRetrievalReadinessReasonApi | string;
  retrieval_action: KnowledgeRetrievalActionApi | null;
  quality_score: KnowledgeQualityScoreApi | null;
  quality_warnings: string[];
  extraction_quality_score?: number | null;
  extraction_score_breakdown?: KnowledgeExtractionScoreBreakdownApi | null;
  library_analytics?: KnowledgeLibraryAnalyticsApi | null;
  ocr_needed?: boolean;
  reindex_recommended?: boolean;
  chunk_count: number;
  citation_count: number;
  approved_by_name: string | null;
  approved_at: string | null;
  executive_summary?: string | null;
  key_procedures?: string[];
  important_warnings?: string[];
  affected_departments?: string[];
  related_document_ids?: string[];
  summary_generated_at?: string | null;
  chunks: KnowledgeChunkApi[];
  semantic_relevance: number | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSuggestionApi {
  id: string;
  org_id: string;
  document_id: string | null;
  suggestion_type: string;
  title: string;
  detail: string;
  proposed_changes: Record<string, unknown>;
  evidence: Record<string, unknown>;
  status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeRelatedItemApi {
  document_id: string;
  title: string;
  source_type: string;
  score: number;
  reason: string;
}

export interface KnowledgeRelatedKnowledgeApi {
  related_sops: KnowledgeRelatedItemApi[];
  related_guides: KnowledgeRelatedItemApi[];
  related_lessons: KnowledgeRelatedItemApi[];
  related_projects: string[];
  similar_questions: string[];
}

export interface KnowledgeDocumentAiSummaryApi {
  document_id: string;
  executive_summary: string | null;
  key_procedures: string[];
  important_warnings: string[];
  affected_departments: string[];
  related_document_ids: string[];
  summary_generated_at: string | null;
}

export interface KnowledgeDocumentLifecycleActionApi {
  note?: string | null;
  rejection_reason?: string | null;
  effective_date?: string | null;
  expiry_date?: string | null;
}

export interface KnowledgeDocumentApprovalEventApi {
  id: string;
  document_id: string;
  actor_id: string | null;
  actor_name?: string | null;
  from_status: KnowledgeStatusApi | string | null;
  to_status: KnowledgeStatusApi | string;
  action: string;
  note?: string | null;
  created_at: string;
}

export interface KnowledgeStructuredAnswerApi {
  policy: string;
  steps: string;
  owner: string;
  evidence: string;
  next_action: string;
}

export type KnowledgeConversationHistoryRoleApi = "user" | "assistant";

export interface KnowledgeConversationHistoryTurnApi {
  role: KnowledgeConversationHistoryRoleApi;
  content: string;
}

export interface KnowledgeAskResponseApi {
  answer_text: string;
  next_step: string;
  confidence_score: number;
  confidence_band?: "high" | "medium" | "low" | "very_low" | string | null;
  confidence_reasons: string[];
  structured_answer: KnowledgeStructuredAnswerApi | null;
  query_id: string | null;
  conversation_id?: string | null;
  model_used: string | null;
  retrieval_debug?: KnowledgeRetrievalDebugApi | null;
}

export interface KnowledgeConversationSummaryApi {
  id: string;
  title: string;
  turn_count: number;
  updated_at: string;
}

export interface KnowledgeConversationTurnApi {
  query_id: string;
  query_text: string;
  answer: KnowledgeAskResponseApi;
}

export interface KnowledgeConversationApi {
  id: string;
  turns: KnowledgeConversationTurnApi[];
}

export type KnowledgeAnswerModeApi = "internal" | "client_safe";

export interface KnowledgeRetrievalDebugApi {
  query_text?: string;
  query_type?: string;
  original_query?: string;
  normalized_query?: string;
  retrieval_query?: string;
  rewritten_query?: string | null;
  query_rewrite?: Record<string, unknown>;
  conversation_history?: Record<string, unknown>;
  prompt?: Record<string, unknown>;
  grounding?: Record<string, unknown>;
  client_safe_validation?: Record<string, unknown>;
  confidence_band?: string;
  confidence_breakdown?: Record<string, unknown>;
  answer_mode?: KnowledgeAnswerModeApi | string;
  include_histories?: boolean;
  max_sources?: number;
  max_candidates?: number;
  min_relevance_score?: number;
  project?: string | null;
  department?: string | null;
  eligible_doc_count?: number;
  has_embeddings?: boolean;
  confidence_score?: number;
  fallback_level?: number;
  candidate_count?: number;
  vector_candidate_count?: number;
  keyword_candidate_count?: number;
  candidates_after_deduplication?: number;
  selected_source_count?: number;
  applied_filters?: Record<string, unknown>;
  sources?: Array<{
    document_id: string;
    chunk_id: string;
    title: string;
    section_path?: string | null;
    page?: number | string | null;
    source_type?: string | null;
    effective_date?: string | null;
    readiness?: string | null;
    visibility?: string | null;
    relevance_score: number;
    vector_score: number;
    keyword_score: number;
    score_breakdown?: Record<string, number> | null;
  }>;
  citations?: Array<{
    document_id: string;
    chunk_id: string;
    title: string;
    section_path?: string | null;
    page?: number | string | null;
    source_type?: string | null;
    effective_date?: string | null;
    readiness?: string | null;
    visibility?: string | null;
    relevance_score: number;
  }>;
}

export interface KnowledgeDocumentVersionApi {
  id: string;
  version: string;
  is_active: boolean;
  uploaded_at: string;
  uploaded_by_name: string | null;
  supersedes_version_id?: string | null;
  superseded_by_version_id?: string | null;
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
  min_relevance: number;
  min_confidence: number;
  max_sources: number;
  max_candidates: number;
  project: string | null;
  department: string | null;
  source_types: string[];
  folder_ids: string[];
  recency_preference: number;
  exact_term_preference: number;
}

export type KnowledgeFeedbackRatingApi = "up" | "down";

export interface KnowledgeFeedbackRequestApi {
  query_id: string;
  rating: KnowledgeFeedbackRatingApi;
  comment?: string | null;
  feedback_reason?: KnowledgeFeedbackReasonApi | null;
}

export type KnowledgeFeedbackReasonApi =
  | "accurate"
  | "helpful"
  | "clear"
  | "good_sources"
  | "complete"
  | "missing_knowledge"
  | "incorrect"
  | "weak_sources"
  | "outdated"
  | "unclear"
  | "incomplete"
  | "unsafe_for_client"
  | "citation_problem"
  | "too_slow"
  | "other";

export interface KnowledgeFeedbackResponseApi {
  id: string;
  query_id: string;
  rating: KnowledgeFeedbackRatingApi;
  comment: string | null;
  feedback_reason?: KnowledgeFeedbackReasonApi | string | null;
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

export interface KnowledgeDocumentFilters {
  sourceType?: string;
  owner?: string;
  visibility?: string;
  ready?: boolean;
  workflowState?: string;
  effectiveDateFrom?: string;
  effectiveDateTo?: string;
  semanticQuery?: string;
  aiRank?: boolean;
}
