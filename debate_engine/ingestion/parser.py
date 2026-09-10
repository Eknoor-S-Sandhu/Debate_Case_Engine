"""Format-independent parser dispatch and failure containment."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Protocol

from debate_engine.ingestion.parsers import (
    DocxParser,
    LegacyDocParser,
    PdfParser,
    TextParser,
)
from debate_engine.schemas import DocumentFormat, ParsedDocument, ParseStatus

LOGGER = logging.getLogger("debate_engine.ingestion.parser")

_FORMAT_BY_EXTENSION = {
    ".docx": DocumentFormat.DOCX,
    ".doc": DocumentFormat.DOC,
    ".pdf": DocumentFormat.PDF,
    ".md": DocumentFormat.MARKDOWN,
    ".txt": DocumentFormat.TEXT,
}


class DocumentParser(Protocol):
    """Behavior required from a format-specific parser."""

    extensions: frozenset[str]

    def parse(self, path: Path) -> ParsedDocument:
        """Parse ``path`` into a format-independent result."""
        ...


def build_parser_registry() -> dict[str, DocumentParser]:
    """Build the default extension-to-parser registry."""
    parser_instances: tuple[DocumentParser, ...] = (
        DocxParser(),
        LegacyDocParser(),
        PdfParser(),
        TextParser(),
    )
    return {extension: parser for parser in parser_instances for extension in parser.extensions}


def parse_document(
    path: Path,
    *,
    parsers: Mapping[str, DocumentParser] | None = None,
) -> ParsedDocument:
    """Parse one document without allowing file-specific errors to escape."""
    path = path.expanduser().resolve()
    extension = path.suffix.casefold()
    detected_format = _FORMAT_BY_EXTENSION.get(extension, DocumentFormat.UNKNOWN)
    registry = parsers if parsers is not None else build_parser_registry()
    parser = registry.get(extension)

    if parser is None:
        message = f"No parser is registered for extension {extension or '(none)'}."
        LOGGER.warning("Unsupported document %s: %s", path, message)
        return ParsedDocument(
            source_path=path,
            filename=path.name,
            detected_format=detected_format,
            parse_status=ParseStatus.UNSUPPORTED,
            warnings=[message],
        )

    try:
        result = parser.parse(path)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Failed to parse %s: %s", path, message)
        return ParsedDocument(
            source_path=path,
            filename=path.name,
            detected_format=detected_format,
            parse_status=ParseStatus.FAILED,
            warnings=[message],
            error_message=message,
        )

    if result.parse_status in {ParseStatus.FAILED, ParseStatus.UNSUPPORTED}:
        LOGGER.warning(
            "Parser returned %s for %s: %s",
            result.parse_status,
            path,
            result.error_message or "; ".join(result.warnings),
        )
    elif result.parse_status in {ParseStatus.PARTIAL, ParseStatus.NEEDS_OCR}:
        LOGGER.info(
            "Parser returned %s for %s: %s",
            result.parse_status,
            path,
            "; ".join(result.warnings),
        )
    return result


def parse_documents(paths: Iterable[Path]) -> list[ParsedDocument]:
    """Parse a batch while preserving input order and isolating failures."""
    registry = build_parser_registry()
    return [parse_document(path, parsers=registry) for path in paths]
