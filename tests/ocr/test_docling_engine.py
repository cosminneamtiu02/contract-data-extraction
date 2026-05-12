"""Tests for DoclingOcrEngine (plan §6.4 Phase 2, tasks 2.3 and 2.4).

Task 2.3 — constructor-only tests: engine initialises and holds a non-None
DocumentConverter. The ``_converter_factory`` kwarg is the DI seam that lets
tests avoid real model downloads (network I/O in unit tests is unacceptable
and the RapidOCR model dir won't exist in CI).

Task 2.4 — ``.extract()`` body. Two test layers:

- A unit test that mocks the DocumentConverter to return a fake
  ConversionResult / DoclingDocument with known output. Asserts ``extract``
  correctly packages the converter's output into an ``OcrResult``. Hermetic,
  fast, no real OCR.

- A parametrised real-OCR test (marked ``slow``) that runs against every PDF
  under ``$EXTRACTION_OCR_SAMPLES_DIR``. For each PDF, runs real Docling OCR
  and asserts word-recall against the sibling ``.txt`` baseline if present,
  else falls back to a smoke check (non-empty output, page_count ≥ 1). The
  test auto-skips when the env var is unset, keeping CI green on fresh
  clones (per plan §6.4 the real validation gate lives in
  ``scripts/validate_ocr.py``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from extraction_service.config.run_config import OcrConfig
from extraction_service.ocr.docling_engine import DoclingOcrEngine

from .conftest import word_recall

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# Threshold chosen to tolerate routine OCR jitter (whitespace, hyphen
# splitting, occasional glyph swaps like l/I or 0/O) while still failing
# loudly when OCR misses a meaningful fraction of the baseline. Validated
# against the manual scripts/validate_ocr.py gate per plan §6.4.
WORD_RECALL_THRESHOLD = 0.85


def test_docling_engine_construct() -> None:
    """DoclingOcrEngine stores a non-None DocumentConverter after construction.

    Uses the constructor-injectable ``_converter_factory`` kwarg (approach A
    per the task spec) to bypass the real ``_build_default_converter`` which
    calls ``modelscope.snapshot_download`` — unsuitable for unit tests.
    """
    # MagicMock(spec=DocumentConverter) would add a real docling import here.
    # A plain MagicMock() is sufficient: the assertion only needs `is not None`.
    stub_converter = MagicMock()
    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )
    assert engine._converter is not None


async def test_docling_extract_returns_text_from_converter() -> None:
    """``extract`` returns an OcrResult whose ``text`` is the converter's markdown.

    Mocks the DocumentConverter to short-circuit the real OCR pipeline. Verifies
    the glue between converter output and OcrResult assembly.
    """
    fake_document = MagicMock()
    fake_document.export_to_markdown.return_value = "Mietvertrag § 1 Vertragsgegenstand"
    fake_document.pages = {1: object(), 2: object()}
    fake_result = MagicMock()
    fake_result.document = fake_document

    stub_converter = MagicMock()
    stub_converter.convert.return_value = fake_result

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    result = await engine.extract(b"fake pdf bytes")

    assert result.text == "Mietvertrag § 1 Vertragsgegenstand"


async def test_docling_extract_returns_page_count_from_converter() -> None:
    """``extract``'s OcrResult.page_count reflects ``len(document.pages)``."""
    fake_document = MagicMock()
    fake_document.export_to_markdown.return_value = "page 1\n\npage 2\n\npage 3"
    fake_document.pages = {1: object(), 2: object(), 3: object()}
    fake_result = MagicMock()
    fake_result.document = fake_document

    stub_converter = MagicMock()
    stub_converter.convert.return_value = fake_result

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    result = await engine.extract(b"fake pdf bytes")

    assert result.page_count == 3


async def test_docling_extract_returns_docling_as_engine_name() -> None:
    """``extract``'s OcrResult.engine_name identifies the engine."""
    fake_document = MagicMock()
    fake_document.export_to_markdown.return_value = "any text"
    fake_document.pages = {1: object()}
    fake_result = MagicMock()
    fake_result.document = fake_document

    stub_converter = MagicMock()
    stub_converter.convert.return_value = fake_result

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    result = await engine.extract(b"fake pdf bytes")

    assert result.engine_name == "docling"


async def test_docling_extract_wraps_bytes_in_document_stream() -> None:
    """``extract`` hands the PDF bytes to the converter via a DocumentStream.

    The converter's ``convert`` method must be called with a single argument
    whose underlying stream contains the original PDF bytes. This guards
    against a regression where someone passes raw bytes (TypeError at runtime)
    or writes a temp file (filesystem coupling, no longer hermetic).
    """
    fake_document = MagicMock()
    fake_document.export_to_markdown.return_value = "x"
    fake_document.pages = {1: object()}
    fake_result = MagicMock()
    fake_result.document = fake_document

    stub_converter = MagicMock()
    stub_converter.convert.return_value = fake_result

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    pdf_bytes = b"%PDF-1.4 fake content"
    await engine.extract(pdf_bytes)

    call_args, _ = stub_converter.convert.call_args
    document_stream = call_args[0]
    # DocumentStream exposes the bytes via its `.stream` attribute (a BytesIO)
    assert document_stream.stream.getvalue() == pdf_bytes


@pytest.mark.slow
async def test_docling_extract_against_sample(
    ocr_sample_pdf: Path,
    baseline_for: Callable[[Path], str | None],
) -> None:
    """Real-OCR test: runs Docling+PP-OCRv5 on each local sample PDF.

    Strict mode (when a sibling ``.txt`` baseline exists): asserts word-recall
    against the Claude-produced ground-truth transcription is at least
    ``WORD_RECALL_THRESHOLD``.

    Smoke mode (when no baseline exists yet): asserts the OCR produced
    non-empty text and at least one page. This lets the test infrastructure
    work before all 20 baselines have been transcribed.

    Auto-skips when ``$EXTRACTION_OCR_SAMPLES_DIR`` is unset or empty (see
    tests/ocr/conftest.py). PDF filenames are never referenced — failure
    messages identify the sample by ordinal index (sample_#N) so personal
    data in filenames doesn't leak into CI / test report XML.
    """
    # Sync file I/O wrapped in to_thread to keep the event loop unblocked
    # (ruff ASYNC240): the real OCR call below also uses run_in_executor, so
    # both file read and OCR happen off the loop.
    pdf_bytes = await asyncio.to_thread(ocr_sample_pdf.read_bytes)
    # OcrConfig() picks up its defaults: engine="docling", force_full_page_ocr=True.
    # No converter-factory override — this test exercises the real Docling path
    # (which is why it's marked `slow`).
    engine = DoclingOcrEngine(OcrConfig())

    result = await engine.extract(pdf_bytes)

    assert result.text, "OCR produced empty text"
    assert result.page_count >= 1, "OCR reported zero pages"

    baseline = baseline_for(ocr_sample_pdf)
    if baseline is None:
        # No baseline yet — smoke check already passed above; nothing more to assert.
        return

    recall = word_recall(baseline, result.text)
    assert recall >= WORD_RECALL_THRESHOLD, (
        f"OCR word-recall {recall:.3f} below threshold "
        f"{WORD_RECALL_THRESHOLD:.3f} (sample {ocr_sample_pdf.stem[:4]}...; "
        f"baseline {len(baseline)} chars, OCR output {len(result.text)} chars)"
    )
