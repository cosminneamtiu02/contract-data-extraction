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


def test_stage_state_str_produces_value() -> None:
    # StrEnum overrides __str__ so log lines stay clean.
    assert str(StageState.IN_PROGRESS) == "in_progress"


def test_stage_state_fstring_interpolation_produces_value() -> None:
    # StrEnum overrides __format__ so f-string interpolation stays clean.
    assert f"{StageState.DONE}" == "done"


# --- StageError ----------------------------------------------------------


def test_stage_error_is_frozen() -> None:
    err = StageError(code="ocr_engine_failed", description="x")

    with pytest.raises(ValidationError):
        err.code = "changed"  # type: ignore[misc]  # intentional frozen-model mutation to verify ValidationError fires.


# --- StageRecord ---------------------------------------------------------


T0 = datetime(2026, 5, 12, 12, 0, 0, tzinfo=UTC)


def test_stage_record_defaults_state_to_pending() -> None:
    assert StageRecord().state == StageState.PENDING


def test_stage_record_defaults_started_at_to_none() -> None:
    assert StageRecord().started_at is None


def test_stage_record_defaults_completed_at_to_none() -> None:
    assert StageRecord().completed_at is None


def test_stage_record_defaults_error_to_none() -> None:
    assert StageRecord().error is None


def test_stage_record_defaults_duration_ms_to_none() -> None:
    assert StageRecord().duration_ms is None


def test_stage_record_start_returns_new_record_in_progress() -> None:
    started = StageRecord().start(now=T0)

    assert started.state == StageState.IN_PROGRESS


def test_stage_record_start_sets_started_at_on_new_record() -> None:
    started = StageRecord().start(now=T0)

    assert started.started_at == T0


def test_stage_record_start_leaves_completed_at_none_on_new_record() -> None:
    started = StageRecord().start(now=T0)

    assert started.completed_at is None


def test_stage_record_start_leaves_original_record_unchanged() -> None:
    # Frozen + functional: start() must return a new record; the original
    # must not mutate (state stays PENDING, started_at stays None).
    record = StageRecord()
    record.start(now=T0)

    assert record.state == StageState.PENDING
    assert record.started_at is None


def test_stage_record_complete_transitions_state_to_done() -> None:
    record = StageRecord().start(now=T0)

    finished = record.complete(now=T0 + timedelta(milliseconds=250))

    assert finished.state == StageState.DONE


def test_stage_record_complete_sets_completed_at_to_now() -> None:
    record = StageRecord().start(now=T0)

    finished = record.complete(now=T0 + timedelta(milliseconds=250))

    assert finished.completed_at == T0 + timedelta(milliseconds=250)


def test_stage_record_complete_carries_started_at_forward() -> None:
    """started_at must persist through complete() so duration_ms can derive
    from both timestamps; an explicit assert here prevents a future refactor
    that resets started_at on transition from silently breaking it."""
    record = StageRecord().start(now=T0)

    finished = record.complete(now=T0 + timedelta(milliseconds=250))

    assert finished.started_at == T0


def test_stage_record_complete_derives_duration_ms() -> None:
    record = StageRecord().start(now=T0)

    finished = record.complete(now=T0 + timedelta(milliseconds=250))

    assert finished.duration_ms == 250


def test_stage_record_fail_transitions_state_to_failed() -> None:
    error = StageError(code="ocr_empty_output", description="no text extracted")
    record = StageRecord().start(now=T0)

    failed = record.fail(error=error, now=T0 + timedelta(milliseconds=120))

    assert failed.state == StageState.FAILED


def test_stage_record_fail_sets_completed_at_to_now() -> None:
    error = StageError(code="ocr_empty_output", description="no text extracted")
    record = StageRecord().start(now=T0)

    failed = record.fail(error=error, now=T0 + timedelta(milliseconds=120))

    assert failed.completed_at == T0 + timedelta(milliseconds=120)


def test_stage_record_fail_records_error() -> None:
    error = StageError(code="ocr_empty_output", description="no text extracted")
    record = StageRecord().start(now=T0)

    failed = record.fail(error=error, now=T0 + timedelta(milliseconds=120))

    assert failed.error == error


def test_stage_record_fail_carries_started_at_forward() -> None:
    """started_at must persist through fail() so duration_ms can derive
    from both timestamps; an explicit assert here prevents a future refactor
    that resets started_at on transition from silently breaking it."""
    error = StageError(code="ocr_empty_output", description="no text extracted")
    record = StageRecord().start(now=T0)

    failed = record.fail(error=error, now=T0 + timedelta(milliseconds=120))

    assert failed.started_at == T0


def test_stage_record_fail_derives_duration_ms() -> None:
    error = StageError(code="ocr_empty_output", description="no text extracted")
    record = StageRecord().start(now=T0)

    failed = record.fail(error=error, now=T0 + timedelta(milliseconds=120))

    assert failed.duration_ms == 120


def test_stage_record_duration_ms_is_none_when_pending() -> None:
    pending = StageRecord()

    assert pending.duration_ms is None


def test_stage_record_duration_ms_is_none_when_in_progress_before_complete() -> None:
    in_progress = StageRecord().start(now=T0)

    assert in_progress.duration_ms is None


def test_stage_record_is_frozen() -> None:
    record = StageRecord()

    with pytest.raises(ValidationError):
        record.state = StageState.DONE  # type: ignore[misc]  # intentional frozen-model mutation to verify ValidationError fires.


def test_stage_record_complete_accepts_extracted_payload() -> None:
    # data_parsing stage's Phase 4 worker writes the validated JSON here
    # (docs/plan.md §3.2). Default for non-LLM stages: None.
    # State transition is covered separately by test_stage_record_complete_transitions_state_to_done.
    record = StageRecord().start(now=T0)

    finished = record.complete(
        now=T0 + timedelta(milliseconds=10),
        extracted={"contract_number": "C-001", "amount_eur": 1000},
    )

    assert finished.extracted == {"contract_number": "C-001", "amount_eur": 1000}


def test_stage_record_complete_defaults_extracted_to_none() -> None:
    record = StageRecord().start(now=T0).complete(now=T0 + timedelta(milliseconds=10))

    assert record.extracted is None


def test_stage_record_round_trips_through_model_dump_json_when_done() -> None:
    # Structural equality (restored == original) exercises all fields including
    # the computed duration_ms that Phase 5 HTTP response will read directly.
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


def test_stage_record_round_trips_through_model_dump_json_when_pending() -> None:
    original = StageRecord()

    payload = original.model_dump_json()
    restored = StageRecord.model_validate_json(payload)

    assert restored == original


def test_stage_record_start_with_default_now_uses_current_time() -> None:
    """The production call path (``record.start()`` with no argument) must
    assign a timezone-aware datetime — a future refactor that drops the
    default would silently leave ``started_at`` at ``None``."""
    record = StageRecord().start()

    assert record.started_at is not None
    assert record.started_at.tzinfo is not None


def test_stage_record_complete_with_default_now_uses_current_time() -> None:
    """The production call path (``record.complete()`` with no argument) must
    assign a timezone-aware ``completed_at`` — a future refactor that drops
    the ``datetime.now(UTC)`` default would silently leave ``completed_at``
    at ``None``, breaking ``duration_ms`` derivation without a test catching
    it."""
    record = StageRecord().start(now=T0)

    finished = record.complete()

    assert finished.completed_at is not None
    assert finished.completed_at.tzinfo is not None
    assert finished.duration_ms is not None
    assert finished.duration_ms >= 0


def test_stage_record_fail_with_default_now_uses_current_time() -> None:
    """The production call path (``record.fail(error=...)`` with no ``now``
    argument) must assign a timezone-aware ``completed_at`` — a future
    refactor that drops the ``datetime.now(UTC)`` default would silently
    leave ``completed_at`` at ``None``, breaking ``duration_ms`` derivation
    without a test catching it."""
    error = StageError(code="ocr_engine_failed", description="x")
    record = StageRecord().start(now=T0)

    failed = record.fail(error=error)

    assert failed.completed_at is not None
    assert failed.completed_at.tzinfo is not None
    assert failed.duration_ms is not None
    assert failed.duration_ms >= 0
