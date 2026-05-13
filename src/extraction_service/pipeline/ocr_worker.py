"""OCR worker — async loop that drains the intake queue (plan §6.6 task 4.3).

``run_ocr_worker`` is a long-running coroutine. It blocks on
``state.intake_queue.get()``, processes each ``ContractJob`` through an
``OcrEngine``, updates the result store, and pushes an ``OcrCompleted``
payload onto the interstage queue for the LLM worker to consume.

Design notes (WHY this shape):
- Function, not class: no state beyond what PipelineState already carries;
  a plain async function is the minimal abstraction the plan requires.
- task_done() in finally: ensures asyncio.Queue.join() counts the job even
  when an unhandled exception propagates (e.g., OcrError before task 4.4
  adds the try/except).
- No OcrError handling here: task 4.4 adds that in this same module; for
  task 4.3 all exceptions propagate so the caller (TaskGroup in Phase 5)
  can react uniformly.
- asyncio.CancelledError propagates naturally because the loop's only
  blocking point is ``await state.intake_queue.get()``; no bare except /
  no CancelledError swallow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

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

    For each ContractJob:
      1. update ocr stage to IN_PROGRESS via result_store.update_stage
      2. call engine.extract(job.pdf_bytes)
      3. update ocr stage to DONE
      4. push OcrCompleted(contract_id, ocr_text=result.text) onto interstage_queue
      5. call state.intake_queue.task_done()

    Respects asyncio.CancelledError (no swallow). No OcrError handling in
    this function — task 4.4 adds that.
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

            ocr_result = await engine.extract(job.pdf_bytes)

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
