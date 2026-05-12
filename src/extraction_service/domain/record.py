"""ContractRecord — mutable container of per-stage StageRecord snapshots.

Each contract_id maps to one ContractRecord in the result store
(docs/plan.md §3.2). Workers reassign individual stage fields under the
asyncio.Lock described in §3.5. The container is mutable; each StageRecord
inside it is frozen (functional transitions return new instances).

``overall_status`` and ``current_stage`` are derived from the three stage
states per the transition table in §3.3 — never stored, never written by
callers. ``ContractRecord.fresh(now)`` is the canonical factory used by the
HTTP intake handler.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from extraction_service.domain.stage import StageRecord, StageState

# These two Literal aliases are returned by ContractRecord's computed_fields,
# so they ARE part of this module's public surface. Phase 5's HTTP response
# models (src/extraction_service/http/responses.py, not yet created) will
# re-export them as part of the locked status shape.
OverallStatus = Literal["in_progress", "done", "failed"]
StageName = Literal["intake", "ocr", "data_parsing"]

_STAGE_FIELDS: tuple[StageName, ...] = ("intake", "ocr", "data_parsing")


class ContractRecord(BaseModel):
    """Mutable container for the three per-stage StageRecords of one contract."""

    intake: StageRecord = Field(default_factory=StageRecord)
    ocr: StageRecord = Field(default_factory=StageRecord)
    data_parsing: StageRecord = Field(default_factory=StageRecord)

    @classmethod
    def fresh(cls, now: datetime | None = None) -> "ContractRecord":
        """Build a record for a just-arrived contract: intake done, others pending."""
        t = now if now is not None else datetime.now(UTC)
        return cls(
            intake=StageRecord(state=StageState.DONE, started_at=t, completed_at=t),
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_status(self) -> OverallStatus:
        """Derived top-level status. ``failed`` if any stage failed, ``done`` only
        when all three stages are done, ``in_progress`` otherwise. Per the
        transition table in docs/plan.md §3.3."""
        states = [self.intake.state, self.ocr.state, self.data_parsing.state]
        if StageState.FAILED in states:
            return "failed"
        if all(s == StageState.DONE for s in states):
            return "done"
        return "in_progress"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def current_stage(self) -> StageName | None:
        """The first non-DONE stage in pipeline order, or None if all done.

        A FAILED stage is returned as the current (failure-point) stage.
        """
        for name in _STAGE_FIELDS:
            stage: StageRecord = getattr(self, name)
            if stage.state != StageState.DONE:
                return name
        return None
