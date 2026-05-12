# Phase 2 (OCR layer) — spec deviations

This file records material deviations from [docs/plan.md §6.4](../../plan.md)
introduced during Phase 2 development. Append a new `§17.N` subsection per
pass; do not retroactively rewrite earlier subsections. Convention mirrors
the Phase 0.5 spec at
`docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md §17`.

---

## §17.1 — Task 2.5 (watermark sample test) DROPPED

**Plan text:** "DoclingOcrEngine handles watermark sample — add
`sample_with_watermark.pdf`; assert OCR result contains watermark word".

**Deviation:** Task 2.5 is dropped in its entirety.

**Why:** User feedback (2026-05-12 session): "watermarks on contracts will in
97% of the cases not exist". The Austrian/German bank credit contracts that
make up the actual corpus this service will ingest do not bear watermarks
the OCR layer needs to capture. The Task 2.5 test as written would either
require a synthetic-watermark PDF (testing OCR against a fabricated signal
that doesn't represent real input) or commit a real watermarked contract
(privacy violation in a public repo). Neither serves the validation
purpose the plan intended.

`force_full_page_ocr=True` — the underlying mechanism Task 2.5 was meant to
verify — is still enforced. It flows from `OcrConfig.force_full_page_ocr`
into `RapidOcrOptions(force_full_page_ocr=...)` in
`_build_default_converter`. If a real-world watermark requirement ever
surfaces, the wiring is in place; the verification test would re-land in
Phase 6's `scripts/validate_ocr.py` manual gate rather than as a unit test.

---

## §17.2 — Task 2.6 (logo sample test) REFOCUSED

**Plan text:** "DoclingOcrEngine handles logo text sample — similar with
`sample_with_logo.pdf`".

**Deviation:** Task 2.6 is not a separate test file; the logo-text-extraction
concern is folded into the Task 2.4 parametrised real-OCR test. Semantic
logo identification ("this logo = Bank X") is explicitly **deferred to a
later phase or never** per user direction.

**Why:** User feedback: logo text extraction matters (banks' names live
inside stylised-font logos and the LLM stage needs that text for issuer
identification), but the relevant signal is "the OCR captured the text
glyphs inside the logo graphic". That signal is identical to "the OCR
captured all the text on the page" — which is exactly what the Task 2.4
real-OCR test verifies via the `tests/ocr/conftest.py::word_recall` metric
against the `.txt` baseline. A separate test would add complexity (a
second parametrise dimension, a second baseline format) without adding
distinct signal.

Semantic logo identification ("the logo is from Bank Volksbank") is a
classification problem belonging to the LLM stage at earliest (Phase 3+),
and is deferred per user direction "no logo extraction atm; leave that
for later".

---

## §17.3 — Test strategy: real PDFs + Claude-produced `.txt` baselines

**Plan text:** "pass a tiny PDF (committed to `tests/ocr/data/sample_clean.pdf`),
assert returned text contains expected snippet" (Task 2.4 GREEN).

**Deviation:** Real-OCR validation runs against a user-provided corpus of
~20 Austrian/German bank credit contracts at a stable in-project path
(`/Users/cosminneamtiu/Work/contract-data-extraction/tests/ocr/data/` —
**not** inside a worktree, so worktree cleanup preserves them). Both the
source PDFs and their `.txt` baseline transcriptions are gitignored; only
the `.gitkeep` placeholder + gitignore rules are committed. Tests resolve
the directory via `$EXTRACTION_OCR_SAMPLES_DIR`; auto-skip when unset.

The `.txt` baselines are produced by **Claude reading each PDF directly**
(via the native PDF support in the Read tool) and writing the ground-truth
transcription alongside each PDF. This is a one-time operation per PDF; the
baselines persist locally. Tests compare OCR output against baseline via
word-set recall (≥ 0.85 threshold) — robust to OCR jitter (hyphen splits,
whitespace, glyph swaps) while still failing when meaningful content is
missed.

**Why:** Three reinforcing constraints.

1. **Public repo, sensitive content.** The 20 PDFs are real bank credit
   contracts with personal names, account numbers, and amounts. Committing
   them — even with cosmetic anonymisation — is incompatible with the
   public repo. Synthetic PDFs (reportlab-generated text with overlaid
   "watermark") are also poor validation: they exercise born-digital text
   reading, not the rasterised-scan OCR path the production code will
   handle.

2. **Plan §6.4 already prescribes a manual validation gate.** The
   `scripts/validate_ocr.py` step ("run on 5–10 of your actual contracts;
   manually inspect") is the real-world validation. Unit tests against
   real PDFs duplicate that work; the cleaner separation is "unit tests
   verify wiring and glue; the manual gate verifies real-world OCR
   quality".

3. **Test infrastructure works incrementally.** Without baselines the
   test falls back to a smoke assertion (non-empty result, page_count
   ≥ 1). As baselines arrive (transcribed by Claude in a follow-up task
   or by the user), the assertion tightens automatically. The test code
   doesn't change — only the data directory grows. Failures name the
   sample by ordinal index (`sample_#N`), never by filename, so personal
   data doesn't leak into pytest output / report XML / CI logs.

The `EXTRACTION_OCR_SAMPLES_DIR` env var lets the canonical directory live
anywhere the developer prefers — including outside the repo entirely. The
user's preference (2026-05-12 session) is to keep it inside the project
folder (at `tests/ocr/data/`) but outside any `.worktrees/` worktree, so
worktree cleanup doesn't take the samples with it.

---

## §17.4 — `OcrEngineFactory`: `raise on unknown` clause omitted

**Plan text:** Task 2.7 GREEN: "switch on `run_config.ocr.engine` string;
raise on unknown".

**Deviation:** `build_ocr_engine` uses `match run_config.ocr.engine: case
"docling": return DoclingOcrEngine(...)` with no `case _:` fallback.

**Why:** `OcrConfig.engine` is typed `Literal["docling"]` — a closed 1-arm
Literal. Mypy proves exhaustiveness statically without a runtime guard.
The "raise on unknown" branch is unreachable today and would be dead code.
When Phase 3+ broadens the Literal (e.g., adds `"tesseract"` for the
Fraktur fallback per plan §2.3), mypy fails with "Missing return
statement" until a new `case` arm lands — pointing future contributors
directly at this file. This is exactly the Phase-1-panel-pass §17.9
precedent (`assert_never` on a 2-arm Literal was rejected as ceremony;
type-system exhaustiveness was treated as sufficient).

---

## §17.5 — Task 2.9 extended with `ConversionStatus.FAILURE` handling

**Plan text:** Task 2.9 RED specifies two test cases:
`test_docling_extract_empty_output_raises_ocr_empty_output` and
`test_docling_internal_exception_wraps_as_ocr_engine_failed`.

**Deviation:** A third test
(`test_docling_extract_failed_conversion_status_raises_ocr_error`) and
corresponding production check were added. The engine now raises
`OcrError("ocr_engine_failed")` when `ConversionResult.status != SUCCESS`,
in addition to wrapping exceptions and detecting empty markdown.

**Why:** Docling exposes "soft" failures (recoverable parse errors, missing
layout model, OCR-region detection failure) by returning a
`ConversionResult` with `status=FAILURE` rather than raising. Without an
explicit check, a failed conversion would silently propagate as a partial
or empty `OcrResult.text` and the LLM stage (Phase 3) would chew on
garbage. The check is defense-in-depth with zero current false-positive
risk: any real-world failed conversion will benefit from being surfaced at
the OCR boundary rather than discovered downstream in the prompt
construction. The third test verifies the check fires; the existing
success-path tests now set `fake_result.status = ConversionStatus.SUCCESS`
to acknowledge the new check explicitly.

---

## §17.6 — `TimeoutError` propagates unwrapped from `extract`

**Plan text:** Task 2.9 GREEN: "try/except in extract, map to `OcrError`
subclasses".

**Deviation:** `TimeoutError` is the one exception the engine does **not**
wrap. The try block re-raises it explicitly before the generic
`except Exception → OcrError` catch.

**Why:** Two diagnostic signals deserve to be distinct at the caller's
seam. `TimeoutError` means "OCR did not complete within the configured
budget" — a runtime/resource concern. `OcrError("ocr_engine_failed")`
means "OCR attempted but failed structurally" — a content/configuration
concern. Phase 4's worker code (per plan §3.3 "OCR errors are
deterministic on the input and therefore never retried") will log and
attribute these differently. Collapsing them into a single error code
loses information that's already there in the exception type.

Plan §3.3 / `run_config.py`'s `_OCR_RETRY_CODES_REJECTED` validator
already rejects retry-on for OCR error codes; that policy is unchanged
by the unwrapped `TimeoutError`. If Phase 4 needs a uniform "OCR failed"
classification, it can wrap timeout itself at the worker boundary.

---

## §17.7 — CLAUDE.md tightening: parallel-per-layer trigger language

**Plan text:** N/A — methodology refinement, not a §6.4 task.

**Deviation:** CLAUDE.md "Phase development methodology" section gains an
explicit "parallel dispatch is the default for any layer with ≥2
file-disjoint tasks" paragraph and the "When NOT to use this methodology"
exception is rewritten to clarify it's a per-WHOLE-PHASE threshold, not
per-layer. New memory note at
`~/.claude/projects/.../memory/feedback_parallel_dispatch_default.md`.

**Why:** The methodology said "parallel subagent dispatch is the wall-clock
multiplier" and "fall back to serial when ≤2 independent tasks" — wording
ambiguous enough to be misread as licensing serial fallback on individual
2-task layers. The Phase 2 worked example (Layer B = {2.2, 2.3} = 2
file-disjoint tasks → parallel dispatch correctly applied; Layers C–F
forced serial by shared `docling_engine.py` → main-conversation TDD) is
now embedded in the methodology so future re-reads can't accidentally
invent a new exception. Recorded in commit `5bf0ee2`.

---

## Phase 2 commit log

| Commit | Subject | Task |
|---|---|---|
| `cafb514` | feat(2.1): OcrResult + OcrEngine Protocol | 2.1 |
| `5bf0ee2` | docs(claude): codify parallel-per-layer trigger | (methodology) |
| `b1f45b9` | feat(2.2): FakeOcrEngine helper | 2.2 |
| `91edbf7` | feat(2.3): DoclingOcrEngine skeleton | 2.3 |
| `093027f` | feat(2.7): OcrEngineFactory | 2.7 |
| `c1f7a0c` | chore(gitignore): exclude local sample PDFs | (infra) |
| `9c7b35b` | chore(tests): slow marker + samples fixture | (infra) |
| `5d1c780` | feat(2.4): DoclingOcrEngine.extract() body + tests | 2.4 (+ 2.6 merged) |
| `0b660b3` | feat(2.8): extract enforces timeout | 2.8 |
| `0d24644` | feat(2.9): wrap OCR failures as OcrError | 2.9 |

Tasks 2.5 dropped (§17.1). Task 2.6 absorbed into 2.4 (§17.2). Future
panel-review passes appending to this file should use `§17.8`, `§17.9`, etc.
