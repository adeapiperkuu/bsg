"""Deterministic document intelligence for knowledge ingestion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

CHUNK_TARGET_TOKENS = 900
CHUNK_OVERLAP_TOKENS = 120
SECTION_LARGE_TOKEN_THRESHOLD = 1200
EXTRACTION_MIN_CHARS = 200
EXTRACTION_MIN_CHARS_PER_PAGE = 80
EXTRACTION_MIN_CHUNKS = 2

OPERATIONAL_KEYWORD_TERMS = (
    "sop",
    "procedure",
    "policy",
    "escalation",
    "approval",
    "workflow",
    "onboarding",
    "training",
    "milestone",
    "quality",
    "compliance",
    "standard",
    "checklist",
    "runbook",
    "playbook",
    "incident",
    "resolution",
    "guidance",
    "process",
)

ROLE_TERMS = (
    "delivery manager",
    "project manager",
    "qa lead",
    "team lead",
    "operations manager",
    "bsg leadership",
    "approver",
    "reviewer",
    "client",
)

PHASE_TERMS = ("discovery", "onboarding", "pilot", "production", "hypercare", "closure")

WARNING_PREFIXES = ("warning:", "caution:", "important:", "note:", "alert:")

NUMBERED_STEP_RE = re.compile(r"^\d+[\.)]\s+", re.MULTILINE)
BULLET_RE = re.compile(r"^[-*•]\s+", re.MULTILINE)
HEADING_MD_RE = re.compile(r"^(#{1,6})\s+(.+)$")
CODE_FENCE_RE = re.compile(r"^```")
SOP_ID_RE = re.compile(r"\bSOP[-\s]?\d{2,5}\b", re.IGNORECASE)
TICKET_RE = re.compile(r"\b(?:INC|TKT|TICKET|ISSUE)[-#]?\d{2,8}\b", re.IGNORECASE)
HASH_TICKET_RE = re.compile(r"#\d{4,8}\b")
VERSION_RE = re.compile(r"\bv(?:ersion)?\s*\d+(?:\.\d+){0,2}\b", re.IGNORECASE)
PROJECT_RE = re.compile(r"\bProject\s+[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)?\b")
PHASE_RE = re.compile(r"\bPhase\s+\d+\b", re.IGNORECASE)
MILESTONE_RE = re.compile(r"\bMilestone\s+\d+\b", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)
CROSS_REF_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sop", re.compile(r"\b(?:see|refer to|per)\s+(SOP[-\s]?\d{2,5})\b", re.IGNORECASE)),
    ("section", re.compile(r"\b(?:see|refer to|per)\s+Section\s+([\w.]+)\b", re.IGNORECASE)),
    ("appendix", re.compile(r"\b(?:see|refer to)\s+Appendix\s+([A-Z0-9]+)\b", re.IGNORECASE)),
    ("guide", re.compile(r"\b(?:see|refer to)\s+([A-Z][A-Za-z\s]+Guide)\b", re.IGNORECASE)),
    ("document", re.compile(r"\b(?:see|refer to)\s+([A-Z][A-Za-z0-9\s-]{3,40})\b", re.IGNORECASE)),
]


@dataclass
class SemanticBlock:
    kind: str
    lines: list[str]
    token_count: int = 0

    def text(self) -> str:
        return "\n".join(self.lines).strip()


def tokenize_words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def count_tokens(text: str) -> int:
    return len(tokenize_words(text))


def is_table_like_text(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    pipe_lines = sum(1 for line in lines if line.count("|") >= 2)
    if pipe_lines >= 2:
        return True
    tab_lines = sum(1 for line in lines if "\t" in line)
    if tab_lines >= max(2, len(lines) // 3):
        return True
    row_lines = sum(1 for line in lines if re.match(r"^Row \d+:", line, flags=re.IGNORECASE))
    return row_lines >= 3


def count_operational_keywords(text: str) -> int:
    lower = text.lower()
    return sum(1 for term in OPERATIONAL_KEYWORD_TERMS if term in lower)


def _line_kind(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "blank"
    if HEADING_MD_RE.match(stripped):
        return "heading"
    if CODE_FENCE_RE.match(stripped):
        return "code_fence"
    if any(stripped.lower().startswith(prefix) for prefix in WARNING_PREFIXES):
        return "warning"
    if NUMBERED_STEP_RE.match(stripped):
        return "numbered"
    if BULLET_RE.match(stripped):
        return "bullet"
    if is_table_like_text(stripped):
        return "table_line"
    return "text"


def segment_section_into_blocks(text: str) -> list[SemanticBlock]:
    lines = text.splitlines()
    blocks: list[SemanticBlock] = []
    current_kind = "text"
    current_lines: list[str] = []
    in_code = False

    def flush() -> None:
        nonlocal current_lines, current_kind
        if not current_lines:
            return
        body = "\n".join(current_lines).strip()
        if body:
            blocks.append(SemanticBlock(kind=current_kind, lines=current_lines.copy(), token_count=count_tokens(body)))
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if CODE_FENCE_RE.match(stripped):
            if in_code:
                current_lines.append(line)
                flush()
                in_code = False
                current_kind = "text"
                continue
            flush()
            in_code = True
            current_kind = "code"
            current_lines = [line]
            continue
        if in_code:
            current_lines.append(line)
            continue

        kind = _line_kind(line)
        if kind == "blank":
            flush()
            current_kind = "text"
            continue
        if kind == "heading":
            flush()
            current_kind = "heading"
            current_lines = [line]
            flush()
            current_kind = "text"
            continue
        if kind == "warning":
            if current_kind not in {"warning", "numbered", "bullet"}:
                flush()
            current_kind = "warning"
            current_lines.append(line)
            continue
        if kind == "numbered":
            if current_kind != "numbered":
                flush()
                current_kind = "numbered"
            current_lines.append(line)
            continue
        if kind == "bullet":
            if current_kind != "bullet":
                flush()
                current_kind = "bullet"
            current_lines.append(line)
            continue
        if kind == "table_line":
            if current_kind not in {"table", "text"}:
                flush()
            if current_kind == "text" and current_lines:
                current_kind = "table"
            elif current_kind != "table":
                current_kind = "table"
            current_lines.append(line)
            continue
        if current_kind in {"numbered", "bullet", "warning", "table", "code"}:
            flush()
        current_kind = "text"
        current_lines.append(line)
    flush()
    return blocks


def _boundary_score(prev_block: SemanticBlock | None, next_block: SemanticBlock | None) -> float:
    if next_block is None:
        return 1.0
    if prev_block is None:
        return 0.2
    if prev_block.kind in {"numbered", "bullet", "warning", "code", "table", "heading"}:
        return 0.0
    if next_block.kind == "heading":
        return 1.0
    if next_block.kind in {"numbered", "bullet", "warning", "table"}:
        return 0.0
    return 0.7


def chunk_semantic_blocks(
    blocks: list[SemanticBlock],
    *,
    section_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    if not blocks:
        return []
    chunks: list[dict[str, Any]] = []
    buffer_blocks: list[SemanticBlock] = []
    buffer_tokens = 0

    def flush_buffer() -> None:
        nonlocal buffer_blocks, buffer_tokens
        if not buffer_blocks:
            return
        text = "\n\n".join(block.text() for block in buffer_blocks if block.text()).strip()
        if not text:
            buffer_blocks = []
            buffer_tokens = 0
            return
        meta = analyze_chunk_content(text)
        chunks.append(
            {
                "chunk_text": text,
                "token_count": count_tokens(text),
                "page_number": section_meta.get("page_number"),
                "section_title": section_meta.get("section_title"),
                "section_path": section_meta.get("section_path"),
                "heading_level": section_meta.get("heading_level"),
                "chunk_type": "table" if meta["contains_table"] else section_meta.get("chunk_type", "text"),
                **meta,
            }
        )
        buffer_blocks = []
        buffer_tokens = 0

    for index, block in enumerate(blocks):
        block_tokens = block.token_count
        if block.kind == "heading" and not block.text().lstrip("#").strip():
            continue
        if block_tokens > CHUNK_TARGET_TOKENS and block.kind == "text":
            words = tokenize_words(block.text())
            start = 0
            while start < len(words):
                end = min(start + CHUNK_TARGET_TOKENS, len(words))
                part = " ".join(words[start:end]).strip()
                if part:
                    meta = analyze_chunk_content(part)
                    chunks.append(
                        {
                            "chunk_text": part,
                            "token_count": len(words[start:end]),
                            "page_number": section_meta.get("page_number"),
                            "section_title": section_meta.get("section_title"),
                            "section_path": section_meta.get("section_path"),
                            "heading_level": section_meta.get("heading_level"),
                            "chunk_type": section_meta.get("chunk_type", "text"),
                            **meta,
                        }
                    )
                if end == len(words):
                    break
                start = max(end - CHUNK_OVERLAP_TOKENS, start + 1)
            continue

        prospective = buffer_tokens + block_tokens
        if buffer_blocks and prospective > CHUNK_TARGET_TOKENS:
            boundary = _boundary_score(buffer_blocks[-1], block)
            if boundary < 0.5 and prospective < CHUNK_TARGET_TOKENS + 200:
                buffer_blocks.append(block)
                buffer_tokens = prospective
                continue
            flush_buffer()
        buffer_blocks.append(block)
        buffer_tokens += block_tokens

        if block.kind == "table" and index > 0 and blocks[index - 1].kind == "text":
            prev = blocks[index - 1]
            if prev.token_count < 180 and prev not in buffer_blocks[:-2]:
                pass
    flush_buffer()

    if len(chunks) > 1 and chunks[0]["token_count"] < 40 and chunks[0].get("section_title") and not chunks[0].get("contains_procedure"):
        merged_text = f"{chunks[0]['chunk_text']}\n\n{chunks[1]['chunk_text']}".strip()
        meta = analyze_chunk_content(merged_text)
        chunks[1] = {
            **chunks[1],
            "chunk_text": merged_text,
            "token_count": count_tokens(merged_text),
            **meta,
        }
        chunks.pop(0)
    return chunks


def chunk_sections_semantic(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_chunks: list[dict[str, Any]] = []
    for section in sections:
        text = str(section.get("text") or "").strip()
        if not text:
            continue
        blocks = segment_section_into_blocks(text)
        if not blocks:
            continue
        section_chunks = chunk_semantic_blocks(blocks, section_meta=section)
        all_chunks.extend(section_chunks)
    if not all_chunks:
        raise ValueError("No chunks could be created from extracted text.")
    total = len(all_chunks)
    for index, chunk in enumerate(all_chunks):
        chunk["chunk_index"] = index
        chunk["total_chunks"] = total
        chunk["chunk_summary"] = summarize_chunk(chunk["chunk_text"])
        if index > 0:
            chunk["previous_chunk_index"] = index - 1
        if index < total - 1:
            chunk["next_chunk_index"] = index + 1
    return all_chunks


def summarize_chunk(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    for end in (". ", "? ", "! ", "\n"):
        pos = cleaned.find(end)
        if 0 < pos < 220:
            return cleaned[: pos + 1].strip()
    if len(cleaned) <= 180:
        return cleaned
    return cleaned[:177].rstrip() + "..."


def analyze_chunk_content(text: str) -> dict[str, Any]:
    lower = text.lower()
    return {
        "contains_procedure": bool(
            NUMBERED_STEP_RE.search(text) or "procedure" in lower or "step " in lower
        ),
        "contains_warning": any(lower.startswith(prefix) or f"\n{prefix}" in lower for prefix in WARNING_PREFIXES),
        "contains_decision": any(term in lower for term in ("if ", "unless ", "decision", "approve", "reject", "escalate")),
        "contains_checklist": bool(
            BULLET_RE.search(text) and ("checklist" in lower or "verify" in lower or "confirm" in lower)
        ),
        "contains_table": is_table_like_text(text),
        "contains_roles": any(role in lower for role in ROLE_TERMS),
        "contains_dates": bool(DATE_RE.search(text)),
        "entities": extract_operational_entities(text),
        "cross_references": extract_cross_references(text),
    }


def extract_operational_entities(text: str) -> dict[str, list[str]]:
    entities: dict[str, set[str]] = {
        "projects": set(),
        "milestones": set(),
        "departments": set(),
        "phases": set(),
        "roles": set(),
        "approval_stages": set(),
        "risks": set(),
        "issue_ids": set(),
        "ticket_numbers": set(),
        "sop_identifiers": set(),
        "document_versions": set(),
        "customers": set(),
    }
    for match in PROJECT_RE.findall(text):
        entities["projects"].add(match.strip())
    for match in MILESTONE_RE.findall(text):
        entities["milestones"].add(match.strip())
    for match in PHASE_RE.findall(text):
        entities["phases"].add(match.strip())
    for match in SOP_ID_RE.findall(text):
        entities["sop_identifiers"].add(match.upper().replace(" ", "-"))
    for match in VERSION_RE.findall(text):
        entities["document_versions"].add(match.strip())
    for match in TICKET_RE.findall(text):
        entities["ticket_numbers"].add(match.upper())
    for match in HASH_TICKET_RE.findall(text):
        entities["issue_ids"].add(match)
    for role in ROLE_TERMS:
        if role in text.lower():
            entities["roles"].add(role.title())
    for phase in PHASE_TERMS:
        if re.search(rf"\b{re.escape(phase)}\b", text, re.IGNORECASE):
            entities["phases"].add(phase.title())
    for match in re.findall(r"\b(?:approval|review|sign-off|signoff)\s+stage\s+[\w-]+\b", text, re.IGNORECASE):
        entities["approval_stages"].add(match.strip())
    for match in re.findall(r"\b(?:risk|issue):\s*([^\n.]{3,80})", text, re.IGNORECASE):
        entities["risks"].add(match.strip())
    for match in re.findall(r"\bDepartment:\s*([A-Za-z][A-Za-z\s/&-]{1,40})", text):
        entities["departments"].add(match.strip())
    for match in re.findall(r"\bCustomer:\s*([A-Za-z][A-Za-z0-9\s/&-]{1,40})", text):
        entities["customers"].add(match.strip())
    return {key: sorted(values) for key, values in entities.items() if values}


def extract_cross_references(text: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for ref_type, pattern in CROSS_REF_PATTERNS:
        for match in pattern.finditer(text):
            target = match.group(1).strip()
            key = (ref_type, target.lower(), match.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            refs.append(
                {
                    "reference_type": ref_type,
                    "referenced_document": target if ref_type in {"sop", "guide", "document"} else "",
                    "referenced_section": target if ref_type in {"section", "appendix"} else "",
                    "matched_text": match.group(0).strip(),
                }
            )
    return refs


def aggregate_document_entities(chunks: list[dict[str, Any]]) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = {}
    for chunk in chunks:
        for key, values in (chunk.get("entities") or {}).items():
            merged.setdefault(key, set()).update(values)
    return {key: sorted(values) for key, values in merged.items()}


def aggregate_cross_references(chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    refs: list[dict[str, str]] = []
    for chunk in chunks:
        for ref in chunk.get("cross_references") or []:
            key = (ref.get("reference_type", ""), ref.get("referenced_document", ""), ref.get("referenced_section", ""))
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def text_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def similarity_ratio(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", " ", left.lower()).strip()
    right_norm = re.sub(r"\s+", " ", right.lower()).strip()
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def detect_document_duplicates(
    *,
    org_id: str,
    document_id: str,
    title: str,
    version: str,
    file_name: str,
    checksum_sha256: str,
    cleaned_text: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    fingerprint = text_fingerprint(cleaned_text)
    for candidate in candidates:
        if str(candidate.get("id")) == document_id:
            continue
        candidate_checksum = str(candidate.get("checksum_sha256") or "")
        candidate_text = str(candidate.get("extracted_text") or candidate.get("preview_text") or "")
        candidate_title = str(candidate.get("title") or "")
        candidate_version = str(candidate.get("version") or "")
        candidate_name = str(candidate.get("file_name") or "")
        ratio = similarity_ratio(cleaned_text, candidate_text) if candidate_text else 0.0

        if candidate_checksum and candidate_checksum == checksum_sha256:
            warnings.append(
                {
                    "kind": "duplicate_upload",
                    "document_id": str(candidate.get("id")),
                    "title": candidate_title,
                    "similarity": 1.0,
                    "message": f"Identical file to '{candidate_title}' ({candidate_name}).",
                }
            )
            continue
        if fingerprint and candidate_text and text_fingerprint(candidate_text) == fingerprint:
            warnings.append(
                {
                    "kind": "identical_content",
                    "document_id": str(candidate.get("id")),
                    "title": candidate_title,
                    "similarity": 1.0,
                    "message": f"Identical extracted content as '{candidate_title}' despite different filename.",
                }
            )
            continue
        if ratio >= 0.94:
            warnings.append(
                {
                    "kind": "near_duplicate",
                    "document_id": str(candidate.get("id")),
                    "title": candidate_title,
                    "similarity": round(ratio, 4),
                    "message": f"Near-duplicate of '{candidate_title}' ({int(ratio * 100)}% similar).",
                }
            )
            continue
        if ratio >= 0.82:
            left_analysis = analyze_chunk_content(cleaned_text)
            right_analysis = analyze_chunk_content(candidate_text) if candidate_text else {}
            overlapping_procedure = bool(
                left_analysis.get("contains_procedure") and right_analysis.get("contains_procedure")
            )
            kind = "overlapping_procedure" if overlapping_procedure else "semantic_near_duplicate"
            warnings.append(
                {
                    "kind": kind,
                    "document_id": str(candidate.get("id")),
                    "title": candidate_title,
                    "similarity": round(ratio, 4),
                    "message": (
                        f"Overlapping procedure content with '{candidate_title}' ({int(ratio * 100)}% similar)."
                        if overlapping_procedure
                        else f"Semantically similar to '{candidate_title}' ({int(ratio * 100)}% similar)."
                    ),
                }
            )
            continue
        if candidate_title.lower() == title.lower() and candidate_version and version and candidate_version != version:
            warnings.append(
                {
                    "kind": "newer_version",
                    "document_id": str(candidate.get("id")),
                    "title": candidate_title,
                    "similarity": round(ratio, 4),
                    "message": f"Another version exists ({candidate_version}); uploaded version is {version}.",
                }
            )
            continue
        candidate_status = str(candidate.get("status") or "").lower()
        if (
            ratio >= 0.7
            and candidate_title.lower() == title.lower()
            and candidate_status in {"expired", "archived", "needs_reindex"}
        ):
            warnings.append(
                {
                    "kind": "outdated_copy",
                    "document_id": str(candidate.get("id")),
                    "title": candidate_title,
                    "similarity": round(ratio, 4),
                    "message": (
                        f"Possible outdated copy of '{candidate_title}' "
                        f"(status={candidate_status}, {int(ratio * 100)}% similar)."
                    ),
                }
            )
    return warnings


def build_library_analytics(chunks: list[dict[str, Any]], *, estimated_retrieval_quality: int) -> dict[str, Any]:
    token_counts = [int(chunk.get("token_count") or 0) for chunk in chunks if int(chunk.get("token_count") or 0) > 0]
    return {
        "average_chunk_tokens": round(sum(token_counts) / len(token_counts), 1) if token_counts else 0.0,
        "largest_chunk_tokens": max(token_counts) if token_counts else 0,
        "smallest_chunk_tokens": min(token_counts) if token_counts else 0,
        "heading_count": sum(1 for chunk in chunks if chunk.get("section_title")),
        "table_count": sum(1 for chunk in chunks if chunk.get("contains_table")),
        "warning_count": sum(1 for chunk in chunks if chunk.get("contains_warning")),
        "entity_count": sum(len(sum((chunk.get("entities") or {}).values(), [])) for chunk in chunks),
        "estimated_retrieval_quality": estimated_retrieval_quality,
    }


def compute_extraction_score_breakdown(
    *,
    file_name: str,
    cleaned_text: str,
    sections: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    page_count: int | None,
    headers_footers_removed: int,
    metadata_complete: bool,
    duplicate_warnings: list[dict[str, Any]],
    page_char_counts: list[int] | None = None,
) -> tuple[int, list[str], dict[str, Any]]:
    warnings: list[str] = []
    char_count = len(cleaned_text.strip())
    chunk_count = len(chunks)
    pages = page_count or len({section.get("page_number") for section in sections if section.get("page_number")}) or 1
    heading_sections = sum(1 for section in sections if section.get("section_title"))
    table_sections = sum(1 for section in sections if section.get("contains_table") or section.get("chunk_type") == "table" or is_table_like_text(str(section.get("text") or "")))
    operational_hits = count_operational_keywords(cleaned_text)
    token_counts = [int(chunk.get("token_count") or 0) for chunk in chunks]
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0.0
    empty_pages = 0
    if page_char_counts:
        empty_pages = sum(1 for count in page_char_counts if count < 20)
    image_ratio = 0.0
    if pages > 0:
        image_ratio = max(0.0, min(1.0, 1.0 - (char_count / max(pages * EXTRACTION_MIN_CHARS_PER_PAGE, 1))))

    heading_coverage = min(1.0, heading_sections / max(len(sections), 1))
    if Path(file_name).suffix.lower() == ".pdf" and pages > 0:
        ocr_confidence = max(0.0, min(1.0, char_count / (pages * EXTRACTION_MIN_CHARS_PER_PAGE)))
    else:
        ocr_confidence = 1.0
    metadata_completeness = 1.0 if metadata_complete else 0.55
    table_quality = 1.0 if table_sections == 0 else min(1.0, 0.5 + (table_sections / max(chunk_count, 1)))
    if token_counts:
        balance_spread = (max(token_counts) - min(token_counts)) / max(max(token_counts), 1)
        section_balance = max(0.0, 1.0 - balance_spread)
    else:
        section_balance = 0.0
    duplicate_penalty = min(1.0, len(duplicate_warnings) * 0.35)
    empty_page_ratio = empty_pages / pages if pages else 0.0
    operational_keyword_density = min(1.0, operational_hits / 6.0)

    if not char_count:
        warnings.append("No text found after extraction.")
    elif char_count < EXTRACTION_MIN_CHARS:
        warnings.append("Document is too short to retrieve reliably.")
    elif char_count < EXTRACTION_MIN_CHARS * 2:
        warnings.append("Very low text density after extraction.")
    if chunk_count < EXTRACTION_MIN_CHUNKS:
        warnings.append("Few chunks created — document may be hard to search.")
    if table_sections >= 2 or cleaned_text.count("|") >= 12:
        warnings.append("Table-heavy document detected — table-aware extraction recommended.")
    if pages > 0 and char_count / pages < EXTRACTION_MIN_CHARS_PER_PAGE:
        if Path(file_name).suffix.lower() == ".pdf":
            warnings.append("Likely scanned or image-heavy PDF — OCR recommended.")
        else:
            warnings.append("Very low text density per page — content may be image-heavy.")
    if sections and heading_sections == 0:
        warnings.append("No section headings detected — structure may be weak for retrieval.")
    if any(count > SECTION_LARGE_TOKEN_THRESHOLD for count in token_counts):
        warnings.append("Very large chunks detected — semantic boundaries may be weak.")
    if headers_footers_removed > 0:
        warnings.append("Repeated headers or footers were removed during cleanup.")
    if operational_hits == 0 and char_count >= EXTRACTION_MIN_CHARS:
        warnings.append("No useful operational keywords detected — verify this is an operational document.")
    if duplicate_warnings:
        warnings.append("Potential duplicate content detected — review before indexing.")
    if empty_page_ratio > 0.3:
        warnings.append("Multiple empty or near-empty pages detected.")

    weighted = (
        heading_coverage * 14
        + ocr_confidence * 16
        + metadata_completeness * 12
        + table_quality * 8
        + section_balance * 12
        + (1.0 - duplicate_penalty) * 14
        + (1.0 - empty_page_ratio) * 8
        + (1.0 - image_ratio) * 8
        + operational_keyword_density * 8
    )
    overall = max(0, min(100, int(round(weighted))))
    ocr_needed = ocr_confidence < 0.55 or any("OCR" in item for item in warnings)
    reindex_recommended = overall < 70 or chunk_count < EXTRACTION_MIN_CHUNKS or duplicate_penalty > 0

    breakdown = {
        "heading_coverage": round(heading_coverage, 4),
        "ocr_confidence": round(ocr_confidence, 4),
        "metadata_completeness": round(metadata_completeness, 4),
        "table_quality": round(table_quality, 4),
        "section_balance": round(section_balance, 4),
        "duplicate_penalty": round(duplicate_penalty, 4),
        "empty_page_ratio": round(empty_page_ratio, 4),
        "image_ratio": round(image_ratio, 4),
        "operational_keyword_density": round(operational_keyword_density, 4),
        "overall": overall,
    }
    diagnostics = {
        "warnings": warnings,
        "quality_score": overall,
        "score_breakdown": breakdown,
        "char_count": char_count,
        "chunk_count": chunk_count,
        "page_count": pages,
        "file_name": file_name,
        "heading_section_count": heading_sections,
        "table_section_count": table_sections,
        "operational_keyword_hits": operational_hits,
        "headers_footers_removed": headers_footers_removed,
        "ocr_needed": ocr_needed,
        "reindex_recommended": reindex_recommended,
        "average_chunk_tokens": round(avg_tokens, 1),
    }
    return overall, warnings, diagnostics
