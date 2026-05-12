"""Unit tests for the extraction-service exception hierarchy (Task 1.5).

Each concrete exception carries a class-level ``code`` attribute that Phase 4
workers will copy into the ``StageError`` they attach to the failed stage
(docs/plan.md §3.3, §4.13). Tests assert both the codes themselves and the
inheritance chain — Phase 3 retry policy needs to match on base classes
(``except LlmError``) to retry the right subset of failures.
"""

import pytest

from extraction_service.domain.errors import (
    ContextOverflow,
    ExtractionError,
    LlmError,
    OcrEmptyOutput,
    OcrError,
    SchemaInvalid,
)


def test_base_extraction_error_inherits_from_exception() -> None:
    assert issubclass(ExtractionError, Exception)


@pytest.mark.parametrize(
    ("cls", "expected_code"),
    [
        (OcrError, "ocr_engine_failed"),
        (OcrEmptyOutput, "ocr_empty_output"),
        (LlmError, "llm_failed"),
        (ContextOverflow, "context_overflow"),
        (SchemaInvalid, "schema_invalid"),
    ],
)
def test_concrete_errors_have_expected_code(cls: type[ExtractionError], expected_code: str) -> None:
    assert cls.code == expected_code


@pytest.mark.parametrize(
    ("subclass", "ancestors"),
    [
        (OcrError, (ExtractionError, Exception)),
        (OcrEmptyOutput, (OcrError, ExtractionError, Exception)),
        (LlmError, (ExtractionError, Exception)),
        (ContextOverflow, (LlmError, ExtractionError, Exception)),
        (SchemaInvalid, (LlmError, ExtractionError, Exception)),
    ],
)
def test_inheritance_chain(
    subclass: type[ExtractionError], ancestors: tuple[type[BaseException], ...]
) -> None:
    for parent in ancestors:
        assert issubclass(subclass, parent)


def test_raised_error_preserves_code_and_message() -> None:
    with pytest.raises(OcrEmptyOutput) as exc_info:
        raise OcrEmptyOutput("no text extracted")

    assert exc_info.value.code == "ocr_empty_output"
    assert str(exc_info.value) == "no text extracted"
