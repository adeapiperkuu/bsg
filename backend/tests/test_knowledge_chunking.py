from datetime import date
from uuid import uuid4

from app.db.models.entities import (
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentStatus,
    KnowledgeFolder,
    KnowledgeFolderKind,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.services.knowledge import (
    _analyze_extraction_quality,
    _chunk_sections,
    _chunk_to_read,
    _sections_from_text,
)


def test_sections_with_headings_create_chunk_metadata() -> None:
    text = """# Escalation SOP

Approval workflow for Project Alpha requires delivery manager sign-off.

## Notification steps
Notify the client within four hours of escalation.
"""
    sections = _sections_from_text(text)
    chunks = _chunk_sections(sections)

    assert any(section.get("section_title") for section in sections)
    assert chunks
    assert chunks[0]["section_title"] == "Escalation SOP"
    assert chunks[0]["heading_level"] == 1
    assert any("Notification" in str(chunk.get("section_path") or "") for chunk in chunks)


def test_table_heavy_document_gets_warning() -> None:
    table_text = "\n".join(
        [
            "Metrics | Owner | SLA | Notes",
            "Escalation | Ops | 1 day | P1",
            "Approval | Manager | 2 days | P2",
            "Notification | PM | 4 hours | P3",
            "Resolution | QA | 3 days | P4",
            "Closure | PM | 1 day | P5",
        ]
    )
    sections = [{"text": table_text, "section_title": "Table", "chunk_type": "table"}]
    chunks = _chunk_sections(sections)
    warnings, score, diagnostics = _analyze_extraction_quality(
        file_name="metrics.csv",
        raw_text=table_text,
        cleaned_text=table_text,
        sections=sections,
        chunks=chunks,
    )

    assert any("Table-heavy" in warning for warning in warnings)
    assert diagnostics["table_section_count"] >= 1
    assert score < 100


def test_image_heavy_low_text_document_gets_warning() -> None:
    warnings, score, diagnostics = _analyze_extraction_quality(
        file_name="scan.pdf",
        raw_text="tiny",
        cleaned_text="short",
        sections=[{"text": "short", "page_number": 1}],
        chunks=[{"chunk_text": "short"}],
        page_count=6,
    )

    assert any("OCR" in warning for warning in warnings)
    assert diagnostics["ocr_needed"] is True
    assert score < 100


def test_missing_heading_document_gets_warning() -> None:
    text = "This paragraph has no headings and only generic prose about operations."
    sections = _sections_from_text(text)
    chunks = _chunk_sections(sections)
    warnings, _, diagnostics = _analyze_extraction_quality(
        file_name="notes.txt",
        raw_text=text,
        cleaned_text=text,
        sections=sections,
        chunks=chunks,
    )

    assert diagnostics["heading_section_count"] == 0
    assert any("No section headings" in warning for warning in warnings)


def test_chunk_metadata_includes_document_metadata() -> None:
    doc_id = uuid4()
    folder_id = uuid4()
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
        effective_date=date(2025, 6, 1),
        project="Project Alpha",
        department="Delivery",
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
        id=uuid4(),
        org_id=doc.org_id,
        document_id=doc_id,
        folder_id=folder_id,
        chunk_index=0,
        section_title="Approval workflow",
        section_path="H2|Escalation SOP > Approval workflow",
        page_number=2,
        content="Approval steps",
        chunk_text="Approval steps",
        token_count=2,
        chunk_type="text",
        project=doc.project,
        department=doc.department,
    )

    read = _chunk_to_read(chunk, doc, folder)

    assert read.document_id == doc_id
    assert read.source_type == "sop"
    assert read.folder_name == "SOPs"
    assert read.project == "Project Alpha"
    assert read.department == "Delivery"
    assert read.effective_date == date(2025, 6, 1)
    assert read.owner_approver == "Ops Lead"
    assert read.heading_level == 2
    assert read.section_path == "Escalation SOP > Approval workflow"
    assert read.is_table is False
