from uuid import uuid4

from app.services.knowledge import _chunk_sections, _chunk_to_read
from app.services.knowledge_intelligence import (
    aggregate_cross_references,
    aggregate_document_entities,
    build_library_analytics,
    chunk_sections_semantic,
    compute_extraction_score_breakdown,
    detect_document_duplicates,
    extract_cross_references,
    extract_operational_entities,
    segment_section_into_blocks,
)
from app.db.models.entities import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentStatus,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeSourceType,
    KnowledgeVisibility,
)


def test_numbered_procedure_stays_in_one_chunk() -> None:
    text = "\n".join(
        [
            "1. Open the escalation tracker.",
            "2. Notify the delivery manager within four hours.",
            "3. Record the incident ID in the ticket system.",
            "4. Confirm client acknowledgement.",
            "5. Schedule the follow-up review.",
        ]
    )
    blocks = segment_section_into_blocks(text)
    chunks = chunk_sections_semantic([{"text": text, "section_title": "Escalation procedure"}])
    assert any(block.kind == "numbered" for block in blocks)
    assert len(chunks) == 1
    assert chunks[0]["contains_procedure"] is True


def test_bullet_list_stays_together() -> None:
    text = "\n".join(
        [
            "- Verify owner approval",
            "- Confirm effective date",
            "- Checklist complete before go-live",
        ]
    )
    chunks = chunk_sections_semantic([{"text": text, "section_title": "Checklist"}])
    assert len(chunks) == 1
    assert chunks[0]["contains_checklist"] is True


def test_warning_block_is_preserved() -> None:
    text = "Warning: Do not skip approval stage 2.\nProceed only after QA sign-off."
    chunks = chunk_sections_semantic([{"text": text}])
    assert len(chunks) == 1
    assert chunks[0]["contains_warning"] is True


def test_chunk_navigation_metadata() -> None:
    sections = [
        {"text": "First section with enough operational procedure content for chunk one."},
        {"text": "Second section with escalation workflow and approval guidance for chunk two."},
    ]
    chunks = _chunk_sections(sections)
    assert chunks[0]["chunk_index"] == 0
    assert chunks[-1]["chunk_index"] == len(chunks) - 1
    assert chunks[0]["total_chunks"] == len(chunks)
    assert "chunk_summary" in chunks[0]
    assert chunks[1].get("previous_chunk_index") == 0
    assert chunks[0].get("next_chunk_index") == 1


def test_entity_extraction_is_deterministic() -> None:
    text = (
        "Project Alpha milestone requires delivery manager approval. "
        "See SOP-014 and ticket INC-4421. Version 2.1 effective 2025-06-01."
    )
    entities = extract_operational_entities(text)
    assert "Project Alpha" in entities.get("projects", [])
    assert any("SOP" in item for item in entities.get("sop_identifiers", []))
    assert entities.get("ticket_numbers")
    assert entities.get("document_versions")
    assert entities.get("roles")


def test_cross_reference_detection() -> None:
    text = "See SOP-014. Refer to Section 5. See Appendix A. Refer to Escalation Guide."
    refs = extract_cross_references(text)
    types = {ref["reference_type"] for ref in refs}
    assert "sop" in types
    assert "section" in types
    assert "appendix" in types
    assert "guide" in types
    assert any(ref.get("referenced_document") for ref in refs)


def test_duplicate_detection_warns_without_deleting() -> None:
    doc_id = str(uuid4())
    other_id = str(uuid4())
    content = "Escalation workflow for Project Alpha with approval and QA checklist."
    warnings = detect_document_duplicates(
        org_id=str(uuid4()),
        document_id=doc_id,
        title="Escalation SOP",
        version="v2.0",
        file_name="escalation-v2.pdf",
        checksum_sha256="abc123",
        cleaned_text=content,
        candidates=[
            {
                "id": other_id,
                "title": "Escalation SOP",
                "version": "v1.0",
                "file_name": "escalation.pdf",
                "checksum_sha256": "abc123",
                "extracted_text": content,
            }
        ],
    )
    assert warnings
    assert warnings[0]["kind"] == "duplicate_upload"
    assert "message" in warnings[0]


def test_quality_scoring_returns_breakdown() -> None:
    text = "# Escalation SOP\n\nApproval workflow for operations and QA escalation procedure."
    sections = [{"text": text, "section_title": "Escalation SOP", "heading_level": 1}]
    chunks = chunk_sections_semantic(sections)
    score, warnings, diagnostics = compute_extraction_score_breakdown(
        file_name="escalation.md",
        cleaned_text=text,
        sections=sections,
        chunks=chunks,
        page_count=1,
        headers_footers_removed=0,
        metadata_complete=True,
        duplicate_warnings=[],
        page_char_counts=[len(text)],
    )
    assert 0 <= score <= 100
    assert "score_breakdown" in diagnostics
    breakdown = diagnostics["score_breakdown"]
    assert "heading_coverage" in breakdown
    assert "ocr_confidence" in breakdown
    assert breakdown["overall"] == score
    assert isinstance(warnings, list)


def test_chunk_read_includes_intelligence_metadata() -> None:
    doc_id = uuid4()
    folder_id = uuid4()
    chunk_id = uuid4()
    prev_id = uuid4()
    next_id = uuid4()
    doc = KnowledgeDocument(
        id=doc_id,
        org_id=uuid4(),
        folder_id=folder_id,
        title="Escalation SOP",
        source_type=KnowledgeSourceType.SOP,
        version="v1.0",
        visibility=KnowledgeVisibility.INTERNAL_ONLY,
        status=KnowledgeDocumentStatus.APPROVED,
        owner_approver="Ops Lead",
        file_name="escalation.md",
        file_mime_type="text/markdown",
    )
    folder = KnowledgeFolder(
        id=folder_id,
        org_id=doc.org_id,
        name="SOPs",
        folder_kind=KnowledgeFolderKind.SOPS,
        display_order=1,
    )
    chunk = KnowledgeDocumentChunk(
        id=chunk_id,
        org_id=doc.org_id,
        document_id=doc_id,
        folder_id=folder_id,
        chunk_index=1,
        section_title="Escalation",
        section_path="H1|Escalation SOP",
        content="Warning: escalate within four hours.",
        chunk_text="Warning: escalate within four hours.",
        token_count=6,
        chunk_type="text",
    )
    read = _chunk_to_read(
        chunk,
        doc,
        folder,
        intelligence={
            "chunk_summary": "Warning: escalate within four hours.",
            "contains_warning": True,
            "contains_procedure": False,
            "contains_table": False,
        },
        previous_chunk_id=prev_id,
        next_chunk_id=next_id,
        total_chunks=3,
    )
    assert read.total_chunks == 3
    assert read.previous_chunk_id == prev_id
    assert read.next_chunk_id == next_id
    assert read.chunk_summary == "Warning: escalate within four hours."
    assert read.contains_warning is True


def test_library_analytics_and_entity_aggregation() -> None:
    chunks = chunk_sections_semantic(
        [
            {
                "text": "Warning: follow escalation procedure.\nSee SOP-014.\n- Verify delivery manager approval\nProject Beta phase checklist.",
                "section_title": "Procedure",
            }
        ]
    )
    entities = aggregate_document_entities(chunks)
    refs = aggregate_cross_references(chunks)
    analytics = build_library_analytics(chunks, estimated_retrieval_quality=82)
    assert entities
    assert refs
    assert analytics["entity_count"] > 0
    assert analytics["warning_count"] >= 1
    assert analytics["estimated_retrieval_quality"] == 82
