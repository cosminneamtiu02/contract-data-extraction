"""OCR worker — async loop that drains the intake queue (plan §6.6 tasks 4.3 + 4.4).

``run_ocr_worker`` is a long-running coroutine. It blocks on
``state.intake_queue.get()``, processes each ``ContractJob`` through an
``OcrEngine``, updates the result store, and pushes an ``OcrCompleted``
payload onto the interstage queue for the LLM worker to consume.

Design notes (WHY this shape):
- Function, not class: no state beyond what PipelineState already carries;
  a plain async function is the minimal abstraction the plan requires.
- task_done() in finally: ensures asyncio.Queue.join() counts the job even
  when an exception (OcrError or CancelledError) propagates.
- OcrError handling (task 4.4): try/except OcrError around engine.extract
  records a failed stage and skips the interstage push so the LLM worker
  never receives a job whose OCR failed (plan §3.3). The worker continues
  draining the queue — one bad job does not kill the pipeline.
- Non-OcrError exceptions (CancelledError, generic Exception) propagate
  unchanged so the caller (TaskGroup in Phase 5) can react uniformly.
- asyncio.CancelledError propagates naturally because the loop's only
  blocking point is ``await state.intake_queue.get()``; no bare except /
  no CancelledError swallow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from extraction_service.domain.errors import OcrError
from extraction_service.domain.stage import StageError
from extraction_service.pipeline.state import OcrCompleted

if TYPE_CHECKING:
    from extraction_service.domain.job import ContractJob
    from extraction_service.ocr.base import OcrEngine
    from extraction_service.pipeline.state import PipelineState


async def run_ocr_worker(
    *,
    state: PipelineState,
    engine: OcrEngine,
) -> None:
    """Drain state.intake_queue indefinitely.

    For each ContractJob on the happy path:
      1. update ocr stage to IN_PROGRESS via result_store.update_stage
      2. call engine.extract(job.pdf_bytes)
      3. update ocr stage to DONE
      4. push OcrCompleted(contract_id, ocr_text=result.text) onto interstage_queue
      5. call state.intake_queue.task_done()

    On OcrError (any subclass, e.g. OcrEmptyOutputError):
      - ocr stage is updated to FAILED with a StageError(code, description)
      - nothing is pushed to interstage_queue (data_parsing stays PENDING)
      - task_done() still fires; the worker continues to the next job

    Respects asyncio.CancelledError (no swallow).
    """
    while True:
        job: ContractJob = await state.intake_queue.get()
        try:
            now_start = datetime.now(UTC)
            record = await state.result_store.get(job.contract_id)
            # record is guaranteed to exist: HTTP intake (Phase 5) creates it
            # before enqueue; tests create it in the fixture.
            assert record is not None  # noqa: S101  # invariant, not user input
            in_progress = record.ocr.start(now_start)
            await state.result_store.update_stage(job.contract_id, "ocr", in_progress)

            try:
                ocr_result = await engine.extract(job.pdf_bytes)
            except OcrError as exc:
                # OCR failure: record the error on the stage and skip downstream.
                # data_parsing stays PENDING — the LLM never runs (plan §3.3).
                now_fail = datetime.now(UTC)
                failed_record = await state.result_store.get(job.contract_id)
                assert failed_record is not None  # noqa: S101  # same invariant
                failed_stage = failed_record.ocr.fail(
                    now_fail,
                    error=StageError(code=exc.code, description=str(exc)),
                )
                await state.result_store.update_stage(job.contract_id, "ocr", failed_stage)
                continue  # do NOT push to interstage_queue; task_done() fires in finally

            now_done = datetime.now(UTC)
            updated_record = await state.result_store.get(job.contract_id)
            assert updated_record is not None  # noqa: S101  # same invariant
            done = updated_record.ocr.complete(now_done)
            await state.result_store.update_stage(job.contract_id, "ocr", done)

            await state.interstage_queue.put(
                OcrCompleted(contract_id=job.contract_id, ocr_text=ocr_result.text)
            )
        finally:
            state.intake_queue.task_done()
