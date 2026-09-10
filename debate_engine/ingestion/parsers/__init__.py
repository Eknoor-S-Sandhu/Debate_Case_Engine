"""Format-specific document parsers."""

from debate_engine.ingestion.parsers.docx_parser import DocxParser
from debate_engine.ingestion.parsers.legacy_doc_parser import LegacyDocParser
from debate_engine.ingestion.parsers.pdf_parser import PdfParser
from debate_engine.ingestion.parsers.text_parser import TextParser

__all__ = ["DocxParser", "LegacyDocParser", "PdfParser", "TextParser"]
