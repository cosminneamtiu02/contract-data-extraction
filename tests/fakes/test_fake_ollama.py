"""Tests that pin FakeOllamaClient's contract against its intended behaviour.

The most load-bearing tests verify that:
- ``last_call`` records exactly the keyword arguments passed to ``.chat()``.
- The configured ``content`` string reaches ``.message.content`` on the response.
- Unknown keyword arguments are accepted (forward-compatibility with tasks 3.5-3.7).
- ``FakeChatResponse`` and ``FakeChatMessage`` are frozen (project convention).

``asyncio_mode = "auto"`` in ``pyproject.toml`` covers async without decorators.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_fake_ollama_client_satisfies_chat_client_protocol() -> None:
    """Mirrors the OCR pattern: pin protocol conformance at the runtime-checkable boundary.

    The production ``OllamaLlmClient`` declares ``_ChatClientProtocol`` as
    ``@runtime_checkable``. Without this assertion, a signature drift in
    ``FakeOllamaClient.chat`` (parameter rename, return-type change,
    sync/async flip) would silently break the Phase 4/5 dependency-injection
    seam before those phases exist to catch it. Mirrors
    ``tests/fakes/test_fake_ocr.py::test_fake_ocr_engine_satisfies_ocr_engine_protocol``.
    """
    from extraction_service.llm.client import _ChatClientProtocol
    from tests.fakes.fake_ollama import FakeOllamaClient

    assert isinstance(FakeOllamaClient(), _ChatClientProtocol)


async def test_fake_ollama_client_default_content_is_empty_json() -> None:
    """No-argument form returns a response whose content is an empty JSON object."""
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient()
    response = await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=[], format={}, options={})

    assert response.message.content == "{}"


async def test_fake_ollama_client_configurable_content() -> None:
    """Configured content string is returned verbatim in response.message.content."""
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content='{"party": "Acme GmbH"}')
    response = await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=[], format={}, options={})

    assert response.message.content == '{"party": "Acme GmbH"}'


async def test_fake_ollama_client_records_last_call_model() -> None:
    """last_call records the ``model`` argument after a chat() call."""
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content="{}")
    await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=[], format={}, options={})

    assert fake.last_call["model"] == "gemma4:e2b-it-q4_K_M"


async def test_fake_ollama_client_records_last_call_messages() -> None:
    """last_call records the ``messages`` list verbatim."""
    from tests.fakes.fake_ollama import FakeOllamaClient

    messages = [{"role": "user", "content": "hello"}]
    fake = FakeOllamaClient(content="{}")
    await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=messages, format={}, options={})

    assert fake.last_call["messages"] == messages


async def test_fake_ollama_client_records_last_call_format() -> None:
    """last_call records the ``format`` schema dict verbatim."""
    from tests.fakes.fake_ollama import FakeOllamaClient

    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    fake = FakeOllamaClient(content='{"name": "Test"}')
    await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=[], format=schema, options={})

    assert fake.last_call["format"] == schema


async def test_fake_ollama_client_records_last_call_options() -> None:
    """last_call records the ``options`` dict verbatim."""
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content="{}")
    await fake.chat(
        model="gemma4:e2b-it-q4_K_M", messages=[], format={}, options={"temperature": 0}
    )

    assert fake.last_call["options"] == {"temperature": 0}


async def test_fake_ollama_client_accepts_unknown_kwargs() -> None:
    """Unknown keyword arguments are silently accepted for forward-compatibility."""
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content="{}")
    # ``keep_alive`` and ``stream`` are not used by task-3.1 but will be added
    # by tasks 3.6/3.7 — the fake must not raise on unknown kwargs.
    response = await fake.chat(
        model="gemma4:e2b-it-q4_K_M",
        messages=[],
        format={},
        options={},
        keep_alive="5m",
        stream=False,
    )

    assert response.message.content == "{}"


async def test_fake_ollama_client_last_call_updated_on_repeated_calls() -> None:
    """last_call reflects the MOST RECENT call, not the first.

    Verified via ``messages`` payload variance because the project pins
    a single sanctioned model variant (``gemma4:e2b-it-q4_K_M``); a
    second-call *model* variance would require a non-E2B identifier,
    which is forbidden post-§17.3.
    """
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content="{}")
    first_messages = [{"role": "user", "content": "first"}]
    second_messages = [{"role": "user", "content": "second"}]
    await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=first_messages, format={}, options={})
    await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=second_messages, format={}, options={})

    assert fake.last_call["messages"] == second_messages


async def test_fake_ollama_client_records_last_call_before_raising() -> None:
    """When ``raise_exc`` is set, ``last_call`` is still populated.

    Pins the fake's error-path contract: tests that need to assert what
    arguments the wrapper passed BEFORE the exception fired (e.g. "did
    the wrapper still try the right model when Ollama 400'd?") can rely
    on ``last_call`` being recorded prior to the raise. Without this
    test the fake could silently drift to raising before recording and
    break those assertions.
    """
    from tests.fakes.fake_ollama import FakeOllamaClient

    boom = RuntimeError("simulated failure")
    fake = FakeOllamaClient(raise_exc=boom)

    with pytest.raises(RuntimeError):
        await fake.chat(model="gemma4:e2b-it-q4_K_M", messages=[], format={}, options={})

    assert fake.last_call["model"] == "gemma4:e2b-it-q4_K_M"


def test_fake_chat_message_is_frozen() -> None:
    """FakeChatMessage is immutable (project convention for value objects)."""
    from tests.fakes.fake_ollama import FakeChatMessage

    msg = FakeChatMessage(content="hello")
    with pytest.raises(ValidationError):
        msg.content = "mutated"  # type: ignore[misc]  # exercising frozen=True


def test_fake_chat_response_is_frozen() -> None:
    """FakeChatResponse is immutable (project convention for value objects)."""
    from tests.fakes.fake_ollama import FakeChatMessage, FakeChatResponse

    resp = FakeChatResponse(message=FakeChatMessage(content="hello"))
    with pytest.raises(ValidationError):
        resp.message = FakeChatMessage(content="mutated")  # type: ignore[misc]  # exercising frozen=True
