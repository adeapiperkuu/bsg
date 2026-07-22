"""DOCX/PDF export helpers for governance project charters."""

from __future__ import annotations

import io
import re
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

        h1_match = re.match(r"^#\s+(.+)$", trimmed)
        h2_match = re.match(r"^##\s+(.+)$", trimmed)
        h3_match = re.match(r"^###\s+(.+)$", trimmed)
        ordered_match = re.match(r"^(\d+)\.\s+(.+)$", trimmed)
        bullet_match = re.match(r"^[-*]\s+(.+)$", trimmed)
        nested_bullet_match = re.match(r"^\s{2,}[-*]\s+(.+)$", raw)

        if h1_match:
            flush_list()
            blocks.append(RenderBlock(kind="heading1", text=h1_match.group(1).strip()))
            continue

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
        elif block.kind == "heading1":
            paragraphs.append(_paragraph_xml(block.text, bold=True, size=30))
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
    """Escape PDF literal string and map common Unicode to WinAnsi octets."""
    mapped = (
        text.replace("\u2022", "\x95")  # bullet
        .replace("\u00b7", "\xb7")  # middle dot
        .replace("\u2013", "\x96")  # en dash
        .replace("\u2014", "\x97")  # em dash
        .replace("\u2026", "\x85")  # ellipsis
        .replace("\u2018", "\x91")
        .replace("\u2019", "\x92")
        .replace("\u201c", "\x93")
        .replace("\u201d", "\x94")
    )
    encoded = mapped.encode("latin-1", errors="replace").decode("latin-1")
    return (
        encoded.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _approx_text_width(text: str, size: float) -> float:
    # Helvetica average glyph width ~0.5em; good enough for wrapping.
    return len(text) * size * 0.5


def _wrap_pdf_text(text: str, *, size: float, max_width: float) -> list[str]:
    if not text:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _approx_text_width(candidate, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _pdf_color(r: float, g: float, b: float) -> str:
    return f"{r:.3f} {g:.3f} {b:.3f} rg"


def _pdf_stroke(r: float, g: float, b: float) -> str:
    return f"{r:.3f} {g:.3f} {b:.3f} RG"


@dataclass(frozen=True)
class _PdfFragment:
    kind: str
    text: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    height: float = 0.0
    size: float = 10.0
    bold: bool = False
    indent: float = 0.0
    gap_before: float = 0.0


def _fragment_height(fragment: _PdfFragment) -> float:
    return fragment.gap_before + fragment.height


def _build_pdf_fragments(document: CharterExportDocument) -> list[_PdfFragment]:
    content_width = 612 - 54 - 54
    fragments: list[_PdfFragment] = [
        _PdfFragment(kind="cover_rule", height=0, gap_before=0),
        _PdfFragment(
            kind="eyebrow",
            text="BSG  \u00b7  GOVERNED REPORT",
            size=8,
            height=12,
            gap_before=2,
        ),
        _PdfFragment(
            kind="title",
            text=document.title,
            size=20,
            bold=True,
            height=26,
            gap_before=4,
        ),
    ]

    if document.metadata:
        fragments.append(_PdfFragment(kind="spacer", height=6, gap_before=2))
        for label, value in document.metadata:
            lines = _wrap_pdf_text(
                f"{label}:  {value}",
                size=9,
                max_width=content_width,
            )
            for index, line in enumerate(lines):
                fragments.append(
                    _PdfFragment(
                        kind="meta",
                        text=line,
                        size=9,
                        height=12,
                        gap_before=1 if index == 0 else 0,
                    )
                )
        fragments.append(_PdfFragment(kind="divider", height=10, gap_before=8))
    else:
        fragments.append(_PdfFragment(kind="divider", height=10, gap_before=10))

    title_norm = document.title.strip().casefold()
    blocks = parse_delivery_markdown(document.markdown)
    while blocks and blocks[0].kind == "blank":
        blocks = blocks[1:]
    if (
        blocks
        and blocks[0].kind == "heading1"
        and _strip_inline_markdown(blocks[0].text).casefold() == title_norm
    ):
        blocks = blocks[1:]
        while blocks and blocks[0].kind == "blank":
            blocks = blocks[1:]

    previous_was_blank = False
    for block in blocks:
        if block.kind == "blank":
            if previous_was_blank:
                continue
            fragments.append(_PdfFragment(kind="spacer", height=6, gap_before=0))
            previous_was_blank = True
            continue
        previous_was_blank = False

        if block.kind == "heading1":
            text = _strip_inline_markdown(block.text)
            for index, line in enumerate(
                _wrap_pdf_text(text, size=16, max_width=content_width)
            ):
                fragments.append(
                    _PdfFragment(
                        kind="h1",
                        text=line,
                        size=16,
                        bold=True,
                        height=20,
                        gap_before=14 if index == 0 else 2,
                    )
                )
            fragments.append(_PdfFragment(kind="section_rule", height=8, gap_before=2))
            continue

        if block.kind == "heading2":
            text = _strip_inline_markdown(block.text)
            for index, line in enumerate(
                _wrap_pdf_text(text, size=13, max_width=content_width)
            ):
                fragments.append(
                    _PdfFragment(
                        kind="h2",
                        text=line,
                        size=13,
                        bold=True,
                        height=17,
                        gap_before=14 if index == 0 else 2,
                    )
                )
            fragments.append(_PdfFragment(kind="section_rule", height=8, gap_before=2))
            continue

        if block.kind == "heading3":
            text = _strip_inline_markdown(block.text)
            for index, line in enumerate(
                _wrap_pdf_text(text, size=11, max_width=content_width - 8)
            ):
                fragments.append(
                    _PdfFragment(
                        kind="h3",
                        text=line,
                        size=11,
                        bold=True,
                        height=14,
                        gap_before=10 if index == 0 else 1,
                    )
                )
            continue

        if block.kind == "hr":
            fragments.append(_PdfFragment(kind="divider", height=10, gap_before=6))
            continue

        if block.kind == "table":
            rows = tuple(
                tuple(_strip_inline_markdown(cell) for cell in row)
                for row in block.rows
            )
            if not rows:
                continue
            row_h = 16
            table_h = len(rows) * row_h + 6
            fragments.append(
                _PdfFragment(
                    kind="table",
                    rows=rows,
                    height=float(table_h),
                    gap_before=8,
                    size=9,
                )
            )
            continue

        if block.kind in {"bullet", "nested_bullet", "numbered"}:
            level = 1 if block.kind == "nested_bullet" else 0
            if block.kind == "numbered":
                prefix = ""
                body = _strip_inline_markdown(block.text)
            else:
                prefix = "\u2022 "
                body = _strip_inline_markdown(block.text)
            indent = 12.0 + (level * 14.0)
            wrap_width = content_width - indent - 10
            lines = _wrap_pdf_text(f"{prefix}{body}", size=10, max_width=wrap_width)
            for index, line in enumerate(lines):
                line_indent = indent if index == 0 else indent + 10
                fragments.append(
                    _PdfFragment(
                        kind="bullet",
                        text=line,
                        size=10,
                        height=13,
                        gap_before=3 if index == 0 else 1,
                        indent=line_indent,
                    )
                )
            continue

        text = _strip_inline_markdown(block.text)
        lines = _wrap_pdf_text(text, size=10, max_width=content_width)
        for index, line in enumerate(lines):
            fragments.append(
                _PdfFragment(
                    kind="paragraph",
                    text=line,
                    size=10,
                    height=13,
                    gap_before=4 if index == 0 else 1,
                )
            )

    return fragments


def _paginate_fragments(
    fragments: list[_PdfFragment],
    *,
    first_page_top: float,
    later_page_top: float,
    bottom: float,
) -> list[list[_PdfFragment]]:
    pages: list[list[_PdfFragment]] = []
    current: list[_PdfFragment] = []
    y = first_page_top

    for fragment in fragments:
        needed = _fragment_height(fragment)
        if fragment.kind in {"h1", "h2", "h3"} and y - needed < bottom + 36 and current:
            pages.append(current)
            current = []
            y = later_page_top
        if y - needed < bottom and current:
            pages.append(current)
            current = []
            y = later_page_top
        current.append(fragment)
        y -= needed

    pages.append(current or [_PdfFragment(kind="spacer", height=1)])
    return pages


def _draw_table(
    ops: list[str],
    *,
    x: float,
    y_top: float,
    width: float,
    rows: tuple[tuple[str, ...], ...],
    size: float,
) -> float:
    if not rows:
        return y_top
    col_count = max(len(row) for row in rows)
    col_w = width / col_count
    row_h = 16.0
    y = y_top

    for row_index, row in enumerate(rows):
        padded = list(row) + [""] * (col_count - len(row))
        is_header = row_index == 0
        box_bottom = y - row_h
        if is_header:
            ops.append(_pdf_color(0.93, 0.94, 0.96))
            ops.append(f"{x:.2f} {box_bottom:.2f} {width:.2f} {row_h:.2f} re f")
        ops.append(_pdf_stroke(0.80, 0.82, 0.85))
        ops.append("0.6 w")
        ops.append(f"{x:.2f} {box_bottom:.2f} {width:.2f} {row_h:.2f} re S")
        ops.append("BT")
        for col_index, cell in enumerate(padded):
            cell_x = x + 6 + col_index * col_w
            ops.append(
                _pdf_color(0.12, 0.14, 0.18)
                if is_header
                else _pdf_color(0.2, 0.22, 0.25)
            )
            font = "F2" if is_header else "F1"
            ops.append(f"/{font} {size:.0f} Tf")
            display = cell
            while display and _approx_text_width(display, size) > col_w - 12:
                display = display[:-1]
            if display != cell and display:
                display = display[:-1] + "\u2026"
            ops.append(f"1 0 0 1 {cell_x:.2f} {box_bottom + 5:.2f} Tm")
            ops.append(f"({_escape_pdf_text(display)}) Tj")
        ops.append("ET")
        y = box_bottom

    return y - 4


def generate_charter_pdf(document: CharterExportDocument) -> bytes:
    """Render a clean multi-page PDF with cover chrome, sections, lists, and tables."""
    page_w, page_h = 612.0, 792.0
    margin_l, margin_r = 54.0, 54.0
    content_w = page_w - margin_l - margin_r
    first_top = 720.0
    later_top = 734.0
    bottom = 58.0

    fragments = _build_pdf_fragments(document)
    pages = _paginate_fragments(
        fragments,
        first_page_top=first_top,
        later_page_top=later_top,
        bottom=bottom,
    )
    page_count = len(pages)

    streams: list[bytes] = []
    for page_index, page_fragments in enumerate(pages, start=1):
        ops: list[str] = []
        # Top accent bar
        ops.append(_pdf_color(0.12, 0.16, 0.22))
        ops.append(f"0 {page_h - 18:.2f} {page_w:.2f} 18 re f")
        # Footer band
        ops.append(_pdf_color(0.97, 0.97, 0.98))
        ops.append(f"0 0 {page_w:.2f} 44 re f")
        ops.append(_pdf_stroke(0.86, 0.88, 0.90))
        ops.append("0.7 w")
        ops.append(f"0 44 m {page_w:.2f} 44 l S")

        y = first_top if page_index == 1 else later_top
        if page_index > 1:
            ops.append("BT")
            ops.append(_pdf_color(0.45, 0.48, 0.52))
            ops.append("/F1 8 Tf")
            ops.append(f"1 0 0 1 {margin_l:.2f} 748 Tm")
            continued = (
                document.title
                if len(document.title) <= 70
                else document.title[:67] + "..."
            )
            ops.append(f"({_escape_pdf_text(continued)}) Tj")
            ops.append("ET")
            ops.append(_pdf_stroke(0.86, 0.88, 0.90))
            ops.append("0.7 w")
            ops.append(
                f"{margin_l:.2f} 740 m {page_w - margin_r:.2f} 740 l S"
            )

        for fragment in page_fragments:
            y -= fragment.gap_before
            if fragment.kind == "cover_rule":
                continue
            if fragment.kind == "spacer":
                y -= fragment.height
                continue
            if fragment.kind == "divider":
                ops.append(_pdf_stroke(0.84, 0.86, 0.88))
                ops.append("0.8 w")
                ops.append(
                    f"{margin_l:.2f} {y - 2:.2f} m {page_w - margin_r:.2f} {y - 2:.2f} l S"
                )
                y -= fragment.height
                continue
            if fragment.kind == "section_rule":
                ops.append(_pdf_color(0.18, 0.35, 0.48))
                ops.append(f"{margin_l:.2f} {y - 1:.2f} 36 1.5 re f")
                y -= fragment.height
                continue
            if fragment.kind == "table":
                y = _draw_table(
                    ops,
                    x=margin_l,
                    y_top=y,
                    width=content_w,
                    rows=fragment.rows,
                    size=fragment.size,
                )
                continue

            x = margin_l + fragment.indent
            if fragment.kind == "eyebrow":
                color = _pdf_color(0.40, 0.44, 0.50)
            elif fragment.kind == "meta":
                color = _pdf_color(0.38, 0.41, 0.46)
            elif fragment.kind in {"title", "h1", "h2", "h3"}:
                color = _pdf_color(0.10, 0.12, 0.16)
            else:
                color = _pdf_color(0.18, 0.20, 0.24)

            font = "F2" if fragment.bold else "F1"
            baseline = y - fragment.size
            ops.append("BT")
            ops.append(color)
            ops.append(f"/{font} {fragment.size:.0f} Tf")
            ops.append(f"1 0 0 1 {x:.2f} {baseline:.2f} Tm")
            ops.append(f"({_escape_pdf_text(fragment.text)}) Tj")
            ops.append("ET")
            y -= fragment.height

        ops.append("BT")
        ops.append(_pdf_color(0.42, 0.45, 0.50))
        ops.append("/F1 8 Tf")
        ops.append(f"1 0 0 1 {margin_l:.2f} 18 Tm")
        ops.append(f"(Page {page_index} of {page_count}) Tj")
        ops.append(f"1 0 0 1 {page_w - margin_r - 24:.2f} 18 Tm")
        ops.append("(BSG) Tj")
        ops.append("ET")

        streams.append("\n".join(ops).encode("latin-1", errors="replace"))

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets: list[int] = []

    def write_obj(obj_id: int, body_bytes: bytes) -> None:
        offsets.append(buffer.tell())
        buffer.write(f"{obj_id} 0 obj\n".encode())
        buffer.write(body_bytes)
        buffer.write(b"\nendobj\n")

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
    write_obj(
        font_regular_id,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    )
    write_obj(
        font_bold_id,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    )

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
