"""Structlog configuration for the extraction service.

``configure_logging(mode)`` is called once during app lifespan startup (Phase 5).
Mode chooses the renderer:

- ``production`` -> JSON (machine-readable, one event per line; log shippers
  parse the timestamp/level/event fields directly).
- ``development`` -> pretty ConsoleRenderer without ANSI colors so the output
  is also tail-friendly in CI logs and editor terminals.

Per docs/plan.md §4.8, workers bind ``contract_id`` and ``stage`` into
contextvars at the top of each iteration so every downstream log carries them.
The processor chain includes ``merge_contextvars`` for that.

The ``stream`` parameter is a testability hook: production passes nothing and
gets ``sys.stdout``; tests inject ``io.StringIO`` to capture rendered output.
"""

import logging
import sys
from typing import Literal, TextIO

import structlog


def configure_logging(
    mode: Literal["development", "production"],
    *,
    stream: TextIO | None = None,
) -> None:
    """Install the structlog processor chain for the chosen mode."""
    output = stream if stream is not None else sys.stdout

    renderer: structlog.typing.Processor
    match mode:
        case "production":
            renderer = structlog.processors.JSONRenderer()
        case "development":
            renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=output),
        cache_logger_on_first_use=False,
    )
