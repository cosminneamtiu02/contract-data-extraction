"""OCR engine integration tests and engine-specific unit tests (Phase 2).

Tests here exercise the concrete ``DoclingOcrEngine`` plus a parametrised
real-OCR test that runs against user-supplied PDFs from
``$EXTRACTION_OCR_SAMPLES_DIR`` (see spec deviation §17.3 in
``docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md`` —
Task 2.5 was dropped per §17.1 in the same file, and the watermark/logo
verification is folded into the real-OCR baseline-comparison test per §17.2
also in the same file).  Unit tests for the Protocol / value-object layer
(``OcrResult``, ``OcrEngine``) live in ``tests/unit/``.
"""
