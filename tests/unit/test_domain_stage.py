"""Unit tests for StageState (Task 1.2) and StageRecord/StageError (Task 1.3).

StageState is the source of truth for ContractRecord.overall_status derivation
(docs/plan.md §3.3). Choosing StrEnum (Python 3.11+) over the older
``(str, Enum)`` pairing makes ``str()`` and f-string interpolation produce the
plain value, which structlog consumes cleanly in §4.8 logging context.

StageRecord uses frozen + functional transitions (rather than in-place mutation)
so that the asyncio.Lock-guarded read-modify-write in §3.5 reasons about whole
records, not half-transitioned ones. Transition methods accept an optional
``now`` for deterministic tests; production callers pass nothing.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from extraction_service.domain.stage import StageError, StageRecord, StageState


def test_stage_state_has_expected_member_values() -> None:
    assert {state.value for state in StageState} == {
        "pending",
        "in_progress",
        "done",
        "failed",
    }


def test_stage_state_members_are_str_instances() -> None:
    # StrEnum members ARE strings — locks in the str-subclass contract that
    # later phases rely on (e.g., direct use as dict keys, JSON output).
    for state in StageState:
        assert isinstance(state, str)


def test_stage_state_str_coerces_to_value() -> None:
    # StrEnum overrides __str__ so log lines and f-strings stay clean.
    assert str(StageState.IN_PROGRESS) == "in_progress"
    assert f"{StageState.DONE}" == "done"


# --- StageError ----------------------------------------------------------


def test_stage_error_constructs_with_code_and_description() -> None:
    err = StageError(code="ocr_engine_failed", description="Docling raised IOError")

    assert err.code == "ocr_engine_failed"
    assert err.description == "Docling raised IOError"


def test_stage_error_is_frozen() -> None:
    err = StageError(code="ocr_engine_failed", description="x")

    with pytest.raises(ValidationError):
        err.code = "changed"  # type: ignore[misc]  # intentional frozen-model mutation to verify ValidationError fires.


# --- StageRecord ---------------------------------------------------------


T0 = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)


def test_stage_record_defaults_to_pending_with_no_timestamps_or_error() -> None:
    record = StageRecord()

    assert record.state == StageState.PENDING
    assert record.started_at is None
    assert record.completed_at is None
    assert record.error is None
    assert record.duration_ms is None


def test_stage_record_start_returns_new_record_with_started_at() -> None:
    record = StageRecord()

    started = record.start(now=T0)

    assert started.state == StageState.IN_PROGRESS
    assert started.started_at == T0
    assert started.completed_at is None
    # Original record is untouched (frozen + functional).
    assert record.state == StageState.PENDING
    assert record.started_at is None


def test_stage_record_complete_sets_completed_at_and_computes_duration_ms() -> None:
    record = StageRecord().start(now=T0)

    finished = record.complete(now=T0 + timedelta(milliseconds=250))

    assert finished.state == StageState.DONE
    assert finished.completed_at == T0 + timedelta(milliseconds=250)
    assert finished.duration_ms == 250


def test_stage_record_fail_sets_state_completed_at_and_error() -> None:
    error = StageError(code="ocr_empty_output", description="no text extracted")
    record = StageRecord().start(now=T0)

    failed = record.fail(error=error, now=T0 + timedelta(milliseconds=120))

    assert failed.state == StageState.FAILED
    assert failed.completed_at == T0 + timedelta(milliseconds=120)
    assert failed.error == error
    assert failed.duration_ms == 120


def test_stage_record_duration_ms_is_none_until_both_timestamps_set() -> None:
    pending = StageRecord()
    in_progress = pending.start(now=T0)

    assert pending.duration_ms is None
    assert in_progress.duration_ms is None


def test_stage_record_is_frozen() -> None:
    record = StageRecord()

    with pytest.raises(ValidationError):
        record.state = StageState.DONE  # type: ignore[misc]  # intentional frozen-model mutation to verify ValidationError fires.


def test_stage_record_complete_accepts_extracted_payload() -> None:
    # data_parsing stage's Phase 4 worker writes the validated JSON here
    # (docs/plan.md §3.2). Default for non-LLM stages: None.
    record = StageRecord().start(now=T0)

    finished = record.complete(
        now=T0 + timedelta(milliseconds=10),
        extracted={"contract_number": "C-001", "amount_eur": 1000},
    )

    assert finished.state == StageState.DONE
    assert finished.extracted == {"contract_number": "C-001", "amount_eur": 1000}


def test_stage_record_complete_defaults_extracted_to_none() -> None:
    record = StageRecord().start(now=T0).complete(now=T0 + timedelta(milliseconds=10))

    assert record.extracted is None


def test_stage_record_round_trips_through_model_dump_json_when_done() -> None:
    # The duration_ms computed_field must survive serialization so the
    # HTTP response in Phase 5 can read it directly.
    original = (
        StageRecord()
        .start(now=T0)
        .complete(
            now=T0 + timedelta(milliseconds=250),
            extracted={"key": "value"},
        )
    )

    payload = original.model_dump_json()
    restored = StageRecord.model_validate_json(payload)

    assert restored == original
    assert restored.duration_ms == 250
    assert restored.extracted == {"key": "value"}


def test_stage_record_round_trips_through_model_dump_json_when_pending() -> None:
    original = StageRecord()

    payload = original.model_dump_json()
    restored = StageRecord.model_validate_json(payload)

    assert restored == original
    assert restored.duration_ms is None
    assert restored.extracted is None


def test_stage_record_start_with_default_now_uses_current_time() -> None:
    """The production call path (``record.start()`` with no argument) must
    assign a timezone-aware datetime — a future refactor that drops the
    default would silently leave ``started_at`` at ``None``."""
    record = StageRecord().start()

    assert record.state == StageState.IN_PROGRESS
    assert record.started_at is not None
    assert record.started_at.tzinfo is not None
