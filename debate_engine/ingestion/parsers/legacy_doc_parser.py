"""Isolated macOS ``textutil`` adapter for legacy Word ``.doc`` files."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from debate_engine.ingestion.parsers.text_parser import read_text_with_fallback
from debate_engine.schemas import (
    DocumentFormat,
    ParsedBlock,
    ParsedDocument,
    ParseStatus,
)

DEFAULT_TEXTUTIL_PATH = Path("/usr/bin/textutil")
DEFAULT_TIMEOUT_SECONDS = 30.0


def find_textutil() -> Path | None:
    """Return an executable textutil path, preferring the macOS system binary."""
    if DEFAULT_TEXTUTIL_PATH.is_file() and os.access(DEFAULT_TEXTUTIL_PATH, os.X_OK):
        return DEFAULT_TEXTUTIL_PATH
    discovered = shutil.which("textutil")
    return Path(discovered) if discovered else None


def _result(
    path: Path,
    status: ParseStatus,
    *,
    warnings: list[str] | None = None,
    error_message: str | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        source_path=path,
        filename=path.name,
        detected_format=DocumentFormat.DOC,
        parse_status=status,
        warnings=warnings or [],
        error_message=error_message,
    )


class LegacyDocParser:
    """Convert a copy of legacy Word content to temporary plain text."""

    extensions = frozenset({".doc"})

    def __init__(
        self,
        *,
        executable: Path | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def parse(self, path: Path) -> ParsedDocument:
        executable = self._executable or find_textutil()
        if executable is None or not executable.is_file() or not os.access(executable, os.X_OK):
            message = (
                "Legacy .doc parsing is unsupported because an executable "
                "textutil binary was not found."
            )
            return _result(path, ParseStatus.UNSUPPORTED, warnings=[message])

        try:
            with tempfile.TemporaryDirectory(prefix="debate-doc-") as temporary_directory:
                output_path = Path(temporary_directory) / f"{path.stem}.txt"
                command = [
                    str(executable),
                    "-convert",
                    "txt",
                    "-encoding",
                    "UTF-8",
                    "-output",
                    str(output_path),
                    str(path),
                ]
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                )
                stderr = completed.stderr.strip()
                if completed.returncode != 0:
                    message = f"textutil exited with status {completed.returncode}" + (
                        f": {stderr}" if stderr else "."
                    )
                    return _result(
                        path,
                        ParseStatus.FAILED,
                        warnings=[message],
                        error_message=message,
                    )
                if not output_path.is_file():
                    message = "textutil reported success but did not create converted text."
                    return _result(
                        path,
                        ParseStatus.FAILED,
                        warnings=[message],
                        error_message=message,
                    )

                raw_text, decode_warnings = read_text_with_fallback(output_path)
                warnings = list(decode_warnings)
                if stderr:
                    warnings.append(f"textutil warning: {stderr}")
                if not raw_text.strip():
                    warnings.append("Converted document contains no non-whitespace text.")

                blocks = [
                    ParsedBlock(text=line, index=index, block_type="line")
                    for index, line in enumerate(raw_text.splitlines())
                ]
                return ParsedDocument(
                    source_path=path,
                    filename=path.name,
                    detected_format=DocumentFormat.DOC,
                    raw_text=raw_text,
                    blocks=blocks,
                    warnings=warnings,
                    parse_status=ParseStatus.PARTIAL if warnings else ParseStatus.SUCCESS,
                )
        except subprocess.TimeoutExpired:
            message = f"textutil timed out after {self._timeout_seconds:g} seconds."
            return _result(
                path,
                ParseStatus.FAILED,
                warnings=[message],
                error_message=message,
            )
        except OSError as exc:
            message = f"textutil could not be executed: {exc}"
            return _result(
                path,
                ParseStatus.FAILED,
                warnings=[message],
                error_message=message,
            )
