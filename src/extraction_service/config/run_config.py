"""Per-deployment run-config YAML loader.

The run config is the business-knobs file pointed at by
``EXTRACTION_RUN_CONFIG`` (docs/plan.md §4.7). It captures which OCR engine to
use, the LLM prompt template path, the retry policy, and the user-supplied
domain-schema path — distinct from the process-level ``Settings``.

The schema uses ``extra="forbid"`` on every sub-model so misspelled keys
(``ocr.engien`` instead of ``ocr.engine``) surface at boot, not at first OCR
call. ``load_run_config`` reads + validates and raises ``ValidationError`` on
any schema violation.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

# Mirrors ExtractionError.code class attributes in extraction_service.domain.errors.
# Kept as a separate Literal here (rather than importing from errors.py) to avoid
# a config -> domain dependency and to surface config typos at boot via Pydantic.
# The base-class sentinel "extraction_error" is intentionally excluded — it is
# never a concrete retry trigger (catch-all uses subclass codes). A test in
# tests/unit/test_run_config.py asserts this Literal stays in sync with the
# concrete ExtractionError subclasses' .code attributes.
RetryOnCode = Literal[
    "ocr_engine_failed",
    "ocr_empty_output",
    "llm_failed",
    "context_overflow",
    "schema_invalid",
]

# OCR errors are deterministic on the input (plan §3.3) — retrying them is a
# config-level mistake. The field_validator on RetryConfig rejects these codes
# at boot. Keeping them in the Literal preserves type-completeness; the
# validator is the semantic guard.
_OCR_RETRY_CODES_REJECTED: frozenset[str] = frozenset(
    {"ocr_engine_failed", "ocr_empty_output"}
)

_DEFAULT_RETRY_ON: list[RetryOnCode] = ["llm_failed", "schema_invalid"]


class OcrConfig(BaseModel):
    """OCR engine choice and timeout knobs (docs/plan.md §2.5)."""

    model_config = ConfigDict(extra="forbid")

    engine: Literal["docling"] = "docling"
    force_full_page_ocr: bool = True
    timeout_seconds: PositiveInt = 60


class LlmConfig(BaseModel):
    """LLM stage configuration: prompt template path and timeout (docs/plan.md §6.5)."""

    model_config = ConfigDict(extra="forbid")

    prompt_template_path: Path
    timeout_seconds: PositiveInt = 60


class RetryConfig(BaseModel):
    """Retry policy for the LLM stage. ``retry_on`` lists error codes that
    trigger a retry; OCR errors are always non-retried (docs/plan.md §3.3).
    Entries are validated against the ExtractionError code Literal AND
    rejected at boot if any OCR code (deterministic failure) is listed."""

    model_config = ConfigDict(extra="forbid")

    retry_on: list[RetryOnCode] = Field(default_factory=lambda: list(_DEFAULT_RETRY_ON))

    @field_validator("retry_on")
    @classmethod
    def _reject_ocr_codes(cls, codes: list[RetryOnCode]) -> list[RetryOnCode]:
        invalid = [c for c in codes if c in _OCR_RETRY_CODES_REJECTED]
        if invalid:
            msg = (
                f"retry_on may not contain OCR error codes (deterministic failures per "
                f"plan §3.3): {sorted(invalid)}"
            )
            raise ValueError(msg)
        return codes


class PathsConfig(BaseModel):
    """User-supplied filesystem paths. Currently just the domain-model JSON
    Schema; will grow as later phases add prompt-template directories,
    model-cache locations, etc."""

    model_config = ConfigDict(extra="forbid")

    domain_model_path: Path


class RunConfig(BaseModel):
    """Top-level per-deployment configuration loaded from the YAML file
    pointed at by ``EXTRACTION_RUN_CONFIG`` (docs/plan.md §4.7)."""

    model_config = ConfigDict(extra="forbid")

    ocr: OcrConfig = Field(default_factory=OcrConfig)
    llm: LlmConfig
    retry: RetryConfig = Field(default_factory=RetryConfig)
    paths: PathsConfig


def load_run_config(path: Path) -> RunConfig:
    """Parse and validate a run-config YAML file from disk."""
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return RunConfig.model_validate(data)
