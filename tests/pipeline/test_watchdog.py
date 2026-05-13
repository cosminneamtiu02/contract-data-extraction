"""Tests for IdleWatchdog background task (task 4.8).

Each test targets one behaviour, uses small thresholds (20-200ms) to keep the
suite fast, and relies on asyncio_mode = "auto" so no decorator is required.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from extraction_service.pipeline.watchdog import IdleWatchdog


async def test_idle_watchdog_triggers_shutdown_after_threshold() -> None:
    """Plan seed test: threshold 0.1 s, stale timestamp → callback fires."""
    fired = asyncio.Event()

    async def on_idle() -> None:
        fired.set()

    stale = datetime(2000, 1, 1, tzinfo=UTC)  # far in the past
    watchdog = IdleWatchdog(
        threshold=timedelta(milliseconds=100),
        get_last_activity_at=lambda: stale,
        on_idle=on_idle,
        check_interval=timedelta(milliseconds=20),
    )

    await asyncio.wait_for(watchdog.run(), timeout=2.0)

    assert fired.is_set()


async def test_idle_watchdog_fires_callback_when_threshold_exceeded() -> None:
    """Callback fires when last_activity_at is older than the threshold."""
    fired = asyncio.Event()

    async def on_idle() -> None:
        fired.set()

    stale = datetime(2000, 1, 1, tzinfo=UTC)
    watchdog = IdleWatchdog(
        threshold=timedelta(milliseconds=50),
        get_last_activity_at=lambda: stale,
        on_idle=on_idle,
        check_interval=timedelta(milliseconds=20),
    )

    await asyncio.wait_for(watchdog.run(), timeout=2.0)

    assert fired.is_set()


async def test_idle_watchdog_does_not_fire_when_recent_activity() -> None:
    """Callback does NOT fire when last_activity_at is always fresh."""
    fired = asyncio.Event()

    async def on_idle() -> None:
        fired.set()

    # always returns the current time — never idle
    watchdog = IdleWatchdog(
        threshold=timedelta(milliseconds=200),
        get_last_activity_at=lambda: datetime.now(UTC),
        on_idle=on_idle,
        check_interval=timedelta(milliseconds=20),
    )

    task = asyncio.create_task(watchdog.run())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not fired.is_set()


async def test_idle_watchdog_fires_only_once_then_returns() -> None:
    """After on_idle fires, run() returns and the callback is not called again."""
    call_count = 0

    async def on_idle() -> None:
        nonlocal call_count
        call_count += 1

    stale = datetime(2000, 1, 1, tzinfo=UTC)
    watchdog = IdleWatchdog(
        threshold=timedelta(milliseconds=50),
        get_last_activity_at=lambda: stale,
        on_idle=on_idle,
        check_interval=timedelta(milliseconds=20),
    )

    task = asyncio.create_task(watchdog.run())
    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)

    # Give a little extra time to confirm it does NOT fire a second time.
    await asyncio.sleep(0.1)

    assert call_count == 1
    assert task.done()


async def test_idle_watchdog_resets_after_activity_then_fires_when_idle_again() -> None:
    """Callback fires only after activity becomes stale, not during fresh polls."""
    fired = asyncio.Event()
    call_count = 0

    async def on_idle() -> None:
        nonlocal call_count
        call_count += 1
        fired.set()

    # First 3 calls return "now" (fresh); subsequent calls return stale time.
    poll_count = 0

    def get_last_activity() -> datetime:
        nonlocal poll_count
        poll_count += 1
        if poll_count <= 3:
            return datetime.now(UTC)
        return datetime(2000, 1, 1, tzinfo=UTC)

    watchdog = IdleWatchdog(
        threshold=timedelta(milliseconds=50),
        get_last_activity_at=get_last_activity,
        on_idle=on_idle,
        check_interval=timedelta(milliseconds=20),
    )

    await asyncio.wait_for(watchdog.run(), timeout=2.0)

    # Callback fired exactly once, only after staleness began.
    assert call_count == 1
    assert fired.is_set()


async def test_idle_watchdog_propagates_cancellation() -> None:
    """CancelledError raised on the task propagates to the awaiter."""
    fired = asyncio.Event()

    async def on_idle() -> None:
        fired.set()

    # Fresh activity — watchdog will never fire on its own.
    watchdog = IdleWatchdog(
        threshold=timedelta(milliseconds=200),
        get_last_activity_at=lambda: datetime.now(UTC),
        on_idle=on_idle,
        check_interval=timedelta(milliseconds=20),
    )

    task = asyncio.create_task(watchdog.run())
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
