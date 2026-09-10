"""Page-ordered PDF text extraction and likely-scan detection."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from debate_engine.schemas import (
    DocumentFormat,
    ParsedBlock,
    ParsedDocument,
    ParseStatus,
)

MIN_EXTRACTABLE_CHARACTERS = 20


class PdfParser:
    """Extract each PDF page independently so one bad page is non-fatal."""

    extensions = frozenset({".pdf"})

    def parse(self, path: Path) -> ParsedDocument:
        reader = PdfReader(path)
        page_count = len(reader.pages)
        blocks: list[ParsedBlock] = []
        warnings: list[str] = []

        for page_index, page in enumerate(reader.pages):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # pypdf can surface several backend exceptions
                text = ""
                warnings.append(f"Page {page_index + 1} could not be extracted: {exc}")
            blocks.append(
                ParsedBlock(
                    text=text,
                    index=page_index,
                    block_type="page",
                    page_number=page_index + 1,
                )
            )

        raw_text = "\n\n".join(block.text for block in blocks)
        extractable_character_count = len(re.sub(r"\s+", "", raw_text))

        if page_count and extractable_character_count < MIN_EXTRACTABLE_CHARACTERS:
            warnings.append(
                "PDF has pages but almost no extractable text; it is likely scanned "
                "or image-only and requires OCR."
            )
            status = ParseStatus.NEEDS_OCR
        elif page_count == 0:
            warnings.append("PDF contains no pages.")
            status = ParseStatus.PARTIAL
        elif warnings:
            status = ParseStatus.PARTIAL
        else:
            status = ParseStatus.SUCCESS

        return ParsedDocument(
            source_path=path,
            filename=path.name,
            detected_format=DocumentFormat.PDF,
            raw_text=raw_text,
            blocks=blocks,
            page_count=page_count,
            warnings=warnings,
            parse_status=status,
        )
