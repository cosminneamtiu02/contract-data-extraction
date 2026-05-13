"""OCR engine Protocol and the ``OcrResult`` value object (plan §6.4 task 2.1).

The Protocol is the seam between the pipeline (Phase 4) and concrete OCR
backends. Carrying it as a ``typing.Protocol`` rather than an ``abc.ABC``
keeps engines free of inheritance ceremony — any class with the right
``extract`` method shape is acceptable.

``@runtime_checkable`` is set so tests and the FastAPI dependency-injection
plumbing can do ``isinstance(obj, OcrEngine)``. The runtime check only
verifies attribute presence; mypy is the load-bearing check that ``extract``
has the right signature (``async`` returning ``OcrResult``).
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class OcrResult(BaseModel):
    """Output of a single OCR run over a contract PDF.

    Frozen per project convention for value objects. ``extra="forbid"`` so a
    future caller that mistypes a field (e.g., ``engine="docling"`` instead of
    ``engine_name="docling"``) fails loudly rather than silently dropping data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    page_count: int
    engine_name: str


@runtime_checkable
class OcrEngine(Protocol):
    """Pluggable OCR backend. Implementations live in sibling modules
    (``docling_engine`` for production, ``tests/fakes/fake_ocr`` for tests).

    ``extract`` is async because production engines wrap synchronous OCR work
    in ``asyncio.to_thread`` (see Phase 2 task 2.8 + deviation §17.9 in
    ``docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md`` for
    the Docling implementation; not to be confused with the CI/CD spec's own
    §17.9 on closed-Literal exhaustiveness). Returning ``OcrResult`` keeps the
    protocol typed end to end — Phase 4's worker code can rely on ``.text`` /
    ``.page_count`` / ``.engine_name`` being present on every implementation.
    """

    async def extract(self, pdf_bytes: bytes) -> OcrResult: ...
