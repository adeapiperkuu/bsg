"""DOCX/PDF export helpers for governance project charters."""

from __future__ import annotations

import io
import re
import textwrap
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

MARKDOWN_TAG_PATTERN = re.compile(r"</?markdown>", re.IGNORECASE)
TABLE_ROW_PATTERN = re.compile(r"^\|.*\|$")
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|?[\s:-]+\|[\s|:-]+\|?$")


@dataclass(frozen=True)
class CharterExportDocument:
    title: str
    metadata: list[tuple[str, str]]
    markdown: str


@dataclass(frozen=True)
class RenderBlock:
    kind: str
    text: str = ""
    rows: list[list[str]] = field(default_factory=list)


def sanitize_delivery_markdown(content: str) -> str:
    """Mirror frontend DeliveryMarkdown sanitization."""
    cleaned = MARKDOWN_TAG_PATTERN.sub("", content)
    cleaned = cleaned.replace("\r\n", "\n").strip()
    cleaned = re.sub(r"^```(?:markdown)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def _is_table_row(line: str) -> bool:
    return bool(TABLE_ROW_PATTERN.match(line.strip()))


def _is_table_separator(line: str) -> bool:
    return bool(TABLE_SEPARATOR_PATTERN.match(line.strip()))


def _parse_table_row(line: str) -> list[str]:
    trimmed = line.strip().strip("|")
    return [cell.strip() for cell in trimmed.split("|")]


def _strip_inline_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def parse_delivery_markdown(markdown: str) -> list[RenderBlock]:
    """Parse markdown using the same rules as frontend DeliveryMarkdown."""
    sanitized = sanitize_delivery_markdown(markdown)
    blocks: list[RenderBlock] = []
    list_items: list[tuple[str, str]] = []
    list_ordered = False
    table_rows: list[list[str]] = []

    def flush_list() -> None:
        nonlocal list_items, list_ordered
        if not list_items:
            return
        for kind, text in list_items:
            blocks.append(RenderBlock(kind=kind, text=text))
        list_items = []
        list_ordered = False

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        blocks.append(RenderBlock(kind="table", rows=[row[:] for row in table_rows]))
        table_rows = []

    for raw in sanitized.split("\n"):
        trimmed = raw.strip()

        if not trimmed:
            flush_list()
            flush_table()
            blocks.append(RenderBlock(kind="blank"))
            continue

        if trimmed in {"---", "***"}:
            flush_list()
            flush_table()
            blocks.append(RenderBlock(kind="hr"))
            continue

        if _is_table_row(trimmed):
            flush_list()
            if _is_table_separator(trimmed):
                continue
            table_rows.append(_parse_table_row(trimmed))
            continue

        if table_rows:
            flush_table()

        h2_match = re.match(r"^##\s+(.+)$", trimmed)
        h3_match = re.match(r"^###\s+(.+)$", trimmed)
        ordered_match = re.match(r"^(\d+)\.\s+(.+)$", trimmed)
        bullet_match = re.match(r"^[-*]\s+(.+)$", trimmed)
        nested_bullet_match = re.match(r"^\s{2,}[-*]\s+(.+)$", raw)

        if h2_match:
            flush_list()
            blocks.append(RenderBlock(kind="heading2", text=h2_match.group(1).strip()))
            continue

        if h3_match:
            flush_list()
            blocks.append(RenderBlock(kind="heading3", text=h3_match.group(1).strip()))
            continue

        if nested_bullet_match:
            list_items.append(("nested_bullet", nested_bullet_match.group(1).strip()))
            continue

        if ordered_match:
            if list_items and not list_ordered:
                flush_list()
            list_ordered = True
            list_items.append(("numbered", f"{ordered_match.group(1)}. {ordered_match.group(2).strip()}"))
            continue

        if bullet_match:
            if list_items and list_ordered:
                flush_list()
            list_items.append(("bullet", bullet_match.group(1).strip()))
            continue

        flush_list()
        blocks.append(RenderBlock(kind="paragraph", text=trimmed))

    flush_list()
    flush_table()
    return blocks


def _inline_runs_xml(text: str, *, size: int = 20, default_bold: bool = False) -> str:
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    runs: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            content = part[2:-2]
            bold = True
        else:
            content = _strip_inline_markdown(part)
            bold = default_bold
        props = [f'<w:sz w:val="{size}"/>']
        if bold:
            props.append("<w:b/>")
        runs.append(
            f'<w:r><w:rPr>{"".join(props)}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(content)}</w:t></w:r>'
        )
    if not runs:
        runs.append(
            f'<w:r><w:rPr><w:sz w:val="{size}"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(_strip_inline_markdown(text))}</w:t></w:r>'
        )
    return "".join(runs)


def _paragraph_xml(
    text: str,
    *,
    bold: bool = False,
    size: int = 22,
    style: str | None = None,
) -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    runs = _inline_runs_xml(text, size=size, default_bold=bold)
    return f"<w:p>{style_xml}{runs}</w:p>"


def _bullet_xml(text: str, *, prefix: str = "- ") -> str:
    return _paragraph_xml(f"{prefix}{text}", size=20)


def _table_xml(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    col_count = max(len(row) for row in rows)
    grid = "".join('<w:gridCol w:w="2400"/>' for _ in range(col_count))
    table_rows: list[str] = []
    for row_index, row in enumerate(rows):
        cells: list[str] = []
        for col_index in range(col_count):
            cell_text = row[col_index] if col_index < len(row) else ""
            cell_runs = _inline_runs_xml(cell_text, size=18, default_bold=row_index == 0)
            cells.append(f"<w:tc><w:p>{cell_runs}</w:p></w:tc>")
        table_rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (
        "<w:tbl>"
        "<w:tblPr><w:tblW w:w=\"5000\" w:type=\"pct\"/>"
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CCCCCC\"/>"
        "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CCCCCC\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CCCCCC\"/>"
        "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CCCCCC\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CCCCCC\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CCCCCC\"/>"
        "</w:tblBorders></w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        f"{''.join(table_rows)}"
        "</w:tbl>"
    )


def _render_blocks_to_docx_paragraphs(blocks: list[RenderBlock]) -> list[str]:
    paragraphs: list[str] = []
    for block in blocks:
        if block.kind == "blank":
            paragraphs.append(_paragraph_xml("", size=8))
        elif block.kind == "hr":
            paragraphs.append(_paragraph_xml("—" * 24, size=18))
        elif block.kind == "heading2":
            paragraphs.append(_paragraph_xml(block.text, bold=True, size=26))
        elif block.kind == "heading3":
            paragraphs.append(_paragraph_xml(block.text, bold=True, size=22))
        elif block.kind == "bullet":
            paragraphs.append(_bullet_xml(block.text))
        elif block.kind == "nested_bullet":
            paragraphs.append(_bullet_xml(f"  {block.text}"))
        elif block.kind == "numbered":
            paragraphs.append(_bullet_xml(block.text, prefix=""))
        elif block.kind == "table":
            paragraphs.append(_table_xml(block.rows))
            paragraphs.append(_paragraph_xml("", size=8))
        else:
            paragraphs.append(_paragraph_xml(block.text, size=20))
    return paragraphs


def generate_charter_docx(document: CharterExportDocument) -> bytes:
    paragraphs = [
        _paragraph_xml(document.title, bold=True, size=32),
        _paragraph_xml("", size=8),
    ]
    for label, value in document.metadata:
        paragraphs.append(_paragraph_xml(f"{label}: {value}", size=18))
    paragraphs.append(_paragraph_xml("", size=8))
    paragraphs.extend(_render_blocks_to_docx_paragraphs(parse_delivery_markdown(document.markdown)))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/></w:sectPr>'
        "</w:body></w:document>"
    )

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_line_for_block(block: RenderBlock) -> tuple[int, str, bool]:
    bold = False
    if block.kind == "heading2":
        return 15, _strip_inline_markdown(block.text), True
    if block.kind == "heading3":
        return 12, _strip_inline_markdown(block.text), True
    if block.kind == "bullet":
        return 10, f"- {_strip_inline_markdown(block.text)}", False
    if block.kind == "nested_bullet":
        return 10, f"  - {_strip_inline_markdown(block.text)}", False
    if block.kind == "numbered":
        return 10, _strip_inline_markdown(block.text), False
    if block.kind == "hr":
        return 10, "—" * 24, False
    if block.kind == "table":
        return 10, " | ".join(_strip_inline_markdown(cell) for cell in block.rows[0]), True
    if block.kind == "blank":
        return 10, "", False
    return 10, _strip_inline_markdown(block.text), False


def generate_charter_pdf(document: CharterExportDocument) -> bytes:
    rendered: list[tuple[int, str, bool]] = [
        (18, document.title, True),
        (10, "", False),
    ]
    for label, value in document.metadata:
        rendered.append((10, f"{label}: {value}", False))
    rendered.append((10, "", False))

    blocks = parse_delivery_markdown(document.markdown)
    for block in blocks:
        if block.kind == "table":
            header, *body = block.rows
            rendered.append(_pdf_line_for_block(RenderBlock(kind="table", rows=[header])))
            for row in body:
                rendered.append((10, " | ".join(_strip_inline_markdown(cell) for cell in row), False))
            continue
        rendered.append(_pdf_line_for_block(block))

    output_lines: list[tuple[int, str, bool]] = []
    for size, text, bold in rendered:
        if not text:
            output_lines.append((size, "", bold))
            continue
        width = 78 if size <= 10 else 60
        wrapped = textwrap.wrap(text, width=width, replace_whitespace=False) or [""]
        for index, line in enumerate(wrapped):
            output_lines.append((size, line, bold if index == 0 else False))

    pages: list[list[tuple[int, str, bool]]] = []
    current: list[tuple[int, str, bool]] = []
    y = 750
    for size, text, bold in output_lines:
        line_height = max(13, size + 5)
        if y - line_height < 50 and current:
            pages.append(current)
            current = []
            y = 750
        current.append((size, text, bold))
        y -= line_height
    pages.append(current or [(10, "", False)])

    streams: list[bytes] = []
    for page_lines in pages:
        content_lines = ["BT", "50 750 Td"]
        previous_size = 10
        first = True
        for size, text, bold in page_lines:
            if not first:
                content_lines.append(f"0 -{max(13, previous_size + 5)} Td")
            font = "F2" if bold or size >= 12 else "F1"
            content_lines.append(f"/{font} {size} Tf")
            content_lines.append(f"({_escape_pdf_text(text)}) Tj")
            previous_size = size
            first = False
        content_lines.append("ET")
        streams.append("\n".join(content_lines).encode("latin-1", errors="replace"))

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets: list[int] = []

    def write_obj(obj_id: int, body_bytes: bytes) -> None:
        offsets.append(buffer.tell())
        buffer.write(f"{obj_id} 0 obj\n".encode())
        buffer.write(body_bytes)
        buffer.write(b"\nendobj\n")

    page_count = len(streams)
    page_ids = list(range(3, 3 + page_count))
    content_ids = list(range(3 + page_count, 3 + (page_count * 2)))
    font_regular_id = 3 + (page_count * 2)
    font_bold_id = font_regular_id + 1

    write_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    write_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    for page_id, content_id in zip(page_ids, content_ids, strict=True):
        write_obj(
            page_id,
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                + f"/Contents {content_id} 0 R ".encode()
                + (
                    f"/Resources << /Font << /F1 {font_regular_id} 0 R "
                    f"/F2 {font_bold_id} 0 R >> >> >>"
                ).encode()
            ),
        )
    for content_id, stream in zip(content_ids, streams, strict=True):
        write_obj(
            content_id,
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        )
    write_obj(font_regular_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    write_obj(font_bold_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    xref_pos = buffer.tell()
    buffer.write(f"xref\n0 {len(offsets) + 1}\n".encode())
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets:
        buffer.write(f"{offset:010d} 00000 n \n".encode())
    trailer = (
        f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    buffer.write(trailer.encode())
    return buffer.getvalue()


def generate_simple_docx(title: str, body: str) -> bytes:
    """Backward-compatible wrapper for existing imports."""
    return generate_charter_docx(CharterExportDocument(title=title, metadata=[], markdown=body))
