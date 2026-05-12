"""Stage state machine for the contract pipeline.

The pipeline has three stages (intake, OCR, data parsing). Each stage carries
a ``StageState`` plus timing and optional error metadata in a ``StageRecord``.
``ContractRecord.overall_status`` is derived from the three stage states per
the table in docs/plan.md §3.3.

Using ``StrEnum`` (Python 3.11+) rather than the older ``class X(str, Enum)``
form makes ``str()`` and f-string interpolation return the plain value, which
keeps log lines and JSON-coerced output clean for structlog (§4.8).

``StageRecord`` is frozen and uses functional transitions (``start``,
``complete``, ``fail``) that return new instances. This keeps the
asyncio.Lock-guarded read-modify-write of §3.5 reasoning about whole records
rather than mid-transition state. ``StageError`` is the data structure
captured on a failed stage; the exception hierarchy that *raises* it lives
in ``errors.py`` (Task 1.5).

The transition methods are deliberately UNGUARDED against invalid orderings
(e.g., ``start()`` on a DONE record, ``complete()`` on a PENDING record).
Pipeline workers (Phase 4) own the state-machine sequencing under their
asyncio.Lock; pushing the check into ``StageRecord`` would either duplicate
the worker guard or force the worker into a two-phase try/check pattern that
defeats the functional-transition design.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, computed_field


class StageState(StrEnum):
    """Lifecycle states for a single pipeline stage."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class StageError(BaseModel):
    """Structured error info attached to a failed stage."""

    model_config = ConfigDict(frozen=True)

    code: str
    description: str


class StageRecord(BaseModel):
    """Timing + state for a single pipeline stage. Frozen; use transition methods.

    The ``extracted`` field is the data-parsing payload: when the LLM stage
    completes successfully in Phase 4, the worker writes the validated JSON
    object here (docs/plan.md §3.2 — orchestrator polls and reads
    ``data_parsing.extracted`` when ``overall_status == "done"``). It is
    ``None`` on every other stage and before completion.

    ``extracted`` is typed ``dict[str, Any] | None`` — an IO-boundary case
    where ``Any`` is explicitly accepted per docs/plan.md §7 (the LLM produces
    caller-supplied-schema-shaped JSON the service does not introspect).
    """

    model_config = ConfigDict(frozen=True)

    state: StageState = StageState.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: StageError | None = None
    extracted: dict[str, Any] | None = None

    @computed_field  # type: ignore[prop-decorator]  # pydantic.mypy doesn't model @computed_field + @property stacking; pattern is Pydantic-recommended.
    @property
    def duration_ms(self) -> int | None:
        """Elapsed wall time in milliseconds, or ``None`` if the stage has not
        both started and completed. Derived live so it never goes stale."""
        if self.started_at is None or self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at).total_seconds() * 1000)

    def start(self, now: datetime | None = None) -> Self:
        """Return a new record transitioned to IN_PROGRESS with ``started_at`` set.

        ``now`` is injectable for deterministic tests; production callers pass
        nothing and get ``datetime.now(UTC)`` at call time."""
        return self.model_copy(
            update={
                "state": StageState.IN_PROGRESS,
                "started_at": now if now is not None else datetime.now(UTC),
            }
        )

    def complete(
        self,
        now: datetime | None = None,
        *,
        extracted: dict[str, Any] | None = None,
    ) -> Self:
        """Return a new record transitioned to DONE with ``completed_at`` set.

        ``extracted`` is the data-parsing payload — Phase 4's LLM worker
        populates it when the ``data_parsing`` stage completes successfully
        (docs/plan.md §3.2). Non-LLM stages and pre-completion states leave
        it ``None``. Kwarg-only so it can never be transposed with ``now``."""
        return self.model_copy(
            update={
                "state": StageState.DONE,
                "completed_at": now if now is not None else datetime.now(UTC),
                "extracted": extracted,
            }
        )

    def fail(self, now: datetime | None = None, *, error: StageError) -> Self:
        """Return a new record transitioned to FAILED with ``completed_at`` and ``error`` set.

        Signature mirrors ``complete()``: ``now`` first (optional), domain
        payload (``error``) keyword-only — prevents transposition at Phase 4
        call sites that mix ``start`` / ``complete`` / ``fail`` close together."""
        return self.model_copy(
            update={
                "state": StageState.FAILED,
                "completed_at": now if now is not None else datetime.now(UTC),
                "error": error,
            }
        )
