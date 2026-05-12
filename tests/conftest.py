"""Project-wide pytest fixtures.

The autouse ``_reset_structlog_state`` fixture below addresses a real
test-isolation hazard surfaced by the Phase 1 panel review (convergent
finding from Lens 14 "Pytest infrastructure" and Lens 16 "Test isolation
& determinism"):

- ``extraction_service.logging.configure_logging`` mutates the
  module-level structlog configuration. Without an autouse reset, the
  renderer / stream from one test leaks into the next.
- ``structlog.contextvars.bind_contextvars`` writes to a global
  ContextVar store. If a test fails before its inline cleanup runs,
  bound keys (``contract_id``, ``stage``) appear in unrelated tests'
  log output and silently corrupt assertions.

The fixture runs at function scope before AND after each test (yield),
so it tolerates both forward-leaks (prior test left state) and
backward-leaks (current test raised before its own cleanup).
"""

from collections.abc import Iterator

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog_state() -> Iterator[None]:
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
