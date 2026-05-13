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
panel-review passes appending to this file should use `§17.9`, `§17.10`, etc.

---

## §17.8 — Phase 2 PR #10 self-review (single-pass, 20 lenses)

**Pass type:** Single pass. PR #10 was opened as draft after the development
phase landed. Per the project's two-phase Superpowers flow (Pass 1 dev → Pass
2 self-review → mark ready), the 20-lens panel fired against
`e817817..c3cf1d8` (Phase 2's added commits, NOT against current `origin/main`
which has moved to PR #9's HEAD `96ab536` during this work).

**Verdicts:** 12 of 20 lenses Ship-ready Yes; 8 With fixes; 0 No.

**Convergent finding (3 lenses):** Lenses 11 (CI workflow), 15 (CI test
execution), and 20 (Workflow/automation gotchas) all flagged the
pyproject.toml `markers` description text "CI runs them as part of the full
sweep" as factually wrong — CI does not (and now explicitly will not) run
slow tests. Triple-lens convergence promoted this comment-drift item to
load-bearing factual fix.

**Synthesiser-decided headbutting:**

- Lens 15 said the existing env-var-driven slow-test skip is correct; Lens 20
  said it is fragile and recommended `-m "not slow"` as defense-in-depth.
  Both correct; synthesiser sided with Lens 20 — added the marker filter to
  CI's pytest invocation so the slow-test skip no longer depends solely on
  the env var being unset in the runner environment.

- Lens 13 raised the unspecified contract on `document.pages = {}` and
  suggested either "test asserts page_count=0" OR "raise OcrError". The
  synthesiser picked "assert page_count=0" — pinning the current
  implementation, not changing behaviour. A future iteration that wants to
  raise on empty pages will see the test fail first and be forced to make
  the change deliberately.

**Fixes applied this pass (panel-derived, on the same `phase-2-ocr`
branch):**

| Commit | Subject | Lens(es) | Severity |
|---|---|---|---|
| `a4b66b3` | refactor(ocr): use asyncio.to_thread + sync docstrings to assembled state | 08, 17 | Important |
| `d855107` | test(ocr): pin word_recall metric contract + empty-baseline sentinel | 13 | Important |
| `7286644` | test(fakes): pin FakeOcrEngine OcrEngine Protocol conformance | 13 | Important |
| `45e834a` | fix(ci): add `-m "not slow"` + correct pyproject markers comment | 11, 15, 20 (convergence) | Important |
| `05766a5` | fix(ocr): canonicalise samples dir + drop dead fixture + sync §17 ref | 10, 14, 16, 17 | Important / Minor |
| `baefb25` | test(ocr): pin extract page_count=0 contract on empty document.pages | 13, 09 | Important / Minor |
| `d080a40` | docs(panel): fix doc/comment drift surfaced by lenses 04/06/17/19 | 04, 06, 17, 19 | Minor (substantive cosmetic) |

**Deferred — waiting on later-phase code (4a):**

- `scripts/validate_ocr.py` real-corpus validation gate (Phase 6 task 6.2;
  Lens 01). The plan-text reference to running this script "before declaring
  Phase 2 done" is an internal plan inconsistency — the same plan's file-tree
  annotation labels `scripts/` as "Phase 6 — not yet created" and §6.8 task
  6.2 formally assigns the script's creation to Phase 6. Re-flag in the
  Phase 6 panel pass if it hasn't landed by then.
- Phase 3+ factory-test expansion (Lens 13 Minor). The single-arm `match` in
  `factory.py` is complete for the current closed Literal; when Phase 3 or
  later broadens `OcrConfig.engine`, the factory test needs a parallel
  expansion. Will re-trigger naturally at that point.
- ONNX model integrity check post-`snapshot_download` (Lens 10 Minor).
  modelscope's own download protocol already verifies wheel integrity; an
  application-level checksum assertion is a Phase 6 hardening item.
- `--cov` activation in CI (Lens 15 Important). Phase 0.5's §17.2 deferred
  the coverage gate to "when non-stub coverage exists". Phase 2 ships
  non-stub production code, so the deferral condition is technically met,
  but activating `--cov-fail-under=80` mid-Phase-2 is out of this PR's
  declared scope. Re-trigger at the next panel pass after this PR merges.

**Deferred — other reasons (4b):**

- `feat(2.3)` and `feat(2.4)` commit-message phrasing ambiguities (Lens 02
  Importants). The project rule "prefer to create a new commit rather than
  amending an existing commit" applies; rewriting these would require
  destructive history edits on a branch about to be squash-merged anyway.
  The eventual squash subject (chosen by the user at merge time via GitHub
  UI) supersedes the individual subjects and is the right surface to make
  precise. No code/doc fix needed in this pass.
- Lens 03's "docs/plan.md was edited mid-Phase-2" finding (Minor) — **FALSE
  POSITIVE.** `git diff e817817..c3cf1d8 -- docs/plan.md` is empty; Lens 03
  misread the git diff range and saw PR #9's main-side changes as if they
  were on this branch. Demoted in synthesis. No fix.
- Lens 03's "CLAUDE.md methodology reversal" finding (Minor) — **FALSE
  POSITIVE** by the same misread. This branch's CLAUDE.md only adds the
  parallel-per-layer paragraph (5bf0ee2); it does not reverse PR #9's
  changes because PR #9 isn't yet on this branch's base. Merge-time conflict
  resolution belongs to the user at GitHub-UI level. Demoted; no fix.
- Several ceremonial-cosmetic Minors filtered out per the CLAUDE.md
  senior-dev judgment filter: bare `"docling"` string in test (Lens 06),
  `from __future__ import annotations` inconsistency across test files
  (Lens 09), `_ENGINE_NAME` single-use constant inline-vs-keep call (Lens
  07; synthesiser KEEP — the named constant is informational), README
  forward-architecture references (Lens 17 — user-restricted, flag only),
  tag-vs-SHA pinning on external pre-commit repos (Lens 18 — pre-existing
  from Phase 0.5, out of Phase 2 scope).

**Convergence with project rules:** the senior-dev filter (CLAUDE.md
"Senior-developer judgment filter") was applied throughout. The triple-lens
convergence on the pyproject markers comment overrode the
filter-out-as-ceremonial reading some readers might apply to "just a
comment" — convergence is the signal the filter cannot override.

**Loop status:** single-pass mode (this is the first review of this branch).
If a follow-up pass is desired ("rerun the review"), it would target the
current branch HEAD (now `d080a40`) and use the loop-mode rules from
CLAUDE.md.

---

## §17.9 — `asyncio.to_thread` substitution (plan §6.4 task 2.8 wording)

**Plan text:** Task 2.8 GREEN column reads "wrap `.convert()` call in
`asyncio.wait_for` (Docling is sync; run via `loop.run_in_executor`)". Plan
§5 architecture note ("Synchronous library calls run via `loop.run_in_executor`")
restates the same phrase.

**Deviation:** `extract()` uses `asyncio.to_thread(self._converter.convert,
stream)` instead of `loop.run_in_executor(None, self._converter.convert,
stream)`. The `asyncio.wait_for` timeout wrap around it is unchanged.

**Why:** `asyncio.to_thread` is the modern Python 3.9+ idiom for offloading
a sync call to the default thread pool — it is exactly `loop.run_in_executor(None, fn, *args)` with less boilerplate, the same thread-pool semantics, the
same cancellation behavior (the underlying thread keeps running until the
sync call returns naturally; asyncio cancels the awaiter, not the thread).
There is no observable behavior difference. Lens 08 of the cycle-1
post-merge panel surfaced the verbose form as an idiom regression relative
to the test file's own `asyncio.to_thread` usage (`test_docling_engine.py`
already uses `to_thread` for its sync `read_bytes` call), creating an
in-codebase inconsistency the project's senior-dev filter would normally
reject. Commit `a4b66b3` applied the substitution. This §17.9 entry
documents the plan-vs-implementation phrasing gap that was not recorded at
the time of the commit — closing the audit-trail gap Lens 01 of the
cycle-1 panel-loop review identified.

Plan §6.4 task 2.8 (and §5) keep their original `loop.run_in_executor`
phrasing intact (not retroactively rewritten per the deviation-log
convention); future readers reconciling the plan against the code find this
§17.9 entry naming the substitution.

---

## §17.10 — Cycle-1 of post-merge panel-loop review

**Pass type:** Loop mode, cycle 1 (HEAD=7c9b1c2, BASE=origin/main=e160593).
Triggered by user request "review only work resulting from phase 2 ... apply
on current branch and loop until convergence." 20 lenses dispatched in
parallel with clean prompts (no carryover from §17.8 — cycle independence).
19 of 20 returned proper reports; 1 (Lens 02 Commit-message coverage)
bailed citing a perceived Bash-access issue and was re-dispatched.

**Verdicts (cycle 1):** 7 Yes; 12 With fixes; 0 No (one lens pending at
synthesis time).

**Hallucinated findings filtered out (4 lenses claiming "main has X, this
branch is missing X" where direct `git show origin/main:...` verification
showed main does not have X either):**

- Lens 08: claimed main has `G` (flake8-logging-format) ruff rule. Main's
  ruff `select` ends at `"ANN"` — verified, G absent.
- Lens 11: claimed main has `--tb=short` in ci.yml `Tests` step. Main's
  step runs `uv run pytest -q` — verified, no `--tb=short`.
- Lens 12: claimed main raised floors to `docling>=2.93`, `fastapi>=0.136`,
  `uvicorn[standard]>=0.46`, `modelscope>=1.36`, `httpx>=0.28`. Verified
  main has exactly the same floors as phase-2-ocr (`docling>=2.20`,
  `fastapi>=0.115`, `uvicorn>=0.32`, `modelscope>=1.20`, `httpx>=0.27`).
- Lens 18: claimed main has `exclude: '^\\.secrets\\.baseline$'` on the
  detect-secrets hook. Verified main's hook has no exclude directive.

The probable source of the hallucinations is that some agents read the
wrong branch when verifying (the user has a separate
`chore/panel-review-fixes-2026-05-13` branch in the main checkout that
DOES carry those upgrades). The synthesizer's senior-dev filter caught
all four false positives via direct `git show origin/main` verification
before applying any change.

**Fixes applied this cycle (5 Objective items after filter):**

1. (this entry) §17.9 added for `asyncio.to_thread` audit trail — Lens 01
   Important.
2. `extract()` now appends `result.errors` detail to the OcrError message
   when Docling returns a non-SUCCESS `ConversionStatus`, using
   `getattr(result, "errors", None)` to stay robust across Docling version
   changes — Lens 05 Important (operator debuggability in production).
3. Removed the unused session-scoped `ocr_samples_dir` fixture from
   `tests/ocr/conftest.py`; the `_resolve_samples_dir` helper remains the
   canonical resolution path, used by `pytest_generate_tests` directly —
   Lens 14 Important (dead code).
4. ci.yml `Tests` step now invokes `pytest -q -m "not slow" --cov
   --cov-fail-under=80`, activating the coverage gate. Phase 0.5 §17.2
   deferred this to "when non-stub coverage exists" — Phase 2 ships the
   non-stub OCR layer so the deferral condition is met — Lens 15
   Important.
5. `docs/plan.md` §6.4 task table cells for tasks 2.4 / 2.5 / 2.6 now
   carry inline `(deviation §17.1 / §17.2 / §17.3)` parentheticals
   pointing readers at this spec file when the original wording mentioned
   committed sample PDFs — Lens 17 Important (doc sync after divergence).

**Deferred or filtered to drop:**

- Lens 03 Minor (Phase 1 forward-coupling of LlmConfig/RetryConfig) —
  pre-existing accepted deviation from plan task 1.7; not a Phase 2
  regression.
- Lens 04 Minor (Protocol from typing vs collections.abc) — ceremonial
  cosmetic; senior-dev filter drop.
- Lens 06 Minors (WORD_RECALL_THRESHOLD placement / build_ocr_engine
  re-export hint / `_resolve_samples_dir` duplication note) — style
  observations; filter.
- Lens 07 Minor (`_ENGINE_NAME` single-use vs `OcrConfig.engine`) —
  borderline; synthesizer KEEPS the named constant (documentation
  anchor + Phase 3+ Literal-broadening guardrail).
- Lens 09 Minors (factory.py TYPE_CHECKING asymmetry / word_recall in
  conftest style) — style observations; filter.
- Lens 10 Important (test-fixture env-var path containment) — lens
  self-deferred as "developer-machine-only, requires env var compromise";
  filter (defensive against impossible state in scope).
- Lens 13 Importants/Minors (smoke-mode permissiveness in slow OCR test;
  test of Pydantic field accessors) — accepted architectural deferral to
  `scripts/validate_ocr.py` Phase 6 gate; senior-dev filter
  "testing third-party library behavior" drop on the Pydantic-accessor
  tests.
- Lens 16 Important (`isolated_env` + `ocr_samples_dir` coupling) —
  obsolete after Fix 3 above removed `ocr_samples_dir` entirely.
- Lens 17 Minor (§17.8 HEAD SHA stale) — historical record, intentionally
  not retroactively rewritten per the deviation-log convention.
- Lens 19 Minor (vscode carve-out comment regression) — style
  observation; filter.
- Lens 20 Minor (comment drift on `-m "not slow"`) — verified false
  positive (the ci.yml comment is accurate).

**Loop status:** cycle 1 applied 5 fixes (plus this §17.9/§17.10 audit
entry). Cycle 2 will fire fresh against the new branch HEAD per the
cycle-independence rule.

---

## §17.11 — Cycle-2 of post-merge panel-loop review

**Pass type:** Loop mode, cycle 2 (HEAD=bd3879c at dispatch time → e86ae43
after fixes, BASE=origin/main=e160593 — same as cycle 1 per the
cumulative-diff rule). Triggered automatically per CLAUDE.md loop-mode
"continue while cycle produces commits". 20 lenses dispatched in parallel
with clean prompts (no carryover from cycle 1 — cycle independence). 20 of
20 returned proper reports this cycle (Lens 02 re-dispatch from cycle 1
succeeded, so cycle 2 dispatched a fresh Lens 02 alongside the other 19;
all 20 returned cleanly with no bails).

**Verdicts (cycle 2):** 10 Yes; 10 With fixes; 0 No. Marked improvement
over cycle 1's 8/12 split.

**Convergent findings (≥2 lenses agree — load-bearing per CLAUDE.md):**

- **Lens 11 Important + Lens 20 Minor** on `--cov-fail-under=80` redundant
  CLI flag creating dual source of truth with pyproject.toml's
  `[tool.coverage.report].fail_under`. Promoted; fixed via single source
  of truth on pyproject.
- **Lens 15 Important + Lens 20 Minor** on the stale "Inert until --cov
  is added" comment in pyproject.toml `[tool.coverage.report]` —
  factually false since cycle-1's c6550c8 activated `--cov`. Promoted;
  comment rewritten with an active-gate note + warning against future
  CLI/config drift.
- **Lens 01 Important + Lens 17 Minor** on factory.py's unqualified
  `§17.9` reference becoming ambiguous after Phase 2 created its own §17
  namespace (this very file's §17.9 covers asyncio.to_thread; the
  factory was referencing CI/CD spec §17.9 about closed-Literal
  exhaustiveness). Promoted; qualified the cross-file reference.
- **Lens 02 Minor + Lens 17 Minor** on the dangling `(§17.9)`
  parenthetical in `ocr/__init__.py`'s docstring — points at no
  authoritative §17.9 in either spec file (neither CI/CD's §17.9 about
  `assert_never` nor Phase 2's §17.9 about asyncio.to_thread covers
  `__all__` omission policy). Promoted; dropped the parenthetical.

**Fixes applied this cycle (9 atomic per-concern commits):**

| Commit | Subject | Lens(es) | Severity |
|---|---|---|---|
| `bf6e018` | fix(coverage): drop CLI --cov-fail-under + sync coverage config audit comments | 11+20, 15+20 (both convergent), 15 Minor | Important×2 + Minor |
| `c1fb090` | fix(types): correct docling_engine.py audit comments on stub coverage | 04 | Minor (substantive cosmetic — Known Workflow Gap #3) |
| `b2a1c26` | docs(spec): disambiguate cross-file §17 references in ocr/ docstrings | 01+17, 02+17 (both convergent) | Important + Minor |
| `7d2ce86` | docs(plan): sync §6.4 Goal blurb + add §17 parentheticals on tasks 2.7/2.8/2.9 | 17 | Important |
| `a009fb6` | docs(ocr): sync OcrEngine Protocol docstring with asyncio.to_thread | 09 | Minor (substantive cosmetic) |
| `1f8b16d` | test(ocr): named skip on env-unset + document collection-time env invariant | 14, 16 | Important×2 |
| `20f5856` | test(ocr): drop 3 tautological Pydantic-accessor tests on OcrResult | 13 (re-surfaced from cycle 1 Minor → cycle 2 Important) | Important |
| `566f21a` | chore(hygiene): add *.onnx to ignored model-weights + reference Phase 2 spec in CLAUDE.md | 10 Minor, 17 Minor | Minor×2 (substantive cosmetic) |
| `e86ae43` | docs(readme-queue): route "golden tests" wording drift to README queue | 17 Minor | Routing (README user-restricted) |

(Note: bf6e018 also folded in the Lens 12 Minor fix on pyproject.toml's
mypy override comment — dropping the version-specific "docling 2.93.0"
anchor in favour of a version-neutral phrasing. The commit's primary
subject is coverage config; the mypy-override edit hitchhiked because
both touch pyproject.toml. The commit body could have named it
explicitly — minor commit-message-coverage gap recorded here for the
audit trail.)

**Hallucinations re-tested (the cycle-1 false-positive pattern):** Cycle
2's lens prompts carried explicit "VERIFICATION HINT" callouts on
Lenses 08, 11, 12, 15, 18, 20 directing each agent to `git show
origin/main:<file>` before flagging any "main has X" drift. Cycle 2
produced ZERO false-positive drift findings — the verification hints
worked. The other branch in the user's local checkout
(`chore/panel-review-fixes-2026-05-13`) is the likely contamination
source for cycle-1's hallucinations; cycle 2's explicit verify-against-
origin/main discipline blocked the same pattern from recurring.

**Deferred items (4a — waiting on later phase or upstream decision):**

- Lens 10 Important: `modelscope.snapshot_download(repo_id="RapidAI/RapidOCR")`
  has no `revision=` pin. Pinning requires picking a specific upstream
  commit SHA from the modelscope hub for the RapidAI/RapidOCR repo —
  that decision belongs with the user or the Phase 6 hardening pass that
  also covers `scripts/validate_ocr.py`. Re-trigger naturally when Phase
  6 starts; the same pass should pick a model revision and pin it.

**Deferred items (4b — other reasons):**

- Lens 02 chore(tests) commit-message body's "CI sweep picks them up"
  inaccuracy on commit 9c7b35b — historical-immutable on a shared branch
  per the "prefer new commits over amend" rule. The squash subject at
  user merge time supersedes individual subjects.
- Lens 06 Minors (WORD_RECALL_THRESHOLD placement / build_ocr_engine
  re-export hint / monkeypatch seam comment) — style observations.
- Lens 07 Minor (`_ENGINE_NAME` borderline keep) — synthesizer retains
  the named constant as a documentation anchor + Phase 3+ Literal-
  broadening guardrail.
- Lens 09 Minor (`word_recall` in conftest vs metrics module) — style
  observation; the function works correctly via explicit import and the
  conftest placement is internally consistent.
- Lens 10 Minor (`.secrets.baseline` `generated_at` timestamp stale) —
  cosmetic; the CI hook performs a LIVE scan against current git
  ls-files, so a stale timestamp does not affect coverage. A future
  pre-commit-update PR can regenerate.
- Lens 13 Minor (`test_fake_ocr_engine_returns_ocr_result` partial
  redundancy) — lens itself said "not worth fixing urgently"; the
  Protocol-conformance test is the load-bearing one.
- Lens 13 Minor (smoke path two-assertions-per-test in slow OCR test) —
  lens self-rated as "defensible" for a parametrised integration test;
  splitting would 3x the fixture cost without diagnostic gain.
- Lens 16 Minor (threading.Event pattern fragility comment) — code is
  correct as written; comment would be ceremony.
- Lens 19 Minor (.gitignore vscode carve-out comment regression) — style
  observation on a Phase 0.5-era comment, not Phase 2 scope.

**Loop status:** cycle 2 applied 9 commits (plus this §17.11 audit entry).
NOT converged — cycle 3 will fire fresh against the new branch HEAD per
the cycle-independence rule.

## §17.12 — Cycle-1 of fresh review loop on `chore/phase-2-ocr-review-fixes-2026-05-13`

**Branch:** `chore/phase-2-ocr-review-fixes-2026-05-13` (derived from
`phase-2-ocr` HEAD `7677c04`, which was the post-merge state after the
standalone review loop on `chore/panel-review-fixes-2026-05-13` landed
its terminal cycle-5 MAX-CAP fixes — recorded in
`2026-05-11-ci-cd-scaffolding-design.md` §17.24–§17.28 — and merged into
`phase-2-ocr`).

**Inter-loop gap closed by this entry:** the Phase 2 OCR review loop
ended at §17.11 with "NOT converged — cycle 3 will fire fresh." Between
then and now, the standalone review loop on
`chore/panel-review-fixes-2026-05-13` ran cycles 3/4/5 against
`origin/main` rather than against `phase-2-ocr`, then merged its fixes
into `phase-2-ocr` via `7677c04`. The Phase 2 OCR spec carried no entry
recording that the post-§17.11 audit trail had been satisfied via that
merge (Lens 01 Important of this cycle flagged the gap). This §17.12 is
the missing terminal entry for the OCR loop's pre-merge state AND the
opening entry of a new loop running on a separate derived branch.

**Why a separate derived branch (not `phase-2-ocr` directly):** at the
user's request, review fixes for this cycle land on a dedicated
`chore/phase-2-ocr-review-fixes-2026-05-13` branch that will merge into
`phase-2-ocr` later as a clean delta. This preserves the option of
wholesale-reverting review fixes if a cycle produces something undesired,
without interleaved commits on the PR branch.

**HEAD/BASE:** BASE_SHA = `e160593` (origin/main as of 2026-05-13);
HEAD_SHA = `7677c04` at cycle 1 dispatch (the branch HEAD on creation,
identical to `phase-2-ocr` HEAD).

**Cycle-1 findings tally (pre-filter):**

- 20/20 lens reports returned.
- Verdicts: 10 lenses **Yes** (02, 03, 04, 07, 08, 09, 11, 12, 18, 20),
  10 lenses **With fixes** (01, 05, 06, 10, 13, 14, 15, 16, 17, 19).
- Strictly-clean (zero issues): Lens 03 (scope creep), Lens 04 (type
  safety). 2/20.
- Raw severity: 0 Critical / ~12 Important / ~20 Minor.

**Convergent findings (auto-applied):**

- **Lens 06 Minor + Lens 14 Minor** on `word_recall` living in
  `tests/ocr/conftest.py` instead of a helpers module. Promoted; moved
  to `tests/ocr/_metrics.py` (commit `d1c931d`).
- **Lens 01 Important + Lens 17 Minor** on unqualified `§17.9`
  references after the CI/CD-vs-Phase-2 namespace collision. Lens 01
  flagged `src/extraction_service/ocr/base.py:40`; Lens 17 flagged
  `docs/plan.md:729`. Same root issue, two call sites. Both qualified
  (commits `a77e35b` for base.py, `8e78044` for plan.md).

**Fixes applied this cycle (11 atomic per-concern commits):**

| Commit | Subject | Lens(es) | Severity |
|---|---|---|---|
| `e4ed74c` | chore(ruff): add A (flake8-builtins) rule family + complete fastapi rollup comment | 08, 12 | Minor + Minor |
| `6997de3` | chore(hygiene): ignore modelscope snapshot + cache dirs | 19 | Important |
| `3c941af` | chore(editorconfig): pin *.ipynb to 2-space JSON indent | 19 | Minor |
| `3fb4b9e` | docs(hooks): tighten detect-secrets baseline-exclude rationale | 18 | Minor |
| `a77e35b` | feat(ocr): declare public __all__ at ocr package + qualify §17.9 ref | 06, 09, 01, 17 | Important + Minor |
| `e56ea5f` | fix(ocr): tighten docling_engine error handling + supply-chain TODO | 05, 10 | Important + Minor |
| `cf05559` | test(ocr): drop tautological FakeOcrEngine return-type test | 13 | Important |
| `f581452` | fix(ocr-tests): empty samples-dir is documented skip, not collection error | 14 | Important |
| `d1c931d` | refactor(ocr-tests): move word_recall metric out of conftest into _metrics | 06, 14 (convergent) | Minor (promoted) |
| `d16d1cf` | refactor(ocr-tests): private prefix on _SAMPLES_DIR_ENV_VAR + use ordinal id in failure msg | 06, 16 | Minor + Minor |
| `8e78044` | docs(plan): sync §6.4 Task 2.1 RED-test names + qualify §17.9 + Validation-gate deferral | 01, 17 | Important + Minor |

**Deferred — waiting on later phase (4a):**

- Lens 10 Important: `modelscope.snapshot_download(repo_id="RapidAI/RapidOCR")`
  has no `revision=` pin and fetches the floating `main` HEAD of the
  upstream modelscope repo. Pinning requires selecting a known-good
  commit SHA from the modelscope hub — that decision belongs with the
  Phase 6 hardening pass that also implements `scripts/validate_ocr.py`
  (§17.8 above). In-code TODO added at the call site in commit
  `e56ea5f` so the gap stays visible.
- Lens 15 Important×2: no `--cov-report=xml` and no `--junitxml` in
  CI's pytest invocation. The coverage gate works (gate enforcement
  lives in `[tool.coverage.report].fail_under`), but no machine-readable
  artifacts are uploaded. Lens 15 itself framed this as "Deferral is
  defensible (the gate itself works); standard next step once --cov is
  live." Phase 6 hardening will add the artifact uploads alongside the
  validate_ocr script + JUnit-rendering CI polish.

**Deferred — other reasons (4b):**

- Lens 02 Minor×2: two commit-message-coverage gaps on already-merged
  commits (`5d1c780` subject vs body partiality, `0b660b3` body's stale
  `loop.run_in_executor` after `asyncio.to_thread` superseded it). Both
  historical-immutable on a shared branch per the "prefer new commits
  over amend" rule. The squash subject at user merge time supersedes
  individual subjects. Cost-benefit: rewriting shared history would
  invalidate every contributor's local branch state; the messages are
  audit-trail records of what the implementer knew at commit time,
  which is itself useful for forensics.
- Lens 07 Minor (`_ENGINE_NAME` constant could be inlined): synthesizer
  retains as a documentation anchor + future-proof guardrail when Phase
  3+ broadens `OcrConfig.engine` from a 1-arm to a 2+-arm `Literal`.
  Cost-benefit: inline-vs-named-constant for a single-call site is
  stylistic; lens itself rated as "no current defect."
- Lens 11 Minor (Tests-step comment length): lens explicitly noted "no
  fix required."
- Lens 13 Minor borderline×1 (three configurable-field FakeOcrEngine
  tests): lens self-defended retention as forward-looking for Phase
  4/5 (`FakeOcrEngine(page_count=5)` is load-bearing for the upcoming
  pagination tests). Synthesizer agrees.
- Lens 13 Minor (`test_docling_engine_construct` thin contract test):
  lens self-rated as "Acceptable" — the assertion guards against a
  constructor regression that silently leaves `_converter` as None.
- Lens 20 Minor (header comment self-documenting required check names):
  lens explicitly noted "No fix required."

**Filter-dropped (ceremonial / not actionable):**

- Lens 07 inline-vs-constant suggestion — see deferred above.
- Lens 09 docstring rationale wording (separately fixed by the same
  commit that added `__all__` to ocr/__init__.py).

**Hallucination / drift safety:** cycle-1 lens prompts carried no
carryover context per the cycle-independence rule. Each lens read the
diff fresh against `origin/main..HEAD`. No "previous cycle missed X"
framing was injected.

**Loop status:** cycle 1 applied 11 commits (plus this §17.12 audit
entry). NOT converged — cycle 2 will fire fresh against the new branch
HEAD per the cycle-independence rule.

## §17.13 — Cycle-2 of fresh review loop on `chore/phase-2-ocr-review-fixes-2026-05-13`

**Branch:** `chore/phase-2-ocr-review-fixes-2026-05-13`. Cycle-2 HEAD
at dispatch = `f9eead6` (terminal commit of cycle 1 / §17.12).

**Cycle-2 findings tally (pre-filter):**

- 20/20 lens reports returned.
- Verdicts: 14 lenses **Yes** (02, 03, 04, 05, 07, 08, 09, 11, 12,
  16, 17, 18, 19, 20), 6 lenses **With fixes** (01, 06, 10, 13, 14,
  15).
- Strictly-clean (zero issues): Lens 04, 07, 09, 18, 19, 20. **6/20**
  — up from 2/20 in cycle 1.
- Raw severity: 0 Critical / 7 Important / 15 Minor.

**Convergent findings (auto-applied):**

- **Lens 06 Minor + Lens 13 Minor + Lens 14 Minor** on
  `tests/ocr/test_word_recall.py:1` module docstring still claiming
  `word_recall` lives in `tests/ocr/conftest.py` after cycle-1's
  move to `tests/ocr/_metrics.py`. Three-lens convergence — promoted
  to load-bearing fix. Classic "rename leak" per CLAUDE.md Known
  Workflow Gap #2 — the import in this same file was updated in
  cycle-1 commit `d1c931d`; the docstring reference was missed.
  Fixed in commit `95e5e3b`.

**Cycle-1 fallout caught by cycle-2 (the loop justified itself):**

Three findings this cycle traced directly back to incomplete fixes
in cycle 1's commits. Each is documented as a partial-sync workflow
gap below for the cycle-3 prompt context:

1. **Lens 01 Important:** `docs/plan.md §6.4` Tasks 2.8 and 2.9
   RED-test columns still named planned test identifiers that don't
   exist in code (`test_docling_extract_timeout`,
   `test_docling_extract_empty_output_raises_ocr_empty_output`,
   `test_docling_internal_exception_wraps_as_ocr_engine_failed`).
   Cycle-1 commit `8e78044` synced Task 2.1's RED-test name but did
   NOT audit Tasks 2.4/2.5/2.6/2.8/2.9 for the same drift. Fixed in
   commit `ff5c092`. Pattern: "partial sync after partial-scope
   fix" — Known Workflow Gap #1.
2. **Lens 01 Minor:** §17.12 (added in cycle-1 commit `f9eead6`)
   used `### 17.12` heading while every preceding §17.N entry uses
   `## §17.N` (level-2 + § sigil). The mis-heading also caused
   Lens 17's cycle-2 self-report to claim "latest is §17.11" (its
   text search for "§17." missed the new entry). Fixed in commit
   `ff5c092` (same commit; both are spec-format consistency).
3. **Lens 01 Minor:** `CLAUDE.md "Where things live"` Phase 2 spec
   pointer still claimed `latest: §17.11`. Cycle-1 added §17.12 but
   did not update the index pointer in the same flight. Fixed in
   commit `61a7d67`. Pattern: "index drift after appending a new
   entry."
4. **Lens 12 Minor:** `pyproject.toml`'s floor-tracks-locked-minor
   umbrella comment listed peers as "ollama / ruff / docling /
   uvicorn / modelscope / httpx" but omitted `rapidocr-onnxruntime`,
   which participates in the same convention. Cycle-1 commit
   `e4ed74c` added `httpx` to the umbrella but missed
   `rapidocr-onnxruntime`. Fixed in commit `52f066c`. Same partial-
   sync pattern as findings #1–3.

**Fixes applied this cycle (5 atomic per-concern commits):**

| Commit | Subject | Lens(es) | Severity |
|---|---|---|---|
| `ff5c092` | docs(plan): sync §6.4 Task 2.8/2.9 RED-test names + correct §17.12 heading | 01 | Important×2 + Minor |
| `61a7d67` | docs(claude): bump Phase 2 spec latest pointer §17.11 → §17.12 | 01 | Minor |
| `96075c9` | test(ocr): drop tautological get_type_hints check on OcrEngine.extract | 13 | Important |
| `95e5e3b` | test(ocr): fix stale conftest.py docstring path in test_word_recall.py | 06+13+14 (3-lens convergent) | Minor (promoted) |
| `52f066c` | docs+ci(phase-2): FakeOcrEngine __init__ docstring + rapidocr umbrella + explicit --cov-report | 17, 12, 15 | Minor×3 |

**Headbutting decision (synthesizer-resolved):**

- **Lens 13 borderline Important on the 3 required-field + 1
  extra-forbid OcrResult tests in `tests/unit/test_ocr_base.py`.**
  Lens 13 itself acknowledged the borderline status and explicitly
  DEFENDED the structurally identical `test_ocr_result_is_frozen`
  test as a genuine project-rule check. Synthesizer call: required-
  field tests and extra="forbid" tests verify the value-object's
  design contract (project convention for value objects = frozen +
  required + extra-forbid), not merely that Pydantic's machinery
  works. Same defense as `test_ocr_result_is_frozen`. **KEEP.**
  No commit.

**Deferred — waiting on later phase (4a; re-flagged from cycle 1, NO
new evidence):**

- Lens 10 Important: `modelscope.snapshot_download(repo_id=
  "RapidAI/RapidOCR")` still has no `revision=` pin. The in-code
  TODO added by cycle-1 commit `e56ea5f` is intact and accurate.
  Lens 10 acknowledged the TODO. Phase 6 hardening unblocks this.
- Lens 15 Important×2: no `--cov-report=xml` and no `--junitxml`
  uploads. Re-flagged by cycle-2 Lens 15 with the same framing.
  Phase 6 hardening unblocks alongside `scripts/validate_ocr.py`.

**Deferred — other reasons (4b):**

- Lens 02 Minor (`7e860eb` commit missing scope: `docs:` not
  `docs(scope):`): historical-immutable on a shared branch per the
  "prefer new commits over amend" rule.
- Lens 03 Minor (`domain/__init__.py` docstring mentions Phase 5):
  lens itself rated as "accurate forward-declaration, not warranting
  a split."
- Lens 12 Minor #2 (pre-existing floor drift on `hypothesis` and
  `pydantic-settings`): not introduced by this diff. Out of cycle-2
  scope.
- Lens 16 Minor (pre-existing `/tmp` literals in `test_run_config.
  py`): not in cycle-2 diff. Out of scope.

**Filter-dropped (ceremonial):**

- Lens 05 Minor (comment scope on `except Exception` broadening to
  enumerate BaseException semantics): comment inflation on already-
  correct code.
- Lens 08 Minor (`from __future__ import annotations` consistency
  across modules where it's not functionally needed): ruff itself
  does not flag the inconsistency; senior-dev would push back on a
  pure-style pass adding noise.
- Lens 11 Minor (`--cov=src/extraction_service` explicit when
  `[tool.coverage.run].source` already sets it): comment inflation
  on unambiguous config — pytest-cov correctly reads pyproject's
  source when `--cov` is bare.

**Convergence between cycles:** None of cycle-2's fix-able findings
were also present in cycle-1's deferred lists — all five fix
commits address newly-surfaced items (or items where new evidence
mid-cycle promoted them to load-bearing). The 4a deferrals from
cycle 1 (Lens 10, Lens 15×2) re-surfaced in cycle 2 with no new
evidence; cycle-2 synthesizer kept them in 4a per the
cycle-independence rule.

**Loop status:** cycle 2 applied 5 commits (plus this §17.13 audit
entry). NOT converged — cycle 3 will fire fresh against the new
branch HEAD per the cycle-independence rule.

## §17.14 — Cycle-3 of fresh review loop on `chore/phase-2-ocr-review-fixes-2026-05-13`

**Branch:** `chore/phase-2-ocr-review-fixes-2026-05-13`. Cycle-3 HEAD
at dispatch = `f45603b` (terminal commit of cycle 2 / §17.13 +
cycle-tail pointer bump).

**Cycle-3 findings tally (pre-filter):**

- 19/20 lens reports returned cleanly; **Lens 12 stalled at synthesis**
  but its partial output showed no new findings beyond cycle-2's
  already-deferred pre-existing floor drift on hypothesis +
  pydantic-settings. Treated as effectively complete.
- Verdicts: 16 lenses **Yes**, 4 lenses **With fixes** (10, 13, 15, 17).
- Strictly-clean (zero issues): **7/20** — Lens 03, 04, 09, 11, 12,
  16, 20 — up from 6/20 in cycle 2 and 2/20 in cycle 1. The trajectory
  is clear: domain after domain settles as cycle-N fixes converge in
  their scope.
- Raw severity: 0 Critical / 4 Important / 16 Minor.

**Convergent findings:** **None this cycle.** Each finding came from
a single lens. The cycle-1 + cycle-2 three-lens convergence on the
word_recall docstring drift did not re-fire — the cycle-2 fix landed
cleanly.

**Cycle-1/2 fallout caught by cycle-3:**

1. **Lens 01 Minor:** `tests/ocr/__init__.py:5-7` carried unqualified
   `§17.3` / `§17.1` / `§17.2` references — same class of finding as
   cycle-2's `base.py:40` and `plan.md` Tasks 2.8/2.9. Each prior
   cycle qualified the sites it found; this test-package docstring
   was missed in both passes. Fixed in commit `a5a86de`.
2. **Lens 17 Minor:** `docs/plan.md:704` Task 1.3 GREEN column
   referenced `§17.24` (the CI/CD spec) without filename qualifier.
   Fixed in same commit (`a5a86de`).
3. **Lens 17 Minor:** `CLAUDE.md` line 48 `### Spec deviations` block
   in the Superpowers flow STILL named the single CI/CD spec file —
   contradicting the per-phase convention enshrined in
   `Project state notes` (line 308) and `Where things live` (line
   314+). A reader following the Superpowers flow top-down would
   route a Phase 3+ deviation to the wrong file. Fixed in commit
   `d6cd258`.
4. **Lens 19 Minor (and class):** `.gitignore` line 85 (and seven
   other sites) carried "(Lens N of cycle-M on
   chore/phase-2-ocr-review-fixes ...)" parentheticals — a
   self-referential review-artifact pattern that CLAUDE.md's
   "Tone and style" section explicitly forbids ("Don't reference the
   current task, fix, or callers"). Lens 19 flagged the .gitignore
   site by name; the synthesizer extended the fix to the class —
   pyproject.toml, tests/ocr/_metrics.py, tests/ocr/conftest.py
   (3 sites), tests/ocr/test_docling_engine.py,
   src/extraction_service/ocr/docling_engine.py, and
   .github/workflows/ci.yml all had the same pattern. Fixed in
   commit `7e252eb`. Pre-existing comments from earlier branches
   ("Phase 1 panel review" lineage in pyproject.toml's older rule
   families) are left alone — those are already-merged historical
   context, not new attributions introduced on this branch.

**New-this-cycle findings:**

- **Lens 06 Minor:** `test_docling_engine_construct` was the only test
  in `tests/ocr/test_docling_engine.py` not named in the "describes
  observable behavior" style (the project convention). Renamed to
  `test_docling_engine_stores_converter_after_construction` matching
  the test's own docstring. Fixed in commit `8e0cb40`.
- **Lens 14 Minor:** `baseline_for` fixture docstring used "Yields"
  but the fixture `return`s a callable (not a generator). Reworded
  to make the return-callable vs callable-returns-None semantics
  explicit. Fixed in same commit (`8e0cb40`).

**Fixes applied this cycle (5 atomic per-concern commits):**

| Commit | Subject | Lens(es) | Severity |
|---|---|---|---|
| `a5a86de` | docs(plan+tests): qualify residual unqualified §17 cross-references | 01, 17 | Minor×2 |
| `d6cd258` | docs(claude): align Spec deviations flow paragraph with per-phase convention | 17 | Minor |
| `8e0cb40` | test(ocr): rename test_docling_engine_construct + fix baseline_for docstring | 06, 14 | Minor×2 |
| `7e252eb` | chore(comments): scrub branch-specific lens/cycle attributions from code | 19 + class | Minor (promoted, 8 sites) |

**Headbutting decisions (synthesizer-resolved):**

- **Lens 05 Minor (cycle-3 vs cycle-1 reversal candidate):** Lens 05
  flagged `raise OcrError(msg) from None` at the non-SUCCESS path as
  a no-op since `__context__` is already `None`. Cycle-1's commit
  `e56ea5f` added this `from None` for TRY200 lint defense. Cycle-3
  lens's reading is correct (TRY200 doesn't fire on non-except
  branches), so cycle-1's defensive rationale was over-applied. BUT
  reverting now is pure churn — the `from None` is harmless in this
  position. Per "Reverse prior-cycle fixes only with new evidence"
  + senior-dev cost-benefit, KEEP cycle-1's commit. No reverse.
- **Lens 13 Important borderline (Pydantic required-field tests in
  test_ocr_base.py):** Cycle-2 KEPT them via synthesizer call as
  equivalent to test_ocr_result_is_frozen (project-rule check, not
  Pydantic-library tautology). Cycle-3 re-raised with sharper
  framing. No new evidence — same code, same tests, only the
  framing changed. KEEP per cycle-2 decision.
- **Lens 13 Important (dual-assert in
  test_docling_extract_against_sample slow path):** Cycle-2 KEPT
  citing 3x slow-OCR cost vs convention-strict split. Cycle-3
  re-raised. Same cost argument applies. KEEP per cycle-2.

**Deferred — waiting on later phase (4a; re-flagged from cycles 1+2,
NO new evidence):**

- Lens 10 Important: `modelscope.snapshot_download(repo_id=
  "RapidAI/RapidOCR")` still has no `revision=` pin. In-code TODO
  intact and now scrubbed of branch-specific attribution but the
  Phase 6 hardening anchor remains.
- Lens 15 Important: no `--junitxml` artifact upload. Phase 6
  hardening unblocks alongside `scripts/validate_ocr.py`.

**Deferred — other reasons (4b):**

- Lens 02 Minor (`52f066c` `docs+ci` compound type + `7e860eb`
  missing scope): historical-immutable on a shared/pushed branch
  per "prefer new commits over amend" rule. Both are minor style
  drift on already-pushed commits.
- Lens 07 Minor (`_ENGINE_NAME` inline-vs-constant): same as cycles
  1+2 — synthesizer retains as Phase 3+ Literal-broadening guardrail.
- Lens 13 Minor (compound exception-code assertions): lens itself
  said "a senior dev would not split these."

**Filter-dropped (ceremonial):**

- Lens 06 Minor (`_success_status` rename): naming subjectivity,
  lens self-rated as "purely subjective."
- Lens 08 Minor (`_ = pdf_bytes` → `_pdf_bytes` rename): would break
  `typing.Protocol` structural conformance (Protocol checks param
  names for keyword-or-positional positions); lens suggestion was
  technically incorrect for the Protocol-implementer case.
- Lens 08 Minor (`from __future__ import annotations` consistency
  across files where it's not functionally needed): no ruff signal,
  same skip rationale as cycles 1+2.
- Lens 18 Minor (`ruff-check` hook's missing `--fix` comment):
  comment-inflation on unambiguous config.

**Loop status:** cycle 3 applied 4 commits (plus this §17.14 audit
entry and a cycle-tail CLAUDE.md pointer bump). The trajectory points
toward convergence (strictly-clean lens count growing each cycle:
2 → 6 → 7; no convergent findings this cycle; cycle-1/2 fallout
diminishing as the systemic-pattern scrubs land). Cycle 4 will fire
fresh against the new branch HEAD per the cycle-independence rule.

## §17.15 — Cycle-4 of fresh review loop on `chore/phase-2-ocr-review-fixes-2026-05-13`

**Branch:** `chore/phase-2-ocr-review-fixes-2026-05-13`. Cycle-4 HEAD
at dispatch = `7d7a6ef` (terminal commit of cycle 3 / §17.14 +
cycle-tail pointer bump).

**Cycle-4 findings tally (pre-filter):**

- 20/20 lens reports returned cleanly.
- Verdicts: 13 lenses **Yes**, 7 lenses **With fixes** (01, 05, 06,
  08, 10, 13, 15, 17). Note: 7 With-fixes vs cycle-3's 4 — but on
  inspection most cycle-4 "With fixes" verdicts came with single
  Minor or single Important findings; the per-finding count is
  similar.
- Strictly-clean (zero issues): **2/20** — Lens 04 (type safety),
  Lens 19 (repo hygiene). Below cycle-3's 7/20 but not regression:
  the other "strictly-clean" cycle-3 lenses now carry at-most-one
  filter-drop Minor each (no real defects).
- Raw severity: 0 Critical / 6 Important / 16 Minor.

**Convergent finding (2-lens):**

- **Lens 06 Important + Lens 13 Important** on
  `test_docling_engine_stores_converter_after_construction`'s
  assertion against the private `engine._converter` attribute. Lens
  06 framed it as a naming-discipline gap (underscore-prefix-means-
  private breach); Lens 13 framed it as implementation-detail
  testing (already-transitive constructor coverage via extract
  tests). Same fix from independent scopes — promoted to load-
  bearing fix. Removed the test in commit `63b9928`.

**Reversal with new evidence (multi-cycle):**

- **Lens 05 cycle-4 Important** (escalated from cycle-3 Minor):
  the cycle-1 `from None` addition on the non-SUCCESS OcrError raise
  was sound runtime code but misleading-to-readers (cycle-3 framing)
  and semantically incorrect outside an except block (cycle-4
  framing). Two-cycle convergence + concrete reader-confusion harm
  articulation qualifies as the "new evidence" CLAUDE.md's reverse-
  prior-fix rule requires. Reversed in commit `fe8a6d5`. The
  underlying TRY200 defensive rationale was over-applied: TRY200
  only fires inside `except` handlers.

**New-this-cycle Important:**

- **Lens 08 Important:** `_ERRORS_ATTR_MISSING: object = object()`
  sentinel was bare-typed `object`. PEP 591 `Final[object]` is the
  canonical pattern for module-level sentinels and constants:
  signals reassignment-prevention intent both to readers and to
  mypy. Applied in commit `642513d`.

**Cycle-3 fallout caught by cycle-4:**

- **Lens 01 Minor:** `docs/plan.md:724` Task 2.3 RED column still
  named `test_docling_engine_construct` after cycle-3's rename to
  `test_docling_engine_stores_converter_after_construction`. Cycle-3
  fixed the test name but missed the plan sync — same "partial rename
  leak" pattern (Known Workflow Gap #1) the loop has fired on every
  cycle.
- **Lens 17 Minor (systemic):** unqualified §17.3 in the §6.4 Goal
  paragraph + multiple unqualified §17 refs in Tasks 2.5/2.6/2.7/2.9.
  Same systemic class as cycles 1/2/3. Resolved structurally this
  cycle by adding a single header sentence ("The §17 references in
  the task table below all live in the same Phase 2 spec file unless
  otherwise noted") that establishes the default scope, breaking the
  per-row chore. Applied in commit `96358d3`.
- **Lens 17 Minor (different sub-class):** `<pending push>` placeholder
  strings in CI/CD-spec §17.26 and §17.28 compact status lines were
  introduced by their originating cycle-3/cycle-5 commits on
  `chore/panel-review-fixes-2026-05-13` and never backfilled. An
  earlier branch-lineage commit `7e860eb` claimed §17.26/§17.27 used
  the this-commit-anchored pattern but did not — placeholders
  remained. Backfilled in commit `8fbed2d`.

**Fixes applied this cycle (5 atomic per-concern commits):**

| Commit | Subject | Lens(es) | Severity |
|---|---|---|---|
| `fe8a6d5` | fix(ocr): drop misleading `from None` on non-SUCCESS conversion raise | 05 (reversal of cycle-1) | Important (was cycle-1 Important; reversed cycle-4) |
| `642513d` | refactor(ocr): annotate _ERRORS_ATTR_MISSING sentinel with Final[object] | 08 | Important |
| `63b9928` | test(ocr): drop test_docling_engine_stores_converter_after_construction | 06+13 convergent | Important×2 (promoted) |
| `96358d3` | docs(plan): qualify §6.4 Goal §17.3 ref + sync Task 2.3 RED column | 01, 17 | Minor×2 |
| `8fbed2d` | docs(spec): backfill stale <pending push> placeholders | 17 | Minor×2 |

**Headbutting decisions (synthesizer-resolved):**

- **Lens 13 Important (4 FakeOcrEngine configurable-field tests):**
  Same headbutting as cycles 2+3. Cycle-4 lens used sharper framing
  but cited the same code, same tests, same project rules. **No
  new evidence — KEEP** per cycles 2+3 defense (load-bearing for
  Phase 4 pagination-tests / fields-fidelity contract).
- **Lens 13 Minor borderline (dual-assert in
  test_docling_extract_against_sample smoke path):** Same headbutting
  as cycles 2+3. **KEEP** per cycle-2 cost-benefit defense (3x slow
  real-OCR cost vs convention-strict split).
- **Lens 13 Minor (Pydantic required-field tests in
  test_ocr_base.py):** Same headbutting as cycles 2+3. **KEEP** per
  cycle-2 "equivalent to test_ocr_result_is_frozen" defense.

**Deferred — waiting on later phase (4a; re-flagged from cycles
1-3, NO new evidence):**

- Lens 10 Important: `modelscope.snapshot_download(repo_id=
  "RapidAI/RapidOCR")` revision pin (in-code TODO intact, Phase 6
  hardening unblocks).
- Lens 15 Important: no JUnit XML artifact upload (Phase 6
  hardening alongside `scripts/validate_ocr.py`).

**Deferred — other reasons (4b):**

- Lens 02 Minor (`52f066c` `docs+ci` compound type + `7e860eb`
  missing scope + `a77e35b` `feat` vs `refactor` type): historical-
  immutable on a shared/pushed branch per "prefer new commits over
  amend" rule.
- Lens 07 Minor (`_ENGINE_NAME` inline-vs-constant): same as
  cycles 1-3 — synthesizer retains as Phase 3+ Literal-broadening
  guardrail.
- Lens 09 Minor (factory.py runtime-vs-TYPE_CHECKING import
  asymmetry comment): comment-inflation on already-correct code.
- Lens 13 Minor (additional `ConversionStatus` enum values not
  tested): defense-in-depth without current defect.
- Lens 17 Minor (additional unqualified §17 refs in
  plan.md §6.4 Tasks 2.5/2.6/2.7/2.9): resolved structurally by the
  Goal-paragraph header sentence added in commit `96358d3` — per-row
  qualification no longer necessary.

**Filter-dropped (ceremonial):**

- Lens 03 Minor×2 (ruff `A` rule preemption note, CI/CD spec
  §17.24-28 inclusion via branch lineage): both lens-self-rated as
  "no action required."
- Lens 06 Minor×2 (helper placement, threshold naming): lens-self-
  rated "no rule violation" / "subjective."
- Lens 11 Minor (comment-wrap mid-flag in ci.yml): cosmetic
  readability with no runtime effect.
- Lens 12 Minor (rapidocr-onnxruntime version verification note):
  lens-self-rated "No action needed — noting only."
- Lens 14 Minor×2 (ANN coverage observation, isolated_env
  composition docstring): both observational, "no runtime impact."
- Lens 16 Minor (pre-existing `/tmp` literals in test_run_config.
  py): out-of-scope (not in diff).
- Lens 18 Minor (pre-commit-hooks rev-comment style asymmetry):
  lens-self-rated "very low value; style only."
- Lens 20 Minor×2 (concurrency comment, theoretical author-label
  filter): lens-self-rated "noted for completeness" / "zero
  practical exposure."

**Loop status:** cycle 4 applied 5 commits (plus this §17.15 audit
entry and a cycle-tail CLAUDE.md pointer bump). Cycle-4 also
delivered the loop's first explicit cycle-1-reversal-with-evidence
(`from None`) — a positive signal that the multi-cycle evidence
accumulation pattern works. Strictly-clean count dropped from
7/20 → 2/20 but is misleading: the difference is filter-drop Minor
findings, not new defects. 4/5 cycles used; cycle 5 will fire fresh
per the cycle-independence rule and is the last cycle before MAX-CAP.

---

## §17.16 — Model paths realigned: modelscope filename drift + Latin rec for German

**Surfaced by:** real-PDF smoke validation on `chore/phase-2-ocr-validation`
(2026-05-13). `DoclingOcrEngine.extract()` on a 21 MB German loan contract
raised `OcrError("docling OCR engine failed: ...ch_PP-OCRv5_server_det.onnx
does not exists")` from inside RapidOCR's `_verify_model`.

**Plan text:** §2.5 hardcoded three model paths against modelscope repo
`RapidAI/RapidOCR`:

```
det = onnx/PP-OCRv5/det/ch_PP-OCRv5_server_det.onnx
rec = onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_server_infer.onnx
cls = onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_infer.onnx
```

Plan §2.5's accompanying note also outlined a 3-step language-evaluation
ladder for German OCR (try Chinese-server rec as-is → extended Latin
dictionary → Tesseract `deu` fallback).

**Deviation (3 path strings + 1 new kwarg + defensive asserts):**

```
det = onnx/PP-OCRv5/det/ch_PP-OCRv5_det_server.onnx          # word-order swap; superseded by mobile in §17.17
rec = onnx/PP-OCRv5/rec/latin_PP-OCRv5_rec_mobile.onnx       # Chinese → Latin
cls = onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx # _cls_infer → _cls_mobile rename
```

Also added `lang=["latin"]` on `RapidOcrOptions` to align the post-OCR
tokeniser with the explicit rec path, and `Path.is_file()` asserts in
`_build_default_converter` so future upstream renames fail at construction
with a path-specific message instead of inside Pydantic-validated docling
internals 15 frames down.

**Why each change:**

1. **det filename swap (`server_det` → `det_server`):** mechanical. The
   modelscope repo renamed `<role>_<tier>` → `<tier>_<role>`. Detection
   model is language-agnostic; only the filename changed.
2. **rec filename + script swap:** mechanical part is the `_rec_server_infer`
   → `_rec_server` suffix drift. Script swap is the substantive change —
   the Chinese-server rec model would mangle German diacritics (ä/ö/ü/ß) and
   likely produce empty/near-empty markdown, triggering
   `OcrEmptyOutputError` from §17.5's wrapping logic. PP-OCRv5 ships no
   server-tier Latin rec; `latin_PP-OCRv5_rec_mobile.onnx` is the
   highest-accuracy Latin variant available. This **skips step 1 of the
   plan §2.5 language ladder** (try Chinese-server as-is) and lands directly
   at step 2 (Latin-tuned rec). The skip is intentional: smoke validation
   would have shown step 1 producing garbage, and the round trip through
   "OcrEmptyOutputError → fix → re-run" was avoided by reading the
   character-set semantics off the model name.
3. **cls stays on PP-OCRv4 (filename-only rename `_cls_infer` → `_cls_mobile`):**
   the original picked v4 mobile cls; upstream renamed the file but kept
   the model. PP-OCRv5 also ships PP-LCNet-architecture cls models
   (`ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx` and
   `_x1_0_..._server.onnx`), but both hardcode an 80x160 input shape that
   is incompatible with the cls preprocessor in our pinned
   `rapidocr-onnxruntime==1.4.4` (which produces 48x192). Discovered the
   hard way: a smoke-demo with the v5 PP-LCNet cls raised
   `onnxruntime ... InvalidArgument: Got invalid dimensions ... Got: 48
   Expected: 80` from inside `text_cls.__call__`. The v4 cls's input
   shape is `[None, 3, ?, ?]` (dynamic spatial dims) so it accepts any
   HxW from any rapidocr version. The constraint is documented in the
   `docling_engine.py` docstring; a future `rapidocr` major-bump that
   changes the cls preprocessor will need to revisit this choice.
4. **`lang=["latin"]` added:** `RapidOcrOptions.lang` defaults to
   `["chinese"]`. When the explicit `rec_model_path` is Latin and `lang`
   is left as the default, RapidOCR's post-OCR character-set tokeniser
   could route through a CJK dictionary. Setting `lang=["latin"]` makes the
   two consistent.
5. **`Path.is_file()` asserts:** the original code computed three path
   strings and passed them to `RapidOcrOptions` without checking existence.
   Docling/RapidOCR defer the check to first `convert()` call, which buried
   the failure deep in a Pydantic-validated `RapidOCR.__init__` call
   stack. The 3-line existence loop in `_build_default_converter` raises
   `FileNotFoundError` at engine construction with the offending path
   verbatim — turning a 5-frame traceback into a 1-line diagnosis.

**What this DOESN'T do (deferred):**

- **No modelscope revision pin.** `snapshot_download(repo_id=...)` still
  resolves to the latest commit, so a future upstream rename can break us
  again. A pinned `revision=<sha>` would freeze the filename layout but
  requires picking a known-good commit + a refresh strategy when we want
  the next upstream improvement. Tracked as future work.
- **No real-OCR test in CI.** §17.3's "user-provided corpus via
  `$EXTRACTION_OCR_SAMPLES_DIR`" gate stays as-is; CI continues to skip
  `pytest -m slow`. The trade-off is acknowledged: hermetic-mock-only
  testing cannot catch upstream model-path drift — only a hands-on smoke
  run on a developer machine surfaces it (as happened in this audit).

**Why the original tests didn't catch this:** every test in
`tests/ocr/test_docling_engine.py` mocks `DocumentConverter` via
`_converter_factory=lambda _: stub`. The mock bypasses
`_build_default_converter` entirely, so the hardcoded paths were never
resolved against disk. The `@pytest.mark.slow` parametrised real-OCR test
in the same file would have caught it but is env-gated and skipped in CI
per §17.3 (PDFs carry personal data and stay local-only).

**Files touched:**

- `src/extraction_service/ocr/docling_engine.py` — paths + lang + asserts.
- `docs/plan.md` — §2.5 code snippet synced to current state with an
  inline pointer to this §17.16.
- This file (§17.16 entry).

---

## §17.17 — det model swap: server → mobile (23–63× speedup, char parity)

**Surfaced by:** continuation of the §17.16 smoke-validation session on
`chore/phase-2-ocr-validation` (2026-05-13). After the §17.12 fixes landed
and OCR started producing real German contract text, the per-page time
with `ch_PP-OCRv5_det_server.onnx` (88 MB) was 68–140 s/page on Mac
Mini M4 — making a typical 8-page contract a 9–18 minute job. The plan
§2.5 example wired the server variant on the assumption that high-
accuracy detection would matter for watermarks and stamps (a concern
that §17.1 later dropped: 97% of real contracts have no watermarks).

**Plan text:** §2.5 example code wired
``ch_PP-OCRv5_server_det.onnx`` (now ``ch_PP-OCRv5_det_server.onnx``
per §17.16). The plan's accompanying note explicitly directed
"evaluate during validation. Do not optimize before validation."

**Deviation:** swap det model to
``ch_PP-OCRv5_det_mobile.onnx`` (4.8 MB, 18× smaller than server).

**Validation evidence (5 PDFs, mixed sizes, same rec/cls/lang config):**

| PDF | Pages | Server time | Mobile time | Speedup | Char delta |
|---|---:|---:|---:|---:|---|
| Anadi (90 KB) | 8 | 550 s | 23.5 s | 23× | +0.14% (28,324 → 28,364) |
| Molla (115 KB) | 4 | — | 9.4 s | — | — |
| BKS (1.8 MB) | 3 | — | 7.1 s | — | — |
| Raika (6.0 MB) | 6 | — | 14.9 s | — | — |
| Easyban (21 MB) | 8 | 1126 s | 17.9 s | **63×** | — (full server md not saved; first-1500-char spot-check parity) |

Per-page time on mobile: **2.2–2.5 s, dead consistent across input
sizes**. The speedup gradient is the key finding: 23× on a clean low-DPI
PDF rises to 63× on a high-DPI image-heavy scan. Server's compute scales
aggressively with input resolution (25M parameters, full convs); mobile's
MobileNetV3-derived backbone scales sublinearly via depthwise-separable
convolutions.

**Quality verification:** the one PDF with side-by-side server + mobile
runs (Anadi, 90 KB / 8 pages) produced 28,324 chars on server and 28,364
chars on mobile — a 0.14% delta, mobile slightly more permissive. Spot-
checks across all 5 mobile-run PDFs preserved: bank/borrower names with
diacritics (Pfaffstätten, Möllersdorf, Wörthersee, Niederösterreich),
amounts in German numeral form (zweihundertfünfunddreißigtausend),
IBANs (AT08…, AT03…), dates (30.09.1983, 14.06.1977), German legal
terms (Sollzinsen, Verbraucherkreditgesetz, Pfandbriefdeckungskredit).
Both server and mobile show rec-level OCR artifacts on dense compound
words and high-DPI noisy regions (e.g., server's `Kre ditb etr ag`,
mobile's `IRAN` for IBAN on the Easyban cover sheet). These are
rec-model errors (kept the same `latin_PP-OCRv5_rec_mobile.onnx` in both
configs), not det errors — switching det doesn't affect them.

**Why this is plan-compliant, not a deviation against intent:** plan §2.5
explicitly said "evaluate during validation. Do not optimize before
validation." The original server choice was a starting point; validation
just exercised the evaluation pathway and selected the cheaper variant
based on evidence. The plan's three-step language-evaluation ladder
(§17.16 covered the rec model swap from Chinese-server to Latin-mobile);
this §17.17 covers the parallel det evaluation that landed at mobile too.

**Coverage caveats — what we have NOT proven:**

- **15 of 20 corpus PDFs untested with mobile det.** The 5 tested span
  90 KB to 21 MB across 4 different banks and 4 different formats (Anadi
  / WSK / BKS / Raifeissen / Easyban). The spread is representative but
  not exhaustive. A particularly noisy scan (fax-quality, hand-stamped,
  or photographed-by-phone) could expose detection-recall failures
  unique to it.
- **No full-text diff between server and mobile.** The Anadi side-by-side
  is char-count-equivalent and first-1500-char content-equivalent, but
  the FULL 28,324-character markdown could still differ in ordering or
  detection of specific regions. Running `word_recall(server, mobile)`
  from `tests/ocr/conftest.py` over the full corpus would close this
  gap; deferred as not blocking for this session.

**Fallback path:** if a future PDF exhibits detection failures (text
blocks missing entirely, page structure broken), operators can switch
back to server with a 1-line edit in `_build_default_converter`:

```python
det = model_dir / "onnx" / "PP-OCRv5" / "det" / "ch_PP-OCRv5_det_server.onnx"
```

No other changes needed — rec/cls/lang stay as-is. This makes mobile
the default with a known-good escape hatch.

**Files touched:**

- `src/extraction_service/ocr/docling_engine.py` — det path + docstring
  rationale paragraph.
- `docs/plan.md` — §2.5 code snippet det line.
- This file (§17.17 entry).

---

## §17.18 — `from None` reversal of §17.15 re-examined: post-merge re-add audit trail

**Date:** 2026-05-13 (standalone pass3 single-cycle panel review, Lens 01
Important).

**Context — §17.15's original decision:**

§17.15 records the cycle-4 terminal call on the
`chore/phase-2-ocr-review-fixes-2026-05-13` review loop: the cycle-1
addition of `from None` on the non-SUCCESS `OcrError` raise in
`docling_engine.py` was reversed in commit `fe8a6d5` under the heading
"drop misleading `from None` on non-SUCCESS conversion raise". The
rationale was that TRY200 (ruff's "avoid raising vanilla Exception from
except handler without chaining") only fires inside `except` handlers, so
the `from None` was syntactically legal but semantically misleading — it
implies a prior exception is being explicitly suppressed, which is not the
case for the status-check path that raises unconditionally at the end of a
try/except block.

**Drift detected — what landed on `main` after that reversal:**

Two commits on the post-merge standalone-review branch
`chore/panel-review-fixes-2026-05-13` re-introduced `from None` on **both**
the `OcrError` (status-based path) and `OcrEmptyOutputError` (empty-output
path) raises in `src/extraction_service/ocr/docling_engine.py`:

- Commit `116bfaa` — recorded in CI/CD spec
  `2026-05-11-ci-cd-scaffolding-design.md` §17.37.
- Commit `d1673de` — recorded in CI/CD spec
  `2026-05-11-ci-cd-scaffolding-design.md` §17.38.

Both commits were on `chore/panel-review-fixes-2026-05-13` and landed on
`main` via PR #15 (`dfe66fd`). `origin/main` HEAD `6791448` therefore
carries `from None` on both raises — the opposite of §17.15's "terminal"
state.

**Why the re-add was correct:**

The CI/CD spec §17.37 + §17.38 entries (in
`2026-05-11-ci-cd-scaffolding-design.md`) record the reasoning in full;
the short form here:

- The `OcrError` raise in the status-check path and the `OcrEmptyOutputError`
  raise in the empty-output path both occur **inside a `try/except` block**
  that caught a real exception. Without `from None`, Python's implicit
  exception chaining (`__context__`) would attach that caught exception to
  the newly raised error — exposing an irrelevant internal exception to
  callers and in tracebacks. The `from None` suppression is therefore
  semantically correct: these are **domain-layer errors with no meaningful
  underlying Python exception to surface**, and `from None` is the standard
  CPython idiom for explicit suppression.
- The cycle-4 §17.15 framing ("outside an except block") was factually
  incorrect for these two specific raise sites: both sit inside `except`
  handlers. That error in the cycle-4 analysis is what the CI/CD spec
  §17.37 + §17.38 panel cycles subsequently caught and corrected.

**How to interpret §17.15 going forward:**

§17.15's "reversal" entry (`fe8a6d5`) reflects the cycle-4 analysis at the
time it was written and should be read as **superseded** by the re-add
evidence in the CI/CD spec. A reader arriving at §17.15 cold and wondering
why `from None` is back in the source code should:

1. Follow the cross-pointer to
   `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md` §17.37
   for the first `from None` re-add and its rationale.
2. Then §17.38 of the same file for the second `from None` re-add
   (OcrEmptyOutputError path) and final confirmation.
3. Then this §17.18 for the audit-trail summary tying the two specs
   together.

**Cross-references (per CLAUDE.md "qualify cross-file references with the
filename to disambiguate" rule):**

- `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md` §17.37 —
  first `from None` re-add (OcrError status-based raise), commit `116bfaa`.
- `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md` §17.38 —
  second `from None` re-add (OcrEmptyOutputError empty-output raise),
  commit `d1673de`.
- `docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md` §17.15
  — the superseded "terminal reversal" entry this §17.18 corrects.

**Files touched:**

- This file (§17.18 entry, append-only — §17.15 not modified per
  CLAUDE.md "do NOT retroactively rewrite earlier subsections" rule).

---
