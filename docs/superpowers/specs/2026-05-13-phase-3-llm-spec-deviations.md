# Phase 3 (LLM layer) — spec deviations

This file records material deviations from [docs/plan.md §6.5](../../plan.md)
introduced during Phase 3 development. Append a new `§17.N` subsection per
pass; do not retroactively rewrite earlier subsections. Convention mirrors
the Phase 2 spec at
`docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md §17` and
the Phase 0.5 spec at
`docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md §17`.

---

## §17.1 — `scripts/prewarm.py` exit-criterion DEFERRED to Phase 6

**Plan text:** Phase 3 exit criteria ([docs/plan.md §6.5 line 756](../../plan.md)):
"all unit tests pass; `scripts/prewarm.py` script can hit a real Ollama
instance and get a valid JSON response. Commit, merge."

**Deviation:** Phase 3 ships the LLM layer code (tasks 3.1–3.7) but does
NOT include `scripts/prewarm.py`. The unit-test gate alone is treated as
the sufficient exit signal for Phase 3.

**Why:** `scripts/prewarm.py` is later re-assigned to Phase 6
([docs/plan.md §6.8 line 805](../../plan.md), task 6.1: "Real Ollama smoke
test script — hits Ollama with a 1-token request to load the model").
The plan has two references to the same artifact — Phase 3 exit criteria
and Phase 6 task 6.1 — that disagree about ownership. Phase 6 is the
correct home because: (1) prewarm requires a running Ollama process,
which makes it a manual / ops artifact rather than a unit-test concern;
(2) it pairs naturally with Phase 6 task 6.4 ("Pre-warm at startup —
in lifespan, before returning ready, send a trivial chat to Ollama")
which calls the same code path from the FastAPI lifespan; (3) Phase 3's
genuine deliverable is the LLM-client *library* code, which is
verifiable end-to-end via the 15-test suite against `FakeOllamaClient`
without needing real Ollama.

**How to apply:** Treat Phase 3 as complete when unit tests pass and the
verification gate (`uv run ruff check`, `uv run mypy`, `uv run pytest`,
`uv run pip-audit`, `uv run pre-commit run --all-files`, `uv build
--wheel`) is green. The `prewarm.py` script lands in Phase 6.

---

## §17.2 — Minor cosmetic deviations (PR body-level only)

The following minor design choices ship as Phase 3 deliverable but are
NOT material — they appear here only as a stable record of the
"why-this-shape" decisions for future maintainers:

1. **PEP 695 generic syntax in `retry.py`.** `async def retry_extraction[T](...)`
   over module-level `T = TypeVar("T")`. The project pins Python 3.13 in
   `.python-version`, `pyproject.toml [project] requires-python`, and
   `[tool.mypy] python_version`; PEP 695 is the idiomatic native form on
   3.12+. No behavioral or type-safety difference.

2. **Private structural protocols in `client.py`** (`_ChatResponse`,
   `_ChatMessage`, `_ChatClientProtocol`). Keeps `ollama.AsyncClient`
   from being imported at module load time, lets `FakeOllamaClient`
   structurally satisfy the wrapper's expected client shape without
   subclassing, and makes the test seam explicit. Equivalent to the
   Phase 2 OCR pattern (`OcrEngine` Protocol in `ocr/base.py`).

3. **`Sequence[str | int]` path typing in `schema.py`.** Matches
   `jsonschema.absolute_path`'s typed shape directly (via
   `jsonschema-stubs`), avoiding a `cast()` to `deque[str | int]` plus a
   `# type: ignore` rationale that would only restate the cast.

4. **`_debug` block as underscore-prefixed top-level key in `extract()`
   result (dev mode).** Returns `dict[str, Any]` with `_debug` as a
   sibling key alongside the LLM's structured output. Convention: any
   leading-underscore key is side-channel metadata; downstream code
   (Phase 4 worker → `data.pop("_debug", None)` before validator;
   Phase 5 HTTP response shaping → strip-or-include per request mode)
   handles it explicitly. The alternative (storing on
   `self._last_debug` instance attribute) has reentrancy problems
   because Phase 4 runs two LLM workers per plan §3.5 that may share
   the same `OllamaLlmClient` singleton. A typed return wrapper would
   change the task-3.1 spec contract (`extract -> dict[str, Any]`).

   This is FLAGGED for re-evaluation at Phase 5 when HTTP response
   shaping is being designed and the PII-leakage concern from a panel
   review against this PR becomes concrete. The convention is the
   right default for Phase 3; Phase 5 may choose to switch to a typed
   wrapper once it has a concrete serialization path to defend.

**How to apply:** None of these need to change in Phase 3. The PII
re-evaluation is a Phase 5 design decision; no Phase 4 work is gated.
