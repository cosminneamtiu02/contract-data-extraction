"""Unit tests for the extraction-service exception hierarchy (Task 1.5).

Each concrete exception carries a class-level ``code`` attribute that Phase 4
workers will copy into the ``StageError`` they attach to the failed stage
(docs/plan.md §3.3, §4.13). Tests assert both the codes themselves and the
inheritance chain — Phase 3 retry policy needs to match on base classes
(``except LlmError``) to retry the right subset of failures.
"""

import pytest

from extraction_service.domain.errors import (
    ContextOverflowError,
    ExtractionError,
    LlmError,
    OcrEmptyOutputError,
    OcrError,
    SchemaInvalidError,
)


def test_base_extraction_error_inherits_from_exception() -> None:
    assert issubclass(ExtractionError, Exception)


def test_base_extraction_error_has_sentinel_code() -> None:
    # A caller that catches the base class must always be able to read .code
    # to populate a StageError description (docs/plan.md §3.3).
    assert ExtractionError.code == "extraction_error"


@pytest.mark.parametrize(
    ("cls", "expected_code"),
    [
        (OcrError, "ocr_engine_failed"),
        (OcrEmptyOutputError, "ocr_empty_output"),
        (LlmError, "llm_failed"),
        (ContextOverflowError, "context_overflow"),
        (SchemaInvalidError, "schema_invalid"),
    ],
)
def test_concrete_errors_have_expected_code(cls: type[ExtractionError], expected_code: str) -> None:
    assert cls.code == expected_code


@pytest.mark.parametrize(
    ("subclass", "ancestors"),
    [
        (OcrError, (ExtractionError, Exception)),
        (OcrEmptyOutputError, (OcrError, ExtractionError, Exception)),
        (LlmError, (ExtractionError, Exception)),
        (ContextOverflowError, (LlmError, ExtractionError, Exception)),
        (SchemaInvalidError, (LlmError, ExtractionError, Exception)),
    ],
)
def test_inheritance_chain(
    subclass: type[ExtractionError], ancestors: tuple[type[BaseException], ...]
) -> None:
    for parent in ancestors:
        assert issubclass(subclass, parent)


def test_raised_error_preserves_code_and_message() -> None:
    with pytest.raises(OcrEmptyOutputError) as exc_info:
        raise OcrEmptyOutputError("no text extracted")

    assert exc_info.value.code == "ocr_empty_output"
    assert str(exc_info.value) == "no text extracted"
