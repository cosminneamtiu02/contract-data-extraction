"""OCR engine abstraction (plan §6.4).

Concrete engines implement the ``OcrEngine`` Protocol from ``base`` and are
wired by the Phase 4 pipeline via ``build_ocr_engine`` in ``factory``.

The three names below are the stable public surface of this subpackage:
``OcrEngine`` (Protocol), ``OcrResult`` (value object), and ``build_ocr_engine``
(factory). Declaring ``__all__`` makes the intended surface explicit for
IDEs, ``from ... import *``, and downstream callers — and prevents private
helpers (e.g., ``_build_default_converter`` in ``docling_engine``) from
accidentally becoming part of the contract.
"""

from extraction_service.ocr.base import OcrEngine, OcrResult
from extraction_service.ocr.factory import build_ocr_engine

__all__ = ["OcrEngine", "OcrResult", "build_ocr_engine"]
