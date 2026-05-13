# Phase 3 (LLM layer) — spec deviations

This file records material deviations from [docs/plan.md §6.5](../../plan.md)
introduced during Phase 3 development. Append a new `§17.N` subsection per
pass; do not retroactively rewrite earlier subsections. Convention mirrors
the Phase 2 spec at
`docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md §17` and
the Phase 0.5 spec at
`docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md §17`.

**Namespace note:** `§17.N` here is the Phase 3 namespace and is independent
of the CI/CD spec's `§17.N` and the Phase 2 spec's `§17.N`. When citing a
deviation across files, always qualify with the filename (e.g. "phase-3 spec
§17.1 deferred `prewarm.py`") to disambiguate.

---

## §17.1 — `scripts/prewarm.py` exit-criterion DEFERRED to Phase 6

**Plan text:** Phase 3 exit criteria ([docs/plan.md §6.5 line 761](../../plan.md)):
"all unit tests pass; `scripts/prewarm.py` script can hit a real Ollama
instance and get a valid JSON response. Commit, merge."

**Deviation:** Phase 3 ships the LLM layer code (tasks 3.1–3.7) but does
NOT include `scripts/prewarm.py`. The unit-test gate alone is treated as
the sufficient exit signal for Phase 3.

**Why:** `scripts/prewarm.py` is later re-assigned to Phase 6
([docs/plan.md §6.8 line 810](../../plan.md), task 6.1: "Real Ollama smoke
test script — hits Ollama with a 1-token request to load the model").
The plan has two references to the same artifact — Phase 3 exit criteria
and Phase 6 task 6.1 — that disagree about ownership. Phase 6 is the
correct home because: (1) prewarm requires a running Ollama process,
which makes it a manual / ops artifact rather than a unit-test concern;
(2) it pairs naturally with Phase 6 task 6.4 ("Pre-warm at startup —
in lifespan, before returning ready, send a trivial chat to Ollama")
which calls the same code path from the FastAPI lifespan; (3) Phase 3's
genuine deliverable is the LLM-client *library* code, which is
verifiable end-to-end via the unit-test suite against `FakeOllamaClient`
without needing real Ollama. (No specific test count is pinned here —
it drifts as panel reviews add coverage; the authoritative count is
whatever `uv run pytest -q tests/unit/test_llm_*.py
tests/fakes/test_fake_ollama.py` reports at the time of reading.)

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

---

## §17.3 — Single-variant commitment to Gemma 4 E2B (q4_K_M)

**Plan text (post-rewrite):** [docs/plan.md §1 line 21](../../plan.md):
"LLM: Ollama with `gemma4:e2b-it-q4_K_M`, `OLLAMA_NUM_PARALLEL=2`,
`num_ctx=8192`, q8_0 KV cache."

**Deviation (architectural):** The project commits to a single sanctioned
Gemma variant — `gemma4:e2b-it-q4_K_M` — and retires the previously
documented swap-up path to a larger Gemma 4 variant. Four such
references in `docs/plan.md` (the swap-up parenthetical at §1 line 21,
the larger-variant annotation in the §3.1 ASCII diagram at line 199,
rule #14 at line 931 referencing F1 numbers on the larger variant, and
the Stretch Items "MTP speculative decoding" trigger at line 949) were
scrubbed in this pass.

**Why:** User-imposed architectural commitment recorded 2026-05-13:
Gemma 4 E2B is the sole sanctioned variant — no larger Gemma 4
variants and no other Gemma families are permitted. The strict-variant
decision is taken as given; this entry records the consequence, not
the negotiation.

**Test-suite drift remediation (mechanical):** The pre-existing test
fixtures and one docstring example carried two predecessor-Gemma model
literals (one small-size, one large-size) despite the production
default having always been `gemma4:e2b-it-q4_K_M`. The drift never
produced a red gate because `OllamaLlmClient.extract` treats the
`model` kwarg as an opaque pass-through string. Remediation: 33
mechanical literal renames across
[`src/extraction_service/llm/client.py:130`](../../../src/extraction_service/llm/client.py)
(1 docstring example),
[`tests/unit/test_llm_client.py`](../../../tests/unit/test_llm_client.py)
(19 fixture occurrences), and
[`tests/fakes/test_fake_ollama.py`](../../../tests/fakes/test_fake_ollama.py)
(13 fixture occurrences) — all replaced with the production-default tag.

**Test restructure (one):** `test_fake_ollama_client_last_call_updated_on_repeated_calls`
originally relied on two distinct predecessor-Gemma model strings to
demonstrate that `last_call` reflects the most-recent call. With the
strict single-variant rule, two distinct *model* strings are not
available; the test now varies the `messages` payload between calls
and asserts on `last_call["messages"]`. The "second call overwrites
first" property is preserved verbatim — the variance vehicle changed
from `model` to `messages`, nothing else.

**What this deviation does NOT change:**

1. Two-lane LLM-inference design (`OLLAMA_NUM_PARALLEL=2`,
   `num_parallel: PositiveInt = 2`, two FastAPI worker coroutines).
2. 8K context window (`num_ctx=8192`).
3. q8_0 KV-cache configuration.
4. 16-GB Mac Mini M4 hardware target / 20-job intake queue / 4-job
   inter-stage queue sizes.
5. Phase 3 LLM-client behaviour: retry policy, timeout mapping,
   context-overflow → `ContextOverflowError` heuristic, dev-mode
   `_debug` block, format-arg propagation. All unchanged.
6. No exit criteria moved. No library swapped. No public API changed.

**How to apply:** Future contributions MUST use `gemma4:e2b-it-q4_K_M`
as the sole Gemma model identifier anywhere in shipped source. Test
fixtures requiring two-distinct-value semantics MUST vary a non-model
field (messages, options, format, etc.) rather than smuggle a second
Gemma variant. If a future engineering need genuinely requires a larger
variant, the path is to reverse this commitment with a new §17.N
subsection (NOT to retroactively rewrite §17.3).

**Planning artifact:** Full migration scope captured in
[docs/superpowers/plans/2026-05-13-gemma-4-e2b-only-migration.md](../plans/2026-05-13-gemma-4-e2b-only-migration.md).

---

## §17.4 — Panel review cycle 1 close (2026-05-13) on `chore/docs-gemma-4-migration`

**Trigger:** User-requested 20-lens panel against `chore/docs-gemma-4-migration`
(PR #16) after the panel was initially "permanently skipped" per the
PR-self-review exemption in §6 of the migration plan.

**Diff range reviewed:** `origin/main..HEAD` = `dfe66fdb..597de8ee`. All 20
lenses ran in parallel (`subagent_type=general-purpose`, `model=sonnet`)
with cycle-independent clean prompts.

**Per-lens verdict:** 14 Yes (ship-ready within lens) / 5 With fixes / 0 No.
The "With fixes" set concentrated on documentation accuracy; the
code-correctness lenses (typing, error handling, security, package layout,
pytest infrastructure, CI test execution, test isolation, dependency
management, pre-commit, CI workflow, scope creep, naming) all returned
clean.

**Convergent finding (load-bearing — ≥2 lenses):** Lenses 01 (phase plan
adherence) and 17 (documentation completeness) both flagged that the
migration plan's §3.1 described a rule-#14 rewrite landing as "F1 numbers
on Gemma 4 E2B at both q4_K_M and q8_0 quantisations," but the
actually-landed text at `docs/plan.md:931` reads "until F1 numbers
confirm Gemma 4 E2B (Q4_K_M) is insufficient." The q8_0 quant escalation
was dropped mid-migration in response to a user directive that Q4_K_M is
the only sanctioned quant, but the migration plan still described the
older intent. Fixed by aligning the migration plan §3.1 and §6 risk row
to the actually-landed text.

**Single-lens applied findings:**

1. Migration plan §4 / §5 / §7 said "five commits" but the branch carries
   six (planning artifact + five implementation commits). Lens 01 Minor.
   Clarified by qualifying the count as "five implementation commits" and
   naming the planning artifact commit (`5963b40`) separately.
2. Migration plan §3.4 said the restructured test asserts on
   `last_call["messages"][0]["content"]`, but actual code asserts on
   `last_call["messages"]` (the full list). Lens 07 Minor. Fixed by
   updating the §3.4 description.
3. Test docstring at `tests/fakes/test_fake_ollama.py:123` referenced
   `§17.3` without filename qualification, ambiguous given the Phase 2
   spec also has a §17.3 in a different file. Lens 13 Minor. Fixed per
   CLAUDE.md cross-file-reference convention to "§17.3 of the Phase 3
   LLM spec deviations log."
4. `CLAUDE.md § Where things live` roster omitted the Phase 3 LLM spec
   deviation log, making §17.3 invisible to the canonical maintainer
   index. Lens 17 Important. Fixed by adding the Phase 3 entry.
5. PR title used `fix:` prefix but the constituent commits are docs +
   test renames with no production bug fix. Lens 20 Minor. Updated to
   `chore(docs):` to match the branch prefix and the actual change kind.

**Findings dropped per senior-dev filter:**

- Lens 02 Minor: `fix(llm)` → `docs(llm)` type-prefix on commit
  `8704eec`. Force-pushing to mutate a published commit for a cosmetic
  type-prefix is upside-down cost/benefit per CLAUDE.md commit-history
  conventions. The commit body explicitly states "Behavioural impact:
  zero — docstring is documentation only," which mitigates the wording
  mismatch.
- Lens 06 Minor: Suggested adding "(i.e. `gemma3:4b`)" parentheticals
  next to the `predecessor-small-literal` / `predecessor-large-literal`
  placeholders in the migration plan. Dropped — reintroducing `gemma3`
  strings violates the strict-no-gemma3 rule from §17.3.
- Lens 08 Minor: Suggested removing the `§17.3` cross-reference from the
  test docstring (claiming it's spec-deviation justification belonging
  elsewhere). Dropped — the cross-reference is informative
  WHY-documentation for an otherwise non-obvious test restructure;
  reader-utility outweighs the style preference for terse test
  docstrings.
- Lens 12 Minor: Suggested adding `(ollama>=0.6)` version annotation to
  `docs/plan.md:21`. Dropped — adding a new doc convention not present
  in the original spec is scope creep beyond the migration; the
  lockfile pins `ollama==0.6.2` authoritatively.

**Finding deferred (one):**

- Lens 16 Minor: `tests/fakes/fake_ollama.py:115-119` stores caller's
  `messages` list by reference (not snapshot) in `last_call`.
  Pre-existing fragility, not introduced by this diff; no current test
  mutates the list post-call. Deferred to a future cleanup pass when a
  real test mutation pattern requires the snapshot semantics. No
  re-trigger is required because the audit trail here IS the record.

**Outcome:** Cycle 1 closes with 5 applied fixes across 4 atomic commits
(plan doc, test docstring, CLAUDE.md, this §17.4 audit) plus 1 PR-title
update via `gh pr edit` (non-commit). Re-run of the verification gate is
green: `ruff check`, `ruff format --check`, `mypy src tests`,
`pytest -q` (192 passed / 1 unrelated skip), `pip-audit --skip-editable`,
`pre-commit run --all-files` (14 hooks). No further panel cycle will be
dispatched without explicit user instruction.

**How to apply (going forward):** When a panel review identifies a
divergence between a migration plan's described commit text and what
actually lands (because a user directive arrived mid-migration), update
the migration plan to match the landed state — the plan is an as-built
record, not an aspirational draft.

---

## §17.5 — PR #14 squash subject under-stated material constituents (cross-reference)

**Date:** 2026-05-13 (standalone panel single-cycle pass3 review against `main`).

**Source:** Lens 02 (Commit-message coverage) — Important finding.

**What the squash subject claimed:**

```
feat(phase-3): LLM layer (Ollama client + prompt + schema + retry + timeout)
```

**What the 22-commit squash actually delivered beyond the subject:**

1. **`SIDE_CHANNEL_KEYS: frozenset[str]` public export** in
   `src/extraction_service/llm/__init__.py`. This is the Phase 4
   strip-set helper that downstream workers use to pop side-channel
   metadata keys (e.g. `_debug`) before passing the dict to the
   validator. The subject parenthetical names five components but
   omits this public symbol.

2. **`ContextOverflowError` domain-error mapping** in
   `src/extraction_service/domain/errors.py` and
   `src/extraction_service/llm/client.py` — including the private
   `_is_context_overflow_error` heuristic helper. `ContextOverflowError`
   is a dedicated domain exception (distinct from the generic `LlmError`)
   with its own observable public behaviour: callers can `except
   ContextOverflowError` to discriminate prompt-too-large failures from
   transient network errors.

3. **Dev-mode `_debug` block and `ClientMode` literal alias** — a new
   constructor parameter (`mode: ClientMode = "production"`) and a new
   conditional top-level key in the `dict[str, Any]` returned by
   `extract()`. Both constitute new public surface for dev/test callers.

**Why this matters:**

A Phase 4 implementer grepping squash subjects for `SIDE_CHANNEL_KEYS`,
`_debug`, or `ContextOverflowError` via `git log --oneline --grep
"SIDE_CHANNEL_KEYS"` would not find PR #14 without this cross-reference.
All three items above are Phase 4 integration points — the strip-set
helper and the error class appear explicitly in the Phase 4 plan task
table. The spec index entry closes the grep gap.

**Remediation status:**

The commit message on `main` is immutable. Per CLAUDE.md ("historical
immutable items on shared branches" → SKIP the commit-message fix), the
correct remediation route is this `§17.N` cross-reference in the Phase 3
spec so that future grep-by-spec-index finds the under-stated
constituents. This entry IS the audit-trail remediation; no further
action on the commit message itself is warranted.

**Forward note:**

Future phase squashes should enumerate all material new public surfaces
(exported symbols, new domain exceptions, new constructor parameters) in
the subject parenthetical. The existing PR-body "What's in this PR"
section is the right draft source: if a bullet there names a symbol not
visible in the subject, add it to the parenthetical before merging.
