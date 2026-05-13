"""Tests for the async-safe ResultStore.

Tests cover the full public API surface: create, get, update_stage, error
paths, snapshot semantics, and the concurrent-update safety guarantee that
is the primary motivation for the asyncio.Lock guard.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from extraction_service.domain.errors import (
    ContractAlreadyExistsError,
    ContractNotFoundError,
)
from extraction_service.domain.record import ContractRecord
from extraction_service.domain.stage import StageRecord, StageState
from extraction_service.pipeline.result_store import ResultStore


async def test_result_store_create_inserts_record() -> None:
    """create() makes the record visible via get()."""
    store = ResultStore()
    contract_id = uuid4()
    record = ContractRecord.fresh()
    await store.create(contract_id, record)
    result = await store.get(contract_id)
    assert result is not None


async def test_result_store_create_raises_when_contract_id_already_exists() -> None:
    """create() raises ContractAlreadyExistsError on a duplicate contract_id."""
    store = ResultStore()
    contract_id = uuid4()
    record = ContractRecord.fresh()
    await store.create(contract_id, record)
    with pytest.raises(ContractAlreadyExistsError):
        await store.create(contract_id, ContractRecord.fresh())


async def test_result_store_get_returns_none_for_unknown_contract_id() -> None:
    """get() returns None when the contract_id is not present in the store."""
    store = ResultStore()
    result = await store.get(uuid4())
    assert result is None


async def test_result_store_get_returns_snapshot_not_live_reference() -> None:
    """Mutating the record returned by get() does not affect the stored record.

    ContractRecord is mutable; get() must return a copy so that callers
    cannot accidentally corrupt the stored state outside the lock.
    """
    store = ResultStore()
    contract_id = uuid4()
    record = ContractRecord.fresh()
    await store.create(contract_id, record)

    snapshot = await store.get(contract_id)
    assert snapshot is not None

    # Mutate the snapshot in-place (ocr field reassignment)
    snapshot.ocr = StageRecord(state=StageState.IN_PROGRESS)

    # Re-fetch; store's copy must be unchanged
    stored_again = await store.get(contract_id)
    assert stored_again is not None
    assert stored_again.ocr.state == StageState.PENDING


async def test_result_store_update_stage_replaces_only_named_stage() -> None:
    """update_stage() replaces exactly the named stage; other stages are untouched."""
    store = ResultStore()
    contract_id = uuid4()
    now = datetime.now(UTC)
    fresh = ContractRecord.fresh(now=now)
    await store.create(contract_id, fresh)

    ocr_done = StageRecord(state=StageState.DONE)
    await store.update_stage(contract_id, "ocr", ocr_done)

    result = await store.get(contract_id)
    assert result is not None
    assert result.ocr.state == StageState.DONE
    # intake and data_parsing must be untouched
    assert result.intake.state == StageState.DONE  # set by ContractRecord.fresh()
    assert result.data_parsing.state == StageState.PENDING


async def test_result_store_update_stage_raises_when_contract_id_unknown() -> None:
    """update_stage() raises ContractNotFoundError for an unknown contract_id."""
    store = ResultStore()
    with pytest.raises(ContractNotFoundError):
        await store.update_stage(uuid4(), "ocr", StageRecord(state=StageState.DONE))


async def test_result_store_concurrent_updates_are_safe() -> None:
    """100 concurrent update_stage calls on one record produce a coherent final state.

    Part 1: all 100 tasks write state=DONE to the ocr field; after gather,
    the stored ocr.state must be DONE and no exception must have been raised.

    Part 2: 100 tasks each write a unique started_at timestamp; after gather,
    the stored started_at must equal one of the 100 inputs (coherent final
    write, not a torn datetime).
    """
    store = ResultStore()
    contract_id = uuid4()
    await store.create(contract_id, ContractRecord.fresh())

    # Part 1 — all tasks write state=DONE; no exception, coherent state
    done_record = StageRecord(state=StageState.DONE)
    await asyncio.gather(*[store.update_stage(contract_id, "ocr", done_record) for _ in range(100)])
    result = await store.get(contract_id)
    assert result is not None
    assert result.ocr.state == StageState.DONE

    # Part 2 — 100 unique timestamps; final stored value must be one of them
    timestamps = [datetime(2024, 1, 1, 0, 0, 0, microsecond=i, tzinfo=UTC) for i in range(100)]
    tasks = [
        store.update_stage(
            contract_id,
            "ocr",
            StageRecord(state=StageState.DONE, started_at=ts),
        )
        for ts in timestamps
    ]
    await asyncio.gather(*tasks)

    final = await store.get(contract_id)
    assert final is not None
    assert final.ocr.started_at in timestamps
