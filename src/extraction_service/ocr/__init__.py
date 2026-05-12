"""OCR engine abstraction (plan §6.4).

Concrete engines implement the ``OcrEngine`` Protocol from ``base`` and are
wired by the Phase 4 pipeline via ``OcrEngineFactory``. ``__all__`` is
intentionally not declared yet for the same reason as the top-level package
(§17.9): an empty list would silently mask future exports.
"""
