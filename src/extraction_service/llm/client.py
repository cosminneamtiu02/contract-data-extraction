"""Thin async wrapper around ``ollama.AsyncClient`` (plan §6.5 task 3.1).

``OllamaLlmClient`` is the single entry point for LLM inference in this
service. It exposes one method — ``extract`` — and is intentionally thin:
it delegates JSON-mode enforcement to Ollama (via ``format=schema``) and
leaves schema *validation* to the downstream task-3.3 validator.

Constructor injection is the test seam (mirrors the OCR pattern):
  - Production code: ``OllamaLlmClient(client=ollama.AsyncClient(), model=...)``
  - Tests: ``OllamaLlmClient(client=FakeOllamaClient(...), model=...)``

Design constraints preserved for later tasks:
  - ``model`` is a constructor argument so task-3.5 (context overflow with
    fallback model) can reconfigure without touching ``extract``.
  - ``extract`` returns ``dict[str, Any]`` — the IO-boundary type — so
    task-3.3 (jsonschema validation) can wrap or augment without a signature
    change.
  - No ``system`` role message: Gemma does not support the system role;
    the prompt is passed as a single user-role message only.

Tasks 3.5 (context overflow), 3.6 (dev-mode debug capture), and 3.7
(asyncio.wait_for timeout) extend this file in later commits.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable


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
        instance attribute so task-3.5 context-overflow handling can
        override it per-call without mutating the shared client.
    """

    def __init__(self, client: _ChatClientProtocol, model: str) -> None:
        self._client = client
        self._model = model

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
            JSON Schema dict (produced by ``ContractRecord.model_json_schema()``
            in task-3.3). Passed verbatim as ``format`` to Ollama so the model
            enforces schema-shaped output before we receive it.

        Returns
        -------
        dict[str, Any]:
            Parsed JSON from ``response.message.content``. At this layer the
            dict is unvalidated; task-3.3 runs ``jsonschema.validate`` on it.

        Raises
        ------
        json.JSONDecodeError:
            If Ollama returns content that is not valid JSON despite
            ``format`` enforcement (e.g. model truncation mid-token).
        """
        response = await self._client.chat(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            format=schema,
            options={"temperature": 0},
        )
        # Access via attribute, NOT dict key — this changed in ollama 0.4→0.5.
        content: str = response.message.content
        result: dict[str, Any] = json.loads(content)
        return result
