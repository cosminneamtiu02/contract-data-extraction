"""Project-wide pytest fixtures.

The autouse ``_reset_structlog_state`` fixture below addresses a real
test-isolation hazard surfaced by the Phase 1 panel review (convergent
finding from Lens 14 "Pytest infrastructure" and Lens 16 "Test isolation
& determinism"):

- ``extraction_service.log_config.configure_logging`` mutates the
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

import os
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


# Promoted from tests/unit/test_settings.py during the Phase 1 panel re-run
# (Lens 14 + Lens 16 convergent finding): isolating EXTRACTION_* env vars is a
# project-wide concern, not a Settings-specific one. Future tests that
# construct Settings (Phase 5 app startup) can request `isolated_env` directly.
_EXTRACTION_ENV_PREFIX = "EXTRACTION_"


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Clears every ``EXTRACTION_*`` env var at test entry; monkeypatch auto-
    restores at exit. Scans ``os.environ`` dynamically rather than holding a
    static name list, so a Phase 5+ Settings field addition auto-extends the
    clear set without conftest maintenance."""
    for var in [k for k in os.environ if k.startswith(_EXTRACTION_ENV_PREFIX)]:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch
