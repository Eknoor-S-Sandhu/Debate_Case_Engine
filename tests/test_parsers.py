"""Format parser, dispatch, and batch-failure-isolation tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import debate_engine.ingestion.parsers.legacy_doc_parser as legacy_module
from debate_engine.ingestion.parser import parse_document, parse_documents
from debate_engine.ingestion.parsers.legacy_doc_parser import LegacyDocParser
from debate_engine.schemas import DocumentFormat, ParseStatus

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "library"


def fixture_path(relative_path: str) -> Path:
    return FIXTURE_ROOT / relative_path


def test_docx_extracts_ordinary_paragraphs_in_order() -> None:
    result = parse_document(fixture_path("Personal Debate Files/ordinary.docx"))

    assert result.parse_status is ParseStatus.SUCCESS
    assert result.detected_format is DocumentFormat.DOCX
    assert [block.text for block in result.blocks] == [
        "Governments should invest in resilient public transit.",
        "Reliable transit expands access to education and work.",
    ]
    assert result.raw_text == "\n".join(block.text for block in result.blocks)


def test_docx_preserves_heading_style_and_level() -> None:
    result = parse_document(fixture_path("Past Cases/2024/heading.docx"))

    assert result.parse_status is ParseStatus.SUCCESS
    assert result.blocks[0].text == "Public Transit Case"
    assert result.blocks[0].style_name == "Heading 1"
    assert result.blocks[0].heading_level == 1
    assert result.blocks[1].style_name == "Heading 2"
    assert result.blocks[1].heading_level == 2


def test_docx_preserves_lightweight_formatting_flags() -> None:
    result = parse_document(fixture_path("Personal Debate Files/formatting.docx"))
    block = result.blocks[0]

    assert block.contains_bold
    assert block.contains_italic
    assert block.contains_underline
    assert block.contains_highlight
    assert block.text == ("Bold claim. Italic warrant. Underlined impact. Highlighted weighing.")


def test_docx_keeps_table_text_in_body_reading_order() -> None:
    result = parse_document(fixture_path("Other Debate Files/tables/table.docx"))
    block_text = [block.text for block in result.blocks]

    assert result.parse_status is ParseStatus.SUCCESS
    assert block_text == [
        "Comparison follows.",
        "Policy",
        "Benefit",
        "Bus lanes",
        "Shorter travel times",
        "Comparison complete.",
    ]
    assert [block.block_type for block in result.blocks[1:5]] == ["table_cell"] * 4
    assert all(text in result.raw_text for text in block_text)


def test_pdf_extracts_text_in_page_order() -> None:
    result = parse_document(fixture_path("Other Debate Files/reference.PDF"))

    assert result.parse_status is ParseStatus.SUCCESS
    assert result.detected_format is DocumentFormat.PDF
    assert result.page_count == 1
    assert len(result.blocks) == 1
    assert result.blocks[0].page_number == 1
    assert "public transit improves access" in result.raw_text


def test_blank_pdf_is_flagged_as_needing_ocr() -> None:
    result = parse_document(fixture_path("Scans/empty_scan.pdf"))

    assert result.parse_status is ParseStatus.NEEDS_OCR
    assert result.page_count == 1
    assert not result.raw_text.strip()
    assert any("requires OCR" in warning for warning in result.warnings)


def test_markdown_and_text_preserve_original_text() -> None:
    markdown_path = fixture_path("Non-Personal Files/brief.MD")
    text_path = fixture_path("Nested/Research/notes.TXT")

    markdown = parse_document(markdown_path)
    text = parse_document(text_path)

    assert markdown.parse_status is ParseStatus.SUCCESS
    assert markdown.detected_format is DocumentFormat.MARKDOWN
    assert markdown.raw_text == markdown_path.read_text(encoding="utf-8")
    assert text.parse_status is ParseStatus.SUCCESS
    assert text.detected_format is DocumentFormat.TEXT
    assert text.raw_text == text_path.read_text(encoding="utf-8")


def test_non_utf8_text_uses_declared_fallback(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes("Café evidence".encode("cp1252"))

    result = parse_document(path)

    assert result.parse_status is ParseStatus.PARTIAL
    assert result.raw_text == "Café evidence"
    assert any("Windows-1252" in warning for warning in result.warnings)


def test_parser_dispatch_is_case_insensitive() -> None:
    pdf = parse_document(fixture_path("Other Debate Files/reference.PDF"))
    markdown = parse_document(fixture_path("Non-Personal Files/brief.MD"))

    assert pdf.detected_format is DocumentFormat.PDF
    assert markdown.detected_format is DocumentFormat.MARKDOWN


def test_unknown_extension_returns_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "archive.rtf"
    path.write_text("unsupported", encoding="utf-8")

    result = parse_document(path)

    assert result.parse_status is ParseStatus.UNSUPPORTED
    assert result.detected_format is DocumentFormat.UNKNOWN
    assert "No parser is registered" in result.warnings[0]


def test_malformed_file_returns_failed_without_raising() -> None:
    result = parse_document(fixture_path("Broken/malformed.docx"))

    assert result.parse_status is ParseStatus.FAILED
    assert result.error_message
    assert result.detected_format is DocumentFormat.DOCX


def test_bad_file_does_not_stop_batch() -> None:
    results = parse_documents(
        [
            fixture_path("Broken/malformed.docx"),
            fixture_path("Nested/Research/notes.TXT"),
        ]
    )

    assert [result.parse_status for result in results] == [
        ParseStatus.FAILED,
        ParseStatus.SUCCESS,
    ]


def _fake_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "textutil"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_legacy_doc_invokes_textutil_safely_and_cleans_temp_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"synthetic legacy fixture")
    executable = _fake_executable(tmp_path)
    commands: list[list[str]] = []
    keyword_arguments: list[dict[str, Any]] = []
    temporary_directories: list[Path] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        keyword_arguments.append(kwargs)
        output_path = Path(command[command.index("-output") + 1])
        temporary_directories.append(output_path.parent)
        output_path.write_text("Converted legacy debate text.", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(legacy_module.subprocess, "run", fake_run)
    result = LegacyDocParser(executable=executable).parse(source)

    assert result.parse_status is ParseStatus.SUCCESS
    assert result.raw_text == "Converted legacy debate text."
    assert commands == [
        [
            str(executable),
            "-convert",
            "txt",
            "-encoding",
            "UTF-8",
            "-output",
            commands[0][6],
            str(source),
        ]
    ]
    assert keyword_arguments[0] == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 30.0,
    }
    assert "shell" not in keyword_arguments[0]
    assert all(not directory.exists() for directory in temporary_directories)
    assert source.read_bytes() == b"synthetic legacy fixture"


def test_legacy_doc_reports_unavailable_textutil(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(legacy_module, "find_textutil", lambda: None)

    result = LegacyDocParser().parse(source)

    assert result.parse_status is ParseStatus.UNSUPPORTED
    assert "not found" in result.warnings[0]


def test_legacy_doc_reports_nonzero_exit_and_cleans_temp_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"fixture")
    executable = _fake_executable(tmp_path)
    temporary_directories: list[Path] = []

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("-output") + 1])
        temporary_directories.append(output_path.parent)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="conversion failed")

    monkeypatch.setattr(legacy_module.subprocess, "run", fake_run)
    result = LegacyDocParser(executable=executable).parse(source)

    assert result.parse_status is ParseStatus.FAILED
    assert "conversion failed" in (result.error_message or "")
    assert all(not directory.exists() for directory in temporary_directories)


def test_legacy_doc_timeout_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"fixture")
    executable = _fake_executable(tmp_path)

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 2)

    monkeypatch.setattr(legacy_module.subprocess, "run", fake_run)
    result = LegacyDocParser(executable=executable, timeout_seconds=2).parse(source)

    assert result.parse_status is ParseStatus.FAILED
    assert "timed out after 2 seconds" in (result.error_message or "")
