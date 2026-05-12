"""Domain layer — value objects, the state machine, and the exception hierarchy.

Most types here are frozen value objects (``ContractJob``, ``StageRecord``,
``StageError``). ``ContractRecord`` is the one intentionally-mutable container
that workers reassign per stage under the asyncio.Lock of docs/plan.md §3.5.

Phase 1 lives entirely in this package and `extraction_service.config` /
`settings.py` / `log_config.py`. No I/O, no async, no third-party services —
just the types every later phase will depend on. See docs/plan.md §6.3.
"""
