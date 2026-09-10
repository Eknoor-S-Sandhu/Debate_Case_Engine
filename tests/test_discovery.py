"""Recursive discovery and source-group inference tests."""

from __future__ import annotations

from pathlib import Path

from debate_engine.config import SourceGroupPatterns
from debate_engine.ingestion.discovery import (
    SkipReason,
    discover_files,
    infer_source_group,
)
from debate_engine.schemas import SourceGroup

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "library"


def test_recursive_discovery_finds_every_supported_fixture() -> None:
    result = discover_files(FIXTURE_ROOT)

    assert len(result.files) == 9
    assert {item.filename for item in result.files} >= {
        "ordinary.docx",
        "reference.PDF",
        "brief.MD",
        "notes.TXT",
    }


def test_discovery_order_is_deterministic_and_case_insensitive() -> None:
    first = discover_files(FIXTURE_ROOT)
    second = discover_files(FIXTURE_ROOT)
    paths = [item.relative_path.as_posix() for item in first.files]

    assert paths == [item.relative_path.as_posix() for item in second.files]
    assert paths == sorted(paths, key=lambda value: (value.casefold(), value))


def test_extensions_are_normalized_to_lowercase() -> None:
    result = discover_files(FIXTURE_ROOT)

    extension_by_name = {item.filename: item.extension for item in result.files}
    assert extension_by_name["reference.PDF"] == ".pdf"
    assert extension_by_name["brief.MD"] == ".md"
    assert extension_by_name["notes.TXT"] == ".txt"


def test_source_group_is_inferred_from_folder_context() -> None:
    result = discover_files(FIXTURE_ROOT)
    groups = {item.filename: item.source_group for item in result.files}

    assert groups["ordinary.docx"] is SourceGroup.PERSONAL
    assert groups["heading.docx"] is SourceGroup.PAST_CASE
    assert groups["brief.MD"] is SourceGroup.OTHER
    assert groups["notes.TXT"] is SourceGroup.OTHER


def test_non_personal_never_matches_personal_substring() -> None:
    inferred = infer_source_group(Path("Non-Personal Files/example.docx"))

    assert inferred is SourceGroup.OTHER


def test_source_group_patterns_are_configurable() -> None:
    patterns = SourceGroupPatterns(
        personal=("team originals",),
        past_case=("tournament archive",),
        other=("reference shelf",),
    )

    assert (
        infer_source_group(
            Path("Team Originals 2026/case.docx"),
            patterns=patterns,
        )
        is SourceGroup.PERSONAL
    )
    assert (
        infer_source_group(
            Path("Tournament Archive/case.docx"),
            patterns=patterns,
        )
        is SourceGroup.PAST_CASE
    )


def test_temporary_hidden_and_unsupported_files_are_auditable_skips() -> None:
    result = discover_files(FIXTURE_ROOT)
    skipped_by_name = {entry.path.name: entry for entry in result.skipped}

    assert "~$temporary.docx" not in {item.filename for item in result.files}
    assert skipped_by_name["~$temporary.docx"].reason is SkipReason.TEMPORARY_OFFICE_FILE
    assert skipped_by_name["unsupported.csv"].reason is SkipReason.UNSUPPORTED_EXTENSION
    assert skipped_by_name[".DS_Store"].reason is SkipReason.HIDDEN
    assert any(entry.path.name == ".hidden" for entry in result.skipped)
    assert len(result.unsupported) == 1


def test_directory_symlinks_are_not_followed(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "case.txt").write_text("Safe source document.", encoding="utf-8")
    (nested / "loop").symlink_to(tmp_path, target_is_directory=True)

    result = discover_files(tmp_path)

    assert [item.filename for item in result.files] == ["case.txt"]
    assert any(entry.reason is SkipReason.SYMLINK for entry in result.skipped)


def test_missing_and_non_directory_roots_fail_clearly(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    regular_file = tmp_path / "file.txt"
    regular_file.write_text("not a directory", encoding="utf-8")

    try:
        discover_files(missing)
    except FileNotFoundError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing root should fail")

    try:
        discover_files(regular_file)
    except NotADirectoryError as exc:
        assert "not a directory" in str(exc)
    else:
        raise AssertionError("file root should fail")
