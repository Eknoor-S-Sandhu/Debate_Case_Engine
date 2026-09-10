"""Discovery, parsing, structure detection, chunking, and deduplication."""

from debate_engine.ingestion.chunking import (
    approximate_token_count,
    chunk_structured_document,
)
from debate_engine.ingestion.dedupe import (
    detect_duplicates,
    find_exact_duplicate_groups,
    fuzzy_similarity,
    generate_candidate_pairs,
    normalize_duplicate_text,
    select_representative,
    stable_content_hash,
)
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
    "approximate_token_count",
    "chunk_structured_document",
    "detect_duplicates",
    "discover_files",
    "detect_structure",
    "find_exact_duplicate_groups",
    "fuzzy_similarity",
    "generate_candidate_pairs",
    "infer_source_group",
    "normalize_duplicate_text",
    "parse_document",
    "parse_documents",
    "select_representative",
    "stable_content_hash",
]
