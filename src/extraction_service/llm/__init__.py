"""LLM inference layer — Ollama-backed extraction (plan §6.5).

The Phase 3 public surface consists of four building blocks that Phase 4's
pipeline wires together:

  - ``OllamaLlmClient`` (and the ``ClientMode`` literal alias) — the async
    wrapper around ``ollama.AsyncClient`` that submits prompts and returns
    parsed JSON dicts.
  - ``PromptTemplate`` — reads a prompt-template file once at construction
    time and renders it with ``ocr_text`` (substitutes ``{ocr_text}``) and
    ``domain_schema`` (rendered into ``{schema_json}`` after ``json.dumps``).
  - ``validate_extracted_data`` — runs ``jsonschema.validate`` on the
    parsed dict, raising ``SchemaInvalidError`` on failure.
  - ``retry_extraction`` — generic async retry wrapper keyed off the
    ``RetryConfig.retry_on`` list of error codes.

``__all__`` is the stable contract that other phases (notably Phase 4)
depend on. Private helpers (``_format_path``, ``_is_context_overflow_error``,
``_ChatClientProtocol``, etc.) are intentionally excluded.
"""

from extraction_service.llm.client import ClientMode, OllamaLlmClient
from extraction_service.llm.prompt import PromptTemplate
from extraction_service.llm.retry import retry_extraction
from extraction_service.llm.schema import validate_extracted_data

__all__ = [
    "ClientMode",
    "OllamaLlmClient",
    "PromptTemplate",
    "retry_extraction",
    "validate_extracted_data",
]
