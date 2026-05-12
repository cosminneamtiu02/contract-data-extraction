"""Unit tests for StageState (Task 1.2) and StageRecord (Task 1.3 — next).

StageState is the source of truth for ContractRecord.overall_status derivation
(docs/plan.md §3.3). Choosing StrEnum (Python 3.11+) over the older
``(str, Enum)`` pairing makes ``str()`` and f-string interpolation produce the
plain value, which structlog consumes cleanly in §4.8 logging context.
"""

from extraction_service.domain.stage import StageState


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
