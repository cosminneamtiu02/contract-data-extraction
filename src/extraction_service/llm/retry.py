"""LLM-stage retry policy (plan §6.5 task 3.4).

Provides :func:`retry_extraction`, a generic async wrapper that retries a
zero-arg async callable on :class:`~extraction_service.domain.errors.ExtractionError`
subclasses whose ``.code`` appears in the caller-supplied ``retry_on`` list.

No backoff or sleep between retries -- bare retry semantics per the spec.
Backoff, if needed, belongs in a follow-up task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from extraction_service.domain.errors import ExtractionError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

__all__ = ["retry_extraction"]


async def retry_extraction[T](
    extract_fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    retry_on: Sequence[str],
) -> T:
    """Call *extract_fn* and retry on retriable :class:`ExtractionError` codes.

    Parameters
    ----------
    extract_fn:
        A zero-argument async callable to invoke. May be called up to
        ``max_retries + 1`` times.
    max_retries:
        Number of retries **after** the first attempt.  Must be ``>= 0``.
        ``max_retries=0`` means "try once; do not retry."
    retry_on:
        Sequence of :attr:`ExtractionError.code` strings that qualify for
        retry.  Any other exception (including ``ExtractionError`` subclasses
        whose code is absent from this list) re-raises immediately.

    Returns
    -------
    T
        The value returned by *extract_fn* on the first successful call.

    Raises
    ------
    ValueError
        If *max_retries* is negative (config-validation defence-in-depth;
        :class:`~extraction_service.config.run_config.RetryConfig` is the
        primary validation point).
    ExtractionError
        The last caught retriable error once all retries are exhausted, or
        any non-retriable ``ExtractionError`` immediately.
    Exception
        Any non-``ExtractionError`` exception re-raises immediately.
    """
    if max_retries < 0:
        msg = f"max_retries must be >= 0, got {max_retries}"
        raise ValueError(msg)

    exc_bucket: list[ExtractionError] = []

    for _ in range(max_retries + 1):
        try:
            return await extract_fn()
        except ExtractionError as exc:
            if exc.code not in retry_on:
                raise
            exc_bucket.append(exc)

    # exc_bucket is non-empty: the loop ran at least once and only reaches
    # here after catching a retriable error on every attempt.
    raise exc_bucket[-1]
