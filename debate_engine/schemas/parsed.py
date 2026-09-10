"""Loss-light parser output shared by every supported document format."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DocumentFormat(StrEnum):
    """File formats understood by the Milestone 2 parser registry."""

    DOCX = "docx"
    DOC = "doc"
    PDF = "pdf"
    MARKDOWN = "md"
    TEXT = "txt"
    UNKNOWN = "unknown"


class ParseStatus(StrEnum):
    """Outcome of one parse attempt."""

    SUCCESS = "success"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    NEEDS_OCR = "needs_ocr"


class ParsedBlock(BaseModel):
    """An ordered paragraph, table cell, page, or plain-text block.

    Formatting booleans reflect signals directly exposed by the source format.
    A false value can also mean that the format does not carry that signal.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    index: int = Field(ge=0)
    block_type: str = "paragraph"
    style_name: str | None = None
    heading_level: int | None = Field(default=None, ge=1)
    contains_bold: bool = False
    contains_italic: bool = False
    contains_underline: bool = False
    contains_highlight: bool = False
    page_number: int | None = Field(default=None, ge=1)
    table_index: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)


class ParsedDocument(BaseModel):
    """Format-independent result returned for every parse attempt."""

    model_config = ConfigDict(extra="forbid")

    source_path: Path
    filename: str
    detected_format: DocumentFormat
    raw_text: str = ""
    blocks: list[ParsedBlock] = Field(default_factory=list)
    page_count: int | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    parse_status: ParseStatus
    error_message: str | None = None
