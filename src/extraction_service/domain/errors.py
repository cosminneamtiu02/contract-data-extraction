"""Exception hierarchy for extraction-service domain errors.

Mirrors the structure in docs/plan.md §4.13. Each concrete exception carries
a class-level ``code`` matching the string that Phase 4 workers will copy into
the ``StageError`` they attach to the failed stage (§3.3). Phase 3's retry
policy keys off the base classes (``except LlmError``) to retry the right
subset of failures.

OCR errors are *deterministic on the input* (per §3.3) and therefore never
retried — only LLM-side failures retry.
"""

from typing import ClassVar


class ExtractionError(Exception):
    """Base for all extraction-service domain errors."""

    code: ClassVar[str]


class OcrError(ExtractionError):
    """Any failure inside the OCR stage."""

    code: ClassVar[str] = "ocr_engine_failed"


class OcrEmptyOutput(OcrError):
    """OCR returned no usable text."""

    code: ClassVar[str] = "ocr_empty_output"


class LlmError(ExtractionError):
    """Any failure inside the LLM stage. Retried per retry policy."""

    code: ClassVar[str] = "llm_failed"


class ContextOverflow(LlmError):
    """OCR output exceeded the LLM's context window."""

    code: ClassVar[str] = "context_overflow"


class SchemaInvalid(LlmError):
    """LLM returned JSON that failed schema validation."""

    code: ClassVar[str] = "schema_invalid"
