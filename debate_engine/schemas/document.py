"""Document-level schema and the shared provenance enums."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SourceGroup(StrEnum):
    """Where a document came from, which drives its retrieval priority."""

    PERSONAL = "personal"
    PAST_CASE = "past_case"
    OTHER = "other"


class DocumentType(StrEnum):
    """Broad kind of debate document."""

    CASE = "case"
    MASTERFILE = "masterfile"
    BLOCK = "block"
    IMPACT = "impact"
    FACT_SHEET = "fact_sheet"
    THEORY = "theory"
    KRITIK = "kritik"
    UNKNOWN = "unknown"


class Side(StrEnum):
    """Side of the motion a document argues for."""

    AFF = "aff"
    NEG = "neg"
    GOV = "gov"
    OPP = "opp"
    UNKNOWN = "unknown"


class RoundType(StrEnum):
    """Resolution type the document is written for."""

    POLICY = "policy"
    VALUE = "value"
    FACT = "fact"
    UNKNOWN = "unknown"


class DebateDocument(BaseModel):
    """A single ingested file from the debate library."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    document_id: str
    filename: str
    full_path: str

    source_group: SourceGroup = SourceGroup.OTHER
    document_type: DocumentType = DocumentType.UNKNOWN
    side: Side = Side.UNKNOWN
    round_type: RoundType = RoundType.UNKNOWN

    year: int | None = None
    title: str | None = None

    raw_text: str = ""
    priority_weight: float = Field(default=1.0, ge=0.0)
