"""Normalized, hierarchical debate-document structure."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from debate_engine.schemas.parsed import ParsedBlock


class StructuredSection(BaseModel):
    """A detected heading and the body blocks directly owned by it.

    ``section_type`` intentionally remains an extensible string. Formatting
    fields copy lightweight signals from the heading block; source indexes
    retain the link back to every parsed block used by this section.
    """

    model_config = ConfigDict(extra="forbid")

    section_id: str
    section_type: str
    original_heading: str | None
    normalized_heading: str | None
    text: str = ""
    level: int = Field(ge=1)
    order_index: int = Field(ge=0)
    parent_section_id: str | None = None
    children: list[StructuredSection] = Field(default_factory=list)
    source_block_indexes: list[int] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    detection_method: str

    heading_style_name: str | None = None
    heading_contains_bold: bool = False
    heading_contains_italic: bool = False
    heading_contains_underline: bool = False
    heading_contains_highlight: bool = False

    def iter_sections(self) -> Iterator[StructuredSection]:
        """Yield this section and descendants in document order."""
        yield self
        for child in self.children:
            yield from child.iter_sections()


class StructuredDocument(BaseModel):
    """Structure-detection output for one parsed source document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_path: Path
    filename: str
    title: str | None = None
    sections: list[StructuredSection] = Field(default_factory=list)
    unstructured_text: str = ""
    orphan_blocks: list[ParsedBlock] = Field(default_factory=list)
    detection_warnings: list[str] = Field(default_factory=list)
    overall_structure_confidence: float = Field(ge=0.0, le=1.0)

    def iter_sections(self) -> Iterator[StructuredSection]:
        """Yield all sections depth-first in document order."""
        for section in self.sections:
            yield from section.iter_sections()
