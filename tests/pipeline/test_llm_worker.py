"""Tests for run_llm_worker (plan §6.6 task 4.5).

The LLM worker is a long-running coroutine that drains interstage_queue,
calls an OllamaLlmClient through retry_extraction, strips SIDE_CHANNEL_KEYS
from the result, validates the schema, and writes the result to the ResultStore.

Each test exercises one behaviour in isolation (one assertion target per
test, behaviour-named). All tests cancel the worker task after processing
to prevent the coroutine from blocking test cleanup.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from extraction_service.config.run_config import RetryConfig
from extraction_service.domain.errors import LlmError
from extraction_service.domain.record import ContractRecord
from extraction_service.domain.stage import StageRecord, StageState
from extraction_service.llm.client import OllamaLlmClient
from extraction_service.llm.prompt import PromptTemplate
from extraction_service.pipeline.llm_worker import run_llm_worker
from extraction_service.pipeline.state import OcrCompleted, PipelineState
from extraction_service.settings import Settings
from tests.fakes.fake_ollama import FakeChatResponse, FakeOllamaClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(run_config=tmp_path / "run.yaml")


@pytest.fixture
def prompt_template(tmp_path: Path) -> PromptTemplate:
    p = tmp_path / "prompt.txt"
    p.write_text("Extract from: {ocr_text}\n\nSchema:\n{schema_json}", encoding="utf-8")
    return PromptTemplate(p)


_SIMPLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"field": {"type": "string"}},
    "required": ["field"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup_and_run_one(  # noqa: PLR0913  # six args — each is a distinct test dimension
    settings: Settings,
    prompt_template: PromptTemplate,
    fake_content: str = '{"field": "value"}',
    retry_config: RetryConfig | None = None,
    schema: dict[str, Any] | None = None,
    fake_client: FakeOllamaClient | None = None,
) -> tuple[PipelineState, "asyncio.Task[None]", OcrCompleted]:
    """Create a fresh PipelineState, seed a record, enqueue one OcrCompleted,
    start the worker, and return (state, task, completed) for assertions."""
    state = PipelineState.from_settings(settings)
    contract_id = uuid4()
    # Seed the record: intake done, ocr done, data_parsing pending.
    t = datetime.now(UTC)
    record = ContractRecord(
        intake=StageRecord(state=StageState.DONE, started_at=t, completed_at=t),
        ocr=StageRecord(state=StageState.DONE, started_at=t, completed_at=t),
    )
    await state.result_store.create(contract_id, record)

    completed = OcrCompleted(contract_id=contract_id, ocr_text="some ocr text")
    await state.interstage_queue.put(completed)

    used_fake = fake_client if fake_client is not None else FakeOllamaClient(content=fake_content)
    client = OllamaLlmClient(client=used_fake, model="test-model")
    used_schema = schema if schema is not None else _SIMPLE_SCHEMA
    used_retry = retry_config if retry_config is not None else RetryConfig()

    task: asyncio.Task[None] = asyncio.create_task(
        run_llm_worker(
            state=state,
            client=client,
            prompt_template=prompt_template,
            domain_schema=used_schema,
            retry_config=used_retry,
        )
    )
    return state, task, completed


async def _wait_for_data_parsing_done(
    state: PipelineState, contract_id: UUID, *, wait_seconds: float = 2.0
) -> None:
    """Poll until data_parsing.state == DONE or raise TimeoutError."""
    async with asyncio.timeout(wait_seconds):
        while True:
            record = await state.result_store.get(contract_id)
            if record is not None and record.data_parsing.state == StageState.DONE:
                return
            await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_worker_processes_one_job(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """Worker pulls one OcrCompleted job and sets data_parsing.state=done."""
    state, task, completed = await _setup_and_run_one(settings, prompt_template)
    await _wait_for_data_parsing_done(state, completed.contract_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(completed.contract_id)
    assert record is not None
    assert record.data_parsing.state == StageState.DONE


@pytest.mark.asyncio
async def test_llm_worker_writes_extracted_payload_to_record(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """Worker stores the parsed LLM result dict in data_parsing.extracted."""
    state, task, completed = await _setup_and_run_one(
        settings, prompt_template, fake_content='{"field": "value"}'
    )
    await _wait_for_data_parsing_done(state, completed.contract_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(completed.contract_id)
    assert record is not None
    assert record.data_parsing.extracted == {"field": "value"}


@pytest.mark.asyncio
async def test_llm_worker_drops_debug_key_from_extracted(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """Worker strips _debug from the LLM result before storing in the record."""
    state, task, completed = await _setup_and_run_one(
        settings,
        prompt_template,
        fake_content='{"field": "v", "_debug": {"x": 1}}',
    )
    await _wait_for_data_parsing_done(state, completed.contract_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(completed.contract_id)
    assert record is not None
    assert "_debug" not in (record.data_parsing.extracted or {})


@pytest.mark.asyncio
async def test_llm_worker_preserves_real_payload_when_stripping_side_channel_keys(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """Worker keeps the real payload keys after stripping _debug."""
    state, task, completed = await _setup_and_run_one(
        settings,
        prompt_template,
        fake_content='{"field": "v", "_debug": {"x": 1}}',
    )
    await _wait_for_data_parsing_done(state, completed.contract_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(completed.contract_id)
    assert record is not None
    assert "field" in (record.data_parsing.extracted or {})


@pytest.mark.asyncio
async def test_llm_worker_calls_interstage_queue_task_done(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """After processing one job, interstage_queue.unfinished_tasks reaches zero."""
    state, task, completed = await _setup_and_run_one(settings, prompt_template)
    await _wait_for_data_parsing_done(state, completed.contract_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # asyncio.Queue tracks unfinished tasks; task_done() decrements the counter.
    assert state.interstage_queue._unfinished_tasks == 0  # type: ignore[attr-defined]  # CPython internal attr; no public equivalent in asyncio.Queue


@pytest.mark.asyncio
async def test_llm_worker_transitions_through_in_progress_then_done(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """Final record has both started_at and completed_at set on data_parsing."""
    state, task, completed = await _setup_and_run_one(settings, prompt_template)
    await _wait_for_data_parsing_done(state, completed.contract_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(completed.contract_id)
    assert record is not None
    assert record.data_parsing.started_at is not None
    assert record.data_parsing.completed_at is not None


@pytest.mark.asyncio
async def test_llm_worker_propagates_cancellation(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """Cancelling the worker task raises CancelledError rather than swallowing it."""
    state = PipelineState.from_settings(settings)
    client = OllamaLlmClient(client=FakeOllamaClient(), model="test-model")
    task: asyncio.Task[None] = asyncio.create_task(
        run_llm_worker(
            state=state,
            client=client,
            prompt_template=prompt_template,
            domain_schema=_SIMPLE_SCHEMA,
            retry_config=RetryConfig(),
        )
    )
    # Let the worker reach its blocking queue.get() before cancelling.
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_llm_worker_uses_retry_extraction_for_llm_failed_code(
    settings: Settings, prompt_template: PromptTemplate
) -> None:
    """Worker retries when the LLM client raises LlmError and reaches DONE on second call."""
    call_count = 0
    success_content = '{"field": "retried"}'

    class _FailOnceFakeClient(FakeOllamaClient):
        """Raises LlmError on the first call, returns success content on the second."""

        async def chat(
            self,
            *,
            model: str = "",
            messages: list[dict[str, str]] | None = None,
            format: dict[str, Any] | None = None,  # noqa: A002  -- mirrors ollama SDK param name
            options: dict[str, Any] | None = None,
            **_extras: object,
        ) -> FakeChatResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise LlmError("transient failure")
            self._content = success_content  # set to success for subsequent call
            return await super().chat(
                model=model,
                messages=messages,
                format=format,
                options=options,
            )

    fail_once_fake = _FailOnceFakeClient()
    retry_config = RetryConfig(retry_on=["llm_failed"])

    state, task, completed = await _setup_and_run_one(
        settings,
        prompt_template,
        retry_config=retry_config,
        fake_client=fail_once_fake,
    )
    await _wait_for_data_parsing_done(state, completed.contract_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await state.result_store.get(completed.contract_id)
    assert record is not None
    assert record.data_parsing.state == StageState.DONE
