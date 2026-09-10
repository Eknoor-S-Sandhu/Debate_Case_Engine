"""Recursive, deterministic discovery of debate source documents."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from debate_engine.config import SourceGroupPatterns, get_settings
from debate_engine.schemas import SourceGroup

LOGGER = logging.getLogger("debate_engine.ingestion.discovery")

SUPPORTED_EXTENSIONS = frozenset({".docx", ".doc", ".pdf", ".md", ".txt"})
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
    }
)


class SkipReason(StrEnum):
    """Why a filesystem entry was intentionally not discovered."""

    HIDDEN = "hidden"
    TEMPORARY_OFFICE_FILE = "temporary_office_file"
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    SYMLINK = "symlink"
    UNREADABLE_DIRECTORY = "unreadable_directory"


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    """A supported source file plus basic path-derived provenance."""

    path: Path
    filename: str
    extension: str
    relative_path: Path
    source_group: SourceGroup


@dataclass(frozen=True, slots=True)
class SkippedEntry:
    """A filesystem entry omitted from discovery with an explicit reason."""

    path: Path
    relative_path: Path
    reason: SkipReason
    detail: str


@dataclass(slots=True)
class DiscoveryResult:
    """Supported files and auditable omissions from one recursive scan."""

    root: Path
    files: list[DiscoveredFile] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)

    @property
    def unsupported(self) -> list[SkippedEntry]:
        """Return regular files skipped solely because of their extension."""
        return [entry for entry in self.skipped if entry.reason is SkipReason.UNSUPPORTED_EXTENSION]


def _normalize_folder_name(value: str) -> str:
    """Case-fold and collapse punctuation/whitespace for tolerant matching."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _matches_marker(folder: str, marker: str) -> bool:
    """Match a marker as a complete folder label, allowing year suffixes."""
    return folder == marker or folder.startswith(f"{marker} ") or folder.endswith(f" {marker}")


def infer_source_group(
    relative_path: Path,
    *,
    root_name: str = "",
    patterns: SourceGroupPatterns | None = None,
) -> SourceGroup:
    """Infer provenance from folder names, preferring the nearest clear hint.

    The filename itself is deliberately excluded. ``other`` is checked before
    ``personal`` so a folder named ``Non-Personal Files`` cannot be
    misclassified merely because it contains the word "personal".
    """
    configured = patterns or get_settings().source_group_patterns
    normalized_patterns = (
        (
            SourceGroup.OTHER,
            tuple(_normalize_folder_name(item) for item in configured.other),
        ),
        (
            SourceGroup.PAST_CASE,
            tuple(_normalize_folder_name(item) for item in configured.past_case),
        ),
        (
            SourceGroup.PERSONAL,
            tuple(_normalize_folder_name(item) for item in configured.personal),
        ),
    )

    folder_parts = [root_name, *relative_path.parts[:-1]]
    for part in reversed(folder_parts):
        normalized_folder = _normalize_folder_name(part)
        if not normalized_folder:
            continue
        for source_group, markers in normalized_patterns:
            if any(_matches_marker(normalized_folder, marker) for marker in markers):
                return source_group
    return SourceGroup.OTHER


def _relative_or_name(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return Path(path.name)


def discover_files(
    root: Path,
    *,
    patterns: SourceGroupPatterns | None = None,
) -> DiscoveryResult:
    """Recursively find supported files without following directory symlinks.

    Unsupported regular files are recorded and logged rather than silently
    discarded. Hidden and temporary files are recorded as intentional skips.
    """
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Library root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Library root is not a directory: {root}")

    result = DiscoveryResult(root=root)

    def record_skip(path: Path, reason: SkipReason, detail: str) -> None:
        entry = SkippedEntry(
            path=path,
            relative_path=_relative_or_name(path, root),
            reason=reason,
            detail=detail,
        )
        result.skipped.append(entry)
        LOGGER.info("Skipping %s: %s", entry.relative_path, detail)

    def visit(directory: Path) -> None:
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda path: (path.name.casefold(), path.name),
            )
        except OSError as exc:
            record_skip(
                directory,
                SkipReason.UNREADABLE_DIRECTORY,
                f"unable to read directory ({exc})",
            )
            return

        for path in entries:
            if path.is_symlink():
                record_skip(path, SkipReason.SYMLINK, "symbolic links are not followed")
                continue

            name = path.name
            if name.startswith("."):
                record_skip(path, SkipReason.HIDDEN, "hidden entry")
                continue
            if name.startswith("~$"):
                record_skip(
                    path,
                    SkipReason.TEMPORARY_OFFICE_FILE,
                    "temporary Office lock file",
                )
                continue

            if path.is_dir():
                if name.casefold() in IGNORED_DIRECTORY_NAMES:
                    record_skip(path, SkipReason.HIDDEN, "non-source directory")
                else:
                    visit(path)
                continue

            extension = path.suffix.casefold()
            relative_path = path.relative_to(root)
            if extension not in SUPPORTED_EXTENSIONS:
                detail = f"unsupported extension {extension or '(none)'}"
                record_skip(path, SkipReason.UNSUPPORTED_EXTENSION, detail)
                continue

            result.files.append(
                DiscoveredFile(
                    path=path.resolve(),
                    filename=name,
                    extension=extension,
                    relative_path=relative_path,
                    source_group=infer_source_group(
                        relative_path,
                        root_name=root.name,
                        patterns=patterns,
                    ),
                )
            )

    visit(root)
    result.files.sort(
        key=lambda item: (item.relative_path.as_posix().casefold(), item.relative_path.as_posix())
    )
    result.skipped.sort(
        key=lambda item: (item.relative_path.as_posix().casefold(), item.relative_path.as_posix())
    )
    return result
