"""Thin async wrapper around ``ollama.AsyncClient`` (plan §6.5 tasks 3.1-3.7).

``OllamaLlmClient`` is the single entry point for LLM inference in this
service. It exposes one method — ``extract`` — and is intentionally thin:
it delegates JSON-mode enforcement to Ollama (via ``format=schema``) and
leaves schema *validation* to the downstream task-3.3 validator.

Constructor injection is the test seam (mirrors the OCR pattern):
  - Production code: ``OllamaLlmClient(client=ollama.AsyncClient(), model=...)``
  - Tests: ``OllamaLlmClient(client=FakeOllamaClient(...), model=...)``

Design constraints:
  - ``model`` is a constructor argument so future context-overflow
    fallback paths can reconfigure without touching ``extract``.
  - ``extract`` returns ``dict[str, Any]`` — the IO-boundary type — so
    task-3.3 (jsonschema validation) can wrap or augment without a signature
    change.
  - No ``system`` role message: Gemma does not support the system role;
    the prompt is passed as a single user-role message only.

Per-task additions in this module:
  - 3.5: HTTP 400 from Ollama whose error message indicates context-window
    exhaustion is mapped to the domain-layer ``ContextOverflowError``.
  - 3.6: when constructed with ``mode='development'``, a ``_debug`` top-level
    key with the raw request and response payloads is attached to the
    returned dict (the underscore prefix marks it as side-channel metadata
    so downstream schema validation can strip it before delegating to
    ``jsonschema``).
  - 3.7: when ``timeout_seconds`` is set, the chat call is wrapped in
    ``asyncio.wait_for``; the resulting ``TimeoutError`` is mapped to the
    domain-layer ``LlmError`` (whose ``.code`` is ``"llm_failed"``, which
    is retry-eligible per the default ``RetryConfig``).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal, Protocol, runtime_checkable

from ollama import ResponseError

from extraction_service.domain.errors import ContextOverflowError, LlmError

ClientMode = Literal["development", "production"]


class _ChatResponse(Protocol):
    """Minimal structural protocol for the ChatResponse-like return value.

    Only the ``message.content`` attribute path is modelled — that is the
    sole field ``OllamaLlmClient.extract`` reads. Using a Protocol here
    avoids importing ``ollama.types`` at module load time.
    """

    @property
    def message(self) -> _ChatMessage: ...


class _ChatMessage(Protocol):
    """Protocol for the nested message object in a ChatResponse."""

    @property
    def content(self) -> str: ...


@runtime_checkable
class _ChatClientProtocol(Protocol):
    """Structural protocol for the subset of ``ollama.AsyncClient`` we use.

    Keeping a narrow protocol (just ``.chat``) avoids importing the concrete
    ``ollama.AsyncClient`` at module level, which would force a real Ollama
    installation to import this module. The production wiring in Phase 4
    passes an actual ``ollama.AsyncClient`` instance; tests pass
    ``FakeOllamaClient``, which satisfies this protocol structurally.

    ``format`` shadows the Python builtin intentionally — it mirrors the
    parameter name in the ``ollama`` library's public API exactly.
    """

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        format: dict[str, Any],  # noqa: A002  -- name matches ollama SDK public API
        options: dict[str, Any],
    ) -> _ChatResponse:
        """Send a chat request and return a ChatResponse-like object."""
        ...


class OllamaLlmClient:
    """Async wrapper around an Ollama chat client for JSON extraction.

    Parameters
    ----------
    client:
        An ``ollama.AsyncClient`` instance (or any structural conformer of
        ``_ChatClientProtocol``). Injected so tests can pass ``FakeOllamaClient``
        without a running Ollama process.
    model:
        Ollama model tag to use (e.g. ``"gemma3:4b"``). Stored as an
        instance attribute so a future context-overflow fallback path can
        override it per-call without mutating the shared client.
    mode:
        ``"development"`` attaches a ``_debug`` block (raw request +
        raw response content) to every successful ``extract`` result;
        ``"production"`` (default) returns the parsed JSON dict only.
        Mirrors the ``Settings.mode`` literal in
        ``extraction_service.settings`` so the Phase 4 pipeline can
        forward the process-level mode verbatim.
    timeout_seconds:
        If set, the chat call is wrapped in ``asyncio.wait_for`` and a
        timeout raises ``LlmError``. ``None`` (default) means no wrapper —
        the chat call runs unbounded. Phase 4 worker code passes the
        ``LlmConfig.timeout_seconds`` value (default 60s) per
        ``config/run_config.py``.
    """

    def __init__(
        self,
        client: _ChatClientProtocol,
        model: str,
        mode: ClientMode = "production",
        timeout_seconds: float | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._mode = mode
        self._timeout_seconds = timeout_seconds

    async def extract(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a single-turn chat to Ollama and return the parsed JSON dict.

        Parameters
        ----------
        prompt:
            The full extraction prompt (built by task-3.2 ``prompt.py``).
            Passed as a user-role message — Gemma does not support ``system``.
        schema:
            User-supplied JSON Schema dict describing the target structure —
            loaded at startup by ``load_domain_model`` in
            ``extraction_service.config.domain_model`` (Phase 1 task 1.8).
            Passed verbatim as ``format`` to Ollama so the model enforces
            schema-shaped output before we receive it. Task-3.3
            (``validate_extracted_data``) re-validates the parsed dict via
            ``jsonschema.validate`` downstream — the wrapper is intentionally
            schema-agnostic.

        Returns
        -------
        dict[str, Any]:
            Parsed JSON from ``response.message.content``. At this layer the
            dict is unvalidated; task-3.3 runs ``jsonschema.validate`` on it.

        Raises
        ------
        ContextOverflowError:
            If Ollama signals that the rendered prompt exceeded the model's
            context window (HTTP 400 + an error message that mentions
            "context" plus one of "length", "window", "exceed"). Mapping to
            the domain-layer exception lets upstream code distinguish
            overflow from generic LLM failure modes.
        ollama.ResponseError:
            Any other Ollama-side error (e.g. malformed request, server
            error) re-raised unchanged. Tasks 3.6 (dev-mode debug capture)
            and 3.7 (timeout) extend this method but do not remap
            non-overflow ``ResponseError`` — it stays intentionally
            transparent so callers can distinguish overflow / timeout /
            other failure modes by exception class.
        json.JSONDecodeError:
            If Ollama returns content that is not valid JSON despite
            ``format`` enforcement (e.g. model truncation mid-token).
        """
        chat_coro = self._client.chat(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            format=schema,
            options={"temperature": 0},
        )
        try:
            if self._timeout_seconds is None:
                response = await chat_coro
            else:
                response = await asyncio.wait_for(chat_coro, timeout=self._timeout_seconds)
        except TimeoutError as e:
            msg = f"Ollama call timed out after {self._timeout_seconds}s"
            raise LlmError(msg) from e
        except ResponseError as e:
            if e.status_code == _HTTP_BAD_REQUEST and _is_context_overflow_error(e.error):
                # `e.error` is Ollama-server text (not caller-supplied input) —
                # safe to embed verbatim in the domain-exception message for
                # internal logging; not intended to surface to HTTP responses.
                msg = f"Ollama context overflow: {e.error}"
                raise ContextOverflowError(msg) from e
            raise
        # Access via attribute, NOT dict key — this changed in ollama 0.4→0.5.
        content: str = response.message.content
        result: dict[str, Any] = json.loads(content)
        if self._mode == "development":
            # PII WARNING: `prompt` carries the full rendered OCR text of a
            # contract — likely contains party names, addresses, tax IDs,
            # bank details. Callers MUST strip the `_debug` key before
            # logging or HTTP-serializing the result (e.g.
            # `data.pop("_debug", None)` in the Phase 4 worker). Phase 5
            # HTTP response shaping owns the final-serialization defense;
            # see docs/superpowers/specs/2026-05-13-phase-3-llm-spec-deviations.md
            # §17.2 item 4 for the re-evaluation point.
            result["_debug"] = {
                "request": {
                    "model": self._model,
                    "prompt": prompt,
                    "schema": schema,
                },
                "response_content": content,
            }
        return result


_HTTP_BAD_REQUEST = 400
_OVERFLOW_KEYWORDS = ("length", "window", "exceed")


def _is_context_overflow_error(error_message: str) -> bool:
    """Heuristic check for Ollama context-overflow error messages.

    Ollama signals context overflow with HTTP 400 and an error message
    containing the word "context" together with one of the standard
    overflow indicators ("length", "window", "exceed"). Observed in the
    wild:

      - "model context length 2048 exceeded by 500 tokens"
      - "input exceeds context window"
      - "context length exceeded"

    Not all 400s are context overflow (e.g. malformed JSON requests or
    invalid model names), so we require both signals before mapping to
    ``ContextOverflowError``.
    """
    lower = error_message.lower()
    return "context" in lower and any(keyword in lower for keyword in _OVERFLOW_KEYWORDS)
