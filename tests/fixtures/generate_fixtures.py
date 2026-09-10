"""Regenerate the small, synthetic Milestone 2 parser fixtures."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.text import WD_COLOR_INDEX
from pypdf import PdfWriter

FIXTURE_ROOT = Path(__file__).parent / "library"


def _save_document(
    relative_path: str,
    build: Callable[[DocumentObject], None],
) -> None:
    path = FIXTURE_ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    build(document)
    document.save(path)


def _write_text_pdf(path: Path, text: str) -> None:
    """Write a tiny one-page PDF with an extractable Helvetica text stream."""
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{object_number} 0 obj\n".encode())
        content.extend(body)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    path.write_bytes(content)


def generate() -> None:
    if FIXTURE_ROOT.exists():
        shutil.rmtree(FIXTURE_ROOT)

    def ordinary(document: DocumentObject) -> None:
        document.add_paragraph("Governments should invest in resilient public transit.")
        document.add_paragraph("Reliable transit expands access to education and work.")

    def headings(document: DocumentObject) -> None:
        document.add_heading("Public Transit Case", level=1)
        document.add_heading("Accessibility", level=2)
        document.add_paragraph("Affordable transport reduces geographic exclusion.")

    def formatting(document: DocumentObject) -> None:
        paragraph = document.add_paragraph()
        paragraph.add_run("Bold claim.").bold = True
        paragraph.add_run(" Italic warrant.").italic = True
        paragraph.add_run(" Underlined impact.").underline = True
        highlighted = paragraph.add_run(" Highlighted weighing.")
        highlighted.font.highlight_color = WD_COLOR_INDEX.YELLOW

    def table(document: DocumentObject) -> None:
        document.add_paragraph("Comparison follows.")
        table_object = document.add_table(rows=2, cols=2)
        table_object.cell(0, 0).text = "Policy"
        table_object.cell(0, 1).text = "Benefit"
        table_object.cell(1, 0).text = "Bus lanes"
        table_object.cell(1, 1).text = "Shorter travel times"
        document.add_paragraph("Comparison complete.")

    _save_document("Personal Debate Files/ordinary.docx", ordinary)
    _save_document("Personal Debate Files/formatting.docx", formatting)
    _save_document("Past Cases/2024/heading.docx", headings)
    _save_document("Other Debate Files/tables/table.docx", table)

    _write_text_pdf(
        FIXTURE_ROOT / "Other Debate Files/reference.PDF",
        "Extractable evidence says public transit improves access to opportunity.",
    )
    blank_pdf = PdfWriter()
    blank_pdf.add_blank_page(width=612, height=792)
    scan_path = FIXTURE_ROOT / "Scans/empty_scan.pdf"
    scan_path.parent.mkdir(parents=True, exist_ok=True)
    with scan_path.open("wb") as output:
        blank_pdf.write(output)

    markdown_path = FIXTURE_ROOT / "Non-Personal Files/brief.MD"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        "# Synthetic Motion Brief\n\nPublic goods can justify collective investment.\n",
        encoding="utf-8",
    )
    text_path = FIXTURE_ROOT / "Nested/Research/notes.TXT"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        "This is synthetic fixture text.\nIt contains no real debate archive material.\n",
        encoding="utf-8",
    )

    malformed_path = FIXTURE_ROOT / "Broken/malformed.docx"
    malformed_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_path.write_text("This is intentionally not a zip archive.", encoding="utf-8")

    temporary_path = FIXTURE_ROOT / "Temp/~$temporary.docx"
    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path.write_text("Office lock-file fixture", encoding="utf-8")

    unsupported_path = FIXTURE_ROOT / "Other Debate Files/unsupported.csv"
    unsupported_path.write_text("kind,value\nfixture,ignored\n", encoding="utf-8")

    hidden_path = FIXTURE_ROOT / ".hidden/secret.txt"
    hidden_path.parent.mkdir(parents=True, exist_ok=True)
    hidden_path.write_text("Hidden fixture", encoding="utf-8")
    (FIXTURE_ROOT / ".DS_Store").write_bytes(b"fixture")


if __name__ == "__main__":
    generate()
