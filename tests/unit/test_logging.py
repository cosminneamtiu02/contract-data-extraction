"""Unit tests for structlog configuration (Task 1.9).

``configure_logging(mode, stream=...)`` installs the structlog processor chain.
The mode flag chooses the renderer — JSON for production (machine-readable
log shipping), pretty ConsoleRenderer (no ANSI colors) for development.

The optional ``stream`` parameter is for testability: tests inject an
``io.StringIO`` to capture the rendered output. Production callers pass
nothing and get ``sys.stdout`` per docs/plan.md §4.8.
"""

import io
import json

import structlog

from extraction_service.logging import configure_logging


def test_configure_logging_production_emits_json_with_event_and_kwargs() -> None:
    buf = io.StringIO()
    configure_logging("production", stream=buf)

    log = structlog.get_logger()
    log.info("ocr_done", contract_id="abc-123", duration_ms=1500)

    payload = json.loads(buf.getvalue().strip())
    assert payload["event"] == "ocr_done"
    assert payload["contract_id"] == "abc-123"
    assert payload["duration_ms"] == 1500
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_configure_logging_production_serializes_subsequent_events_one_per_line() -> None:
    buf = io.StringIO()
    configure_logging("production", stream=buf)

    log = structlog.get_logger()
    log.info("first")
    log.info("second")

    lines = [line for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "first"
    assert json.loads(lines[1])["event"] == "second"


def test_configure_logging_dev_emits_human_readable_not_json() -> None:
    buf = io.StringIO()
    configure_logging("development", stream=buf)

    log = structlog.get_logger()
    log.info("ocr_done", contract_id="abc-123")

    output = buf.getvalue()
    assert "ocr_done" in output
    assert "abc-123" in output
    # Dev renderer is human-readable; production JSON would start with '{'.
    assert not output.lstrip().startswith("{")


def test_configure_logging_carries_contextvars_into_log_events() -> None:
    # The autouse ``_reset_structlog_state`` fixture in conftest.py guarantees
    # contextvars are clear at test entry and exit, so this test can bind
    # without try/finally cleanup.
    buf = io.StringIO()
    configure_logging("production", stream=buf)

    structlog.contextvars.bind_contextvars(contract_id="ctx-xyz", stage="ocr")

    log = structlog.get_logger()
    log.info("stage_start")

    payload = json.loads(buf.getvalue().strip())
    assert payload["contract_id"] == "ctx-xyz"
    assert payload["stage"] == "ocr"
