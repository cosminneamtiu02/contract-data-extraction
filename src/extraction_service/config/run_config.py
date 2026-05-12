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
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

# Mirrors ExtractionError.code class attributes in extraction_service.domain.errors.
# Kept as a separate Literal here (rather than importing from errors.py) to avoid
# a config -> domain dependency and to surface config typos at boot via Pydantic.
RetryOnCode = Literal[
    "ocr_engine_failed",
    "ocr_empty_output",
    "llm_failed",
    "context_overflow",
    "schema_invalid",
]

_DEFAULT_RETRY_ON: list[RetryOnCode] = ["llm_failed", "schema_invalid"]


class OcrConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["docling"] = "docling"
    force_full_page_ocr: bool = True
    timeout_seconds: PositiveInt = 60


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_template_path: Path
    timeout_seconds: PositiveInt = 60


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry_on: list[RetryOnCode] = Field(default_factory=lambda: list(_DEFAULT_RETRY_ON))


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_model_path: Path


class RunConfig(BaseModel):
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
