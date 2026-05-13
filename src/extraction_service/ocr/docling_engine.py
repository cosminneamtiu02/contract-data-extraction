"""Docling-backed OCR engine — production implementation (plan §6.4 tasks 2.3, 2.4, 2.8, 2.9).

This module wires the §2.5 DocumentConverter setup into a class that conforms
to the ``OcrEngine`` Protocol defined in ``base.py``.  The ``.extract()``
method is fully implemented: it runs the converter in a thread via
``asyncio.to_thread``, enforces ``OcrConfig.timeout_seconds`` via
``asyncio.wait_for``, and wraps failures as ``OcrError`` or
``OcrEmptyOutputError``.

## Design: constructor-injectable factory (approach A)

The ``_converter_factory`` keyword-only parameter is the dependency-injection
seam for tests.  When ``None`` (the default in production), the constructor
calls the module-level ``_build_default_converter`` which runs
``modelscope.snapshot_download`` — a network call that is unacceptable in unit
tests and would fail in CI where the model cache doesn't exist.  Tests pass a
lambda returning a stub, keeping them hermetic.

The underscore prefix on ``_converter_factory`` signals "for tests only":
production callers always let it default to ``None``.

## force_full_page_ocr

``OcrConfig.force_full_page_ocr`` (default ``True``) is read here and threaded
into ``RapidOcrOptions``.  Operators can flip it to ``False`` in the run-config
YAML to re-enable layout-first OCR (faster, misses watermarks/stamps).  The
flag never requires a code change — it flows from YAML → ``OcrConfig`` →
``_build_default_converter`` → ``RapidOcrOptions`` at startup.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from extraction_service.domain.errors import OcrEmptyOutputError, OcrError
from extraction_service.ocr.base import OcrResult

if TYPE_CHECKING:
    # All imports below are annotation-only.  ``from __future__ import
    # annotations`` makes every annotation a string at runtime, so none of
    # these names need to be present in the module namespace at execution time.
    # TC001/TC003 (ruff) enforces this pattern to avoid circular imports and
    # keep cold-start import cost low.
    from collections.abc import Callable

    # docling ships py.typed at its locked version; mypy resolves it natively
    # (no [[tool.mypy.overrides]] entry needed for docling.*).
    from docling.document_converter import DocumentConverter

    from extraction_service.config.run_config import OcrConfig

# Engine identifier copied into every OcrResult so downstream code (Phase 4
# pipeline; Phase 5 HTTP status responses) can tell which engine produced the
# text. Matches the Literal value on OcrConfig.engine (run_config.py).
_ENGINE_NAME = "docling"


def _build_default_converter(ocr_config: OcrConfig) -> DocumentConverter:
    """Build and return the production DocumentConverter per plan §2.5.

    Downloads (and caches) the RapidAI/RapidOCR models via modelscope on first
    call.  Subsequent calls reuse the local cache at ``~/.cache``.  Network I/O
    means this function must NOT be called from unit tests — use the
    ``_converter_factory`` kwarg on ``DoclingOcrEngine`` instead.
    """
    # Deferred to runtime to avoid import-time network calls.
    # docling ships py.typed at its locked version (resolved natively by
    # mypy), and pyproject.toml's [[tool.mypy.overrides]] sets
    # ignore_missing_imports = true for `modelscope.*` (and `rapidocr.*`),
    # the genuinely stub-less packages. Together these suppress
    # missing-stub errors — no per-import `# type: ignore` needed.
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from modelscope import snapshot_download

    # One-time download; cached after first run in ~/.cache.
    model_dir = Path(snapshot_download(repo_id="RapidAI/RapidOCR"))
    det = str(model_dir / "onnx" / "PP-OCRv5" / "det" / "ch_PP-OCRv5_server_det.onnx")
    rec = str(model_dir / "onnx" / "PP-OCRv5" / "rec" / "ch_PP-OCRv5_rec_server_infer.onnx")
    cls = str(model_dir / "onnx" / "PP-OCRv4" / "cls" / "ch_ppocr_mobile_v2.0_cls_infer.onnx")

    ocr_options = RapidOcrOptions(
        det_model_path=det,
        rec_model_path=rec,
        cls_model_path=cls,
        # force_full_page_ocr=True disables the layout-first shortcut: every
        # page is rasterised and fully OCR'd so watermarks/stamps/logos are
        # captured (plan §2.5, §2.1).  Operators can flip this via run-config.
        force_full_page_ocr=ocr_config.force_full_page_ocr,
    )

    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=ocr_options,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        },
    )


class DoclingOcrEngine:
    """Docling+RapidOCR backend for the ``OcrEngine`` Protocol (plan §6.4 tasks 2.3-2.9).

    Production usage — let the factory default to ``None``::

        engine = DoclingOcrEngine(run_config.ocr)

    Test usage — inject a stub to skip model download::

        engine = DoclingOcrEngine(OcrConfig(), _converter_factory=lambda _: stub)

    The ``.extract()`` method runs the Docling converter in a thread via
    ``asyncio.to_thread``, enforces ``OcrConfig.timeout_seconds`` via
    ``asyncio.wait_for``, raises ``OcrEmptyOutputError`` on empty markdown,
    raises ``OcrError`` on non-SUCCESS ``ConversionStatus`` or generic
    converter exceptions, and propagates ``TimeoutError`` unwrapped.
    ``isinstance(engine, OcrEngine)`` returns ``True`` at runtime because the
    Protocol is ``@runtime_checkable`` and ``extract`` is defined on this class.
    """

    def __init__(
        self,
        ocr_config: OcrConfig,
        *,
        _converter_factory: Callable[[OcrConfig], DocumentConverter] | None = None,
    ) -> None:
        """Construct the engine and build (or receive) a DocumentConverter.

        Args:
            ocr_config: Engine knobs — engine name, ``force_full_page_ocr`` flag,
                and ``timeout_seconds``.
            _converter_factory: **For tests only.** When provided, called with
                ``ocr_config`` to produce the ``DocumentConverter`` instead of
                the real ``_build_default_converter``.  The underscore prefix
                is a project convention for test-seam parameters.
        """
        self._ocr_config = ocr_config
        factory = _converter_factory if _converter_factory is not None else _build_default_converter
        self._converter: DocumentConverter = factory(ocr_config)

    async def extract(self, pdf_bytes: bytes) -> OcrResult:
        """Extract OCR text from a PDF byte buffer (plan §6.4 tasks 2.4, 2.8, 2.9).

        Docling's ``DocumentConverter.convert`` is synchronous and CPU-bound
        (it runs the full OCR pipeline: PDF rasterisation → layout analysis →
        RapidOCR/PP-OCRv5 inference → markdown export). Running it via
        ``asyncio.to_thread`` keeps the event loop free for other work —
        critical for Phase 4 where the OCR worker is one of several concurrent
        asyncio tasks driving the pipeline.

        The bytes are wrapped in a ``DocumentStream`` (Docling's in-memory
        input type) so no temp file ever touches the filesystem. ``name`` is
        a synthetic ``contract.pdf`` placeholder because Docling uses it only
        for the input descriptor — actual content is determined by the bytes.

        ``asyncio.wait_for`` enforces ``OcrConfig.timeout_seconds`` at the
        asyncio layer. When the timeout fires, ``TimeoutError`` propagates to
        the caller (Phase 4 worker → ``StageError``) unwrapped — it carries
        its own diagnostic signal distinct from generic OCR failures. The
        underlying executor thread keeps running until ``convert`` returns;
        the work completes harmlessly in the background.

        Error wrapping (plan §6.4 task 2.9):

        - Any non-timeout exception from ``convert`` → ``OcrError`` (code
          ``"ocr_engine_failed"``), preserving the original via ``raise ...
          from e``.
        - ``ConversionStatus`` other than ``SUCCESS`` → ``OcrError``. Docling
          exposes "soft" failures (recoverable parse errors, missing layout
          model) by returning a failed result rather than raising; without
          this check the failure would silently propagate as empty/partial
          ``OcrResult.text`` and the LLM stage would chew on garbage.
        - Empty or whitespace-only markdown → ``OcrEmptyOutputError`` (code
          ``"ocr_empty_output"``). A blank-page scan or a zero-region OCR
          pass is a deterministic failure on the input, not retryable.
        """
        # Local imports to keep cold-start light when no extraction runs (the
        # Docling import chain is heavyweight — see _build_default_converter).
        from docling.datamodel.base_models import ConversionStatus, DocumentStream

        stream = DocumentStream(name="contract.pdf", stream=BytesIO(pdf_bytes))

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._converter.convert, stream),
                timeout=self._ocr_config.timeout_seconds,
            )
        except TimeoutError:
            # Propagate unwrapped — the caller (Phase 4 worker) distinguishes
            # timeout from generic OCR failure for its own diagnostic logging.
            raise
        except Exception as exc:
            # Wrap every other failure (RuntimeError from corrupted PDF, OSError
            # from missing model, ONNX runtime crashes, ...) as OcrError so
            # Phase 4's `except ExtractionError` catch always handles it.
            msg = f"docling OCR engine failed: {exc}"
            raise OcrError(msg) from exc

        if result.status != ConversionStatus.SUCCESS:
            # Surface per-page error records when Docling populates them (they
            # live on result.errors as a list of ConversionError objects with
            # `.error_message` text). Without this, operators get only the
            # status enum repr and no signal about which page or rule failed.
            # `getattr` keeps the engine robust across Docling versions that
            # might rename/drop the attribute.
            errors_detail = getattr(result, "errors", None) or "<no per-page errors reported>"
            msg = f"docling reported conversion status {result.status!r}: {errors_detail}"
            raise OcrError(msg)

        document = result.document
        text = document.export_to_markdown()
        if not text or not text.strip():
            msg = "docling produced empty OCR output"
            raise OcrEmptyOutputError(msg)

        return OcrResult(
            text=text,
            page_count=len(document.pages),
            engine_name=_ENGINE_NAME,
        )
