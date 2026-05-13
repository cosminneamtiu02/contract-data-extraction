"""Domain layer — value objects, the state machine, and the exception hierarchy.

Concrete *model* types (``ContractJob``, ``StageRecord``, ``StageError``,
``ContractRecord``, and the exception classes) are defined in their submodules
and accessed via deep import only (e.g.
``from extraction_service.domain.stage import StageError``); they are NOT
re-exported at this package boundary. The Literal aliases ``OverallStatus``
and ``StageName`` ARE re-exported (and listed in ``__all__``) for Phase 5's
HTTP response models — see record.py for the re-export rationale.

``ContractRecord`` is the one intentionally-mutable container; workers reassign
per stage under the asyncio.Lock of docs/plan.md §3.5. All other types here are
frozen value objects.

Phase 1 lives entirely in this package and `extraction_service.config` /
`settings.py` / `log_config.py`. No I/O, no async, no third-party services —
just the types every later phase will depend on. See docs/plan.md §6.3.
"""

# Re-exported for the Phase 5 HTTP response models per the comment in
# record.py — exposes them at the sub-package boundary so callers can
# write `from extraction_service.domain import OverallStatus` rather
# than the deep `extraction_service.domain.record` import path.
from extraction_service.domain.record import OverallStatus as OverallStatus
from extraction_service.domain.record import StageName as StageName

__all__ = ["OverallStatus", "StageName"]
