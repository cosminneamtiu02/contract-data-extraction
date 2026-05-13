"""Unit tests for ContractRecord (Task 1.4).

ContractRecord is the mutable container that the result store keeps for each
contract_id. Workers reassign individual stage fields (each StageRecord is
itself frozen) under the asyncio.Lock described in docs/plan.md §3.5.

Both ``overall_status`` and ``current_stage`` are derived from the three stage
states per the transition table in §3.3 — never stored, never written by
callers. ``ContractRecord.fresh(now)`` is the canonical factory for a record
created by the HTTP intake handler.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from extraction_service.domain.record import ContractRecord
from extraction_service.domain.stage import StageError, StageRecord, StageState

T0 = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)


# --- fresh-record factory ----------------------------------------------------


def test_fresh_contract_record_marks_intake_done_with_timestamps() -> None:
    record = ContractRecord.fresh(now=T0)

    assert record.intake.state == StageState.DONE
    assert record.intake.started_at == T0
    assert record.intake.completed_at == T0


def test_fresh_contract_record_leaves_ocr_and_parsing_pending() -> None:
    record = ContractRecord.fresh(now=T0)

    assert record.ocr.state == StageState.PENDING
    assert record.data_parsing.state == StageState.PENDING


def test_fresh_contract_record_overall_status_is_in_progress() -> None:
    record = ContractRecord.fresh(now=T0)

    assert record.overall_status == "in_progress"


def test_fresh_contract_record_with_default_now_uses_current_time() -> None:
    """The production call path (``ContractRecord.fresh()`` with no argument)
    must assign a timezone-aware datetime. A future refactor that drops the
    ``datetime.now(UTC)`` default would silently leave ``intake.started_at``
    at ``None`` and overall_status / current_stage would derive incorrectly.
    Mirrors test_stage_record_start_with_default_now_uses_current_time."""
    record = ContractRecord.fresh()

    assert record.intake.state == StageState.DONE
    assert record.intake.started_at is not None
    assert record.intake.started_at.tzinfo is not None
    assert record.intake.completed_at is not None
    assert record.intake.completed_at.tzinfo is not None


# --- overall_status derivation ----------------------------------------------


def test_overall_status_is_done_only_when_all_three_stages_done() -> None:
    done = StageRecord(state=StageState.DONE)
    record = ContractRecord(intake=done, ocr=done, data_parsing=done)

    assert record.overall_status == "done"


def test_overall_status_is_failed_when_ocr_failed() -> None:
    err = StageError(code="ocr_engine_failed", description="x")
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE),
        ocr=StageRecord(state=StageState.FAILED, error=err),
        data_parsing=StageRecord(),
    )

    assert record.overall_status == "failed"


def test_overall_status_is_failed_when_intake_failed() -> None:
    """Although ``fresh()`` marks intake DONE so the failed-intake path is
    rare in production, the ``overall_status`` derivation must still report
    ``failed`` if a result-store bug or a Phase 5 short-circuit produces
    a record with intake in the FAILED state."""
    err = StageError(code="extraction_error", description="intake guard failed")
    record = ContractRecord(
        intake=StageRecord(state=StageState.FAILED, error=err),
        ocr=StageRecord(),
        data_parsing=StageRecord(),
    )

    assert record.overall_status == "failed"


def test_overall_status_is_failed_when_parsing_failed_even_after_ocr_done() -> None:
    err = StageError(code="schema_invalid", description="missing field")
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE),
        ocr=StageRecord(state=StageState.DONE),
        data_parsing=StageRecord(state=StageState.FAILED, error=err),
    )

    assert record.overall_status == "failed"


# --- current_stage derivation -----------------------------------------------


def test_current_stage_is_ocr_when_intake_done_and_ocr_pending() -> None:
    record = ContractRecord.fresh(now=T0)

    assert record.current_stage == "ocr"


def test_current_stage_is_ocr_when_ocr_in_progress() -> None:
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE),
        ocr=StageRecord(state=StageState.IN_PROGRESS, started_at=T0),
        data_parsing=StageRecord(),
    )

    assert record.current_stage == "ocr"


def test_current_stage_is_data_parsing_when_ocr_done() -> None:
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE),
        ocr=StageRecord(state=StageState.DONE),
        data_parsing=StageRecord(state=StageState.IN_PROGRESS, started_at=T0),
    )

    assert record.current_stage == "data_parsing"


def test_current_stage_points_to_failure_point_when_a_stage_failed() -> None:
    err = StageError(code="ocr_engine_failed", description="x")
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE),
        ocr=StageRecord(state=StageState.FAILED, error=err),
        data_parsing=StageRecord(),
    )

    assert record.current_stage == "ocr"


def test_current_stage_points_to_data_parsing_when_data_parsing_failed() -> None:
    err = StageError(code="schema_invalid", description="missing field")
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE),
        ocr=StageRecord(state=StageState.DONE),
        data_parsing=StageRecord(state=StageState.FAILED, error=err),
    )

    assert record.current_stage == "data_parsing"


def test_current_stage_is_none_when_all_stages_done() -> None:
    done = StageRecord(state=StageState.DONE)
    record = ContractRecord(intake=done, ocr=done, data_parsing=done)

    assert record.current_stage is None


# --- mutability lock --------------------------------------------------------


def test_contract_record_allows_stage_reassignment() -> None:
    """ContractRecord is mutable so workers can do ``record.ocr = new_record``
    inside the asyncio.Lock-guarded update of §3.5."""
    record = ContractRecord.fresh(now=T0)

    record.ocr = record.ocr.start(now=T0)

    assert record.ocr.state == StageState.IN_PROGRESS
    assert record.ocr.started_at == T0


def test_stage_field_inside_contract_record_remains_frozen() -> None:
    """ContractRecord is mutable at the container level; its StageRecord children
    must still be frozen so a Phase 4 worker cannot bypass the §3.5 lock by
    mutating a sub-record in place (e.g., ``record.ocr.state = IN_PROGRESS``
    instead of the documented ``record.ocr = record.ocr.start(...)`` pattern)."""
    record = ContractRecord.fresh(now=T0)

    with pytest.raises(ValidationError):
        record.ocr.state = StageState.IN_PROGRESS  # type: ignore[misc]  # intentional frozen-child mutation to verify ValidationError fires.


def test_contract_record_rejects_unknown_field() -> None:
    """Pins ContractRecord's `extra='forbid'` model_config — Phase 4/5 typo'd
    field names are rejected at instantiation rather than silently accepted."""
    with pytest.raises(ValidationError):
        ContractRecord(bogus_field="x")  # type: ignore[call-arg]  # intentional unknown-field to verify extra="forbid" fires.


# --- JSON round-trip ---------------------------------------------------------


def test_contract_record_round_trips_through_model_dump_json_when_all_done() -> None:
    # Exercises overall_status, current_stage, AND nested StageRecord.duration_ms
    # computed_fields through serialization. Required because the Phase 5 HTTP
    # response shape returns this exact model to the orchestrator.
    # Note: computed_fields (overall_status, current_stage) are excluded from the
    # round-trip payload because extra="forbid" correctly rejects them as extra
    # inputs -- they are re-derived at load time from the stored stage fields.
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE, started_at=T0, completed_at=T0),
        ocr=StageRecord(
            state=StageState.DONE,
            started_at=T0,
            completed_at=T0 + timedelta(milliseconds=2000),
        ),
        data_parsing=StageRecord(
            state=StageState.DONE,
            started_at=T0 + timedelta(milliseconds=2000),
            completed_at=T0 + timedelta(milliseconds=22000),
            extracted={"contract_number": "C-001"},
        ),
    )

    payload = record.model_dump_json(exclude={"overall_status", "current_stage"})
    restored = ContractRecord.model_validate_json(payload)

    assert restored == record
    assert restored.overall_status == "done"
    assert restored.current_stage is None
    assert restored.ocr.duration_ms == 2000
    assert restored.data_parsing.extracted == {"contract_number": "C-001"}


def test_contract_record_round_trips_through_model_dump_json_when_failed() -> None:
    err = StageError(code="schema_invalid", description="missing field")
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE),
        ocr=StageRecord(state=StageState.DONE),
        data_parsing=StageRecord(state=StageState.FAILED, error=err),
    )

    payload = record.model_dump_json(exclude={"overall_status", "current_stage"})
    restored = ContractRecord.model_validate_json(payload)

    assert restored == record
    assert restored.overall_status == "failed"
    assert restored.current_stage == "data_parsing"
    assert restored.data_parsing.error == err


def test_default_contract_record_all_pending_has_intake_as_current_stage() -> None:
    """``ContractRecord()`` with no factory call yields all-PENDING stages.
    Production callers go through ``ContractRecord.fresh()``, but the bare
    constructor reachability is a tripwire: if a future result-store bug
    produces an unfreshed record, ``current_stage`` correctly points at
    ``intake`` and ``overall_status`` is ``in_progress``."""
    record = ContractRecord()

    assert record.intake.state == StageState.PENDING
    assert record.current_stage == "intake"
    assert record.overall_status == "in_progress"
