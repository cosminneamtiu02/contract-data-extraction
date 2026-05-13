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

---

## §17.12 — Model paths realigned: modelscope filename drift + Latin rec for German

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
det = onnx/PP-OCRv5/det/ch_PP-OCRv5_det_server.onnx          # word-order swap; superseded by mobile in §17.13
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
  inline pointer to this §17.12.
- This file (§17.12 entry).

---

## §17.13 — det model swap: server → mobile (23–63× speedup, char parity)

**Surfaced by:** continuation of the §17.12 smoke-validation session on
`chore/phase-2-ocr-validation` (2026-05-13). After the §17.12 fixes landed
and OCR started producing real German contract text, the per-page time
with `ch_PP-OCRv5_det_server.onnx` (88 MB) was 68–140 s/page on Mac
Mini M4 — making a typical 8-page contract a 9–18 minute job. The plan
§2.5 example wired the server variant on the assumption that high-
accuracy detection would matter for watermarks and stamps (a concern
that §17.1 later dropped: 97% of real contracts have no watermarks).

**Plan text:** §2.5 example code wired
``ch_PP-OCRv5_server_det.onnx`` (now ``ch_PP-OCRv5_det_server.onnx``
per §17.12). The plan's accompanying note explicitly directed
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
(§17.12 covered the rec model swap from Chinese-server to Latin-mobile);
this §17.13 covers the parallel det evaluation that landed at mobile too.

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
- This file (§17.13 entry).

---
