from __future__ import annotations

import io
import textwrap


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_simple_pdf(title: str, body: str) -> bytes:
    """Minimal paginated PDF generator (stdlib only) for report export."""
    raw_lines = [title, "", *body.splitlines()]
    wrapped_lines: list[str] = []
    for line in raw_lines:
        if not line:
            wrapped_lines.append("")
            continue
        wrapped = textwrap.wrap(line, width=96, replace_whitespace=False) or [""]
        wrapped_lines.extend(wrapped)

    lines_per_page = 52
    pages = [
        wrapped_lines[index : index + lines_per_page]
        for index in range(0, len(wrapped_lines), lines_per_page)
    ] or [[""]]

    streams: list[bytes] = []
    for page_lines in pages:
        content_lines = ["BT", "/F1 10 Tf", "50 750 Td"]
        for i, line in enumerate(page_lines):
            if i > 0:
                content_lines.append("0 -13 Td")
            content_lines.append(f"({_escape_pdf_text(line)}) Tj")
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
    font_id = 3 + (page_count * 2)

    write_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    write_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    for page_id, content_id in zip(page_ids, content_ids, strict=True):
        write_obj(
            page_id,
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                + f"/Contents {content_id} 0 R ".encode()
                + f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
            ),
        )
    for content_id, stream in zip(content_ids, streams, strict=True):
        write_obj(
            content_id,
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        )
    write_obj(font_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

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
