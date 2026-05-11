# extraction-service

Local HTTP service for German legal contract extraction. Ingests scanned PDFs,
OCRs every visible piece of text (body, watermarks, logos, stamps), and uses
a local LLM via Ollama to produce structured JSON matching a caller-supplied
JSON Schema.

Target hardware: Mac Mini M4 (16 GB). Single-process, localhost-only.
See [`docs/plan.md`](docs/plan.md) for the full architecture and development plan.

## Quick start

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run mypy src tests
```

## Layout

- `src/extraction_service/` — the service package
- `tests/` — unit, pipeline, http, ocr, and golden tests
- `config/` — sample run configs and JSON schemas
- `scripts/` — operational scripts (prewarm, validation, benchmark)
- `ops/` — deployment helpers
- `docs/plan.md` — locked architecture + development plan
