"""Domain layer — immutable value objects and the exception hierarchy.

Phase 1 lives entirely in this package and `extraction_service.config` /
`settings.py` / `logging.py`. No I/O, no async, no third-party services —
just the types every later phase will depend on. See docs/plan.md §6.3.
"""
