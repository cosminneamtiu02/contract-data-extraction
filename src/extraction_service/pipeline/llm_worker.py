"""LLM worker - drains interstage_queue and writes extraction results (plan §6.6 task 4.5).

``run_llm_worker`` is a long-running coroutine started by the Phase 5
lifespan wiring (one or more tasks per ``Settings.num_parallel``). It:

1. Pulls an ``OcrCompleted`` event from ``state.interstage_queue`` (blocks
   until one arrives).
2. Marks the record's ``data_parsing`` stage IN_PROGRESS.
3. Renders the extraction prompt via ``prompt_template.render``.
4. Calls ``client.extract`` through ``retry_extraction`` so transient LLM
   failures are retried per ``retry_config``.
5. Strips every key in ``SIDE_CHANNEL_KEYS`` from the result dict - the
   ``_debug`` block injected by ``OllamaLlmClient`` in dev mode carries PII
   (full prompt text, party names, bank details). It MUST NOT reach
   ``StageRecord.extracted`` or any downstream serialisation.
6. Validates the stripped result against ``domain_schema`` via
   ``validate_extracted_data`` (raises ``SchemaInvalidError`` on mismatch).
7. Writes the result to the ``ResultStore`` with ``data_parsing`` DONE.
8. Calls ``state.interstage_queue.task_done()`` in a ``finally`` block so
   ``Queue.join()`` callers (e.g. the Phase 5 lifespan shutdown fence) are
   unblocked even when an exception interrupts steps 2-7.

``asyncio.CancelledError`` is never swallowed - the ``finally`` block calls
``task_done()`` and lets the error propagate naturally so the supervisor task
(Phase 5 TaskGroup) can tear down cleanly.
"""

from datetime import UTC, datetime
from typing import Any

from extraction_service.config.run_config import RetryConfig
from extraction_service.domain.stage import StageRecord
from extraction_service.llm.client import SIDE_CHANNEL_KEYS, OllamaLlmClient
from extraction_service.llm.prompt import PromptTemplate
from extraction_service.llm.retry import retry_extraction
from extraction_service.llm.schema import validate_extracted_data
from extraction_service.pipeline.state import PipelineState


async def run_llm_worker(
    *,
    state: PipelineState,
    client: OllamaLlmClient,
    prompt_template: PromptTemplate,
    domain_schema: dict[str, Any],
    retry_config: RetryConfig,
) -> None:
    """Drain ``state.interstage_queue`` indefinitely.

    For each ``OcrCompleted`` item dequeued:

    1. Update ``data_parsing`` stage to IN_PROGRESS.
    2. Render prompt via ``prompt_template.render``.
    3. Call ``retry_extraction`` wrapping ``client.extract`` per ``retry_config``.
    4. Strip ``SIDE_CHANNEL_KEYS`` from the result (PII guard; see
       ``extraction_service.llm.client`` docstring).
    5. Validate stripped result via ``validate_extracted_data`` - raises
       ``SchemaInvalidError`` on mismatch.
    6. Update ``data_parsing`` stage to DONE with ``extracted=result``.
    7. Call ``state.interstage_queue.task_done()`` in a ``finally`` block.

    Respects ``asyncio.CancelledError`` - never swallowed.
    """
    while True:
        completed = await state.interstage_queue.get()
        try:
            now = datetime.now(UTC)
            in_progress_record = StageRecord().start(now)
            await state.result_store.update_stage(
                completed.contract_id, "data_parsing", in_progress_record
            )

            prompt = prompt_template.render(
                ocr_text=completed.ocr_text,
                domain_schema=domain_schema,
            )

            async def _do_extract(
                _prompt: str = prompt, _schema: dict[str, Any] = domain_schema
            ) -> dict[str, Any]:
                # Default-arg capture binds loop-local values at definition time
                # (avoids B023: lambda does not bind loop variable).
                return await client.extract(prompt=_prompt, schema=_schema)

            result: dict[str, Any] = await retry_extraction(
                _do_extract,
                max_retries=state.settings.max_retries,
                retry_on=list(retry_config.retry_on),
            )

            # Strip side-channel keys (PII guard) before validation and storage.
            for key in SIDE_CHANNEL_KEYS:
                result.pop(key, None)

            validate_extracted_data(result, domain_schema)

            done_record = in_progress_record.complete(datetime.now(UTC), extracted=result)
            await state.result_store.update_stage(
                completed.contract_id, "data_parsing", done_record
            )
        finally:
            state.interstage_queue.task_done()
