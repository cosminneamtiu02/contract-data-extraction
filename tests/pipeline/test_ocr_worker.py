"""Tests for run_ocr_worker (plan §6.6 task 4.3).

The OCR worker is a long-running coroutine that drains intake_queue,
calls an OcrEngine, updates the result store, and pushes OcrCompleted
events onto the interstage queue.

Each test exercises one behaviour in isolation (one assertion target per
test, behaviour-named). All tests cancel the worker task after extraction
to prevent the coroutine from blocking the test cleanup.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from extraction_service.domain.job import ContractJob
from extraction_service.domain.record import ContractRecord
from extraction_service.domain.stage import StageState
from extraction_service.pipeline.ocr_worker import run_ocr_worker
from extraction_service.pipeline.state import OcrCompleted, PipelineState
from extraction_service.settings import Settings
from tests.fakes.fake_ocr import FakeOcrEngine


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(run_config=tmp_path / "run.yaml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup_and_run_one(
    settings: Settings, ocr_text: str = "hello"
) -> tuple[PipelineState, asyncio.Task[None], ContractJob]:
    """Create a fresh PipelineState, enqueue one ContractJob, start the
    worker, and return (state, task, job) for assertions."""
    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    await state.result_store.create(contract_id, ContractRecord.fresh())
    job = ContractJob(contract_id=contract_id, pdf_bytes=b"%PDF")
    await state.intake_queue.put(job)
    engine = FakeOcrEngine(text=ocr_text)
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))
    return state, task, job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ocr_worker_processes_one_job(settings: Settings) -> None:
    """Worker pulls a ContractJob, runs OCR, and reaches ocr.state=done."""
    state, task, job = await _setup_and_run_one(settings)
    await asyncio.wait_for(state.interstage_queue.get(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(job.contract_id)
    assert record is not None
    assert record.ocr.state == StageState.DONE


@pytest.mark.asyncio
async def test_ocr_worker_pushes_ocr_completed_with_text(settings: Settings) -> None:
    """Worker enqueues an OcrCompleted whose ocr_text matches the engine output."""
    state, task, _job = await _setup_and_run_one(settings, ocr_text="hello")
    completed: OcrCompleted = await asyncio.wait_for(state.interstage_queue.get(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert completed.ocr_text == "hello"


@pytest.mark.asyncio
async def test_ocr_worker_transitions_ocr_through_in_progress_then_done(
    settings: Settings,
) -> None:
    """Final record has both started_at and completed_at set (full transition)."""
    state, task, job = await _setup_and_run_one(settings)
    await asyncio.wait_for(state.interstage_queue.get(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(job.contract_id)
    assert record is not None
    assert record.ocr.started_at is not None
    assert record.ocr.completed_at is not None


@pytest.mark.asyncio
async def test_ocr_worker_calls_intake_queue_task_done(settings: Settings) -> None:
    """After processing one job, intake_queue.unfinished_tasks reaches zero."""
    state, task, _job = await _setup_and_run_one(settings)
    await asyncio.wait_for(state.interstage_queue.get(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # asyncio.Queue tracks unfinished tasks; task_done() decrements the counter.
    assert state.intake_queue._unfinished_tasks == 0  # type: ignore[attr-defined]  # CPython internal attr; no public equivalent in asyncio.Queue


@pytest.mark.asyncio
async def test_ocr_worker_processes_two_jobs_sequentially(settings: Settings) -> None:
    """Worker drains two consecutive jobs; both reach ocr.state=done."""
    state = PipelineState.from_settings(settings)
    ids = [uuid4(), uuid4()]
    for cid in ids:
        await state.result_store.create(cid, ContractRecord.fresh())
        await state.intake_queue.put(ContractJob(contract_id=cid, pdf_bytes=b"%PDF"))

    engine = FakeOcrEngine(text="multi")
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    # Drain both OcrCompleted events before cancelling.
    for _ in ids:
        await asyncio.wait_for(state.interstage_queue.get(), timeout=2.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for cid in ids:
        record = await state.result_store.get(cid)
        assert record is not None
        assert record.ocr.state == StageState.DONE


@pytest.mark.asyncio
async def test_ocr_worker_propagates_cancellation(settings: Settings) -> None:
    """Cancelling the worker task raises CancelledError rather than swallowing it."""
    state = PipelineState.from_settings(settings)
    engine = FakeOcrEngine()
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))
    # Let the worker reach its blocking queue.get() before cancelling.
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
