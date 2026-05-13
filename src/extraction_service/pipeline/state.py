"""Pipeline state container — queues, result store, settings (plan §6.6 task 4.2).

``PipelineState`` is the single object knitting the OCR worker (task 4.3),
LLM worker (task 4.5), idle watchdog (task 4.8), and the Phase 5 HTTP layer
together. Lifetime: created once in the FastAPI lifespan, passed to every
worker as a positional argument, treated as read-only after construction —
the dataclass is ``frozen=True`` so a worker cannot reassign a queue mid-run
(mutating the queue itself via ``.put`` / ``.get`` is the intended path).

``OcrCompleted`` is the inter-stage queue payload. The OCR worker enqueues it
after writing ``ocr.state=done`` to the result store; the LLM worker dequeues
it and renders the prompt with ``ocr_text``. The text travels inline because
``StageRecord.extracted`` is reserved for the LLM result (plan §3.2) — the
OCR text is not persisted on the record; the queue payload IS the carrier.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from extraction_service.domain.job import ContractJob
from extraction_service.pipeline.result_store import ResultStore
from extraction_service.settings import Settings


class OcrCompleted(BaseModel):
    """Inter-stage queue payload carrying the OCR text from the OCR worker to
    the LLM worker.

    Frozen because once enqueued, the LLM worker treats it as an immutable
    snapshot; any post-enqueue mutation would be a concurrency hazard.
    ``extra="forbid"`` rejects typos at the worker call site (plan §6.6 row
    4.5 wiring).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_id: UUID
    ocr_text: str


@dataclass(frozen=True, slots=True)
class PipelineState:
    """Process-wide pipeline plumbing.

    Frozen so workers cannot reassign queues post-construction; the queues and
    result store themselves remain mutable (that's the whole point — workers
    push / pop items and write through the lock).
    """

    intake_queue: asyncio.Queue[ContractJob]
    interstage_queue: asyncio.Queue[OcrCompleted]
    result_store: ResultStore = field()
    settings: Settings = field()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        result_store: ResultStore | None = None,
    ) -> Self:
        """Build a PipelineState with queues sized from ``settings`` and a
        fresh ResultStore (or the one supplied for test injection)."""
        return cls(
            intake_queue=asyncio.Queue(maxsize=settings.intake_queue_size),
            interstage_queue=asyncio.Queue(maxsize=settings.interstage_queue_size),
            result_store=result_store if result_store is not None else ResultStore(),
            settings=settings,
        )
