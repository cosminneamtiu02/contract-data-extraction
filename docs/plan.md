# German Legal Contract Extraction Service — Architecture, Best Practices, and Superpowers Development Plan

**Version:** 1.0
**Target hardware:** Mac Mini M4, 16 GB unified memory
**Language:** Python 3.13
**Execution methodology:** Superpowers by Jesse Vincent (obra) in Claude Code

---

## 1. Executive Summary

You are building a single-process, localhost-HTTP service that ingests scanned German legal contracts (PDFs), OCRs every piece of text — body, watermarks, logos, stamps — and uses Gemma 4 E2B Q4_K_M via Ollama to produce structured JSON matching a caller-supplied JSON Schema. The service exposes three endpoints (`GET /health`, `POST /contracts`, `GET /contracts/{id}`), runs a three-stage async pipeline (intake → OCR → LLM extraction) with bounded queues, and self-shuts-down after 10 minutes of HTTP idle.

**Three real technical risks:**
1. **OCR for watermarks and logo text overlaid on body text is a published research problem** (arxiv 2401.05167). Standard document-OCR engines (Tesseract, EasyOCR — Docling's default) assume document flow and skip overlaid/rotated text. **The fix is to use a scene-text detector**, specifically PaddleOCR PP-OCRv5_det, which you can plug into Docling via the RapidOCR backend. This is the most important technical decision in the project.
2. **Memory ceiling on 16 GB.** Two-lane Gemma 4 E2B inference + Docling + FastAPI + macOS leaves ~1 GB of headroom. Anything you add (more workers, larger context, Docling memory spikes on pathological PDFs) tips you into macOS memory compression and throughput collapses.
3. **Validation is non-optional before production.** Benchmarks and engine choices in this document are starting points. The first deliverable after the pipeline works is a 20-contract gold set with field-level F1 measurements. If the OCR misses watermark text on representative samples, change engine settings or stack engines before adding any features.

**Headline architecture commitments:**
- OCR: Docling as orchestrator → RapidOCR backend → PP-OCRv5 ONNX models, with `force_full_page_ocr=True` and optional Tesseract `deu_frak` fallback for historical Fraktur regions.
- LLM: Ollama with `gemma4:e2b-it-q4_K_M` (swappable to E4B), `OLLAMA_NUM_PARALLEL=2`, `num_ctx=8192`, q8_0 KV cache.
- Service: FastAPI + asyncio, two LLM worker coroutines matching `OLLAMA_NUM_PARALLEL`, in-memory result store.
- Toolchain: uv for dependencies, ruff for lint+format, mypy strict for types, pytest + pytest-asyncio + hypothesis for tests, structlog for logs, pydantic-settings for config.

---

## 2. OCR Architecture — Deep Technical Analysis

### 2.1 The watermark/logo problem, stated precisely

Standard document-OCR engines work in two phases:
1. **Layout analysis** identifies "text regions" assuming document flow (columns, paragraphs, headings).
2. **Recognition** OCRs the text inside those regions.

Watermarks and logo text break this assumption in three ways:
- **Orientation:** watermarks are typically rotated diagonally; logo text follows arbitrary baselines.
- **Occlusion:** watermark text overlaps body text. The layout phase sees this as "noise on top of a paragraph" and may merge or skip it.
- **Contrast:** watermarks are intentionally low-contrast. Layout heuristics calibrated for printed body text often filter them out.

This is a published research problem. The Wextract paper (Mlynarski et al., AAAI 2024, arxiv 2401.05167) introduced a benchmark specifically for watermark text spotting and demonstrated that **traditional OCR methods rarely recover overlaid or rotated text reliably**. Their solution uses a hierarchical global+local attention mechanism — overkill for our use case, but the diagnosis is correct: **layout-first OCR pipelines are the wrong tool for watermarks**.

The fix is to use a **scene-text detector**, which makes no assumption about document flow. Scene-text detectors find text bounding boxes anywhere in an image — billboards, license plates, packaging, logos, watermarks — and they handle rotation, curvature, and occlusion natively.

### 2.2 Engine comparison

| Engine | Body text | Watermarks | Logo text | German Fraktur | Stamps | Handwriting | CPU on M4 |
|---|---|---|---|---|---|---|---|
| **Tesseract `deu`** | Excellent | Weak (layout-first) | Weak | No (use `deu_frak` legacy) | Weak | Poor | Fast, native |
| **Tesseract `deu_frak`** | OK | Weak | Weak | Good for historical | Weak | Poor | Fast, native; legacy recognizer only (no LSTM) |
| **EasyOCR (Docling default)** | Good | Weak | OK | None | OK | OK | Slow, CPU-heavy |
| **PaddleOCR PP-OCRv5** | Excellent | **Strong** — DBNet detector finds text anywhere | **Strong** — explicitly trained on scene text including "IDs, street views, books, industrial components" | None natively; can fine-tune | **Strong** — explicit Seal Recognition module | **Strong** — 13% boost over v4 on handwriting | Moderate via ONNX |
| **RapidOCR (PP-OCRv5 in ONNX)** | Same as PaddleOCR | **Strong** | **Strong** | None | **Strong** | **Strong** | **Fast on M4 CPU** — ONNX Runtime is well-optimized for Apple Silicon |
| **Surya OCR** | Excellent | Moderate | Moderate | Good (transformer trained on diverse data) | Moderate | Excellent | Slow on CPU; PyTorch-heavy |
| **doctr / OnnxTR** | Good | Moderate | OK | Limited German vocab | OK | OK | Moderate |

**Sources:** PaddleOCR official docs (paddlepaddle.github.io/PaddleOCR), Wextract paper (arxiv 2401.05167), Tesseract Fraktur wiki (github.com/tesseract-ocr/tesstrain), Surya benchmarks (github.com/datalab-to/surya), Unstract open-source OCR benchmarks 2026.

### 2.3 Single-pass vs multi-pass

**Decision: single-pass with PP-OCRv5 via Docling+RapidOCR, with `force_full_page_ocr=True`, and an optional Tesseract `deu_frak` second-pass *only* if validation shows Fraktur regions are being missed.**

Why single-pass works here:
- PP-OCRv5's detector (DBNet-based, trained on scene text) catches watermark and logo text in the same pass as body text. There's no need for a separate "scene-text engine" because PP-OCRv5 *is* a scene-text-capable engine that also handles documents.
- `force_full_page_ocr=True` in Docling disables the layout-first shortcut. Every page is rasterized and fully OCR'd, so layout analysis can't decide to skip regions.
- Multi-pass adds complexity (region routing, deduplication, conflict resolution between engines) that is not justified unless validation proves it's needed.

When you'd add a second pass:
- If validation shows historical Fraktur text in stamps/seals is being missed → add Tesseract `deu+deu_frak` second pass on detected stamp regions only.
- If a specific class of watermark is consistently missed → train a fine-tuned PaddleOCR model on representative examples (deferred; not v1 work).

### 2.4 Why Docling stays as orchestrator

Docling brings real value that is independent of OCR engine choice:
- Clean Markdown output with preserved document structure.
- Table detection and structured extraction (TableFormer).
- Reading-order resolution.
- A standard Pydantic representation (`DoclingDocument`) you can serialize/inspect.
- Pluggable OCR backends — you swap engines without rewriting the pipeline.

You use Docling for **what it's good at (layout, tables, integration)** and override its default OCR (EasyOCR) with **RapidOCR running PP-OCRv5 models** for everything OCR-related.

### 2.5 Concrete engine configuration

```python
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, RapidOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from modelscope import snapshot_download
import os

# One-time download (cached). Models live in ~/.cache.
# Filenames updated 2026-05-13 to match the current modelscope layout
# and switch the rec model to Latin script for German contracts —
# see docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md §17.16;
# det model swapped server → mobile per §17.17 in the same file (23-63× speedup, char parity).
model_dir = snapshot_download(repo_id="RapidAI/RapidOCR")
det_path = os.path.join(model_dir, "onnx", "PP-OCRv5", "det", "ch_PP-OCRv5_det_mobile.onnx")
rec_path = os.path.join(model_dir, "onnx", "PP-OCRv5", "rec", "latin_PP-OCRv5_rec_mobile.onnx")
cls_path = os.path.join(model_dir, "onnx", "PP-OCRv4", "cls", "ch_ppocr_mobile_v2.0_cls_mobile.onnx")

ocr_options = RapidOcrOptions(
    det_model_path=det_path,
    rec_model_path=rec_path,
    cls_model_path=cls_path,
    lang=["latin"],  # align tokeniser with rec_model_path; default is ["chinese"]
    force_full_page_ocr=True,  # critical: don't skip regions
)

pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    do_table_structure=True,
    ocr_options=ocr_options,
)

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
    },
)
```

Note: PP-OCRv5_server_rec is trained for Chinese/English/Japanese characters. For German, evaluate three options in this order during validation:
1. **PP-OCRv5_server_rec as-is** — Latin glyphs render correctly; specific German letters (ä, ö, ü, ß) need testing.
2. **PP-OCRv5 with extended Latin dictionary fine-tuned for German** — see PaddleOCR's multilingual docs (the framework explicitly lists German as one of 106 supported languages).
3. **Fallback to Tesseract `deu`** — known good for clean German body text, weak for watermarks but a safety net.

Build the OCR engine abstraction (Section 4.3 / Phase 2 of the plan) such that this choice is one config switch. **Do not optimize before validation.**

### 2.6 Performance on Mac Mini M4 (CPU-only)

- **Docling layout + RapidOCR PP-OCRv5 mobile models:** ~2–4 seconds per page on M4 CPU.
- **Docling layout + RapidOCR PP-OCRv5 server models:** ~5–10 seconds per page on M4 CPU. More accurate, slower.
- **Memory:** Docling singleton with ONNX models loaded ~1.5–2 GB. ONNX Runtime is well-tuned for Apple Silicon (CoreML EP available; CPU EP default).
- **Note:** Apple Silicon doesn't get Metal GPU acceleration for these models out of the box without specific ONNX provider configuration. Stay on CPU EP for v1. The bottleneck is LLM inference, not OCR.

### 2.7 What this section did not cover

- Fine-tuning PaddleOCR on a German legal-contract corpus. Deferred.
- Layout-only mode (Docling without OCR) for born-digital PDFs. The spec says scanned PDFs only — single code path.
- DeepSeek-OCR via Docling VlmPipeline. New (Nov 2025), interesting, but requires a hosted/local VLM. Not worth the complexity in v1.

---

## 3. Full System Architecture

### 3.1 Component overview (ASCII diagram)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Orchestrator (external process on same machine)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │ HTTP (localhost:8765)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Extraction Service (single Python process)              │
│                                                                               │
│  HTTP layer (FastAPI)                                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  GET /health                  → 200 OK + queue stats; resets idle timer │  │
│  │  POST /contracts (PDF base64) → 202 + contract_id, or 429 if full       │  │
│  │  GET /contracts/{id}          → status object (+ optional ocr_text)     │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                    │                                          │
│                                    ▼                                          │
│  Pipeline (asyncio)                                                           │
│                                                                               │
│   Intake queue (cap 20)                                                       │
│   ┌──────────┐                                                                │
│   │ ContractJob (pdf_bytes, metadata)                                         │
│   └──────────┘                                                                │
│        │                                                                      │
│        ▼                                                                      │
│   1 × OCR worker  ──── calls Docling+RapidOCR+PP-OCRv5 (singleton)            │
│        │            ── 2–10 s/page CPU                                        │
│        ▼                                                                      │
│   Inter-stage queue (cap 4)                                                   │
│   ┌──────────┐                                                                │
│   │ OcrCompleted (text, metadata)                                             │
│   └──────────┘                                                                │
│        │                                                                      │
│        ▼                                                                      │
│   2 × LLM workers  ─── call Ollama /api/chat (NUM_PARALLEL=2)                 │
│        │            ── 15–25 s per contract                                   │
│        ▼                                                                      │
│   Result store (asyncio-safe in-memory dict)                                  │
│   ┌──────────────────────────────────────────────────────────────────┐       │
│   │ contract_id → ContractRecord(stage states, timings, results)     │       │
│   └──────────────────────────────────────────────────────────────────┘       │
│                                                                               │
│  Idle watchdog: 10 min no HTTP activity → graceful shutdown                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP (localhost:11434)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Ollama (running externally with OLLAMA_NUM_PARALLEL=2, KV q8_0, etc.)        │
│  Model: gemma4:e2b-it-q4_K_M (or e4b), pre-warmed at service startup          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data flow

1. Orchestrator POSTs `{pdf_base64, metadata}` to `/contracts`.
2. Service generates UUID, creates `ContractRecord(intake.state=done, ocr.state=pending, data_parsing.state=pending)`, stores in result store, returns 202 with contract_id.
3. Job enters intake queue. If queue full → 429 immediately.
4. OCR worker pulls from intake queue, sets `ocr.state=in_progress`, calls Docling, sets `ocr.state=done`, attaches text, pushes onto inter-stage queue.
5. Inter-stage queue full → OCR worker blocks on `put` (backpressure).
6. LLM worker pulls from inter-stage queue, sets `data_parsing.state=in_progress`, calls Ollama, validates JSON output against domain schema, sets `data_parsing.state=done` with extracted JSON.
7. Orchestrator polls `GET /contracts/{id}` and reads `data_parsing.extracted` when `overall_status == "done"`.

### 3.3 Error propagation

Per-stage errors. An error in OCR sets `ocr.state=failed` + `ocr.error = {code, description}`, and `overall_status=failed`. `data_parsing.state` stays `pending` (never started). The job does not proceed to the LLM stage.

LLM errors retry up to `max_retries` at the same stage with cached OCR output (no re-OCR). After exhausting retries → `data_parsing.state=failed` + `error`.

Retry logic policy: by default retry `llm_failed` and `schema_invalid`; **never** retry OCR errors (deterministic input → deterministic failure).

### 3.4 Memory model on Apple Silicon

| Region | Where it lives | Swappable? |
|---|---|---|
| Ollama model weights (~7.2 GB for E2B Q4_K_M) | Wired memory (Metal `MTLBuffer`) | **No** — pinned by GPU |
| Ollama KV cache (~600 MB for 2 slots @ 8K, q8_0) | Wired memory | **No** |
| Docling models (~1.5–2 GB) | Process heap | **Yes** — but kept hot by being singleton + active |
| RapidOCR ONNX Runtime tensors | Process heap | **Yes** |
| FastAPI / asyncio / Python state (~500 MB) | Process heap | **Yes** |
| macOS + daemons (~4 GB baseline) | Mostly wired | Mixed |

Total budget: ~15 GB. Headroom: ~1 GB. Set `iogpu.wired_limit_mb=12000` before `ollama serve` to give Metal up to 12 GB of wired space. Pre-warm Gemma at service startup so weights are in wired memory before traffic arrives. Set `OLLAMA_KEEP_ALIVE=-1` so the model never unloads.

### 3.5 Concurrency safety

The result store is mutated from three places: HTTP handlers (creating new records on POST), OCR worker (stage transitions), LLM workers (stage transitions + writes results). All three run in the same asyncio event loop. **Use a single `asyncio.Lock` around any compound update** (read-modify-write of a stage state) and per-record updates inside the lock. Reads (GET handlers) can be lock-free because Python's GIL guarantees attribute reads on a dict are atomic — but if you serialize the record to JSON while it's being mutated, you'll get a torn read. **Acquire the lock for serialization too.** Cheap, simple, correct.

---

## 4. Python Implementation Best Practices

### 4.1 Python version

**Use Python 3.13.** Released October 2024, stable now. Improved asyncio (`TaskGroup` matured), better error messages, faster startup. No reason to use 3.12; no reason yet to use 3.14 (released October 2025, still bedding in).

### 4.2 Dependency management — **uv**

Pick **uv** (astral-sh/uv). Reasons:
- 10–100× faster than pip/poetry for resolve and install.
- Single tool: replaces `pip`, `pip-tools`, `pipx`, `virtualenv`, `pyenv`.
- Native lockfile (`uv.lock`).
- Built-in Python version management (`uv python install 3.13`).
- Active development from Astral (same team as ruff). Wide adoption since 2024.

Don't use poetry: slower, more opinionated, worse interaction with build backends. Don't use plain pip-tools: lacks lock semantics across platforms.

### 4.3 Project layout — **src/ layout**

Why src/:
- Forces the package to be installed before testing — catches `__init__.py` import bugs that flat layouts hide.
- Cleaner separation between code and tests.
- Standard for modern Python (Hatch, uv, pipx all expect it).

Use `pyproject.toml` exclusively (no `setup.py`, no `setup.cfg`). Build backend: **hatchling** (lightweight, PEP 517-compliant, default for uv-managed projects).

### 4.4 Type hints — **mypy strict**

`mypy --strict` as the gate. Reasons:
- Most mature, most stable, most documented type checker.
- "strict" is a known config target (`--strict` enables `--disallow-untyped-defs`, `--no-implicit-optional`, etc.).
- Pyright/basedpyright are good in editors but mypy is the CI authority. Pick one.

Run `mypy src tests` in CI. Tolerate untyped tests if you must, but type-check `src` strictly.

### 4.5 Lint + format — **ruff**

Ruff is the only realistic answer in 2026. One tool, fast, replaces flake8 + isort + pyupgrade + several plugins + black.

Minimum rule set (rationale: aggressive but not noisy):
```toml
[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "F",    # pyflakes
    "I",    # isort
    "B",    # bugbear
    "UP",   # pyupgrade
    "ASYNC",# async correctness
    "PIE",  # idiomatic Python
    "SIM",  # simplifications
    "RET",  # return-related
    "ARG",  # unused arguments
    "PTH",  # use pathlib
    "TID",  # tidy imports
    "T20",  # no print statements
    "RUF",  # ruff-specific
]
ignore = ["E501"]  # line length handled by formatter

[tool.ruff.format]
quote-style = "double"
```

Run `ruff check . --fix` and `ruff format .` in pre-commit. Drop black entirely.

### 4.6 Testing — **pytest + pytest-asyncio + hypothesis**

- `pytest` 8.x.
- `pytest-asyncio` with `asyncio_mode = "auto"` so every `async def test_...` is automatically wrapped (no `@pytest.mark.asyncio` repetition).
- `hypothesis` for property-based testing the JSON-schema-validation logic and the prompt rendering.
- Coverage target: **80%** is the realistic floor. Don't chase 100% — the HTTP handler tests and golden-file OCR tests give you most of the leverage (deviation §17.3 in `2026-05-12-phase-2-ocr-spec-deviations.md`: real-OCR tests use env-var-resolved sample PDFs from `$EXTRACTION_OCR_SAMPLES_DIR` rather than golden files checked into the repo).

### 4.7 Configuration — **pydantic-settings**

Single source of truth for all `EXTRACTION_*` env vars. Validate at startup; fail fast on missing/invalid config.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, PositiveInt

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EXTRACTION_", env_file=".env")

    mode: Literal["development", "production"] = "production"
    port: PositiveInt = 8765
    model: str = "gemma4:e2b-it-q4_K_M"
    num_parallel: PositiveInt = 2
    num_ctx: PositiveInt = 8192
    intake_queue_size: PositiveInt = 20
    interstage_queue_size: PositiveInt = 4
    idle_shutdown_seconds: PositiveInt = 600
    max_retries: int = Field(default=1, ge=0, le=5)
    run_config: Path  # required
```

### 4.8 Logging — **structlog**

`structlog` for structured JSON logs. Reasons:
- Native dict-style logging: `log.info("ocr_done", contract_id=cid, duration_ms=ms)`.
- Configurable per-environment processors (pretty-print in development, JSON in production).
- Integrates with stdlib `logging` so library logs (FastAPI, httpx) still flow through.

Bind `contract_id` and `stage` into context at the top of each worker so every downstream log carries them automatically.

### 4.9 HTTP framework — **FastAPI**

FastAPI. Not Starlette directly (you give up the request/response model wiring), not Litestar (smaller ecosystem, marginal wins).

Use dependency injection for the OCR engine, LLM client, and result store as singletons via `Depends()` returning module-level globals. Or use `fastapi-lifespan` to wire them on startup.

### 4.10 Async patterns

- **`asyncio.TaskGroup`** (3.11+) for worker supervision. Cleaner exception aggregation than `gather`.
- **`asyncio.Queue(maxsize=N)`** for intake and inter-stage queues.
- **`asyncio.Lock`** around result store updates.
- **`anyio`** is unnecessary unless you also support trio. Stick with asyncio.

Worker lifecycle:
```python
async def lifespan(app):
    async with asyncio.TaskGroup() as tg:
        tg.create_task(ocr_worker(state))
        tg.create_task(llm_worker(state, lane=0))
        tg.create_task(llm_worker(state, lane=1))
        tg.create_task(idle_watchdog(state))
        yield
        # cleanup happens automatically when tasks are cancelled
```

### 4.11 Pydantic v2 idioms

- Use `model_config = ConfigDict(frozen=True)` for immutable value objects (e.g. `ContractJob`).
- Use `Field(...)` with constraints (`ge`, `le`, `min_length`) instead of validators where possible.
- Use `model_dump(mode="json")` for serialization with proper handling of `datetime`, `UUID`, etc.
- Use `TypeAdapter` for validating top-level lists or non-model types.

### 4.12 Dependency injection in FastAPI

Don't import singletons directly in handlers. Wire them through `Depends`:

```python
def get_ocr_engine() -> OcrEngine:
    return app.state.ocr_engine

def get_result_store() -> ResultStore:
    return app.state.result_store

@router.get("/contracts/{contract_id}")
async def get_contract(
    contract_id: UUID,
    store: ResultStore = Depends(get_result_store),
    include: str | None = None,
) -> ContractStatusResponse:
    ...
```

Makes testing trivial — override dependencies in tests with `app.dependency_overrides[get_ocr_engine] = fake_engine`.

### 4.13 Error handling

Define a small exception hierarchy:

```python
from typing import ClassVar

class ExtractionError(Exception):
    """Base."""
    code: ClassVar[str] = "extraction_error"

class OcrError(ExtractionError):
    code: ClassVar[str] = "ocr_engine_failed"

class OcrEmptyOutputError(OcrError):
    code: ClassVar[str] = "ocr_empty_output"

class LlmError(ExtractionError):
    code: ClassVar[str] = "llm_failed"

class ContextOverflowError(LlmError):
    code: ClassVar[str] = "context_overflow"

class SchemaInvalidError(LlmError):
    code: ClassVar[str] = "schema_invalid"
```

Each exception carries its error code as a class attribute. Workers catch the appropriate type, record the error on the stage, and either retry or terminate. HTTP exception handlers map the base `ExtractionError` to JSON responses — but for this service, errors live in the status object, not in HTTP responses (always 200 unless 404/429).

### 4.14 Ollama client — **ollama-python official**

Use the official `ollama` Python package. Reasons:
- Maintained by the Ollama team, tracks API changes.
- Native async support (`AsyncClient`).
- Built-in retries on connection errors.

Don't roll your own httpx client unless you need streaming and find the official client's streaming surface insufficient. For batch extraction with structured output, the official `chat()` method with `format="json"` or function-calling is fine.

### 4.15 Testing strategies

| Test type | What it covers | How |
|---|---|---|
| **Unit** | Pydantic models, prompt rendering, retry logic, schema validation | Plain pytest, no I/O |
| **Golden-file OCR** | OCR output stability on known PDFs | `tests/data/contracts/*.pdf` + `tests/data/expected/*.txt` (deviation §17.3 in `2026-05-12-phase-2-ocr-spec-deviations.md`: samples are gitignored; resolved via `$EXTRACTION_OCR_SAMPLES_DIR`) |
| **Pipeline integration** | Queue handoffs, state transitions, error propagation | In-memory pipeline + fake OCR engine + fake LLM client |
| **Contract tests (HTTP API)** | Endpoint shapes, status codes, response schemas | `httpx.AsyncClient` against `app` instance, no real server |
| **End-to-end** | Full path: PDF → OCR → LLM → JSON | Real Docling + real Ollama on dev box, NOT in CI |

For Ollama: ship a `FakeOllamaClient` in `tests/fakes/` that returns canned responses. CI doesn't run Ollama.

For Docling/OCR: ship a `FakeOcrEngine` that returns predetermined text. Golden-file tests use real Docling on 3–5 small sample PDFs you check into the repo. Slow, but they're integration tests. (deviation §17.3 in `2026-05-12-phase-2-ocr-spec-deviations.md`: sample PDFs are gitignored and resolved at runtime via `$EXTRACTION_OCR_SAMPLES_DIR` rather than checked into the repo.)

### 4.16 Observability

Minimum viable:
- **structlog JSON logs** with `contract_id`, `stage`, `duration_ms` on every transition.
- **No OpenTelemetry in v1.** It's overkill for a single-process localhost service.
- Stretch: a `/metrics` endpoint exposing queue depths and processed counts. Defer.

---

## 5. Project Structure

```
extraction-service/
├── pyproject.toml
├── uv.lock
├── README.md
├── .python-version              # 3.13
├── .env.example                 # template, never with real secrets
├── .gitignore
├── .pre-commit-config.yaml
│
├── src/
│   └── extraction_service/
│       ├── __init__.py
│       ├── __main__.py          # `python -m extraction_service` entrypoint
│       ├── settings.py          # pydantic-settings Settings class
│       ├── log_config.py        # structlog config (renamed from logging.py to avoid stdlib shadowing)
│       │
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── job.py           # ContractJob frozen Pydantic model
│       │   ├── stage.py         # StageState, StageRecord, StageError
│       │   ├── record.py        # ContractRecord (full status)
│       │   └── errors.py        # exception hierarchy
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   ├── run_config.py    # parses run config YAML
│       │   └── domain_model.py  # loads & validates user-supplied JSON schema
│       │
│       ├── ocr/
│       │   ├── __init__.py
│       │   ├── base.py          # OcrEngine Protocol + OcrResult
│       │   ├── docling_engine.py # Docling + RapidOCR PP-OCRv5
│       │   └── factory.py       # build_ocr_engine(run_config) -> OcrEngine
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py        # OllamaLlmClient wrapper (singleton)
│       │   ├── prompt.py        # prompt template rendering
│       │   ├── schema.py        # JSON schema validation of LLM output
│       │   └── retry.py         # retry policy
│       │
│       ├── pipeline/            # (Phase 4 — not yet created)
│       │   ├── __init__.py
│       │   ├── state.py         # PipelineState (queues + result store)
│       │   ├── result_store.py  # asyncio-safe in-memory dict
│       │   ├── ocr_worker.py
│       │   ├── llm_worker.py
│       │   └── watchdog.py      # idle shutdown
│       │
│       └── http/                # (Phase 5 — not yet created)
│           ├── __init__.py
│           ├── app.py           # FastAPI app + lifespan
│           ├── deps.py          # Depends() functions
│           ├── routes_health.py
│           ├── routes_contracts.py
│           └── responses.py     # response models matching locked status shape
│
├── tests/
│   ├── conftest.py
│   ├── fakes/
│   │   ├── __init__.py
│   │   ├── fake_ocr.py          # deterministic OcrEngine
│   │   ├── test_fake_ocr.py
│   │   ├── fake_ollama.py       # canned LLM responses
│   │   └── test_fake_ollama.py
│   ├── unit/
│   │   ├── test_domain_errors.py
│   │   ├── test_domain_job.py
│   │   ├── test_domain_model.py
│   │   ├── test_domain_record.py
│   │   ├── test_domain_stage.py
│   │   ├── test_log_config.py
│   │   ├── test_settings.py
│   │   ├── test_run_config.py
│   │   ├── test_ocr_base.py
│   │   ├── test_llm_client.py
│   │   ├── test_llm_prompt.py
│   │   ├── test_llm_schema.py
│   │   ├── test_llm_retry.py
│   │   └── test_result_store.py                                   # (Phase 4 — not yet created)
│   ├── ocr/
│   │   ├── _metrics.py
│   │   ├── conftest.py
│   │   ├── test_docling_engine.py
│   │   ├── test_factory.py
│   │   ├── test_word_recall.py
│   │   └── data/    # PDFs gitignored per §17.3 in 2026-05-12-phase-2-ocr-spec-deviations.md; resolved via $EXTRACTION_OCR_SAMPLES_DIR at test collection time
│   ├── pipeline/            # (Phase 4 — not yet created)
│   │   ├── test_ocr_worker.py
│   │   ├── test_llm_worker.py
│   │   ├── test_watchdog.py
│   │   └── test_pipeline_e2e.py
│   ├── http/                # (Phase 5 — not yet created)
│   │   ├── test_health.py
│   │   ├── test_post_contracts.py
│   │   ├── test_get_contracts.py
│   │   └── test_idle_shutdown.py
│
│   └── e2e/                 # (Phase 6 — not yet created)
├── config/                          # (Phase 6 — not yet created)
│   ├── run_config.example.yaml
│   ├── domain_model.example.json    # JSON Schema sample for a loan contract
│   └── extraction_prompt.example.txt
│
├── scripts/                         # (Phase 6 — not yet created)
│   ├── prewarm.py               # smoke test: hit Ollama with a tiny prompt
│   ├── validate_ocr.py          # run OCR on a directory and dump outputs
│   └── benchmark_e2e.py         # time a batch of contracts
│
└── ops/                             # (Phase 6 — not yet created)
    ├── ollama_env.sh            # exports OLLAMA_* and sysctl iogpu.wired_limit_mb
    └── launchd.plist.example    # macOS launchd unit (optional)
```

### 5.1 pyproject.toml (essential sections)

> The block below is the original plan-time snapshot. The live `pyproject.toml` is the source of truth — it has diverged since Phase 1 review passes added ruff rule-set entries (`EM`, `TRY`, `TCH`, `N`, `S`), per-file-ignores for tests, pytest `markers`/`filterwarnings`, the hatchling `exclude` directive, and version floors on the `types-*` dev deps. See `pyproject.toml` directly for current state; deviations from this snapshot are recorded in `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md §17.8`.

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "extraction-service"
version = "0.1.0"
description = "Local HTTP service for German legal contract extraction"
license = "MIT"
license-files = ["LICENSE"]
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.10",
    "pydantic-settings>=2.6",
    "structlog>=24.4",
    "ollama>=0.4",
    "docling>=2.20",
    "rapidocr-onnxruntime>=1.4",
    "modelscope>=1.20",         # for model snapshot_download
    "jsonschema>=4.23",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[project.scripts]
extraction-service = "extraction_service.__main__:main"

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "hypothesis>=6.115",
    "mypy>=1.13",
    "ruff>=0.9",
    "types-pyyaml",
    "types-jsonschema",
    "pre-commit>=4.0",
    "pip-audit>=2.7",
    "detect-secrets>=1.5",
]

[tool.hatch.build.targets.wheel]
packages = ["src/extraction_service"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "PIE", "SIM", "RET", "ARG", "PTH", "TID", "T20", "RUF", "C4", "FURB", "PT"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["ARG"]  # fixtures often look unused

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.13"
strict = true
warn_unreachable = true
mypy_path = "src"
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["docling.*", "rapidocr.*", "modelscope.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = ["--strict-markers", "--strict-config", "-ra"]

[tool.coverage.run]
source = ["src/extraction_service"]
branch = true

[tool.coverage.report]
fail_under = 80
show_missing = true
skip_empty = true
```

---

## 6. Development Plan — Optimized for Superpowers

### 6.1 Phase structure

Each phase is **its own git worktree** so phases can be reviewed/merged independently. Inside a phase, every task follows **RED → GREEN → REFACTOR**:

1. Write the failing test (RED).
2. Watch it fail.
3. Write the minimum code to pass (GREEN).
4. Refactor if needed.
5. Commit.

**Phase boundaries** mean: when a phase ends, run the full test suite, do a code review pass, and merge to main before starting the next phase. **Tasks within a phase** are bite-sized and pre-planned with file paths so a Superpowers subagent can execute them without ambiguity.

### 6.2 Phase 0 — Project scaffolding

**Goal:** Empty but professional project skeleton. Repo passes `ruff check`, `mypy`, and `pytest` (with zero tests) cleanly.

**Worktree:** `phase-0-scaffolding`

| # | Task | File(s) | RED test | GREEN impl | Verify |
|---|---|---|---|---|---|
| 0.1 | Initialize uv project | `pyproject.toml`, `.python-version`, `uv.lock` | — (one-off bootstrap) | `uv init --package extraction-service`, edit pyproject.toml from Section 5.1 above, `uv sync` | `uv run python -c "import extraction_service"` |
| 0.2 | Create src/ layout | `src/extraction_service/__init__.py`, `src/extraction_service/__main__.py` | `tests/test_smoke.py` asserts `import extraction_service` works | empty `__init__.py`; `__main__.py` with `def main() -> None: pass` (no-op stub; `print` would violate the T20 rule wired in Task 0.3) | `uv run pytest tests/test_smoke.py` |
| 0.3 | Add ruff config | (already in pyproject.toml) | none | apply [tool.ruff.lint] block from Section 5.1 | `uv run ruff check src tests` clean |
| 0.4 | Add mypy strict config | (already in pyproject.toml) | none | apply [tool.mypy] block | `uv run mypy src tests` clean |
| 0.5 | Add pytest config | (already in pyproject.toml) | none | apply [tool.pytest.ini_options] | `uv run pytest` shows 2 passing tests (smoke — import + entrypoint sentinels) |
| 0.6 | Pre-commit hooks | `.pre-commit-config.yaml` | none | hooks for ruff check, ruff format, mypy | `uv run pre-commit run --all-files` clean |
| 0.7 | .gitignore + README stub | `.gitignore`, `README.md` | none | standard Python .gitignore + project description | git status clean |

**Exit criteria:** `uv run pytest && uv run ruff check . && uv run mypy src tests` all green. Commit, merge worktree to main.

### 6.3 Phase 1 — Domain types and configuration

**Goal:** Domain value objects (`ContractJob`, stage state machine, `StageRecord` — frozen) plus the mutable `ContractRecord` container (workers reassign stage fields under the §3.5 lock), settings loading, run config parsing. No I/O, no async — pure data.

**Worktree:** `phase-1-domain`

| # | Task | File | RED test | GREEN impl | Verify |
|---|---|---|---|---|---|
| 1.1 | `ContractJob` frozen Pydantic model | `src/extraction_service/domain/job.py` | `test_contract_job_metadata_defaults_to_empty_dict`; `test_contract_job_is_frozen`; `test_contract_job_round_trips_through_model_dump_json`; `test_contract_job_raises_when_both_required_fields_missing`; `test_contract_job_raises_when_pdf_bytes_missing`; `test_contract_job_raises_when_contract_id_missing` (in `tests/unit/test_domain_job.py`) | Pydantic v2 model with `model_config = ConfigDict(frozen=True)`, fields: `contract_id: UUID`, `pdf_bytes: bytes`, `metadata: dict[str, Any]` | `uv run pytest tests/unit/test_domain_job.py` |
| 1.2 | `StageState` enum | `src/extraction_service/domain/stage.py` | `test_stage_state_has_expected_member_values`; `test_stage_state_str_produces_value`; `test_stage_state_fstring_interpolation_produces_value` (in `tests/unit/test_domain_stage.py`) | `class StageState(StrEnum)` with those four values (Python 3.11+ `StrEnum` over the older `(str, Enum)` form — cleaner `str()` / f-string output for structlog) | pytest |
| 1.3 | `StageRecord` Pydantic model | `src/extraction_service/domain/stage.py` | `test_stage_error_is_frozen`; `test_stage_record_defaults_state_to_pending`; `test_stage_record_defaults_started_at_to_none`; `test_stage_record_defaults_completed_at_to_none`; `test_stage_record_defaults_error_to_none`; `test_stage_record_defaults_duration_ms_to_none`; `test_stage_record_start_returns_new_record_in_progress`; `test_stage_record_start_sets_started_at_on_new_record`; `test_stage_record_start_leaves_completed_at_none_on_new_record`; `test_stage_record_start_leaves_original_record_unchanged`; `test_stage_record_complete_transitions_state_to_done`; `test_stage_record_complete_sets_completed_at_to_now`; `test_stage_record_complete_carries_started_at_forward`; `test_stage_record_complete_derives_duration_ms`; `test_stage_record_fail_transitions_state_to_failed`; `test_stage_record_fail_sets_completed_at_to_now`; `test_stage_record_fail_records_error`; `test_stage_record_fail_carries_started_at_forward`; `test_stage_record_fail_derives_duration_ms`; `test_stage_record_duration_ms_is_none_when_pending`; `test_stage_record_duration_ms_is_none_when_in_progress_before_complete`; `test_stage_record_is_frozen`; `test_stage_record_complete_accepts_extracted_payload`; `test_stage_record_complete_defaults_extracted_to_none`; `test_stage_record_round_trips_through_model_dump_json_when_done`; `test_stage_record_round_trips_through_model_dump_json_when_pending`; `test_stage_record_start_with_default_now_uses_current_time`; `test_stage_record_complete_with_default_now_uses_current_time`; `test_stage_record_fail_with_default_now_uses_current_time` (in `tests/unit/test_domain_stage.py`) | model with state, started_at, completed_at, duration_ms (computed), error (Optional), extracted (Optional Phase-4 LLM payload slot — see §17.24 in `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md`) | pytest |
| 1.4 | `ContractRecord` | `src/extraction_service/domain/record.py` | `test_fresh_contract_record_marks_intake_done_with_timestamps`; `test_fresh_contract_record_leaves_ocr_and_parsing_pending`; `test_fresh_contract_record_overall_status_is_in_progress`; `test_fresh_contract_record_with_default_now_uses_current_time`; `test_overall_status_is_done_only_when_all_three_stages_done`; `test_overall_status_is_failed_when_ocr_failed`; `test_overall_status_is_failed_when_intake_failed`; `test_overall_status_is_failed_when_parsing_failed_even_after_ocr_done`; `test_current_stage_is_ocr_when_intake_done_and_ocr_pending`; `test_current_stage_is_ocr_when_ocr_in_progress`; `test_current_stage_is_data_parsing_when_ocr_done`; `test_current_stage_points_to_failure_point_when_a_stage_failed`; `test_current_stage_points_to_data_parsing_when_data_parsing_failed`; `test_current_stage_is_none_when_all_stages_done`; `test_contract_record_allows_stage_reassignment`; `test_stage_field_inside_contract_record_remains_frozen`; `test_contract_record_round_trips_through_model_dump_json_when_all_done`; `test_contract_record_round_trips_through_model_dump_json_when_failed`; `test_default_contract_record_all_pending_has_intake_as_current_stage` (in `tests/unit/test_domain_record.py`) | model with intake, ocr, data_parsing StageRecords plus a derived `overall_status` and `current_stage` property | pytest |
| 1.5 | Error hierarchy | `src/extraction_service/domain/errors.py` | `test_base_extraction_error_inherits_from_exception`; `test_base_extraction_error_has_sentinel_code`; `test_concrete_errors_have_expected_code`; `test_concrete_error_classes_inherit_from_correct_parents`; `test_raised_error_preserves_code_and_message` (in `tests/unit/test_domain_errors.py`) | exception classes from Section 4.13 | pytest |
| 1.6 | `Settings` (pydantic-settings) | `src/extraction_service/settings.py` | `test_settings_raises_when_run_config_env_var_missing`; `test_settings_loads_documented_defaults_when_only_run_config_set`; `test_settings_overrides_via_extraction_prefixed_env_vars`; `test_settings_rejects_invalid_mode`; `test_settings_rejects_max_retries_above_five`; `test_settings_rejects_negative_max_retries`; `test_settings_rejects_non_positive_port`; `test_settings_accepts_max_retries_at_inclusive_bounds` (in `tests/unit/test_settings.py`) | Section 4.7 settings class | pytest |
| 1.7 | Run config loader | `src/extraction_service/config/run_config.py` | `test_load_minimal_valid_yaml_returns_run_config`; `test_load_minimal_yaml_uses_documented_defaults_for_omitted_sections`; `test_load_full_yaml_overrides_defaults`; `test_load_yaml_raises_when_required_section_missing`; `test_load_yaml_raises_when_required_field_missing`; `test_load_yaml_raises_on_unknown_top_level_field`; `test_load_yaml_raises_on_misspelled_field_in_subsection`; `test_load_run_config_raises_when_file_does_not_exist`; `test_load_yaml_rejects_retry_on_code_that_is_not_a_known_error_code`; `test_load_yaml_accepts_all_documented_llm_retry_codes`; `test_load_yaml_rejects_ocr_engine_failed_in_retry_on`; `test_load_yaml_rejects_ocr_empty_output_in_retry_on`; `test_load_yaml_raises_on_malformed_yaml`; `test_retry_on_code_literal_mirrors_concrete_extraction_error_codes` (in `tests/unit/test_run_config.py`) | YAML parser → Pydantic `RunConfig` model with fields for ocr, llm, retry, paths | pytest |
| 1.8 | Domain model loader | `src/extraction_service/config/domain_model.py` | `test_load_valid_json_schema_returns_dict`; `test_load_round_trips_to_an_independent_dict`; `test_load_raises_schema_error_on_invalid_meta_schema`; `test_load_raises_schema_error_when_required_is_not_a_list`; `test_load_raises_when_file_does_not_exist`; `test_load_raises_when_file_is_not_valid_json` (in `tests/unit/test_domain_model.py`) | uses `jsonschema` library to validate the schema is itself a valid JSON schema | pytest |
| 1.9 | Structlog config | `src/extraction_service/log_config.py` (renamed from `logging.py` to avoid stdlib shadowing) | `test_configure_logging_production_emits_json_with_event_and_kwargs`; `test_configure_logging_production_serializes_subsequent_events_one_per_line`; `test_configure_logging_dev_emits_human_readable_not_json`; `test_configure_logging_carries_contextvars_into_log_events`; `test_configure_logging_dev_mode_carries_contextvars_into_log_events`; `test_configure_logging_filters_below_info_level` (in `tests/unit/test_log_config.py`) | configure_logging(mode) sets renderers | pytest |

**Exit criteria:** all unit tests pass, mypy strict clean. Commit, merge.

### 6.4 Phase 2 — OCR layer

**Goal:** Pluggable OCR engine abstraction; one real implementation (Docling + RapidOCR + PP-OCRv5); validated OCR tests against local sample PDFs (**deviation §17.3 in `2026-05-12-phase-2-ocr-spec-deviations.md`:** sample PDFs are gitignored and resolved via `$EXTRACTION_OCR_SAMPLES_DIR`, NOT committed; "golden tests" wording is pre-deviation). The §17 references in the task table below all live in the same Phase 2 spec file unless otherwise noted.

**Worktree:** `phase-2-ocr`

| # | Task | File | RED test | GREEN impl | Verify |
|---|---|---|---|---|---|
| 2.1 | `OcrResult` + `OcrEngine` Protocol | `src/extraction_service/ocr/base.py` | `test_ocr_engine_protocol_accepts_structural_conformer` + `test_ocr_engine_protocol_rejects_non_conformer` (the original `test_ocr_engine_protocol_compliance` was split into accepts/rejects pair during implementation) | `OcrResult` Pydantic model (text, page_count, engine_name); `OcrEngine` `Protocol` with async `extract(pdf_bytes: bytes) -> OcrResult` | mypy + pytest |
| 2.2 | `FakeOcrEngine` for tests | `tests/fakes/fake_ocr.py` | `tests/fakes/test_fake_ocr.py` — 6 tests including `test_fake_ocr_engine_satisfies_ocr_engine_protocol` (Protocol-conformance signature-drift guard) | implements OcrEngine, returns configurable text | imports in subsequent tests |
| 2.3 | `DoclingOcrEngine` skeleton | `src/extraction_service/ocr/docling_engine.py` | (no dedicated construction-only test — constructor coverage is transitive through every extract test which injects a stub via `_converter_factory` and would fail with AttributeError if `_converter` were left unset; **deviation §17.15:** the planned `test_docling_engine_construct` was removed because asserting on a private attribute breached the project's underscore-prefix convention) | wrap Section 2.5 setup; constructor builds DocumentConverter | pytest |
| 2.4 | DoclingOcrEngine.extract returns text | `src/extraction_service/ocr/docling_engine.py` | `test_docling_extract_clean_pdf` — pass a tiny PDF (committed to `tests/ocr/data/sample_clean.pdf`), assert returned text contains expected snippet (**deviation §17.3:** replaced by parametrised `test_docling_extract_against_sample` over `$EXTRACTION_OCR_SAMPLES_DIR`; no PDFs committed plus `tests/ocr/_metrics.word_recall` + `tests/ocr/test_word_recall.py` (7 tests pin the baseline-overlap metric used by the parametrised real-OCR test)) | implement `extract`: call `converter.convert(BytesIO(pdf_bytes))`, return markdown | pytest (slow) |
| 2.5 | DoclingOcrEngine handles watermark sample | `tests/ocr/test_docling_engine.py::test_watermark_text_captured` | add `sample_with_watermark.pdf` (you provide one or render one synthetically); assert OCR result contains watermark word (**deviation §17.1:** task DROPPED — watermarks are not a relevant signal on the real contract corpus) | (no impl change if 2.4 works; this is a verification test) | pytest |
| 2.6 | DoclingOcrEngine handles logo text sample | `tests/ocr/test_docling_engine.py::test_logo_text_captured` | similar with `sample_with_logo.pdf` (**deviation §17.2:** REFOCUSED — logo-text extraction folded into the §17.3 parametrised real-OCR test; semantic logo identification deferred) | (verification only) | pytest |
| 2.7 | `OcrEngineFactory` | `src/extraction_service/ocr/factory.py` | `test_factory_returns_docling_for_docling_config` | switch on `run_config.ocr.engine` string; raise on unknown (**deviation §17.4:** "raise on unknown" omitted — closed `Literal["docling"]` makes mypy the exhaustiveness guard, no runtime `case _:` needed) | pytest |
| 2.8 | OCR engine respects timeout | `src/extraction_service/ocr/docling_engine.py` | `test_docling_extract_raises_timeout_when_convert_exceeds_budget` — patch the converter to block on a `threading.Event` longer than the configured timeout, assert `asyncio.TimeoutError` (planned name `test_docling_extract_timeout` was expanded during implementation to a behavior-descriptive form) | wrap `.convert()` call in `asyncio.wait_for` (Docling is sync; run via `loop.run_in_executor`) (**deviation §17.9 in `2026-05-12-phase-2-ocr-spec-deviations.md`:** implementation uses `asyncio.to_thread` instead of `loop.run_in_executor` — equivalent Python 3.9+ idiom; distinct from CI/CD spec's own §17.9 on closed-Literal exhaustiveness) | pytest |
| 2.9 | OCR error wraps as OcrError | `src/extraction_service/ocr/docling_engine.py` | `test_docling_extract_empty_markdown_raises_ocr_empty_output` (patch to return empty) + `test_docling_extract_converter_exception_wraps_as_ocr_error` (patch to raise) — planned names `test_docling_extract_empty_output_raises_ocr_empty_output` / `test_docling_internal_exception_wraps_as_ocr_engine_failed` were tightened during implementation to match the actual exception classes + behaviors (**deviation §17.5:** third test added for `ConversionStatus.FAILURE`; **deviation §17.6:** `TimeoutError` propagates unwrapped — not mapped to `OcrError`) | try/except in extract, map to `OcrError` subclasses | pytest |

**Validation gate:** Before declaring Phase 2 done, run `scripts/validate_ocr.py` on a real folder of 5–10 of your actual contracts. Manually inspect the OCR output. If watermark/logo text is missed, do not proceed — iterate on engine config (try `PP-OCRv5_server_det` vs `PP-OCRv5_mobile_det`, try Tesseract `deu_frak` as fallback). (**deviation §17.8 in `2026-05-12-phase-2-ocr-spec-deviations.md`:** the `scripts/validate_ocr.py` script itself is deferred to Phase 6 task 6.2 — Phase 2 ships the parametrised slow real-OCR test in `tests/ocr/test_docling_engine.py` as the interim signal, gated on `$EXTRACTION_OCR_SAMPLES_DIR`.)

**Exit criteria:** all OCR tests pass; manual validation on real samples confirms watermarks/logos captured. Commit, merge. (**deviation §17.1/§17.2 in 2026-05-12-phase-2-ocr-spec-deviations.md:** watermark test dropped; logo-text verification folded into §17.3 parametrised real-OCR test; manual validation confirmed per §17.16–§17.17 in the same Phase 2 spec)

### 6.5 Phase 3 — LLM layer

**Goal:** Ollama client wrapper, prompt rendering, schema validation, retry policy. No pipeline integration yet.

**Worktree:** `phase-3-llm`

| # | Task | File | RED test | GREEN impl | Verify |
|---|---|---|---|---|---|
| 3.1 | Ollama client wrapper | `src/extraction_service/llm/client.py` | `test_ollama_client_calls_correct_endpoint` (use `FakeOllamaClient`) | thin wrapper over `ollama.AsyncClient`, exposes `extract(prompt, schema) -> dict` | pytest |
| 3.2 | Prompt template rendering | `src/extraction_service/llm/prompt.py` | `test_prompt_renders_with_ocr_text_and_schema` (load sample template, substitute placeholders, assert output) | Jinja2-style or simple `str.format`-based renderer; reads template from disk once | pytest |
| 3.3 | JSON schema validation | `src/extraction_service/llm/schema.py` | `test_valid_extracted_data_passes`, `test_invalid_extracted_data_raises_schema_invalid` | use `jsonschema.validate`; wrap exceptions in `SchemaInvalidError` with details | pytest |
| 3.4 | Retry policy | `src/extraction_service/llm/retry.py` | `test_retry_on_listed_error_codes_until_max`, `test_does_not_retry_on_unlisted_codes` | function `retry_extraction(extract_fn, max_retries, retry_on) -> result_or_raises` | pytest |
| 3.5 | Context overflow detection | `src/extraction_service/llm/client.py` | `test_context_overflow_raises_loudly` (FakeOllama returns 400 with overflow indication) | catch Ollama's context-length errors, raise `ContextOverflowError` | pytest |
| 3.6 | Per-attempt _debug capture (dev mode) | `src/extraction_service/llm/client.py` | `test_dev_mode_captures_raw_request_and_response` | accept `mode` param; when development, attach raw payloads to result | pytest |
| 3.7 | LLM client timeout | `src/extraction_service/llm/client.py` | `test_llm_timeout_raises_llm_failed` | wrap call with `asyncio.wait_for`; map to `LlmError` | pytest |

**Exit criteria:** all unit tests pass; `scripts/prewarm.py` script can hit a real Ollama instance and get a valid JSON response. Commit, merge. *(Deviation: the `scripts/prewarm.py` half of this criterion was deferred to Phase 6 task 6.1 per [`docs/superpowers/specs/2026-05-13-phase-3-llm-spec-deviations.md`](superpowers/specs/2026-05-13-phase-3-llm-spec-deviations.md) §17.1 — see that file for rationale.)*

### 6.6 Phase 4 — Pipeline

**Goal:** asyncio queues, workers, result store. Single integration test runs OCR → LLM end-to-end with fakes.

**Worktree:** `phase-4-pipeline`

| # | Task | File | RED test | GREEN impl | Verify |
|---|---|---|---|---|---|
| 4.1 | `ResultStore` | `src/extraction_service/pipeline/result_store.py` | `test_result_store_concurrent_updates_are_safe` (spawn 100 concurrent tasks updating one record, assert no torn reads) | asyncio.Lock + dict; expose `create`, `update_stage`, `get` | pytest |
| 4.2 | `PipelineState` | `src/extraction_service/pipeline/state.py` | `test_pipeline_state_construct` — assert queues sized from settings | dataclass with intake_queue, interstage_queue, result_store, settings | pytest |
| 4.3 | OCR worker basic loop | `src/extraction_service/pipeline/ocr_worker.py` | `test_ocr_worker_processes_one_job` (push a ContractJob, await, assert it appears on interstage queue with `ocr.state=done`) | async generator/loop: pull → update state → call engine → update state → push | pytest |
| 4.4 | OCR worker handles OCR error | same | `test_ocr_worker_handles_ocr_empty_output` (FakeOcr raises `OcrEmptyOutputError`, assert record has `ocr.state=failed` and `data_parsing.state=pending`) | try/except OcrError, record on stage, do not push to interstage | pytest |
| 4.5 | LLM worker basic loop | `src/extraction_service/pipeline/llm_worker.py` | `test_llm_worker_processes_one_job` (push ocr-completed job, await, assert record has `data_parsing.state=done` and `extracted` populated) | async loop: pull from interstage → render prompt → call LLM client (with retry) → validate schema → update record | pytest |
| 4.6 | LLM worker respects retry policy | same | `test_llm_worker_retries_on_schema_invalid_max_times` | use retry policy from Phase 3.4 | pytest |
| 4.7 | Two LLM workers run in parallel | `tests/pipeline/test_llm_worker.py::test_two_lanes_concurrent` | push 4 jobs, await with a FakeOllama that sleeps 100ms; assert wall time ~ 200ms (two lanes), not 400ms (serialized) | start two `llm_worker` tasks; verify in test by timing | pytest |
| 4.8 | Idle watchdog | `src/extraction_service/pipeline/watchdog.py` | `test_idle_watchdog_triggers_shutdown_after_threshold` (set threshold 0.1s, assert callback fires; reset on activity, no fire) | task that loops checking `last_activity_at`; calls shutdown_callback | pytest |
| 4.9 | End-to-end pipeline test | `tests/pipeline/test_pipeline_e2e.py` | `test_full_pipeline_with_fakes` (push 4 jobs through real queues + fakes; assert all 4 emerge with `done`) | wire everything together in a TaskGroup | pytest |

**Exit criteria:** all pipeline tests pass. Commit, merge.

### 6.7 Phase 5 — HTTP layer

**Goal:** FastAPI app, three endpoints, response shaping per locked spec, lifespan wiring.

**Worktree:** `phase-5-http`

| # | Task | File | RED test | GREEN impl | Verify |
|---|---|---|---|---|---|
| 5.1 | FastAPI app skeleton + lifespan | `src/extraction_service/http/app.py` | `test_app_lifespan_starts_and_stops_workers` (use `httpx.AsyncClient(transport=ASGITransport(app=app))`, hit /health) | app factory with lifespan that creates state and starts workers | pytest |
| 5.2 | `GET /health` | `src/extraction_service/http/routes_health.py` | `test_health_returns_200_and_resets_idle_timer` | endpoint returns mode + queue stats; updates `last_activity_at` | pytest |
| 5.3 | `POST /contracts` happy path | `src/extraction_service/http/routes_contracts.py` | `test_post_contracts_returns_202_with_id` | accept `{pdf_base64, metadata}`; create record; push to intake queue; return 202 | pytest |
| 5.4 | `POST /contracts` returns 429 when intake full | same | `test_post_contracts_returns_429_when_intake_full` | catch `asyncio.QueueFull`; return 429 + error code | pytest |
| 5.5 | `POST /contracts` validates PDF size | same | `test_post_contracts_rejects_oversized_pdf` (set max 10MB in settings, send 11MB) | size check before queueing; 413 | pytest |
| 5.6 | `GET /contracts/{id}` returns status | same | `test_get_contracts_returns_status_shape` (compare against locked shape) | look up in result store; serialize per locked spec | pytest |
| 5.7 | `GET /contracts/{id}?include=ocr_text` returns text | same | `test_get_contracts_include_ocr_text_attaches_text`; assert default response has no text | parse query param; conditionally include | pytest |
| 5.8 | `GET /contracts/{id}` returns 404 for unknown id | same | `test_get_contracts_404_for_unknown_id` | result store .get returns None; raise HTTPException(404) | pytest |
| 5.9 | Idle shutdown wiring | `src/extraction_service/http/app.py` | `test_app_self_shuts_down_after_idle_threshold` (set 1s threshold, no requests, assert app exits) | watchdog from 4.8 calls `os.kill(os.getpid(), SIGTERM)` or similar | pytest |
| 5.10 | Dev mode adds _debug blocks | `src/extraction_service/http/responses.py` | `test_dev_mode_includes_debug_on_failed_stage` | response serializer checks settings.mode | pytest |

**Exit criteria:** all HTTP tests pass; manually `curl` against a running instance and inspect responses. Commit, merge.

### 6.8 Phase 6 — End-to-end, ops, hardening

**Worktree:** `phase-6-hardening`

| # | Task | File | What | Verify |
|---|---|---|---|---|
| 6.1 | Real Ollama smoke test script | `scripts/prewarm.py` | hits Ollama with a 1-token request to load the model | run manually before service start |
| 6.2 | OCR validation script | `scripts/validate_ocr.py` | iterates a folder of PDFs, runs the engine, dumps JSON + text outputs for human review | manual: run on 20 real contracts |
| 6.3 | Benchmark script | `scripts/benchmark_e2e.py` | runs N contracts through the live service, measures wall time, throughput, per-stage timing | manual |
| 6.4 | Pre-warm at startup | `src/extraction_service/http/app.py` | in lifespan, before returning ready, send a trivial chat to Ollama with the configured model | manual: time first real request, should not include cold-load |
| 6.5 | Ollama env script | `ops/ollama_env.sh` | exports all OLLAMA_* env vars + sysctl iogpu.wired_limit_mb=12000 | manual smoke test |
| 6.6 | README with run instructions | `README.md` | how to install, configure, run, troubleshoot | manual |
| 6.7 | End-to-end test against real Ollama (manual only, not CI) | `tests/e2e/` | one test that exercises the full path with real services; marked `@pytest.mark.e2e` and skipped unless `--e2e` flag | manual: `uv run pytest --e2e` |
| 6.8 | Idle-shutdown caveat documented | `README.md` | section explaining that any HTTP request (including /health) resets the timer; orchestrator must not heartbeat | review |
| 6.9 | Result store cleanup on shutdown | `src/extraction_service/pipeline/result_store.py` | on shutdown, log a final summary (counts of done/failed/in_progress) | review logs |

**Exit criteria:** end-to-end test passes against real Ollama on dev box; README sufficient for a stranger to set up and run. Commit, merge.

### 6.9 Task discipline rules (apply to every task above)

1. **No code without a failing test first.** If you can't write a failing test, the task is wrong-sized or wrong-shaped.
2. **Minimum implementation.** Don't add a feature that isn't required to pass the test. Future tests will add it.
3. **Commit at GREEN.** One task = one commit. Squash later if needed.
4. **Refactor only with tests passing.** Refactoring under red is debugging.
5. **Type-check + lint on every save.** Pre-commit hooks make this automatic.
6. **No `print()`.** Use structlog.
7. **No silent exception catches.** Every `except` either re-raises or logs *and* records the error.

---

## 7. Best Practices Reference (Always-On Checklist)

**Types & correctness**
- Every public function has full type hints. Return types included.
- `mypy --strict` is the merge gate.
- No `Any` in domain types. `Any` is acceptable only at IO boundaries (raw JSON parsing).
- Pydantic models are `frozen=True` unless they need to mutate.

**Async discipline**
- All I/O is `async`. No `requests`, no blocking file reads inside handlers.
- Synchronous library calls (Docling, jsonschema) run via `loop.run_in_executor` (deviation §17.9 in `2026-05-12-phase-2-ocr-spec-deviations.md`: `asyncio.to_thread` used instead — equivalent Python 3.9+ idiom).
- Every external call has a timeout (`asyncio.wait_for`).
- Use `asyncio.TaskGroup`, not `asyncio.gather`, for worker supervision.
- Cancellation is respected. Workers check `asyncio.CancelledError` in loops.

**State**
- No module-level mutable state. Everything goes through `PipelineState` or `ResultStore`.
- `ResultStore` writes are serialized through `asyncio.Lock`.
- `ResultStore` reads acquire the lock before serializing (to avoid torn JSON).

**Logging**
- structlog, JSON in production, pretty in development.
- Bind `contract_id` + `stage` into context at the start of each worker iteration.
- Every state transition logs once.
- Errors log with `exc_info=True` (or structlog equivalent).

**Errors**
- Custom exception hierarchy under `domain/errors.py`.
- Every public exception has a `code` class attribute.
- Errors are recorded on the stage object, not raised out of workers (workers shouldn't terminate on a single bad contract).
- HTTP handlers map only true HTTP-level errors to HTTPException (404, 429, 413).

**Configuration**
- All config is loaded once at startup via `Settings`.
- No `os.environ` reads outside `settings.py`.
- The run config file is loaded once and held in `app.state`.
- Validation failures crash the service at boot, not at first request.

**Testing**
- Unit tests are fast (<100ms each); pipeline tests use fakes; e2e tests are manual.
- Every public function has at least one test.
- Real-OCR tests parametrise over sample PDFs from `$EXTRACTION_OCR_SAMPLES_DIR` (gitignored; see deviation §17.3 in `2026-05-12-phase-2-ocr-spec-deviations.md`).
- `--strict-markers` and `--strict-config` in pytest catch typos.
- Coverage gate at 80%.

**Dependencies**
- Pin all dependencies via `uv.lock`.
- Production dependencies separate from dev dependencies.
- No dependency added without a real need.

**Memory**
- Docling and Ollama clients are process-lifetime singletons.
- Pre-warm Ollama at startup.
- Never load a second LLM model concurrently.
- Don't add background tasks without considering memory cost.

**Security (minimum)**
- Bind to 127.0.0.1, never 0.0.0.0.
- Validate PDF size before queueing.
- Validate run config schema before accepting it.
- No PDFs ever written to disk (in-memory only) unless explicitly asked.

---

## 8. Limitations, Risks, Open Items

### Must-validate-before-trust items

1. **OCR engine choice for watermarks/logos.** PP-OCRv5 via RapidOCR is the recommended starting point based on scene-text capability. **You MUST verify on real contracts before declaring Phase 2 done.** If watermark text or logo text is missed, options are: switch to server-grade PP-OCRv5 models (slower, more accurate); add a Tesseract `deu_frak` second pass on detected stamp/logo regions; fine-tune a custom PaddleOCR model on your domain.

2. **German recognition with PP-OCRv5 models.** The Chinese-trained PP-OCRv5 dictionary includes Latin characters but may struggle with ä/ö/ü/ß or German-specific punctuation. **Validate this explicitly** on a contract with rich diacritics. Fallback: use PaddleOCR's multilingual recognizer or Tesseract `deu`.

3. **`num_ctx=8192` adequacy.** A typical loan contract is 5–30 pages. OCR markdown of a 20-page contract may exceed 8K tokens. **Measure on your longest real contract before locking the config.** If you need 16K+, recalculate the 2-lane memory budget (it tightens; Scenario B from earlier conversation: ~15.7 GB, no headroom).

4. **Docling memory spikes.** Pathological PDFs (50+ pages of dense scans) can spike Docling memory to 4–6 GB transiently. The current spec runs Docling in-process. If you see FastAPI crashes correlated with specific contracts, refactor Docling to a subprocess with `resource.setrlimit(RLIMIT_AS, 3GB)` isolation per the prior conversation. Defer until observed.

### Behavioral caveats

5. **Idle-shutdown timer conflicts with orchestrator heartbeats.** If the orchestrator pings `/health` on a schedule, the service never idles out. The spec says any HTTP request resets the timer. **The orchestrator must not heartbeat ping** — only ping when it has work or genuinely wants status. Document this in README.

6. **In-memory result store loses everything on restart.** A contract acknowledged with 202 is in RAM only. If the service crashes, the orchestrator must track its own submissions and resubmit. Acceptable for v1; deferred.

7. **No backpressure beyond 429.** When intake is full, orchestrator gets 429 and must retry. No `Retry-After` semantics. Orchestrator decides backoff.

8. **Single-machine, single-process.** No horizontal scaling. If throughput is insufficient, upgrade to a 24 GB M4 Pro Mini before adding architectural complexity.

### External dependencies

9. **Ollama must be running with correct env.** Service assumes `ollama serve` is already running with `OLLAMA_NUM_PARALLEL=2`, KV q8_0, etc. If Ollama crashes or wasn't started with these settings, the service can't detect this beyond connection errors. Manual operational responsibility.

10. **Docling/RapidOCR model downloads at first run.** Pre-fetch in CI or a setup script. Don't make the first POST request pay the download cost.

### Things you might be tempted to do but shouldn't (yet)

11. Don't add OpenTelemetry until you've observed a problem logs don't surface.
12. Don't add SQLite persistence until restart loss becomes a real operational issue.
13. Don't add multi-model concurrent loading until you upgrade to ≥24 GB hardware.
14. Don't switch from Gemma 4 to another family until you have F1 numbers on Gemma E4B and confirmed they're insufficient.
15. Don't add HTTPS until the service moves off localhost.

---

## 9. Stretch Items / Do These Later

| Item | Trigger to do it | Effort |
|---|---|---|
| SQLite persistence for result store | Restarts losing in-flight work becomes operationally painful | 1 day |
| Auto-expire result store entries (1h TTL + DELETE endpoint) | Result store grows unbounded across long sessions | 0.5 day |
| Authentication (API key in header) | Service moves off localhost | 0.5 day |
| HTTPS via reverse proxy (Caddy/nginx) | Network exposure required | 0.5 day |
| OpenTelemetry tracing | Multiple components, distributed deploys | 2 days |
| Prometheus `/metrics` endpoint | You want time-series dashboards | 1 day |
| Container deployment (Dockerfile) | You stop running on the M4 Mini | 1 day |
| Cross-family model swaps (Qwen, Llama) | Gemma 4 quality insufficient | 2–3 days (re-validation) |
| Subprocess isolation for Docling | Docling memory spikes crash service | 1 day |
| MTP speculative decoding | Throughput inadequate on E2B/E4B | 1 day exploration, may regress |
| Fine-tuned PaddleOCR for German legal | Watermark/logo recall on real samples insufficient | 1–2 weeks; needs annotated data |
| Multi-pass OCR (PP-OCRv5 + Tesseract `deu_frak`) | Fraktur regions consistently missed | 1 day |
| Vision-direct OCR via Gemma 4 (no Docling) | Ollama #15626 fixed AND OCR-first proven inadequate | 2 days |
| `/contracts/{id}?include=extracted` opt-in | Result payloads become large | 1 hour |
| Webhook callbacks on completion | Orchestrator wants push not poll | 1 day |

---

## 10. Appendix — Sources

- Docling: https://docling-project.github.io/docling/, https://github.com/docling-project/docling
- Docling RapidOCR with custom models: https://docling-project.github.io/docling/examples/rapidocr_with_custom_models/
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- PaddleOCR PP-OCRv5: https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
- PP-OCRv5 multilingual (German listed): https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
- RapidOCR: https://github.com/RapidAI/RapidOCR
- Tesseract Fraktur: https://github.com/tesseract-ocr/tesstrain/wiki/Training-Fraktur
- Wextract (watermark text spotting): https://arxiv.org/abs/2401.05167
- Surya OCR: https://github.com/datalab-to/surya
- Superpowers: https://github.com/obra/superpowers
- uv: https://github.com/astral-sh/uv
- Ruff: https://docs.astral.sh/ruff/
- FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/
- pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- structlog: https://www.structlog.org/
