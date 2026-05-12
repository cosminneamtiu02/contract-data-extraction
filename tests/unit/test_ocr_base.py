"""Tests for the OCR engine Protocol and result value object (plan §6.4 task 2.1).

The Protocol is split out from concrete engines so Phase 4 (pipeline) can wire
fakes/reals interchangeably and Phase 5 (HTTP) can override via FastAPI
dependency injection. Behaviour under test:

- ``OcrResult`` is a frozen Pydantic value object (project convention; mirrors
  Phase 1's ``ContractJob`` / ``ContractRecord`` posture).
- ``OcrEngine`` is a ``@runtime_checkable`` ``Protocol`` so structurally
  conforming classes both type-check via mypy AND satisfy ``isinstance``.

The runtime ``isinstance`` check only verifies attribute presence, not the
signature of ``extract``. The mypy run in the verification gate is what
catches signature drift (e.g., sync ``extract`` where async is required).
"""

from typing import get_type_hints

import pytest
from pydantic import ValidationError


def test_ocr_result_is_frozen() -> None:
    from extraction_service.ocr.base import OcrResult

    result = OcrResult(text="hello", page_count=1, engine_name="docling")
    with pytest.raises(ValidationError):
        result.text = "mutated"  # type: ignore[misc]  # exercising frozen=True


def test_ocr_result_requires_text() -> None:
    from extraction_service.ocr.base import OcrResult

    with pytest.raises(ValidationError):
        OcrResult(page_count=1, engine_name="docling")  # type: ignore[call-arg]  # intentionally omits text to verify required-field rejection


def test_ocr_result_requires_page_count() -> None:
    from extraction_service.ocr.base import OcrResult

    with pytest.raises(ValidationError):
        OcrResult(text="hello", engine_name="docling")  # type: ignore[call-arg]  # intentionally omits page_count to verify required-field rejection


def test_ocr_result_requires_engine_name() -> None:
    from extraction_service.ocr.base import OcrResult

    with pytest.raises(ValidationError):
        OcrResult(text="hello", page_count=1)  # type: ignore[call-arg]  # intentionally omits engine_name to verify required-field rejection


def test_ocr_result_rejects_unknown_fields() -> None:
    from extraction_service.ocr.base import OcrResult

    with pytest.raises(ValidationError):
        OcrResult(
            text="hello",
            page_count=1,
            engine_name="docling",
            extra_field="boom",  # type: ignore[call-arg]  # intentionally passes an unknown field to verify extra="forbid" rejection
        )


def test_ocr_result_text_accessor() -> None:
    from extraction_service.ocr.base import OcrResult

    result = OcrResult(text="hello world", page_count=2, engine_name="docling")

    assert result.text == "hello world"


def test_ocr_result_page_count_accessor() -> None:
    from extraction_service.ocr.base import OcrResult

    result = OcrResult(text="hello world", page_count=2, engine_name="docling")

    assert result.page_count == 2


def test_ocr_result_engine_name_accessor() -> None:
    from extraction_service.ocr.base import OcrResult

    result = OcrResult(text="hello world", page_count=2, engine_name="docling")

    assert result.engine_name == "docling"


def test_ocr_engine_protocol_accepts_structural_conformer() -> None:
    from extraction_service.ocr.base import OcrEngine, OcrResult

    class StructuralConformer:
        async def extract(self, pdf_bytes: bytes) -> OcrResult:
            return OcrResult(text="x", page_count=1, engine_name="conformer")

    assert isinstance(StructuralConformer(), OcrEngine)


def test_ocr_engine_protocol_rejects_non_conformer() -> None:
    from extraction_service.ocr.base import OcrEngine

    class NotAnEngine:
        def unrelated(self) -> None:
            return None

    assert not isinstance(NotAnEngine(), OcrEngine)


def test_ocr_engine_extract_return_type_annotation() -> None:
    from extraction_service.ocr.base import OcrEngine, OcrResult

    hints = get_type_hints(OcrEngine.extract)
    assert hints["return"] is OcrResult
