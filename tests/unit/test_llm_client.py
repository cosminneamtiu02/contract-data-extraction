"""Tests for the Ollama LLM client wrapper (plan §6.5 tasks 3.1, 3.5, 3.6, 3.7).

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
- Client attaches a ``_debug`` top-level key with raw request + response
  payloads when constructed with ``mode="development"`` (task 3.6).
- Client omits the ``_debug`` key in default/production mode (task 3.6).
- Client wraps the chat call with ``asyncio.wait_for`` when
  ``timeout_seconds`` is set and maps ``TimeoutError`` to ``LlmError``
  (task 3.7).

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


async def test_dev_mode_captures_raw_request_and_response() -> None:
    """In ``mode='development'``, the result includes a ``_debug`` block.

    Spec-named RED test for task 3.6: the wrapper attaches a top-level
    ``_debug`` key containing the raw request payload (model, prompt,
    schema) and the raw response content. The block is keyed under
    ``_debug`` (leading underscore) to mark it as side-channel
    metadata, not part of the LLM's structured output.
    """
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"k": "v"}
    raw_content = json.dumps(payload)
    fake = FakeOllamaClient(content=raw_content)
    client = OllamaLlmClient(client=fake, model="gemma3:4b", mode="development")

    result = await client.extract(prompt="hello", schema={"type": "object"})

    assert "_debug" in result


async def test_production_mode_omits_debug_block() -> None:
    """Default and ``mode='production'`` results contain no ``_debug`` key.

    Companion to the dev-mode capture test: in production mode the
    result is the parsed JSON dict only — no metadata side-channel,
    so downstream schema validation does not need a strip step.
    """
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"k": "v"}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b", mode="production")

    result = await client.extract(prompt="hello", schema={})

    assert "_debug" not in result


async def test_dev_mode_default_is_production() -> None:
    """Omitting ``mode`` defaults to production (no ``_debug`` key).

    Belt-and-braces against an accidental flip of the default flag —
    development mode must be explicit, never inherited from omission.
    """
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"k": "v"}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b")

    result = await client.extract(prompt="hello", schema={})

    assert "_debug" not in result


async def test_dev_mode_debug_request_contains_model_prompt_schema() -> None:
    """The ``_debug.request`` sub-block carries model, prompt, and schema."""
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    payload = {"k": "v"}
    fake = FakeOllamaClient(content=json.dumps(payload))
    client = OllamaLlmClient(client=fake, model="gemma3:4b", mode="development")
    schema = {"type": "object", "properties": {"k": {"type": "string"}}}

    result = await client.extract(prompt="probe", schema=schema)

    assert result["_debug"]["request"] == {
        "model": "gemma3:4b",
        "prompt": "probe",
        "schema": schema,
    }


async def test_dev_mode_debug_response_content_is_raw_string() -> None:
    """The ``_debug.response_content`` field carries the unparsed raw string."""
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    raw_content = '{"k": "v"}'
    fake = FakeOllamaClient(content=raw_content)
    client = OllamaLlmClient(client=fake, model="gemma3:4b", mode="development")

    result = await client.extract(prompt="x", schema={})

    assert result["_debug"]["response_content"] == raw_content


async def test_llm_timeout_raises_llm_failed() -> None:
    """Wrapper maps ``asyncio.wait_for`` timeout to ``LlmError``.

    Spec-named RED test for task 3.7: when the LLM call takes longer than
    ``timeout_seconds``, the wrapper aborts via ``asyncio.wait_for`` and
    raises the domain-layer ``LlmError`` (whose ``.code`` is
    ``"llm_failed"`` — retry-eligible per the default ``RetryConfig``).
    """
    from extraction_service.domain.errors import LlmError
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    # Fake sleeps 10ms; wrapper's timeout is 1ms — guaranteed timeout.
    fake = FakeOllamaClient(content='{"k": "v"}', sleep_seconds=0.010)
    client = OllamaLlmClient(client=fake, model="gemma3:4b", timeout_seconds=0.001)

    with pytest.raises(LlmError):
        await client.extract(prompt="x", schema={})


async def test_no_timeout_argument_does_not_apply_wait_for() -> None:
    """Default ``timeout_seconds=None`` skips ``asyncio.wait_for`` entirely.

    Companion to the timeout test: with no timeout configured the wrapper
    awaits the chat call directly, so a slow fake completes successfully
    without raising.
    """
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content='{"k": "v"}', sleep_seconds=0.005)
    client = OllamaLlmClient(client=fake, model="gemma3:4b")  # no timeout

    result = await client.extract(prompt="x", schema={})

    assert result == {"k": "v"}


async def test_llm_timeout_chains_from_timeout_error() -> None:
    """The raised ``LlmError`` chains from the underlying ``TimeoutError``.

    Preserves the original cause for debugging — Phase 4 worker code can
    inspect ``e.__cause__`` to confirm a timeout vs. a different LlmError
    cause that may emerge in later tasks.
    """
    from extraction_service.domain.errors import LlmError
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content='{"k": "v"}', sleep_seconds=0.010)
    client = OllamaLlmClient(client=fake, model="gemma3:4b", timeout_seconds=0.001)

    with pytest.raises(LlmError) as excinfo:
        await client.extract(prompt="x", schema={})

    assert isinstance(excinfo.value.__cause__, TimeoutError)


async def test_extract_raises_json_decode_error_on_invalid_json_response() -> None:
    """Wrapper propagates ``json.JSONDecodeError`` when content is not valid JSON.

    Pins the documented raise contract on ``OllamaLlmClient.extract``: if
    Ollama returns content that fails ``json.loads`` (e.g. model truncation
    mid-token despite ``format`` enforcement), the wrapper does NOT catch or
    map this — ``json.JSONDecodeError`` propagates verbatim so upstream
    callers can decide how to recover (retry, log, surface as schema-invalid).
    Counterpart to the docstring at ``client.py``'s ``extract`` Raises block.
    """
    from extraction_service.llm.client import OllamaLlmClient
    from tests.fakes.fake_ollama import FakeOllamaClient

    fake = FakeOllamaClient(content="not valid json {")
    client = OllamaLlmClient(client=fake, model="gemma3:4b")

    with pytest.raises(json.JSONDecodeError):
        await client.extract(prompt="x", schema={})
