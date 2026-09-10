"""UTF-8-first parsing for Markdown and plain-text documents."""

from __future__ import annotations

from pathlib import Path

from debate_engine.schemas import (
    DocumentFormat,
    ParsedBlock,
    ParsedDocument,
    ParseStatus,
)


def read_text_with_fallback(path: Path) -> tuple[str, list[str]]:
    """Read text as UTF-8, falling back to Windows-1252 with a warning."""
    try:
        return path.read_text(encoding="utf-8-sig"), []
    except UnicodeDecodeError as utf8_error:
        try:
            text = path.read_text(encoding="cp1252")
        except UnicodeError as fallback_error:
            raise UnicodeError(
                f"could not decode as UTF-8 ({utf8_error}) or Windows-1252 ({fallback_error})"
            ) from fallback_error
        return text, ["Input was not UTF-8; decoded with Windows-1252 fallback."]


class TextParser:
    """Parser shared by ``.md`` and ``.txt`` files."""

    extensions = frozenset({".md", ".txt"})

    def parse(self, path: Path) -> ParsedDocument:
        text, warnings = read_text_with_fallback(path)
        if "\x00" in text:
            raise ValueError("file contains NUL bytes and does not appear to be plain text")

        detected_format = (
            DocumentFormat.MARKDOWN if path.suffix.casefold() == ".md" else DocumentFormat.TEXT
        )
        blocks = [
            ParsedBlock(text=line, index=index, block_type="line")
            for index, line in enumerate(text.splitlines())
        ]

        if not text.strip():
            warnings.append("Document contains no non-whitespace text.")

        return ParsedDocument(
            source_path=path,
            filename=path.name,
            detected_format=detected_format,
            raw_text=text,
            blocks=blocks,
            warnings=warnings,
            parse_status=ParseStatus.PARTIAL if warnings else ParseStatus.SUCCESS,
        )
