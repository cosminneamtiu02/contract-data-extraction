"""FakeOcrEngine — a configurable in-process stand-in for OcrEngine.

Phase 2 test helper. Later phases consume it as follows:

- **Phase 4 worker tests** construct ``FakeOcrEngine(text="some clause ...")``
  to drive the pipeline worker through a specific OCR output without touching
  the filesystem or Docling.
- **Phase 5 FastAPI dependency overrides** inject ``FakeOcrEngine()`` via
  ``app.dependency_overrides`` to bypass real OCR during integration tests of
  the HTTP layer.

The class intentionally keeps mutable instance attributes (no Pydantic,
no ``frozen=True``) so callers can reconfigure a single instance between
assertions if needed. The ``OcrResult`` it returns IS frozen (project
convention for value objects).
"""

from extraction_service.ocr.base import OcrResult

# Note: this module does NOT import OcrEngine. FakeOcrEngine conforms to the
# OcrEngine Protocol structurally (no subclassing) so the import would be
# runtime-unused. Tests that need `isinstance(FakeOcrEngine(), OcrEngine)`
# (see tests/fakes/test_fake_ocr.py) import OcrEngine themselves from
# extraction_service.ocr.base.


class FakeOcrEngine:
    """Configurable stand-in for ``OcrEngine`` (satisfies the Protocol).

    Ignores the ``pdf_bytes`` argument to ``extract`` and returns an
    ``OcrResult`` built from the constructor arguments. This lets tests
    drive specific text/page_count/engine_name values without any I/O.

    ``isinstance(FakeOcrEngine(), OcrEngine)`` returns ``True`` because
    ``OcrEngine`` is ``@runtime_checkable``. mypy structural-subtyping is
    the load-bearing check that the ``extract`` signature matches.
    """

    def __init__(
        self,
        text: str = "fake ocr text",
        page_count: int = 1,
        engine_name: str = "fake",
    ) -> None:
        """Configure the OcrResult fields this fake will return from ``extract``.

        All three parameters have defaults so the no-argument form
        ``FakeOcrEngine()`` is a valid test seam; callers override only the
        dimension they want to drive (e.g., ``FakeOcrEngine(page_count=5)``
        to exercise pagination handling in Phase 4 worker tests).
        """
        self.text = text
        self.page_count = page_count
        self.engine_name = engine_name

    async def extract(self, pdf_bytes: bytes) -> OcrResult:
        """Return a pre-configured OcrResult, ignoring pdf_bytes."""
        _ = pdf_bytes  # intentionally unused — fake always returns configured output
        return OcrResult(
            text=self.text,
            page_count=self.page_count,
            engine_name=self.engine_name,
        )
