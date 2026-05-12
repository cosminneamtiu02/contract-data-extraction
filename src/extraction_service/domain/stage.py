"""Stage state machine for the contract pipeline.

The pipeline has three stages (intake, OCR, data parsing). Each stage carries
a ``StageState`` plus timing and optional error metadata in a ``StageRecord``.
``ContractRecord.overall_status`` is derived from the three stage states per
the table in docs/plan.md §3.3.

Using ``StrEnum`` (Python 3.11+) rather than the older ``class X(str, Enum)``
form makes ``str()`` and f-string interpolation return the plain value, which
keeps log lines and JSON-coerced output clean for structlog (§4.8).
"""

from enum import StrEnum


class StageState(StrEnum):
    """Lifecycle states for a single pipeline stage."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
