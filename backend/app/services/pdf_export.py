from __future__ import annotations

import io


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_simple_pdf(title: str, body: str) -> bytes:
    """Minimal PDF generator (stdlib only) for report export."""
    lines = [title, "", *body.splitlines()]
    content_lines = ["BT", "/F1 12 Tf", "50 750 Td"]
    for i, line in enumerate(lines[:60]):
        prefix = f"0 {-14 * i} Td" if i > 0 else ""
        if i > 0:
            content_lines.append(prefix)
        content_lines.append(f"({_escape_pdf_text(line[:100])}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets: list[int] = []

    def write_obj(obj_id: int, body_bytes: bytes) -> None:
        offsets.append(buffer.tell())
        buffer.write(f"{obj_id} 0 obj\n".encode())
        buffer.write(body_bytes)
        buffer.write(b"\nendobj\n")

    write_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    write_obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    write_obj(
        3,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    )
    write_obj(4, f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    write_obj(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    xref_pos = buffer.tell()
    buffer.write(f"xref\n0 {len(offsets) + 1}\n".encode())
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets:
        buffer.write(f"{offset:010d} 00000 n \n".encode())
    buffer.write(
        f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return buffer.getvalue()
