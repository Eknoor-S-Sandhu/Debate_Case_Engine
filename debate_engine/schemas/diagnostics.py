"""Safe per-stage inference telemetry; no prompt or response bodies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InferenceCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str
    elapsed_seconds: float = Field(ge=0)
    status: Literal["received", "failed", "invalid_output"]
    error_code: str | None = None
    http_status: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
