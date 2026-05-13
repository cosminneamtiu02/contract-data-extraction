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
from extraction_service.ocr.base import OcrResult
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


# ---------------------------------------------------------------------------
# Task 4.4: OcrError handling tests
# ---------------------------------------------------------------------------


class _RaisingOcrEngine:
    """Minimal OcrEngine stand-in that raises a specified exception on extract().

    Preferred over extending FakeOcrEngine (shared fake) — any in-test class
    that satisfies the OcrEngine Protocol structurally is sufficient here.

    ``extract`` is typed to return ``OcrResult`` (matching the Protocol) even
    though it always raises. mypy accepts ``NoReturn`` as a subtype of any
    return type, so the Protocol is satisfied without a cast.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def extract(self, pdf_bytes: bytes) -> OcrResult:
        _ = pdf_bytes
        raise self._exc


class _FirstFailThenSucceedOcrEngine:
    """Raises on the first call to extract(); returns OcrResult on subsequent calls.

    Used by test_ocr_worker_continues_after_one_failure to verify the worker
    keeps draining the queue after a single job failure.
    """

    def __init__(self, exc: Exception, success_text: str = "success text") -> None:
        self._exc = exc
        self._success_text = success_text
        self._call_count = 0

    async def extract(self, pdf_bytes: bytes) -> OcrResult:
        _ = pdf_bytes
        self._call_count += 1
        if self._call_count == 1:
            raise self._exc
        return OcrResult(text=self._success_text, page_count=1, engine_name="fake")


async def _wait_until_intake_drained(state: PipelineState) -> None:
    """Block until every enqueued job has had task_done() called.

    Uses intake_queue.join() so the event loop drives the drain rather than
    a polling loop (avoids ASYNC110 / ASYNC109 linter rules).
    """
    await state.intake_queue.join()


@pytest.mark.asyncio
async def test_ocr_worker_handles_ocr_empty_output(settings: Settings) -> None:
    """Worker marks ocr.state=failed when engine raises OcrEmptyOutputError."""
    from extraction_service.domain.errors import OcrEmptyOutputError

    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    await state.result_store.create(contract_id, ContractRecord.fresh())
    job = ContractJob(contract_id=contract_id, pdf_bytes=b"%PDF")
    await state.intake_queue.put(job)

    engine = _RaisingOcrEngine(OcrEmptyOutputError("pdf empty"))
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    await asyncio.wait_for(_wait_until_intake_drained(state), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(contract_id)
    assert record is not None
    assert record.ocr.state == StageState.FAILED


@pytest.mark.asyncio
async def test_ocr_worker_records_stage_error_code_on_ocr_failure(
    settings: Settings,
) -> None:
    """Worker stores the exception's code on record.ocr.error.code."""
    from extraction_service.domain.errors import OcrEmptyOutputError

    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    await state.result_store.create(contract_id, ContractRecord.fresh())
    job = ContractJob(contract_id=contract_id, pdf_bytes=b"%PDF")
    await state.intake_queue.put(job)

    engine = _RaisingOcrEngine(OcrEmptyOutputError("pdf empty"))
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    await asyncio.wait_for(_wait_until_intake_drained(state), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(contract_id)
    assert record is not None
    assert record.ocr.error is not None
    assert record.ocr.error.code == "ocr_empty_output"


@pytest.mark.asyncio
async def test_ocr_worker_records_stage_error_description_on_ocr_failure(
    settings: Settings,
) -> None:
    """Worker stores str(exc) in record.ocr.error.description."""
    from extraction_service.domain.errors import OcrEmptyOutputError

    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    await state.result_store.create(contract_id, ContractRecord.fresh())
    job = ContractJob(contract_id=contract_id, pdf_bytes=b"%PDF")
    await state.intake_queue.put(job)

    engine = _RaisingOcrEngine(OcrEmptyOutputError("pdf empty"))
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    await asyncio.wait_for(_wait_until_intake_drained(state), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(contract_id)
    assert record is not None
    assert record.ocr.error is not None
    assert "pdf empty" in record.ocr.error.description


@pytest.mark.asyncio
async def test_ocr_worker_does_not_push_to_interstage_on_ocr_failure(
    settings: Settings,
) -> None:
    """Worker does not enqueue an OcrCompleted when engine raises OcrError."""
    from extraction_service.domain.errors import OcrEmptyOutputError

    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    await state.result_store.create(contract_id, ContractRecord.fresh())
    job = ContractJob(contract_id=contract_id, pdf_bytes=b"%PDF")
    await state.intake_queue.put(job)

    engine = _RaisingOcrEngine(OcrEmptyOutputError("pdf empty"))
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    await asyncio.wait_for(_wait_until_intake_drained(state), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert state.interstage_queue.empty()


@pytest.mark.asyncio
async def test_ocr_worker_leaves_data_parsing_pending_on_ocr_failure(
    settings: Settings,
) -> None:
    """Worker leaves data_parsing.state=pending when OCR fails."""
    from extraction_service.domain.errors import OcrEmptyOutputError

    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    await state.result_store.create(contract_id, ContractRecord.fresh())
    job = ContractJob(contract_id=contract_id, pdf_bytes=b"%PDF")
    await state.intake_queue.put(job)

    engine = _RaisingOcrEngine(OcrEmptyOutputError("pdf empty"))
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    await asyncio.wait_for(_wait_until_intake_drained(state), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(contract_id)
    assert record is not None
    assert record.data_parsing.state == StageState.PENDING


@pytest.mark.asyncio
async def test_ocr_worker_continues_after_one_failure(settings: Settings) -> None:
    """Worker processes the second job successfully after the first job raises OcrError."""
    from extraction_service.domain.errors import OcrEmptyOutputError

    state = PipelineState.from_settings(settings)

    failing_id = uuid4()
    succeeding_id = uuid4()
    for cid in (failing_id, succeeding_id):
        await state.result_store.create(cid, ContractRecord.fresh())
        await state.intake_queue.put(ContractJob(contract_id=cid, pdf_bytes=b"%PDF"))

    engine = _FirstFailThenSucceedOcrEngine(OcrEmptyOutputError("pdf empty"))
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    # Wait for the interstage event from the second (successful) job.
    await asyncio.wait_for(state.interstage_queue.get(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(succeeding_id)
    assert record is not None
    assert record.ocr.state == StageState.DONE


@pytest.mark.asyncio
async def test_ocr_worker_calls_task_done_even_when_engine_raises(
    settings: Settings,
) -> None:
    """task_done() fires even when engine.extract raises OcrError."""
    from extraction_service.domain.errors import OcrEmptyOutputError

    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    await state.result_store.create(contract_id, ContractRecord.fresh())
    job = ContractJob(contract_id=contract_id, pdf_bytes=b"%PDF")
    await state.intake_queue.put(job)

    engine = _RaisingOcrEngine(OcrEmptyOutputError("pdf empty"))
    task = asyncio.create_task(run_ocr_worker(state=state, engine=engine))

    await asyncio.wait_for(_wait_until_intake_drained(state), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert state.intake_queue._unfinished_tasks == 0  # type: ignore[attr-defined]  # CPython internal attr; no public equivalent in asyncio.Queue
