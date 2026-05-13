"""End-to-end pipeline integration tests (plan §6.6 task 4.9).

Drives contracts through the full pipeline path
(intake → OCR → LLM → done) using FakeOcrEngine + FakeOllamaClient with
real in-memory queues and a real ResultStore.

Each test exercises one observable behaviour (one assertion target, behaviour-
named). All tests cancel the worker tasks after the expected outcomes are
observed to prevent long-running coroutines from blocking test cleanup.

The manual task-cancellation pattern (asyncio.create_task + cancel-in-finally)
is intentional: asyncio.TaskGroup is unsuitable here because workers are
infinite loops that never return normally — TaskGroup would wait forever.
asyncio.CancelledError from workers is suppressed with contextlib.suppress so
the calling test does not re-raise it during cleanup.
"""

import asyncio
import contextlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from extraction_service.config.run_config import RetryConfig
from extraction_service.domain.errors import OcrEmptyOutputError
from extraction_service.domain.job import ContractJob
from extraction_service.domain.record import ContractRecord
from extraction_service.llm.client import OllamaLlmClient
from extraction_service.llm.prompt import PromptTemplate
from extraction_service.ocr.base import OcrResult
from extraction_service.pipeline.llm_worker import run_llm_worker
from extraction_service.pipeline.ocr_worker import run_ocr_worker
from extraction_service.pipeline.state import PipelineState
from extraction_service.settings import Settings
from tests.fakes.fake_ocr import FakeOcrEngine
from tests.fakes.fake_ollama import FakeOllamaClient

# ---------------------------------------------------------------------------
# Constants reused across tests
# ---------------------------------------------------------------------------

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"field": {"type": "string"}},
    "required": ["field"],
}

_EXTRACTED_CONTENT = '{"field": "v"}'
_EXPECTED_EXTRACTED: dict[str, Any] = {"field": "v"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(run_config=tmp_path / "run.yaml")


def _make_prompt_template(tmp_path: Path) -> PromptTemplate:
    p = tmp_path / "prompt.txt"
    p.write_text("Extract from: {ocr_text}\n\nSchema:\n{schema_json}", encoding="utf-8")
    return PromptTemplate(p)


def _make_llm_client() -> OllamaLlmClient:
    return OllamaLlmClient(
        client=FakeOllamaClient(content=_EXTRACTED_CONTENT),
        model="test-model",
    )


async def _seed_jobs(state: PipelineState, count: int) -> list[UUID]:
    """Create result-store records and enqueue ContractJobs. Returns list of IDs."""
    contract_ids: list[UUID] = []
    for _ in range(count):
        cid = uuid4()
        contract_ids.append(cid)
        await state.result_store.create(cid, ContractRecord.fresh())
        await state.intake_queue.put(
            ContractJob(contract_id=cid, pdf_bytes=b"%PDF-1.4 fake", metadata={})
        )
    return contract_ids


async def _run_workers_until_all_done(
    state: PipelineState,
    workers: list["asyncio.Task[None]"],
    contract_ids: list[UUID],
    *,
    wait_seconds: float = 5.0,
) -> None:
    """Poll the result store until every contract reaches a terminal status
    (done or failed), then cancel all workers.

    Uses asyncio.timeout (Python 3.11+ stdlib) rather than asyncio.wait_for
    so that the full set of IDs is polled inside a single timeout context.
    The parameter is named ``wait_seconds`` (not ``timeout``) to avoid
    ASYNC109 — ruff flags async functions with a ``timeout`` parameter as a
    hint to use ``asyncio.timeout`` instead; here we already do, so the
    rename keeps linting clean.
    """
    try:
        async with asyncio.timeout(wait_seconds):
            for cid in contract_ids:
                while True:
                    record = await state.result_store.get(cid)
                    if record is not None and record.overall_status in ("done", "failed"):
                        break
                    await asyncio.sleep(0.01)
    finally:
        for w in workers:
            w.cancel()
        for w in workers:
            with contextlib.suppress(asyncio.CancelledError):
                await w


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_with_fakes(tmp_path: Path) -> None:
    """Drive 4 contracts through the full pipeline (intake → OCR → LLM → done)
    using fakes for OCR and Ollama. Asserts every contract reaches
    overall_status=done. Plan §6.6 row 4.9 seed."""
    settings = _make_settings(tmp_path)
    state = PipelineState.from_settings(settings)
    ocr_engine = FakeOcrEngine(text="contract text body")
    llm_client = _make_llm_client()
    prompt_template = _make_prompt_template(tmp_path)
    retry_config = RetryConfig()

    contract_ids = await _seed_jobs(state, 4)

    workers: list[asyncio.Task[None]] = [
        asyncio.create_task(run_ocr_worker(state=state, engine=ocr_engine)),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
    ]

    await _run_workers_until_all_done(state, workers, contract_ids)

    finals = [await state.result_store.get(cid) for cid in contract_ids]
    assert all(r is not None and r.overall_status == "done" for r in finals)


@pytest.mark.asyncio
async def test_full_pipeline_writes_extracted_payload_to_each_record(
    tmp_path: Path,
) -> None:
    """Every record's data_parsing.extracted equals the LLM output dict."""
    settings = _make_settings(tmp_path)
    state = PipelineState.from_settings(settings)
    ocr_engine = FakeOcrEngine(text="contract text body")
    llm_client = _make_llm_client()
    prompt_template = _make_prompt_template(tmp_path)
    retry_config = RetryConfig()

    contract_ids = await _seed_jobs(state, 4)

    workers: list[asyncio.Task[None]] = [
        asyncio.create_task(run_ocr_worker(state=state, engine=ocr_engine)),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
    ]

    await _run_workers_until_all_done(state, workers, contract_ids)

    finals = [await state.result_store.get(cid) for cid in contract_ids]
    assert all(r is not None and r.data_parsing.extracted == _EXPECTED_EXTRACTED for r in finals)


@pytest.mark.asyncio
async def test_full_pipeline_drains_both_queues(tmp_path: Path) -> None:
    """Both intake_queue and interstage_queue have _unfinished_tasks == 0 after processing."""
    settings = _make_settings(tmp_path)
    state = PipelineState.from_settings(settings)
    ocr_engine = FakeOcrEngine(text="contract text body")
    llm_client = _make_llm_client()
    prompt_template = _make_prompt_template(tmp_path)
    retry_config = RetryConfig()

    contract_ids = await _seed_jobs(state, 4)

    workers: list[asyncio.Task[None]] = [
        asyncio.create_task(run_ocr_worker(state=state, engine=ocr_engine)),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
    ]

    await _run_workers_until_all_done(state, workers, contract_ids)

    # Both queues must have had task_done() called for every item enqueued.
    # asyncio.Queue tracks unfinished tasks; after join-equivalent drain both
    # counters should be zero.
    assert state.intake_queue._unfinished_tasks == 0  # type: ignore[attr-defined]  # CPython internal; no public equivalent in asyncio.Queue
    assert state.interstage_queue._unfinished_tasks == 0  # type: ignore[attr-defined]  # CPython internal; no public equivalent in asyncio.Queue


class _FailOnSecondCallOcrEngine:
    """Returns OcrResult on all calls EXCEPT the second, which raises OcrEmptyOutputError.

    Used to inject exactly one failure into a 4-job batch while the other three succeed.
    The failure on call 2 (0-indexed: call index 1) maps to whichever contract_id is
    dequeued second by the OCR worker.
    """

    def __init__(self, success_text: str = "contract text body") -> None:
        self._success_text = success_text
        self._call_index = 0

    async def extract(self, pdf_bytes: bytes) -> OcrResult:
        _ = pdf_bytes
        self._call_index += 1
        if self._call_index == 2:
            raise OcrEmptyOutputError("simulated empty output on job 2")
        return OcrResult(text=self._success_text, page_count=1, engine_name="fake")


@pytest.mark.asyncio
async def test_full_pipeline_handles_one_ocr_failure_in_a_batch_failed_record(
    tmp_path: Path,
) -> None:
    """The contract whose OCR raised OcrEmptyOutputError reaches overall_status=failed."""
    settings = _make_settings(tmp_path)
    state = PipelineState.from_settings(settings)
    ocr_engine = _FailOnSecondCallOcrEngine()
    llm_client = _make_llm_client()
    prompt_template = _make_prompt_template(tmp_path)
    retry_config = RetryConfig()

    contract_ids = await _seed_jobs(state, 4)

    workers: list[asyncio.Task[None]] = [
        asyncio.create_task(run_ocr_worker(state=state, engine=ocr_engine)),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
    ]

    await _run_workers_until_all_done(state, workers, contract_ids)

    finals = [await state.result_store.get(cid) for cid in contract_ids]
    failed_count = sum(1 for r in finals if r is not None and r.overall_status == "failed")
    assert failed_count == 1


@pytest.mark.asyncio
async def test_full_pipeline_handles_one_ocr_failure_in_a_batch_remaining_done(
    tmp_path: Path,
) -> None:
    """The 3 contracts not hit by the OCR failure still reach overall_status=done."""
    settings = _make_settings(tmp_path)
    state = PipelineState.from_settings(settings)
    ocr_engine = _FailOnSecondCallOcrEngine()
    llm_client = _make_llm_client()
    prompt_template = _make_prompt_template(tmp_path)
    retry_config = RetryConfig()

    contract_ids = await _seed_jobs(state, 4)

    workers: list[asyncio.Task[None]] = [
        asyncio.create_task(run_ocr_worker(state=state, engine=ocr_engine)),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
        asyncio.create_task(
            run_llm_worker(
                state=state,
                client=llm_client,
                prompt_template=prompt_template,
                domain_schema=_SCHEMA,
                retry_config=retry_config,
            )
        ),
    ]

    await _run_workers_until_all_done(state, workers, contract_ids)

    finals = [await state.result_store.get(cid) for cid in contract_ids]
    done_count = sum(1 for r in finals if r is not None and r.overall_status == "done")
    assert done_count == 3
