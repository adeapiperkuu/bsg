"""One-shot Phase 8 splitter: knowledge.py -> knowledge/ package modules."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app" / "services"
SRC_PATH = ROOT / "knowledge.py"
PKG = ROOT / "knowledge"


def main() -> None:
    src = SRC_PATH.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    body = tree.body

    start = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        start = 1
    import_end_line = 1
    for node in body[start:]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_end_line = node.end_lineno or import_end_line
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "logger" for t in node.targets
        ):
            import_end_line = node.end_lineno or import_end_line
            break
        else:
            break

    header = "".join(lines[:import_end_line])
    header = "".join(ln for ln in header.splitlines(True) if "logger = logging.getLogger" not in ln)

    module_map: dict[str, str] = {}

    def assign(mod: str, *names: str) -> None:
        for name in names:
            module_map[name] = mod

    assign(
        "utils",
        "KNOWLEDGE_AGENT_NAME",
        "PROMPT_STRATEGY_VERSION",
        "CONVERSATION_HISTORY_MAX_TURNS",
        "CONVERSATION_HISTORY_TURN_CHARS",
        "TEXT_EXTENSIONS",
        "NO_APPROVED_ANSWER",
        "STRONG_RELEVANCE_THRESHOLD",
        "CHUNK_TARGET_TOKENS",
        "CHUNK_OVERLAP_TOKENS",
        "EMBEDDING_BATCH_SIZE",
        "EMBEDDING_INPUT_MAX_CHARS",
        "TERM_FALLBACK_CHUNK_LIMIT",
        "RERANK_CANDIDATE_LIMIT",
        "NEIGHBOR_CHUNK_WINDOW",
        "HYBRID_VECTOR_WEIGHT",
        "HYBRID_KEYWORD_WEIGHT",
        "RECENCY_BOOST_MAX",
        "EXACT_TERM_BOOST_MAX",
        "METADATA_BOOST_MAX",
        "LOW_CONFIDENCE_THRESHOLD",
        "CLIENT_SAFE_BLOCKLIST_PATTERNS",
        "DEFAULT_MAX_SOURCES",
        "DEFAULT_MAX_CANDIDATES",
        "KNOWLEDGE_ANSWER_CACHE_TTL_S",
        "EXTRACTION_MIN_CHARS",
        "EXTRACTION_MIN_CHARS_PER_PAGE",
        "EXTRACTION_MIN_CHUNKS",
        "SECTION_LARGE_TOKEN_THRESHOLD",
        "OPERATIONAL_KEYWORD_TERMS",
        "SOP_STALE_DAYS",
        "UPLOAD_APPROVED_MIN_METADATA_SCORE",
        "QUERY_TYPES",
        "HISTORY_SOURCE_TYPES",
        "CURRENT_POLICY_SOURCE_TYPES",
        "IDENTIFIER_EXACT_BOOST_MAX",
        "PHRASE_MATCH_BOOST_MAX",
        "SOURCE_TYPE_BOOST_MAX",
        "QUERY_TYPE_BOOST_MAX",
        "ENTITY_MATCH_BOOST_MAX",
        "VERSION_PREFERENCE_MAX",
        "DUPLICATE_PENALTY_MAX",
        "_EMBED_CACHE_TTL_S",
        "_EMBED_CACHE_MAX",
        "_embed_cache_get",
        "_embed_cache_set",
        "_AskTimings",
        "_invalidate_knowledge_answer_cache",
        "_knowledge_scope_fingerprint",
        "_knowledge_cache_key",
        "_get_knowledge_answer_cache",
        "_set_knowledge_answer_cache",
        "_needs_structured_operational_context",
        "PROMPT_INJECTION_REWRITE_PATTERNS",
        "_neutralize_rewrite_context",
        "_VectorChunk",
        "RetrievalResult",
        "_sse",
        "_prompt_size_diagnostics",
        "_is_missing_schema_error",
        "_loaded_datetime",
        "_clean_optional",
        "_format_decimal",
        "_tokenize_search_text",
        "_FOLLOW_UP_PRONOUN_RE",
        "_normalize_query_text",
        "_chunk_text",
        "_chunk_identity",
        "_cosine_similarity",
        "_batch_user_display_names",
        "_user_display_name",
        "_embed_cache",
        "_knowledge_answer_cache",
    )
    assign("permissions", "can_access_visibility", "_knowledge_permissions_for_role")
    assign("feedback", "POSITIVE_FEEDBACK_REASONS", "NEGATIVE_FEEDBACK_REASONS", "record_knowledge_feedback")
    assign("settings", "get_retrieval_settings", "update_retrieval_settings")
    assign("gaps", "_persist_empty_ask_response")
    assign(
        "grounding",
        "_ground_generation",
        "_extract_generation_claims",
        "_extract_answer_numbers",
        "_extract_answer_dates",
        "_extract_answer_names",
        "_unsupported_answer_entities",
        "_validate_answer_citations",
        "_validate_client_safe_answer",
        "_confidence_band",
        "_compute_answer_confidence",
        "_source_label",
        "_build_confidence_reasons",
    )
    assign(
        "ranking",
        "_phrase_match_boost",
        "_entity_match_boost",
        "_source_type_boost",
        "_query_type_boost",
        "_version_sort_key",
        "_version_preference_boost",
        "_filter_latest_valid_versions",
        "_rank_chunks_by_terms",
        "_rerank_hybrid_candidates",
        "_metadata_match_boost",
        "_diversify_ranked_candidates",
        "_exact_term_boost",
        "_extract_exact_terms",
        "_recency_boost",
        "_chunk_intelligence_for_scoring",
    )
    assign(
        "analytics",
        "BOOTSTRAP_RECENT_DOCUMENT_LIMIT",
        "_health_counts_from_documents",
        "_document_counts_from_documents",
        "get_knowledge_bootstrap",
        "get_knowledge_library_health",
        "RetrievalReadinessAssessment",
        "assess_retrieval_readiness",
        "_is_retrieval_ready",
        "_filter_retrieval_ready_docs",
        "compute_library_readiness_counts",
        "build_library_health",
        "_is_document_expired",
        "_has_valid_org_ownership",
        "_is_missing_metadata",
        "_is_approved_and_indexed",
    )
    assign(
        "library",
        "FOLDER_SEED",
        "FOLDER_DEFAULTS",
        "LIST_DOCUMENT_LOAD_OPTIONS",
        "list_knowledge_folders",
        "ensure_knowledge_folders",
        "create_knowledge_folder",
        "_infer_folder_kind",
        "create_knowledge_folder_by_name",
        "get_folder_by_id",
        "get_folder_for_kind",
        "_list_visible_documents_with_folders",
        "list_documents",
        "_to_document_summary_read",
        "get_document",
        "get_document_file_download",
        "update_document",
        "delete_document",
        "list_document_versions",
        "compare_document_versions",
        "_get_document_or_404",
        "_DocumentListPreload",
        "_ensure_document_timestamps",
        "_build_document_read",
        "_to_document_list_read",
        "_batch_document_list_stats",
        "_to_document_read",
        "_chunk_to_read",
        "_extraction_quality_from_diagnostics",
        "_chunk_intelligence_map",
        "_load_active_extraction_diagnostics",
        "_compute_workflow_state",
        "_compute_quality_score",
        "_version_extracted_text",
        "_rank_documents_semantic",
        "_notify_knowledge_stakeholders",
    )
    assign(
        "ingestion",
        "create_document_from_upload",
        "reindex_document",
        "process_knowledge_document_job",
        "_collect_extraction_warnings",
        "_process_document_version",
        "_store_upload",
        "_read_stored_file",
        "_save_upload_locally",
        "_strip_repeated_headers_footers",
        "_parse_heading_line",
        "_encode_section_path",
        "_decode_section_path",
        "_is_table_like_text",
        "_count_operational_keywords",
        "_compact_chunk_intelligence",
        "_duplicate_candidate_documents",
        "_analyze_extraction_quality",
        "_extract_text",
        "_extract_pdf",
        "_extract_docx",
        "_extract_csv",
        "_clean_text",
        "_normalize_compact_document_text",
        "_is_standalone_heading",
        "_should_join_wrapped_line",
        "_clean_sections",
        "_sections_from_text",
        "_buffer_has_body",
        "_detect_section_title",
        "_chunk_sections",
        "_rebuild_chunk_text",
        "_embed_texts",
        "_assess_upload_quality",
        "_upload_block_message",
        "_post_index_quality_warnings",
    )
    assign(
        "retrieval",
        "_retrieve_knowledge_context",
        "_needs_llm_query_rewrite",
        "_query_rewrite_gate",
        "_fast_retrieval_query",
        "_build_retrieval_query_for_search",
        "_build_standalone_retrieval_query",
        "classify_knowledge_query",
        "_adaptive_max_sources",
        "_query_exact_identifiers",
        "_expand_neighbor_matches",
        "_neighbor_context_for_matches",
        "_build_structured_operational_context",
        "_resolve_structured_context_project",
        "_build_retrieval_query",
        "_build_context_chunks_from_matches",
    )
    assign(
        "qa",
        "KnowledgeHistoryNormalization",
        "normalize_conversation_history",
        "_conversation_key",
        "_validate_knowledge_conversation_id",
        "_answer_metadata_in_retrieval_params",
        "_finalize_knowledge_agent_query",
        "_knowledge_ask_read_from_agent_query",
        "list_knowledge_conversations",
        "get_knowledge_conversation",
        "ask_knowledge_agent",
        "get_knowledge_query_answer",
        "_build_retrieval_params",
    )
    assign(
        "streaming",
        "StreamKnowledgePrepared",
        "prepare_stream_knowledge_ask",
        "stream_prepared_knowledge_ask",
        "stream_knowledge_ask",
    )

    def node_names(node: ast.AST) -> list[str]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return [node.name]
        if isinstance(node, ast.Assign):
            return [t.id for t in node.targets if isinstance(t, ast.Name)]
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return [node.target.id]
        return []

    module_chunks: dict[str, list[str]] = defaultdict(list)
    unmapped: list[tuple[int, list[str]]] = []
    seen: set[str] = set()

    for node in body:
        names = node_names(node)
        if not names or names[0] == "logger":
            continue
        primary = names[0]
        if primary in seen:
            continue
        mod = module_map.get(primary)
        if not mod:
            for name in names:
                if name in module_map:
                    mod = module_map[name]
                    break
        if not mod:
            unmapped.append((getattr(node, "lineno", 0), names))
            continue
        for name in names:
            seen.add(name)
        end = getattr(node, "end_lineno", None) or node.lineno
        chunk = "".join(lines[node.lineno - 1 : end])
        if not chunk.endswith("\n"):
            chunk += "\n"
        module_chunks[mod].append(chunk)

    # Capture cache dicts that may sit between constants
    for match in re.finditer(r"^(_embed_cache|_knowledge_answer_cache)\s*=\s*.+$", src, re.M):
        name = match.group(1)
        line_no = src[: match.start()].count("\n") + 1
        text = lines[line_no - 1]
        if text not in module_chunks["utils"]:
            module_chunks["utils"].insert(0, text if text.endswith("\n") else text + "\n")
            seen.add(name)

    if unmapped:
        print("UNMAPPED:")
        for item in unmapped:
            print(item)
        raise SystemExit(1)

    PKG.mkdir(exist_ok=True)
    module_order = [
        "utils",
        "permissions",
        "ranking",
        "grounding",
        "settings",
        "feedback",
        "gaps",
        "analytics",
        "library",
        "ingestion",
        "retrieval",
        "qa",
        "streaming",
    ]

    # Cross-module import stubs: each non-utils module imports from siblings via package.
    # First write raw modules; a second script / manual pass wires imports.
    # For bootstrap reliability, non-utils modules import * from utils and needed siblings lazily inside functions
    # where the original already used lazy imports. For top-level name refs, add explicit imports.

    for mod in module_order:
        chunks = module_chunks.get(mod, [])
        content = "from __future__ import annotations\n\n"
        # Keep original imports for maximum compatibility; trim later if needed.
        content += header
        if not content.endswith("\n"):
            content += "\n"
        content += f"\nlogger = logging.getLogger(__name__)\n\n"
        if mod != "utils":
            content += (
                "from app.services.knowledge.utils import *  # noqa: F403\n"
                "from app.services.knowledge import permissions as _knowledge_permissions\n\n"
            )
        content += f"# --- {mod} (Phase 8) ---\n\n"
        content += "\n".join(chunks)
        if not content.endswith("\n"):
            content += "\n"
        (PKG / f"{mod}.py").write_text(content, encoding="utf-8")
        print(f"wrote {mod}: {len(chunks)} symbols, {len(content)} chars")

    print("OK preliminary modules written")


if __name__ == "__main__":
    main()
