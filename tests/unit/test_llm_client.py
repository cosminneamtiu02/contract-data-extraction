"""Tests for the Ollama LLM client wrapper (plan §6.5 tasks 3.1 and 3.5).

Behavioural coverage:
- Client calls the configured model name (task 3.1).
- Client passes the prompt as a user-role message (task 3.1).
- Client passes the schema dict as the ``format`` argument (task 3.1).
- Client includes ``temperature=0`` in ``options`` (task 3.1).
- Client parses the response's ``.message.content`` JSON and returns a dict
  (task 3.1).
- Client maps ollama context-overflow errors to ``ContextOverflowError``
  (task 3.5).
- Client re-raises non-overflow ``ollama.ResponseError`` instances (task 3.5).

All tests use ``FakeOllamaClient`` so no real Ollama process is required.
``asyncio_mode = "auto"`` in ``pyproject.toml`` covers async without decorators.
"""

from __future__ import annotations

import json

import pytest
from ollama import ResponseError


async def test_ollama_client_calls_correct_endpoint() -> None:
    """Wrapper sends the chat request to the configured model name."""
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"party": "Acme GmbH"}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b")
    await client.extract(prompt="extract", schema={"type": "object"})

    assert fake.last_call["model"] == "gemma3:4b"


async def test_ollama_client_passes_prompt_as_user_message() -> None:
    """Wrapper passes the prompt text wrapped in a user-role message."""
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"clause": "§3"}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b")
    await client.extract(prompt="analyse this contract", schema={})

    messages = fake.last_call["messages"]
    assert messages == [{"role": "user", "content": "analyse this contract"}]


async def test_ollama_client_passes_schema_as_format() -> None:
    """Wrapper passes the schema dict verbatim as the ``format`` argument."""
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    payload = {"name": "Test"}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b")
    await client.extract(prompt="extract", schema=schema)

    assert fake.last_call["format"] == schema


async def test_ollama_client_sets_temperature_zero() -> None:
    """Wrapper sets ``temperature=0`` in options for deterministic output."""
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"result": True}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b")
    await client.extract(prompt="extract", schema={})

    assert fake.last_call["options"] == {"temperature": 0}


async def test_ollama_client_returns_parsed_json_dict() -> None:
    """Wrapper parses ``.message.content`` as JSON and returns a plain dict."""
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"vertragspartner": "Müller AG", "laufzeit_monate": 12}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b")

    result = await client.extract(prompt="extract", schema={})

    assert result == payload


async def test_context_overflow_raises_loudly() -> None:
    """Wrapper maps ollama 400+context-overflow errors to ``ContextOverflowError``.

    The spec-named RED test for task 3.5: when Ollama returns HTTP 400 with
    an error message indicating the prompt exceeded the model's context
    window, ``OllamaLlmClient.extract`` raises the domain-layer
    ``ContextOverflowError`` instead of leaking the bare ``ResponseError``.
    """
    from extraction_service.domain.errors import ContextOverflowError
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    overflow_err = ResponseError(
        "model context length 2048 exceeded by 500 tokens",
        status_code=400,
    )
    fake = FakeOllamaClient(raise_exc=overflow_err)
    client = OllamaLlmClient(client=fake, model="gemma3:4b")

    with pytest.raises(ContextOverflowError):
        await client.extract(prompt="huge prompt", schema={"type": "object"})


async def test_non_overflow_response_error_re_raises_unchanged() -> None:
    """Non-overflow ``ollama.ResponseError`` instances pass through unmapped.

    A 400 without context-overflow indicators (e.g. malformed JSON request),
    or a 5xx server error, is not mapped to ``ContextOverflowError`` — it
    re-raises so upstream layers can distinguish overflow from other
    failure modes.
    """
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    other_err = ResponseError("internal server error", status_code=500)
    fake = FakeOllamaClient(raise_exc=other_err)
    client = OllamaLlmClient(client=fake, model="gemma3:4b")

    with pytest.raises(ResponseError):
        await client.extract(prompt="x", schema={})
