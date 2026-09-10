"""Document discovery and format-independent parsing.

Debate structure detection and chunking begin in later milestones.
"""

from debate_engine.ingestion.discovery import (
    DiscoveredFile,
    DiscoveryResult,
    SkippedEntry,
    SkipReason,
    discover_files,
    infer_source_group,
)
from debate_engine.ingestion.parser import parse_document, parse_documents
from debate_engine.ingestion.structure import detect_structure

__all__ = [
    "DiscoveredFile",
    "DiscoveryResult",
    "SkippedEntry",
    "SkipReason",
    "discover_files",
    "detect_structure",
    "infer_source_group",
    "parse_document",
    "parse_documents",
]
