"""Async-safe in-memory store for ContractRecord instances.

The store is the single source of truth for all in-flight and completed
contracts within one process lifetime (docs/plan.md §3.5). A single
asyncio.Lock guards every read and write so that concurrent workers —
OCR, LLM, HTTP handlers — never observe a torn record mid-update.

Design rationale (WHY this shape, not just WHAT):
- asyncio.Lock, not threading.Lock: the service is single-threaded asyncio;
  the lock only needs to prevent interleaved coroutine scheduling, not
  true parallelism.  threading.Lock would acquire the GIL unnecessarily.
- Read-modify-write in update_stage (not field mutation): ContractRecord is
  mutable but StageRecord fields are frozen.  model_copy(update=...) builds
  a new StageRecord-bearing ContractRecord atomically under the lock, so no
  caller can hold a reference to the partially-updated container.
- get() returns model_copy (shallow): ContractRecord fields are StageRecord
  objects which are themselves frozen (frozen=True in ConfigDict).  A shallow
  copy is sufficient — the caller cannot mutate the StageRecord values
  through the snapshot, only the top-level container fields.  A deep copy
  would be wasteful.
"""

import asyncio
from typing import Literal
from uuid import UUID

from extraction_service.domain.errors import (
    ContractAlreadyExistsError,
    ContractNotFoundError,
)
from extraction_service.domain.record import ContractRecord
from extraction_service.domain.stage import StageRecord


class ResultStore:
    """Thread-safe (asyncio) in-memory store keyed by contract UUID."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._store: dict[UUID, ContractRecord] = {}

    async def create(self, contract_id: UUID, record: ContractRecord) -> None:
        """Insert a fresh record.

        Raises ContractAlreadyExistsError if contract_id is already present.
        """
        async with self._lock:
            if contract_id in self._store:
                msg = f"Contract {contract_id} already exists in the store"
                raise ContractAlreadyExistsError(msg)
            self._store[contract_id] = record

    async def update_stage(
        self,
        contract_id: UUID,
        stage: Literal["intake", "ocr", "data_parsing"],
        stage_record: StageRecord,
    ) -> None:
        """Atomically replace one StageRecord on the contract.

        Performs a read-modify-write under the lock so no concurrent reader
        can observe the record mid-update.

        Raises ContractNotFoundError if contract_id is not present.
        """
        async with self._lock:
            current = self._store.get(contract_id)
            if current is None:
                msg = f"Contract {contract_id} not found in the store"
                raise ContractNotFoundError(msg)
            self._store[contract_id] = current.model_copy(update={stage: stage_record})

    async def get(self, contract_id: UUID) -> ContractRecord | None:
        """Return a snapshot of the current record, or None if absent.

        Returns model_copy(deep=False): a new ContractRecord container
        pointing to the same (frozen) StageRecord instances.  Callers
        cannot corrupt the store by mutating the returned container's
        fields because the container is a fresh copy.
        """
        async with self._lock:
            record = self._store.get(contract_id)
            if record is None:
                return None
            return record.model_copy()
