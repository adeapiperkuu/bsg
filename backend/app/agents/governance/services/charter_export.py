"""Minimal DOCX export (stdlib only) for governance charter documents."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape


def _paragraph_xml(text: str, *, bold: bool = False) -> str:
    safe = escape(text)
    if bold:
        return f"<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"


def generate_simple_docx(title: str, body: str) -> bytes:
    """Create a minimal Word document from plain text lines."""
    paragraphs = [_paragraph_xml(title, bold=True), _paragraph_xml("")]
    for line in body.splitlines():
        paragraphs.append(_paragraph_xml(line))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
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
