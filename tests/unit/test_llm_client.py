"""Tests for the Ollama LLM client wrapper (plan §6.5 task 3.1).

Behavioural coverage:
- Client calls the configured model name.
- Client passes the prompt as a user-role message.
- Client passes the schema dict as the ``format`` argument.
- Client includes ``temperature=0`` in ``options``.
- Client parses the response's ``.message.content`` JSON and returns a dict.

All tests use ``FakeOllamaClient`` so no real Ollama process is required.
``asyncio_mode = "auto"`` in ``pyproject.toml`` covers async without decorators.
"""

from __future__ import annotations

import json


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
