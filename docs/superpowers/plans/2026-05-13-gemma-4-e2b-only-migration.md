# Plan: Strict migration to Gemma 4 E2B (q4_K_M) — single-variant commitment

**Date:** 2026-05-13
**Branch:** `chore/docs-gemma-4-migration`
**Worktree:** `.worktrees/chore-docs-gemma-4-migration` (cut from `origin/main` at `dfe66fd`)
**Source-of-truth model tag:** `gemma4:e2b-it-q4_K_M`
**Two-lane inference design:** unchanged (`OLLAMA_NUM_PARALLEL=2`, `num_parallel: PositiveInt = 2`, two FastAPI worker coroutines)

---

## 1. Background and scope

The user has issued a strict architectural constraint: **Gemma 4 E2B (instruction-tuned, q4_K_M quant) is the only model tag this project tolerates**. No predecessor Gemma model, no Gemma 4 E4B, no other Gemma variant, no other family. This plan executes that commitment across documentation, the production-default settings, the LLM-client docstring, and every test fixture.

A full-repo audit on 2026-05-13 (before any edit) established the following starting state:

- **`CLAUDE.md`** — already declares the service as "Gemma 4 E2B (Ollama)". Clean.
- **`src/extraction_service/settings.py:32`** — `model: str = "gemma4:e2b-it-q4_K_M"`. Clean.
- **`tests/unit/test_settings.py:45`** — asserts the default is `"gemma4:e2b-it-q4_K_M"`. Clean.
- **`docs/plan.md`** — already uses Gemma 4 prose and the full tag in code samples, but **still references E4B as a swap-up option in four places** (lines 21, 199, 931, 949). The strict-E2B commitment requires removing those.
- **`src/extraction_service/llm/client.py:130`** — docstring example shows `"predecessor-small-literal"`. Stale.
- **`tests/fakes/test_fake_ollama.py`** — 13 occurrences (`predecessor-small-literal` ×11, `predecessor-large-literal` ×2). Stale.
- **`tests/unit/test_llm_client.py`** — 19 occurrences of `predecessor-small-literal`. Stale.
- **`docs/superpowers/specs/*`, `README.md`, `pyproject.toml`** — zero Gemma references; nothing to change.

Total surface: **33 string-literal renames + 4 plan.md edits + 1 test restructure + 1 spec-deviation entry**.

Why the test fixtures lagged behind the production default: `OllamaLlmClient.extract()` treats the `model` kwarg as an opaque pass-through string. Every test in `test_llm_client.py` and `test_fake_ollama.py` exercises *forwarding behaviour*, not model behaviour — the tests would pass against `"banana:flambé"`. The drift therefore never produced a red gate; it is a *grep / onboarding / audit* hazard, surfaced by direct inspection, not by CI.

---

## 2. Mapping rule (single, strict)

| From | To | Notes |
|------|----|-------|
| `"predecessor-small-literal"` | `"gemma4:e2b-it-q4_K_M"` | Exact production default. |
| `"predecessor-large-literal"` | `"gemma4:e2b-it-q4_K_M"` | Same target. The `12b` size existed only to provide a *second distinct value* for one test (see §3.4); that test is restructured rather than smuggling a non-E2B Gemma tag. |
| `(swappable to E4B)` parenthetical in `docs/plan.md:21` | (removed) | E4B is no longer a sanctioned fallback. |
| `(or e4b)` parenthetical in `docs/plan.md:199` ASCII diagram | (removed) | Same reason. |
| "Don't switch from Gemma 4 to another family until you have F1 numbers on Gemma E4B" rule (`docs/plan.md:931`) | Rewritten to escalate via E2B-quant comparisons (q4_K_M → q8_0) instead of E2B → E4B size upgrade. | The "prove the current variant insufficient before switching family" intent is preserved; the path goes through quantisation rather than parameter count. |
| `"Throughput inadequate on E2B/E4B"` trigger in `docs/plan.md:949` | `"Throughput inadequate on E2B"` | Single-variant scope. |

**Alternatives rejected:**
- Two-tag tests with a non-Gemma synthetic string for the second call (e.g. `"override-only:tag"`) — introduces a phantom model identifier that confuses grep, code-review, and onboarding. The restructured test (§3.4) achieves the same signal without smuggling any extra model strings into the codebase.
- Short tags (`gemma4:e2b`) — saves typing but breaks the "tests visibly use the same string as the production default" invariant. Full tag wins.
- Module-level constants (`SMALL_MODEL`, `LARGE_MODEL`) — disproportionate ceremony, and "two sizes" no longer exists in the project's mental model.

---

## 3. Execution plan (commit sequence)

Atomic per-concern, all on `chore/docs-gemma-4-migration`. Verification gate runs once after all edits land, before any commit is finalised. Order chosen so that each commit's diff is locally meaningful.

### 3.1 Commit 1 — `docs(plan): commit to Gemma 4 E2B as sole sanctioned variant`

**File:** [docs/plan.md](../../plan.md)

**Edits:**
- Line 21: `Ollama with `gemma4:e2b-it-q4_K_M` (swappable to E4B), ...` → `Ollama with `gemma4:e2b-it-q4_K_M`, ...`
- Line 199 (ASCII diagram): `Model: gemma4:e2b-it-q4_K_M (or e4b), pre-warmed at service startup` → `Model: gemma4:e2b-it-q4_K_M, pre-warmed at service startup` (preserving the right-border column alignment of the box-drawing diagram).
- Line 931: rewrite the rule from "Don't switch from Gemma 4 to another family until you have F1 numbers on Gemma E4B and confirmed they're insufficient." to "Don't switch from Gemma 4 E2B to another family until you have F1 numbers on Gemma 4 E2B at both q4_K_M and q8_0 quantisations and confirmed both are insufficient." The intent ("burn through Gemma 4 options before family swap") is preserved; the escalation path is quant-up, not size-up.
- Line 949 (Stretch Items table): `Throughput inadequate on E2B/E4B` → `Throughput inadequate on E2B`.

**Out of scope for this commit:**
- Line 16 ("Two-lane Gemma 4 E2B inference") — already E2B-only. No change.
- Line 225 (`~7.2 GB for E2B Q4_K_M` memory budget) — E2B-specific, no E4B reference. No change.
- Line 232 (`iogpu.wired_limit_mb=12000`) — generous upper bound, harmless for E2B-only. No change.
- Line 326 (settings.py example in plan.md) — already shows the production default. No change.
- Line 947 ("Cross-family model swaps (Qwen, Llama) | Gemma 4 quality insufficient") — refers to Gemma 4 generally; consistent with E2B-only commitment.

### 3.2 Commit 2 — `fix(llm): align docstring example with Gemma 4 E2B production default`

**File:** [src/extraction_service/llm/client.py](../../../src/extraction_service/llm/client.py)

**Edit:** line 130, `"predecessor-small-literal"` → `"gemma4:e2b-it-q4_K_M"`

**Why:** docstring example should mirror what `settings.py` actually defaults to. Onboarding signal + grep locality.

### 3.3 Commit 3 — `test(llm): align test_llm_client fixtures with Gemma 4 E2B production default`

**File:** [tests/unit/test_llm_client.py](../../../tests/unit/test_llm_client.py)

**Edit:** 19× `"predecessor-small-literal"` → `"gemma4:e2b-it-q4_K_M"` (mechanical full-file replace; no test-behavior changes).

**Why:** unit-level fixtures should match the docstring example + production default — every test reads the same model string, eliminating the "wait, why is this one different?" question for the next maintainer.

### 3.4 Commit 4 — `test(llm): align test_fake_ollama fixtures and restructure repeated-call test`

**File:** [tests/fakes/test_fake_ollama.py](../../../tests/fakes/test_fake_ollama.py)

**Edits:**
- 11× `"predecessor-small-literal"` → `"gemma4:e2b-it-q4_K_M"` (mechanical).
- 2× `"predecessor-large-literal"` in `test_fake_ollama_client_records_last_call_model` (lines 59, 61) → `"gemma4:e2b-it-q4_K_M"`. This test merely asserts that whatever `model` is passed shows up in `last_call["model"]`; collapsing to the production default preserves the signal.
- **Restructure** `test_fake_ollama_client_last_call_updated_on_repeated_calls` (lines 115–123). The original demonstrates "last_call reflects the MOST RECENT call, not the first" using two distinct model strings (`predecessor-small-literal` then `predecessor-large-literal`) and asserts on `last_call["model"]`. With the strict E2B-only constraint, the model must be identical between the two calls, so the new version varies the **`messages` payload** between calls and asserts on `last_call["messages"][0]["content"]`. Same test intent (last_call gets overwritten on every call), no two-distinct-model-strings requirement.

**Why restructure rather than use a synthetic non-Gemma alt-string:** the restructure is a smaller diff than the alt-string approach, preserves the test's intent verbatim, and keeps the codebase entirely free of non-E2B model identifiers — exactly what the strict constraint demands.

### 3.5 Commit 5 — `docs(spec): §17.3 — Gemma 4 E2B sole-variant migration`

**File:** [docs/superpowers/specs/2026-05-13-phase-3-llm-spec-deviations.md](../specs/2026-05-13-phase-3-llm-spec-deviations.md)

**Edit:** append §17.3 subsection recording (a) the audit finding (docs already on Gemma 4; test fixtures and one docstring stale on predecessor Gemma model); (b) the strict-E2B architectural commitment that retired E4B as a swap-up option; (c) the test restructure rationale (messages-variance over model-variance); (d) that no exit criteria, no library, no runtime configuration changed — only the *sanctioned variant set* tightened.

---

## 4. Verification gate

Run once after all five commits' edits are staged, before any commit is finalised, per [CLAUDE.md § Verification gate](../../../CLAUDE.md):

```bash
unset VIRTUAL_ENV
uv lock --check
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src tests
uv run pytest -q
uv run pip-audit --skip-editable
uv run pre-commit run --all-files
```

**Expectations:**
- `ruff check` / `ruff format --check` — green. Edits are pure string-literal replacements + one test restructure that follows the existing test-file style.
- `mypy src tests` — green. No type signatures change; the restructured test's `messages` payload is a `list[dict[str, str]]`, identical to what the existing `test_fake_ollama_client_records_last_call_messages` test uses.
- `pytest -q` — green. Every test in the affected files exercised opaque-string-forwarding behaviour; the renames change only the string, not the assertion shape.
- `pip-audit` / `pre-commit` — green. No dependency or pre-commit-config edits.
- `uv build --wheel` artifact check — **NOT required** (no package-metadata files touched).

If any gate step fails, fix in-place before committing. Do NOT commit a partially-passing tree.

---

## 5. Risk and rollback

| Risk | Severity | Mitigation |
|------|----------|------------|
| Test logic regression from the `last_call_updated_on_repeated_calls` restructure | Low | The restructured test still verifies the documented behaviour (`last_call` updates on every call); it just verifies via `messages` instead of `model`. The companion test `test_fake_ollama_client_records_last_call_model` continues to pin the `model`-recording behaviour. |
| `docs/plan.md` rewrite of rule #14 obscures the original "burn through Gemma options before family-swap" intent | Low | The rewrite explicitly states the escalation path is now q4_K_M → q8_0 at the E2B size, preserving the spirit of "exhaust Gemma 4 before considering Qwen/Llama". |
| Future need to actually use E4B re-emerges | Low–Medium | The strict-E2B commitment is recorded in §17.3 with the rationale. Reversing the commitment is a one-line plan.md re-edit + a follow-up §17.4 note; nothing in code blocks an E4B tag because `settings.model` is a plain `str`. |
| Test runtime regression | None | Restructured test still uses `FakeOllamaClient`; no real Ollama process is touched. |

**Rollback:** `git revert` the five commits in reverse order. The migration is structurally trivial; reverting restores prior state byte-for-byte.

---

## 6. Why this is NOT a Superpowers-flow phase

Per [CLAUDE.md § When NOT to use the Superpowers flow](../../../CLAUDE.md): "one-off fixes outside a phase (direct branch, no worktree, no TDD ceremony for trivial doc/config)." This migration is exactly that — a mechanical rename + a small plan.md scrub + a one-test restructure + an audit entry. The worktree exists because the user explicitly asked for one. We skip:

- TDD red-test ceremony (no new behaviour; the existing tests *are* the regression net).
- Parallel-subagent dispatch (5 commits, 5 files, all under 25 lines diff each — coordination cost exceeds benefit).
- 20-lens panel self-review (a senior-dev visual diff + the verification gate are sufficient for a rename-and-scrub PR; the panel is reserved for phase-PR diffs).
- Draft-PR ceremony (small enough to open as a regular PR for direct user merge).

---

## 7. Handoff (post-implementation)

After the gate passes and all five commits land:

1. `git push -u origin chore/docs-gemma-4-migration`
2. `gh pr create --title "fix: migrate to Gemma 4 E2B (q4_K_M) as sole sanctioned model variant" --body "<...>"` — body summarises §1–§3 and includes the verification-gate result.
3. Stop. User merges via GitHub UI (project convention — Claude does NOT `gh pr merge`).

---

## 8. Out of scope (intentionally not addressed)

- `README.md` — verified no Gemma references; queueing convention applies if any drift ever appears.
- `pyproject.toml`, `.env*` — verified clean.
- `uv.lock` — binary `git grep` hit was for `modelscope` (unrelated to Gemma).
- Phase 4–6 implementation tasks — orthogonal to this migration.
- Ollama runtime tag pull (`ollama pull gemma4:e2b-it-q4_K_M`) — operator concern, not code.
- The `iogpu.wired_limit_mb=12000` setting in `plan.md:232` — generous upper bound, harmless for E2B-only; tightening to E2B-actual would be a separate hardening pass.

---

## 9. What this plan does NOT change

For audit clarity: the two-lane LLM-inference design (`OLLAMA_NUM_PARALLEL=2`, two FastAPI worker coroutines, `num_parallel: PositiveInt = 2`) is unchanged. The 8K context window (`num_ctx=8192`) is unchanged. The q8_0 KV-cache configuration is unchanged. The 16-job intake queue / 4-job inter-stage queue sizes are unchanged. The Mac Mini M4 / 16 GB hardware target is unchanged. The Phase 3 LLM-client *behaviour* (retry, timeout, context-overflow mapping, dev-mode `_debug` block, format-arg propagation) is unchanged.

This is a model-identifier-tightening migration, not an architectural one.
