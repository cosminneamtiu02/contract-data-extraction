"""Idle watchdog for the extraction pipeline (task 4.8).

WHY this exists: the service runs on a Mac Mini M4 with 16 GB RAM and is
started as an HTTP process.  When no contracts have been submitted for
``threshold`` seconds the process should shut itself down to reclaim memory
and avoid stale-state issues after long idle periods (plan §1).  The
threshold is injected so development runs can use short values (seconds)
while production runs use longer ones (minutes), with no code change.

The watchdog is deliberately self-contained: it receives a
``get_last_activity_at`` *callable* rather than a direct reference to any
state object.  This keeps it decoupled from ``PipelineState``; Phase 5 will
wire it with a closure over whatever tracks HTTP-request activity.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class IdleWatchdog:
    """Background task that triggers a shutdown callback when the service is idle.

    Args:
        threshold: How long elapsed since the last activity before ``on_idle``
            is invoked.
        get_last_activity_at: Zero-argument callable that returns the timestamp
            of the most recent activity.  Called on every check cycle.
        on_idle: Async callable invoked exactly once when the threshold is
            exceeded.  The watchdog returns immediately after awaiting it.
        check_interval: How often the watchdog polls.  Defaults to 50 ms —
            fine-grained enough for sub-second thresholds in tests; deployments
            can leave this at the default or override to reduce CPU wakeups.
    """

    def __init__(
        self,
        *,
        threshold: timedelta,
        get_last_activity_at: Callable[[], datetime],
        on_idle: Callable[[], Awaitable[None]],
        check_interval: timedelta = timedelta(milliseconds=50),
    ) -> None:
        self._threshold = threshold
        self._get_last_activity_at = get_last_activity_at
        self._on_idle = on_idle
        self._check_interval = check_interval

    async def run(self) -> None:
        """Loop every ``check_interval``, fire ``on_idle`` once when idle, then return.

        Propagates ``asyncio.CancelledError`` naturally — there is no
        ``try/except`` wrapping the sleep, so cancellation during a
        ``asyncio.sleep`` call will raise and unwind the coroutine cleanly.
        """
        interval = self._check_interval.total_seconds()

        while True:
            await asyncio.sleep(interval)
            elapsed = datetime.now(UTC) - self._get_last_activity_at()
            if elapsed > self._threshold:
                await self._on_idle()
                return
