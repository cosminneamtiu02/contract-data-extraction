"""Docling-backed OCR engine — constructor skeleton (plan §6.4 task 2.3).

This module wires the §2.5 DocumentConverter setup into a class that conforms
to the ``OcrEngine`` Protocol defined in ``base.py``.  The ``.extract()``
method body is deferred to Task 2.4; the stub below preserves the ``extract``
attribute so ``isinstance(engine, OcrEngine)`` returns ``True`` at runtime
(the Protocol is ``@runtime_checkable`` and checks for attribute presence).

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

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # All imports below are annotation-only.  ``from __future__ import
    # annotations`` makes every annotation a string at runtime, so none of
    # these names need to be present in the module namespace at execution time.
    # TC001/TC003 (ruff) enforces this pattern to avoid circular imports and
    # keep cold-start import cost low.
    from collections.abc import Callable

    from docling.document_converter import DocumentConverter  # no stubs for docling

    from extraction_service.config.run_config import OcrConfig
    from extraction_service.ocr.base import OcrResult


def _build_default_converter(ocr_config: OcrConfig) -> DocumentConverter:
    """Build and return the production DocumentConverter per plan §2.5.

    Downloads (and caches) the RapidAI/RapidOCR models via modelscope on first
    call.  Subsequent calls reuse the local cache at ``~/.cache``.  Network I/O
    means this function must NOT be called from unit tests — use the
    ``_converter_factory`` kwarg on ``DoclingOcrEngine`` instead.
    """
    # Deferred to runtime to avoid import-time network calls.
    # mypy's ``ignore_missing_imports = true`` override for ``docling.*`` and
    # ``modelscope.*`` (pyproject.toml [[tool.mypy.overrides]]) already
    # suppresses missing-stub errors — no per-import ``# type: ignore`` needed.
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
    """Docling+RapidOCR backend for the ``OcrEngine`` Protocol (plan §6.4 task 2.3).

    Production usage — let the factory default to ``None``::

        engine = DoclingOcrEngine(run_config.ocr)

    Test usage — inject a stub to skip model download::

        engine = DoclingOcrEngine(OcrConfig(), _converter_factory=lambda _: stub)

    The ``.extract()`` body is deferred to Task 2.4.  The stub below preserves
    the ``extract`` attribute so ``isinstance(engine, OcrEngine)`` returns
    ``True`` at runtime (the Protocol is ``@runtime_checkable`` and checks for
    attribute presence).
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
        """Extract OCR text from a PDF.  Implemented in Task 2.4.

        Raises:
            NotImplementedError: Always — body is deferred to Task 2.4.
        """
        msg = "extract() body deferred to Task 2.4"
        raise NotImplementedError(msg)
