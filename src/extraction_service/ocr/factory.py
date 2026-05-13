"""OCR engine factory (plan §6.4 task 2.7).

Dispatches on ``run_config.ocr.engine`` and returns the corresponding
``OcrEngine`` implementation. Today there is exactly one supported engine —
``"docling"`` — and ``OcrConfig.engine`` is typed ``Literal["docling"]``, so
mypy proves exhaustiveness on the ``match`` below without a ``case _:`` arm.

When Phase 3+ broadens the Literal (e.g., to add ``"tesseract"`` as a Fraktur
fallback per plan §2.3), mypy will report "Missing return statement" on this
function until a new ``case`` is added — directing future contributors at the
exact file they need to touch. This is the
``docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md §17.9``
precedent applied (the closed-Literal exhaustiveness ruling on
``assert_never``): closed Literals don't need a runtime ``raise on unknown``
guard; the type system is the guard. Phase 2's own recording of THIS factory's
deviation from the plan-text "raise on unknown" GREEN column is in the Phase 2
spec deviation file at §17.4 (not §17.9, which in that file is the
``asyncio.to_thread`` substitution audit).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from extraction_service.ocr.docling_engine import DoclingOcrEngine

if TYPE_CHECKING:
    from extraction_service.config.run_config import RunConfig
    from extraction_service.ocr.base import OcrEngine


def build_ocr_engine(run_config: RunConfig) -> OcrEngine:
    """Return the OCR engine selected by ``run_config.ocr.engine``."""
    match run_config.ocr.engine:
        case "docling":
            return DoclingOcrEngine(run_config.ocr)
