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
from extraction_service.domain.errors import OcrEmptyOutputError, OcrError
from extraction_service.ocr.docling_engine import DoclingOcrEngine

from ._metrics import word_recall

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
    fake_result.status = _success_status()

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
    fake_result.status = _success_status()

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
    fake_result.status = _success_status()

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
    fake_result.status = _success_status()

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


async def test_docling_extract_raises_timeout_when_convert_exceeds_budget() -> None:
    """``extract`` raises ``asyncio.TimeoutError`` when the converter exceeds
    ``OcrConfig.timeout_seconds``.

    Uses a fake converter whose ``convert`` blocks on a ``threading.Event``
    longer than the configured timeout. The user-level timeout fires at the
    asyncio layer; the underlying worker thread keeps running until released
    via the event (Python doesn't have thread cancellation), so the test
    sets the event in ``finally`` right after the assertion to free the
    thread immediately — otherwise pytest waits ~5 s for the thread pool to
    drain.

    The 1-second timeout is the minimum permitted by
    ``OcrConfig.timeout_seconds: PositiveInt``.
    """
    import threading

    release = threading.Event()

    def slow_convert(_stream: object) -> object:
        # Block until release.set() OR 10 s — never reached under normal
        # test flow because release is set right after the timeout fires.
        release.wait(timeout=10)
        return MagicMock()

    stub_converter = MagicMock()
    stub_converter.convert.side_effect = slow_convert

    engine = DoclingOcrEngine(
        OcrConfig(timeout_seconds=1),
        _converter_factory=lambda _cfg: stub_converter,
    )

    try:
        with pytest.raises(TimeoutError):
            await engine.extract(b"any bytes")
    finally:
        release.set()  # Free the leaked executor thread immediately


async def test_docling_extract_empty_markdown_raises_ocr_empty_output() -> None:
    """``extract`` raises ``OcrEmptyOutputError`` when Docling produces no text.

    Empty markdown is a real failure mode: a blank page or an OCR pass that
    detected zero text regions returns an empty string from
    ``export_to_markdown()``. The pipeline must surface this as
    ``OcrEmptyOutputError`` (code ``"ocr_empty_output"``) rather than letting
    an empty ``OcrResult.text`` flow downstream, where the LLM stage would
    silently produce a degenerate extraction.
    """
    fake_document = MagicMock()
    fake_document.export_to_markdown.return_value = "   \n\n  "  # whitespace only
    fake_document.pages = {1: object()}
    fake_result = MagicMock()
    fake_result.document = fake_document
    fake_result.status = _success_status()

    stub_converter = MagicMock()
    stub_converter.convert.return_value = fake_result

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    with pytest.raises(OcrEmptyOutputError):
        await engine.extract(b"any bytes")


async def test_docling_extract_converter_exception_wraps_as_ocr_error() -> None:
    """``extract`` wraps any non-timeout converter exception as ``OcrError``.

    Internal Docling failures (corrupted PDF, missing ONNX model, ONNX
    runtime crash) surface from ``convert()`` as arbitrary exceptions.
    Phase 4's worker catches ``ExtractionError`` (the parent of ``OcrError``)
    to populate ``StageError.code``; an unwrapped ``RuntimeError`` from
    Docling would slip past that catch and crash the worker. Wrapping
    preserves the original cause via ``raise ... from e``.
    """
    stub_converter = MagicMock()
    stub_converter.convert.side_effect = RuntimeError("docling internal failure")

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    with pytest.raises(OcrError) as exc_info:
        await engine.extract(b"any bytes")

    assert exc_info.value.code == "ocr_engine_failed"


async def test_docling_extract_returns_zero_page_count_when_document_pages_empty() -> None:
    """``extract`` returns OcrResult.page_count == 0 when the converter reports no pages.

    Pins the current contract on a degenerate input: if Docling produces a
    DoclingDocument whose ``pages`` dict is empty (plausible on a
    one-page scan where layout analysis found zero page items but the OCR
    pass still emitted text), ``extract`` returns page_count=0 silently
    rather than raising. Phase 4's worker can attribute / log this case
    however it wants — the OCR layer's contract is just "report what the
    converter said." If a future iteration decides empty-pages should be
    an OcrError, this test fails first and forces a deliberate update.
    """
    fake_document = MagicMock()
    fake_document.export_to_markdown.return_value = "some recognised text"
    fake_document.pages = {}
    fake_result = MagicMock()
    fake_result.document = fake_document
    fake_result.status = _success_status()

    stub_converter = MagicMock()
    stub_converter.convert.return_value = fake_result

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    result = await engine.extract(b"any bytes")

    assert result.page_count == 0


async def test_docling_extract_failed_conversion_status_raises_ocr_error() -> None:
    """``extract`` raises ``OcrError`` when ``ConversionResult.status`` is not SUCCESS.

    Docling exposes "soft" failures (recoverable parse errors, missing
    layout model, etc.) by returning a ``ConversionResult`` with
    ``status=FAILED`` rather than raising. Without an explicit status
    check the engine would return an empty ``OcrResult`` from a failed
    conversion — a quiet-bug-by-construction the LLM stage would happily
    chew on. Explicit check surfaces the failure at the OCR boundary.
    """
    # Local import keeps the heavyweight Docling import chain off the import
    # path of tests that don't exercise ConversionStatus — parallels the
    # _success_status() helper below.
    from docling.datamodel.base_models import ConversionStatus

    fake_document = MagicMock()
    fake_document.export_to_markdown.return_value = "partial junk text"
    fake_document.pages = {1: object()}
    fake_result = MagicMock()
    fake_result.document = fake_document
    fake_result.status = ConversionStatus.FAILURE

    stub_converter = MagicMock()
    stub_converter.convert.return_value = fake_result

    engine = DoclingOcrEngine(
        OcrConfig(),
        _converter_factory=lambda _cfg: stub_converter,
    )

    with pytest.raises(OcrError) as exc_info:
        await engine.extract(b"any bytes")

    assert exc_info.value.code == "ocr_engine_failed"


def _success_status() -> object:
    """Return ``ConversionStatus.SUCCESS`` for the success-path mock tests.

    Helper rather than module-level import: keeps the heavyweight Docling
    import chain off the import path of tests that don't actually need
    ``ConversionStatus`` (e.g., the construct test).
    """
    from docling.datamodel.base_models import ConversionStatus

    return ConversionStatus.SUCCESS


@pytest.mark.slow
async def test_docling_extract_against_sample(
    request: pytest.FixtureRequest,
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
    # Identify the failing sample by its parametrise ordinal id (sample_#N)
    # rather than any prefix of the filename. The conftest module docstring
    # explicitly promises "failures reference each sample by ordinal index"
    # to avoid leaking personal data; an earlier `stem[:4]` prefix here drifted
    # from that contract (Lens 16 of cycle-1 review on
    # chore/phase-2-ocr-review-fixes-2026-05-13). request.node.callspec.id is
    # the parametrise id pytest renders in -v output and JUnit XML.
    sample_id = request.node.callspec.id
    assert recall >= WORD_RECALL_THRESHOLD, (
        f"OCR word-recall {recall:.3f} below threshold "
        f"{WORD_RECALL_THRESHOLD:.3f} (sample {sample_id}; "
        f"baseline {len(baseline)} chars, OCR output {len(result.text)} chars)"
    )
