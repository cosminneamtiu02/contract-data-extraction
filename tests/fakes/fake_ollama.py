"""FakeOllamaClient — configurable in-process stand-in for ollama.AsyncClient.

Phase 3 test helper. Later phases consume it as follows:

- **Phase 4 pipeline tests** construct ``FakeOllamaClient(content='{"k":"v"}')``
  to drive the pipeline worker through a specific LLM output without requiring
  a running Ollama process.
- **Phase 5 FastAPI dependency overrides** inject ``FakeOllamaClient()`` via
  ``app.dependency_overrides`` to bypass real LLM calls during HTTP-layer tests.

``FakeOllamaClient`` does NOT subclass ``ollama.AsyncClient`` — it satisfies
the ``_ChatClientProtocol`` in ``extraction_service.llm.client`` structurally
(duck typing). This avoids importing the concrete Ollama client in test fakes
and makes the fake independent of the real library's class hierarchy.

``FakeChatMessage`` and ``FakeChatResponse`` are frozen Pydantic value objects
(project convention for value objects) that mirror the attribute-access shape
of ``ollama.types.ChatResponse``:  ``response.message.content`` (NOT dict-key
access — changed in ollama 0.4→0.5).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class FakeChatMessage(BaseModel, frozen=True):
    """Minimal stand-in for ``ollama.types.Message``.

    Only ``content`` is modelled because that is the single attribute
    ``OllamaLlmClient.extract`` reads. Additional fields (``role``,
    ``tool_calls``, etc.) are intentionally absent — adding them when
    a future task needs them keeps the fake minimal and drift-free.
    """

    content: str


class FakeChatResponse(BaseModel, frozen=True):
    """Minimal stand-in for ``ollama.types.ChatResponse``.

    Exposes ``.message`` as a ``FakeChatMessage`` so callers access
    ``response.message.content`` via attribute lookup — matching the
    real library's post-0.5 API.
    """

    message: FakeChatMessage


class FakeOllamaClient:
    """Configurable stand-in for the subset of ``ollama.AsyncClient`` we use.

    Ignores unknown keyword arguments to ``.chat()`` so the fake stays stable
    as ``OllamaLlmClient`` adds new options in later tasks (3.5/3.6/3.7).
    Records the most-recent call in ``last_call`` for test assertions.

    ``content`` defaults to ``'{}'`` (empty JSON object) so the no-argument
    form ``FakeOllamaClient()`` is a valid test seam; callers override only
    the dimension they want to drive (e.g., ``FakeOllamaClient(content='...')``)
    to exercise specific JSON parsing / schema validation paths.
    """

    def __init__(self, content: str = "{}", raise_exc: Exception | None = None) -> None:
        """Configure what this fake returns (or raises) from ``.chat()``.

        Parameters
        ----------
        content:
            Raw string that will be placed in ``response.message.content``.
            Must be valid JSON if the caller intends ``OllamaLlmClient.extract``
            to succeed (it runs ``json.loads`` on this value).
        raise_exc:
            If non-``None``, ``.chat()`` records the call arguments and then
            raises this exception instead of returning a response. Lets tests
            drive error-path branches (e.g. ``ollama.ResponseError`` with
            ``status_code=400`` for task-3.5 context-overflow detection).
        """
        self._content = content
        self._raise_exc = raise_exc
        self.last_call: dict[str, Any] = {}

    async def chat(
        self,
        *,
        model: str = "",
        messages: list[dict[str, str]] | None = None,
        format: dict[str, Any] | None = None,  # noqa: A002  -- mirrors ollama SDK param name
        options: dict[str, Any] | None = None,
        **_extras: object,  # forward-compat: tasks 3.6/3.7 add keep_alive, stream, etc.
    ) -> FakeChatResponse:
        """Record the call arguments and return (or raise) per configuration.

        Known parameters (model, messages, format, options) are captured into
        ``last_call`` for test assertions BEFORE the optional raise, so tests
        can verify the wrapper still attempted the call when an exception is
        configured. Extra keyword arguments are silently dropped via
        ``**_extras: object`` so the fake remains stable as ``OllamaLlmClient``
        adds new options in tasks 3.6/3.7 without requiring fake updates each
        time.
        """
        self.last_call = {
            "model": model,
            "messages": messages if messages is not None else [],
            "format": format if format is not None else {},
            "options": options if options is not None else {},
        }
        if self._raise_exc is not None:
            raise self._raise_exc
        return FakeChatResponse(message=FakeChatMessage(content=self._content))
