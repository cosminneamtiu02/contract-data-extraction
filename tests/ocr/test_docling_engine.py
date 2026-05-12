"""Tests for DoclingOcrEngine (plan §6.4 Phase 2, tasks 2.3 and 2.4).

Task 2.3 (this file): constructor-only tests — engine initialises and holds a
non-None DocumentConverter.  The ``_converter_factory`` kwarg is the DI seam
that lets tests avoid real model downloads (network I/O in unit tests is
unacceptable and the RapidOCR model dir won't exist in CI).

Task 2.4 will add ``test_extract_*`` tests once the ``.extract()`` body lands.
"""

from unittest.mock import MagicMock

from extraction_service.config.run_config import OcrConfig
from extraction_service.ocr.docling_engine import DoclingOcrEngine


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
