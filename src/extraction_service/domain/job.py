"""ContractJob — frozen value object representing a submitted contract.

A ContractJob is created when `POST /contracts` accepts a payload and the
HTTP handler enqueues work for the OCR worker. It is read (never mutated)
by every later stage. See docs/plan.md §3.2 for the lifecycle and §4.11
for the frozen-by-default Pydantic v2 idiom.

The ``metadata`` field uses ``dict[str, Any]`` — an IO-boundary case where
``Any`` is explicitly accepted per docs/plan.md §7 ("`Any` is acceptable only
at IO boundaries"). The orchestrator passes opaque key/value context the
service does not interpret.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContractJob(BaseModel):
    """A submitted contract awaiting processing.

    The model is frozen: attribute reassignment raises ``ValidationError``.
    Nested ``metadata`` is *not* deep-frozen — callers must not mutate the
    dict they passed in after construction.
    """

    model_config = ConfigDict(frozen=True)

    contract_id: UUID
    pdf_bytes: bytes
    metadata: dict[str, Any] = Field(default_factory=dict)
