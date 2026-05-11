"""Unit tests for ContractJob domain model.

ContractJob is the immutable value object that flows through the pipeline
(intake -> OCR -> LLM). The frozen contract here is load-bearing for the
asyncio.Lock-based concurrency model described in docs/plan.md §3.5: jobs
are read by multiple workers, so they must not be mutable across stages.
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from extraction_service.domain.job import ContractJob


def test_contract_job_constructs_with_required_fields() -> None:
    contract_id = uuid4()
    job = ContractJob(
        contract_id=contract_id,
        pdf_bytes=b"%PDF-1.4 fake",
        metadata={"source": "orchestrator"},
    )

    assert job.contract_id == contract_id
    assert isinstance(job.contract_id, UUID)
    assert job.pdf_bytes == b"%PDF-1.4 fake"
    assert job.metadata == {"source": "orchestrator"}


def test_contract_job_metadata_defaults_to_empty_dict() -> None:
    job = ContractJob(
        contract_id=uuid4(),
        pdf_bytes=b"%PDF-1.4",
    )

    assert job.metadata == {}


def test_contract_job_is_frozen() -> None:
    job = ContractJob(
        contract_id=uuid4(),
        pdf_bytes=b"%PDF-1.4",
    )

    with pytest.raises(ValidationError):
        job.pdf_bytes = b"replaced"  # type: ignore[misc]


def test_contract_job_round_trips_through_model_dump_json() -> None:
    original = ContractJob(
        contract_id=uuid4(),
        pdf_bytes=b"%PDF-1.4 sample bytes",
        metadata={"client": "acme", "priority": 1},
    )

    payload = original.model_dump_json()
    restored = ContractJob.model_validate_json(payload)

    assert restored == original
