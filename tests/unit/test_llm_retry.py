"""Tests for the LLM-stage retry policy (plan §6.5 task 3.4).

Covers ``retry_extraction(extract_fn, *, max_retries, retry_on)``:
- Retries only on ExtractionError subclasses whose .code is in retry_on.
- max_retries is the number of retries AFTER the first attempt.
- Non-retriable exceptions re-raise immediately.
- Negative max_retries raises ValueError before attempting the call.
"""

from __future__ import annotations

import pytest

from extraction_service.domain.errors import (
    ExtractionError,
    LlmError,
    SchemaInvalidError,
)
from extraction_service.llm.retry import retry_extraction

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _CountingCallable:
    """Zero-arg async callable that records calls and raises/returns on schedule.

    ``failures`` is a sequence of exceptions to raise on successive calls.
    Once all failures are exhausted the callable returns ``result``.
    """

    def __init__(
        self,
        failures: list[Exception],
        result: object = "ok",
    ) -> None:
        self._failures = list(failures)
        self._result = result
        self.call_count = 0

    async def __call__(self) -> object:
        self.call_count += 1
        if self._failures:
            raise self._failures.pop(0)
        return self._result


# ---------------------------------------------------------------------------
# Spec-named tests (mandatory)
# ---------------------------------------------------------------------------


async def test_retry_on_listed_error_codes_until_max() -> None:
    """Retries up to max_retries times on an error code in retry_on."""
    err = LlmError("transient")
    fn = _CountingCallable(failures=[err, err], result="done")

    result = await retry_extraction(fn, max_retries=2, retry_on=[LlmError.code])

    assert result == "done"


async def test_does_not_retry_on_unlisted_codes() -> None:
    """Does not retry when the error code is absent from retry_on."""
    err = LlmError("non-retriable")
    fn = _CountingCallable(failures=[err])

    with pytest.raises(LlmError):
        await retry_extraction(fn, max_retries=3, retry_on=["some_other_code"])

    assert fn.call_count == 1


# ---------------------------------------------------------------------------
# Companion tests
# ---------------------------------------------------------------------------


async def test_retry_extraction_returns_first_success_with_no_retries_needed() -> None:
    """Returns the result immediately when the first call succeeds."""
    fn = _CountingCallable(failures=[], result="first")

    result = await retry_extraction(fn, max_retries=3, retry_on=[LlmError.code])

    assert result == "first"


async def test_retry_extraction_returns_success_after_one_retry() -> None:
    """Returns the result after one retriable failure then success."""
    err = LlmError("retry once")
    fn = _CountingCallable(failures=[err], result="second")

    result = await retry_extraction(fn, max_retries=2, retry_on=[LlmError.code])

    assert result == "second"


async def test_retry_extraction_raises_last_exception_after_max_retries_exhausted() -> None:
    """Re-raises the last caught exception once all retries are used up."""
    err = SchemaInvalidError("bad json")
    fn = _CountingCallable(failures=[err, err, err])

    with pytest.raises(SchemaInvalidError):
        await retry_extraction(fn, max_retries=2, retry_on=[SchemaInvalidError.code])


async def test_retry_extraction_does_not_retry_on_non_extraction_error() -> None:
    """Non-ExtractionError exceptions re-raise immediately without retries."""
    err = RuntimeError("unexpected")
    fn = _CountingCallable(failures=[err])

    with pytest.raises(RuntimeError):
        await retry_extraction(fn, max_retries=3, retry_on=[LlmError.code])

    assert fn.call_count == 1


async def test_retry_extraction_rejects_negative_max_retries() -> None:
    """Raises ValueError for a negative max_retries without attempting the call."""
    fn = _CountingCallable(failures=[])

    with pytest.raises(ValueError, match="max_retries"):
        await retry_extraction(fn, max_retries=-1, retry_on=[LlmError.code])

    assert fn.call_count == 0


async def test_retry_extraction_attempt_count_for_max_retries_zero() -> None:
    """max_retries=0 results in exactly one attempt (no retries)."""
    err = LlmError("fails always")
    fn = _CountingCallable(failures=[err])

    with pytest.raises(LlmError):
        await retry_extraction(fn, max_retries=0, retry_on=[LlmError.code])

    assert fn.call_count == 1


async def test_retry_extraction_attempt_count_for_max_retries_two_with_persistent_failure() -> None:
    """max_retries=2 results in exactly 3 total attempts before raising."""
    err = LlmError("always fails")
    fn = _CountingCallable(failures=[err, err, err])

    with pytest.raises(LlmError):
        await retry_extraction(fn, max_retries=2, retry_on=[LlmError.code])

    assert fn.call_count == 3


async def test_retry_extraction_only_retries_matching_code_not_all_extraction_errors() -> None:
    """An ExtractionError subclass whose code is NOT in retry_on re-raises immediately."""
    err = ExtractionError("base error")
    fn = _CountingCallable(failures=[err])

    with pytest.raises(ExtractionError):
        await retry_extraction(fn, max_retries=5, retry_on=[LlmError.code])

    assert fn.call_count == 1
