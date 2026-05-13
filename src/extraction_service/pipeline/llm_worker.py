"""LLM worker - drains interstage_queue and writes extraction results (plan §6.6 tasks 4.5 + 4.6).

``run_llm_worker`` is a long-running coroutine started by the Phase 5
lifespan wiring (one or more tasks per ``Settings.num_parallel``). It:

1. Pulls an ``OcrCompleted`` event from ``state.interstage_queue`` (blocks
   until one arrives).
2. Marks the record's ``data_parsing`` stage IN_PROGRESS.
3. Renders the extraction prompt via ``prompt_template.render``.
4. Calls ``client.extract`` through ``retry_extraction`` so transient LLM
   failures AND schema-validation failures are retried per ``retry_config``
   (validation is inside the retried function so a ``SchemaInvalidError``
   on attempt N can be retried on attempt N+1).
5. Strips every key in ``SIDE_CHANNEL_KEYS`` from the result dict - the
   ``_debug`` block injected by ``OllamaLlmClient`` in dev mode carries PII
   (full prompt text, party names, bank details). It MUST NOT reach
   ``StageRecord.extracted`` or any downstream serialisation.
6. Validates the stripped result against ``domain_schema`` via
   ``validate_extracted_data`` (raises ``SchemaInvalidError`` on mismatch).
7. Writes the result to the ``ResultStore`` with ``data_parsing`` DONE.

If retries are exhausted (or a non-retriable ``ExtractionError`` propagates),
the worker writes ``data_parsing.state=FAILED`` with the terminal exception's
``code`` and ``str(exc)`` description, then continues draining — one bad job
does not kill the pipeline (plan §3.3).

``asyncio.CancelledError`` and any non-``ExtractionError`` exception propagate
naturally so the Phase 5 supervisor TaskGroup can tear down cleanly. The
``finally`` block calls ``task_done()`` so ``Queue.join()`` callers are
unblocked even when an exception interrupts the body.
"""

from datetime import UTC, datetime
from typing import Any

from extraction_service.config.run_config import RetryConfig
from extraction_service.domain.errors import ExtractionError
from extraction_service.domain.stage import StageError, StageRecord
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

    For each ``OcrCompleted`` item dequeued, transition ``data_parsing`` to
    IN_PROGRESS, call the LLM (with retry on ``retry_config.retry_on`` codes
    including ``schema_invalid`` because validation happens inside the
    retried function), and write the result to the store with ``data_parsing``
    DONE — or, if every retry was exhausted, FAILED with the terminal error.

    Respects ``asyncio.CancelledError`` — never swallowed.
    """
    while True:
        completed = await state.interstage_queue.get()
        try:
            in_progress_record = StageRecord().start(datetime.now(UTC))
            await state.result_store.update_stage(
                completed.contract_id, "data_parsing", in_progress_record
            )

            prompt = prompt_template.render(
                ocr_text=completed.ocr_text,
                domain_schema=domain_schema,
            )

            async def _extract_and_validate(
                _prompt: str = prompt, _schema: dict[str, Any] = domain_schema
            ) -> dict[str, Any]:
                # Default-arg capture binds loop-local values at definition time
                # (avoids B023: lambda does not bind loop variable). Validation
                # runs INSIDE the retried function so a schema_invalid result on
                # attempt N triggers retry on attempt N+1 (plan §6.6 task 4.6).
                raw = await client.extract(prompt=_prompt, schema=_schema)
                for key in SIDE_CHANNEL_KEYS:
                    raw.pop(key, None)
                validate_extracted_data(raw, _schema)
                return raw

            try:
                result: dict[str, Any] = await retry_extraction(
                    _extract_and_validate,
                    max_retries=state.settings.max_retries,
                    retry_on=list(retry_config.retry_on),
                )
            except ExtractionError as exc:
                # Terminal failure — either retries exhausted (last retriable
                # error re-raised by retry_extraction) or a non-retriable code
                # propagated on the first attempt. Record FAILED on the stage
                # so GET /contracts/{id} returns the terminal error to the
                # orchestrator; do not push downstream (LLM is the tail).
                failed_record = in_progress_record.fail(
                    datetime.now(UTC),
                    error=StageError(code=exc.code, description=str(exc)),
                )
                await state.result_store.update_stage(
                    completed.contract_id, "data_parsing", failed_record
                )
            else:
                done_record = in_progress_record.complete(datetime.now(UTC), extracted=result)
                await state.result_store.update_stage(
                    completed.contract_id, "data_parsing", done_record
                )
        finally:
            state.interstage_queue.task_done()
