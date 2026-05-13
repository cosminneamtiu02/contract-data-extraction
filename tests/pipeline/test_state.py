"""Tests for PipelineState + OcrCompleted (plan §6.6 task 4.2)."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from extraction_service.pipeline.result_store import ResultStore
from extraction_service.pipeline.state import OcrCompleted, PipelineState
from extraction_service.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A Settings instance with known queue sizes for size-assertion tests."""
    return Settings(
        run_config=tmp_path / "run.yaml",
        intake_queue_size=7,
        interstage_queue_size=3,
    )


def test_pipeline_state_construct(settings: Settings) -> None:
    """Seed test (plan §6.6 row 4.2): queues are sized from Settings."""
    state = PipelineState.from_settings(settings)
    assert state.intake_queue.maxsize == settings.intake_queue_size


def test_pipeline_state_from_settings_sizes_interstage_queue(settings: Settings) -> None:
    state = PipelineState.from_settings(settings)
    assert state.interstage_queue.maxsize == settings.interstage_queue_size


def test_pipeline_state_from_settings_creates_result_store_when_omitted(
    settings: Settings,
) -> None:
    state = PipelineState.from_settings(settings)
    assert isinstance(state.result_store, ResultStore)


def test_pipeline_state_from_settings_uses_provided_result_store(settings: Settings) -> None:
    store = ResultStore()
    state = PipelineState.from_settings(settings, result_store=store)
    assert state.result_store is store


def test_pipeline_state_preserves_settings_reference(settings: Settings) -> None:
    state = PipelineState.from_settings(settings)
    assert state.settings is settings


def test_pipeline_state_is_frozen(settings: Settings) -> None:
    """Workers must not reassign the queues mid-run; the dataclass is frozen."""
    state = PipelineState.from_settings(settings)
    with pytest.raises(FrozenInstanceError):
        state.intake_queue = state.intake_queue  # type: ignore[misc]  # asserting frozen-ness


def test_ocr_completed_is_frozen() -> None:
    contract_id: UUID = uuid4()
    completed = OcrCompleted(contract_id=contract_id, ocr_text="hello")
    with pytest.raises(ValidationError):
        completed.ocr_text = "changed"  # type: ignore[misc]  # asserting frozen-ness


def test_ocr_completed_round_trips_through_model_dump_json() -> None:
    contract_id: UUID = uuid4()
    original = OcrCompleted(contract_id=contract_id, ocr_text="page one\npage two")
    rebuilt = OcrCompleted.model_validate_json(original.model_dump_json())
    assert rebuilt == original
