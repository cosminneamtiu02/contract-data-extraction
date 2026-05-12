"""Unit tests for ContractJob domain model.

ContractJob is the immutable value object that flows through the pipeline
(intake -> OCR -> LLM). The frozen contract here is load-bearing for the
asyncio.Lock-based concurrency model described in docs/plan.md §3.5: jobs
are read by multiple workers, so they must not be mutable across stages.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from extraction_service.domain.job import ContractJob


def test_contract_job_stores_contract_id() -> None:
    contract_id = uuid4()
    job = ContractJob(
        contract_id=contract_id,
        pdf_bytes=b"%PDF-1.4 fake",
        metadata={"source": "orchestrator"},
    )

    assert job.contract_id == contract_id


def test_contract_job_stores_pdf_bytes() -> None:
    job = ContractJob(
        contract_id=uuid4(),
        pdf_bytes=b"%PDF-1.4 fake",
        metadata={"source": "orchestrator"},
    )

    assert job.pdf_bytes == b"%PDF-1.4 fake"


def test_contract_job_stores_metadata() -> None:
    job = ContractJob(
        contract_id=uuid4(),
        pdf_bytes=b"%PDF-1.4 fake",
        metadata={"source": "orchestrator"},
    )

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
        job.pdf_bytes = b"replaced"  # type: ignore[misc]  # intentional frozen-model mutation to verify ValidationError fires.


def test_contract_job_round_trips_through_model_dump_json() -> None:
    original = ContractJob(
        contract_id=uuid4(),
        pdf_bytes=b"%PDF-1.4 sample bytes",
        metadata={"client": "acme", "priority": 1},
    )

    payload = original.model_dump_json()
    restored = ContractJob.model_validate_json(payload)

    assert restored == original


def test_contract_job_raises_when_both_required_fields_missing() -> None:
    """Phase 5's HTTP intake handler constructs ContractJob from untrusted
    request payloads — fully-empty input must be rejected before the
    pipeline sees it."""
    with pytest.raises(ValidationError):
        ContractJob()  # type: ignore[call-arg]  # intentionally omits BOTH required fields to verify required-field rejection.


def test_contract_job_raises_when_pdf_bytes_missing() -> None:
    with pytest.raises(ValidationError):
        ContractJob(contract_id=uuid4())  # type: ignore[call-arg]  # intentionally missing pdf_bytes to verify required-field rejection.


def test_contract_job_raises_when_contract_id_missing() -> None:
    with pytest.raises(ValidationError):
        ContractJob(pdf_bytes=b"%PDF-1.4")  # type: ignore[call-arg]  # intentionally missing contract_id to verify required-field rejection.
