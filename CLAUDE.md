# CLAUDE.md

Operating manual for Claude Code (and any compatible AI assistant) working on `contract-data-extraction`. Loads automatically at session start.

## Project context

Local single-process HTTP service that ingests scanned German legal contracts, OCRs all text (body, watermarks, logos, stamps), and uses Gemma 4 E2B via Ollama to extract structured JSON. Python 3.13, `uv`-managed, ruff + mypy strict, FastAPI + asyncio. Target hardware: Mac Mini M4, 16 GB.

Read [docs/plan.md](docs/plan.md) for the full architecture and phase-by-phase plan. Phase progress lives in commits and in [docs/superpowers/specs/](docs/superpowers/specs/).

## Phase development methodology — go-to strategy (Superpowers flow)

**When the user asks for phase work** — phrases like "start phase 1", "implement Phase N", "begin phase X", "let's do phase Y", "next phase", or "what's next" when the answer is the next phase per the plan — use the full **Superpowers flow** below. It applies to every phase in [docs/plan.md §6](docs/plan.md) (Phases 1 → 6; Phase 0 / Phase 0.5 / Phase 1 are already shipped or in-review on `main`).

The flow has **two phases**, both automatic:

1. **Development** — TDD, worktree isolation, parallel subagent dispatch per dependency layer until every task in the plan table lands.
2. **Self-review** — once dev is done and the PR is opened as draft, **automatically** fire the 20-lens panel on the PR diff, synthesize findings in the main conversation, triage per the project's rules, apply fix-now items as additional commits, then mark the PR ready for review.

The user only takes over **after** the PR is marked ready: they decide on merge timing, request further panel passes if they want, address any reviewer comments. Use both phases together as a single sequence; do not stop after `gh pr create` and ask "do you want a review now?" — the review is part of the standard flow.

### Why this flow

- **The plan IS the spec.** Each phase in [docs/plan.md §6](docs/plan.md) has a numbered task table listing files, RED tests, and GREEN implementations. Re-brainstorming isn't needed.
- **TDD is rigid for production code.** Every task — main-conversation or subagent — follows `superpowers:test-driven-development`: no production code without a failing test first. The plan's RED test column is the contract.
- **Per-phase git worktree isolates the work.** `./.worktrees/phase-N-<slug>/` is the phase's checkout; the main directory stays on `main` so you can answer review comments on an earlier phase's PR without `git stash` dancing. `.worktrees/` is already in `.gitignore`.
- **Parallel subagent dispatch is the wall-clock multiplier.** Independent tasks fire in a single message via multiple `Agent` calls; layer dependencies sequentially. With 6+ independent tasks (as Phase 1 had) this saves ~25 minutes per phase.
- **Self-review before handoff catches the items the dev-time subagents miss.** The 20-lens panel sees the assembled phase as a whole — cross-cutting concerns like type-completeness, test isolation, dependency hygiene that no per-task subagent had the context to flag. Convergent findings (≥2 lenses agree) are the strongest signal of a real defect. Running the review automatically means the user receives a PR that has already absorbed the panel's fix-now bucket, not a raw dev branch.
- **Handoff = PR marked ready.** Once `gh pr ready` returns, the user drives every downstream decision: merge timing, further panel passes, reviewer-comment responses, deferred-items follow-up. **Never** `gh pr merge` without explicit instruction. Never merge locally. See [memory/feedback_pr_workflow.md](../../.claude/projects/-Users-cosminneamtiu-Work-contract-data-extraction/memory/feedback_pr_workflow.md).

### The flow

1. **Identify the phase.** Read its section in [docs/plan.md](docs/plan.md) — §6.3 Phase 1, §6.4 Phase 2, …, §6.8 Phase 6. The task table is the spec.

2. **Sync `main`, cut the worktree.**
   ```bash
   git fetch origin
   git worktree add -b phase-N-<slug> .worktrees/phase-N-<slug> origin/main
   cd .worktrees/phase-N-<slug>
   ```
   The branch name matches the plan: `phase-1-domain`, `phase-2-ocr`, `phase-3-llm`, `phase-4-pipeline`, `phase-5-http`, `phase-6-hardening`. All subsequent commands run from inside the worktree directory.

3. **Build the task dependency graph.** For each task in the plan table, list:
   - The files it touches (e.g., `src/.../stage.py`, `tests/unit/test_domain_stage.py`).
   - Which earlier tasks it imports from (e.g., 1.3 imports `StageState` from 1.2, so 1.3 depends on 1.2).
   - Whether it shares any file with another task in the layer (those can't run in parallel — same-file writes race).

   Group into **layers** where every task in a layer is independent of every other task in that layer:
   - **Layer A** = tasks with no plan-internal dependencies AND no file overlap with other Layer A tasks.
   - **Layer B+** = each layer adds tasks whose dependencies have all landed in earlier layers.

   Example from Phase 1: Layer A = {1.1, 1.2, 1.5, 1.6, 1.7, 1.8, 1.9}; Layer B = {1.3} (touches `stage.py` which 1.2 created); Layer C = {1.4} (imports `StageRecord` from 1.3).

4. **Track tasks with TodoWrite.** One todo per task, plus terminal todos "Run final local verification gate" and "Open PR via gh pr create (HANDOFF — stop after PR is open)."

5. **For each layer, dispatch:**

   **Layer with ≥2 independent tasks** — single assistant message with one `Agent` tool call per task, all running concurrently:
   - `subagent_type: general-purpose` for every task.
   - `model: sonnet` unless the task is genuinely Opus-class (rare for a plan-spec'd implementation task).
   - **No `run_in_background`** — wait for all agents in the layer to return before proceeding. The serial gate runs after the layer.
   - Prompt template — see [§ Subagent dispatch template](#subagent-dispatch-template) below.

   **Layer with 1 task** — main conversation implements it directly under TDD.

6. **After each layer, run the full local verification gate** from the worktree (see [§ Verification gate](#verification-gate-all-must-pass-before-commit) below). Catches cross-task regressions immediately so layer N+1 doesn't build on rot. If anything is red, fix in the main conversation before dispatching the next layer.

7. **Repeat steps 5–6** for every remaining layer.

8. **Final verification gate.** One more pass of every command in [§ Verification gate](#verification-gate-all-must-pass-before-commit) on the assembled branch.

9. **Push the worktree branch.** `git push -u origin phase-N-<slug>` from inside the worktree.

10. **Open the PR as DRAFT.** `gh pr create --draft --title "feat(phase-N): <phase title>" --body "<standard body>"` with the [standard PR body sections](#conventional-commits--pr-conventions): Summary, What's in this PR (per commit), What's NOT in this PR (rationale), Spec deviations, Test plan (local fully checked, CI unchecked — the four required jobs run automatically). Draft state signals "work in progress through self-review pass."

    --- end of development; the self-review pass begins automatically ---

11. **Fire the 20-lens panel on the PR diff.** Use the dispatch mechanics from [§ Code review methodology](#code-review-methodology--go-to-strategy):
    - `BASE_SHA` = `origin/main`
    - `HEAD_SHA` = the just-pushed phase branch HEAD
    - All 20 `Agent` calls in **a single assistant message**, `subagent_type: general-purpose`, `model: sonnet`, `run_in_background: true`.

12. **Synthesize findings in the main conversation** per [§ The synthesizer pass](#the-synthesizer-pass--never-delegate). Demote aggressively; promote convergence (≥2 lenses agree → load-bearing); pick a side on inter-lens disagreement; reverse prior-round fixes when new evidence justifies it.

13. **Triage and apply fix-now items** per [§ Triage rules](#triage-rules--what-gets-fixed-now). **Fixes land on the SAME phase branch** (not a new `chore/panel-review-fixes` branch — that naming is reserved for *standalone* reviews of already-merged code; phase-PR self-review stays on the phase branch). Atomic per-concern commits, conventional-commits format. Update the PR body's "Spec deviations" section if any fix records a new deviation; append to the phase's spec deviation log at [docs/superpowers/specs/](docs/superpowers/specs/) for material deviations.

14. **Re-run the full local verification gate** from the worktree after all fixes apply.

15. **Push the self-review fixes** to the PR: `git push origin phase-N-<slug>`.

16. **Mark the PR ready for review.** `gh pr ready <PR#>`. The self-review pass is complete; the PR is in deliverable state for the user.

17. **STOP. Handoff to user.** Report in one message:
    - PR URL.
    - Dev commits (one line per task).
    - Self-review summary: convergent findings, per-lens verdicts table, fix-now items applied (per commit SHA), items deferred (with one-line rationale each).
    - Spec deviations recorded (if any).
    - User drives from here: merge timing, further panel passes ("rerun the review" → pass-2 against `origin/main..HEAD`), reviewer comments, CI-failure response if the four required checks go red.

    Do NOT, without explicit instruction: `gh pr merge`, dispatch a second panel pass, push further commits, address CI failures, or respond to PR review comments.

### Subagent dispatch template

Each `Agent` call for a Layer-A independent task takes a prompt of this shape. Substitute `{N.M}`, `{TASK_DESCRIPTION}`, `{FILES_OWNED}`, `{FILES_FORBIDDEN}`, `{PLAN_SECTION}`, `{WORKTREE_PATH}`:

```
You are implementing Task {N.M} for the contract-data-extraction project's Phase N.

**Worktree:** {WORKTREE_PATH} — `cd` here first and verify `git rev-parse --abbrev-ref HEAD` returns the phase branch. ALL commands run from inside this worktree.

**Plan reference:** {PLAN_SECTION} of docs/plan.md.

**Your task:** {TASK_DESCRIPTION}

**Files you OWN (read + write):**
{FILES_OWNED}

**Files you must NOT touch** (other agents own them this layer; commits to them will race):
{FILES_FORBIDDEN}

**Workflow — rigid TDD per superpowers:test-driven-development:**
1. Write the failing test(s) first in the test file you own. Split the plan's compact "X and Y and Z" spec into one-behavior-per-test functions.
2. `unset VIRTUAL_ENV && uv run pytest <your-test-file> -v` — confirm the failure mode is "feature missing" (e.g., ModuleNotFoundError), not a typo in the test.
3. Write the minimum implementation in the source file you own. No future-task anticipation.
4. Re-run pytest on your test file. All new tests must pass.
5. Run the full local verification gate from the worktree:
   ```
   unset VIRTUAL_ENV
   uv run ruff check src tests
   uv run ruff format --check src tests
   uv run mypy src tests
   uv run pytest -q
   ```
   Strict-mypy or ruff complaints → restructure the test or code. Do NOT sprinkle `# type: ignore` without a one-line rationale comment on the same line.
6. `git add <your owned files only>` and commit: `feat({N.M}): <subject>` via HEREDOC body explaining WHY, with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` footer. One task = one commit. Do NOT push (the main conversation pushes the whole branch at phase end).

**Project conventions (binding — these override the plan text where they conflict):**
- `frozen=True` Pydantic models for value objects.
- `StrEnum` (Python 3.11+) over `(str, Enum)` for string-valued enums.
- `dict[str, Any]` only at IO boundaries. Every other domain field is concretely typed.
- Test names describe behavior, not implementation (`test_contract_job_is_frozen` ✓; `test_contract_job_pydantic_config` ✗).
- One assertion target per test — split tests if the plan compactly lists "asserts X, Y, Z."

**Return:** brief report (≤200 words) — what you implemented, the commit SHA you produced, and any deviation from the plan text with a one-line rationale. If you couldn't complete the task, report the blocker and DO NOT commit partial work.
```

### Cross-layer reconciliation

Between layers (after step 5, before step 6's gate):

- **No-op in the simple case.** If every agent committed only to files in its `FILES_OWNED` list, the branch is consistent — just run the gate.
- **If an agent reports a deviation** that affects another's task (e.g., renames a symbol another task imports), revise the next layer's dispatch prompts to match the new name. Do not silently let a later task assume the old name.
- **If two agents accidentally touched the same file** (broken file-partitioning): rare with a well-built dependency graph. Inspect with `git diff` per commit; rebase/squash to resolve before the next layer. This is a planning mistake — note it in the spec deviation log so the next phase improves the partition.

### Project-wide best practices to apply uniformly

These survive across phases and override the plan text where they conflict with older wording:

- **`frozen=True` Pydantic models** for value objects ([docs/plan.md §4.11](docs/plan.md)). Nested mutables (e.g., a `dict[str, Any]` metadata field) are *not* deep-frozen — note that in the docstring.
- **`StrEnum` (Python 3.11+) over `class X(str, Enum)`** for string-typed enums. Cleaner `str()` and f-string output for structlog and JSON, identical Pydantic serialization. The plan text predates `StrEnum`; treat its `(str, Enum)` as shorthand.
- **`dict[str, Any]` only at IO boundaries** (e.g., `ContractJob.metadata`, JSON Schema loader output). Every other domain field is concretely typed.
- **No `# type: ignore` without a one-line rationale comment** on the same line. Restructure first; ignore only when there's no clean alternative.
- **Test names describe behavior, not implementation.** `test_contract_job_is_frozen` ✓ ; `test_contract_job_pydantic_config` ✗.
- **One assertion target per test** — split tests when the plan compactly lists "asserts X, Y, Z."

### Spec deviations

- **Minor deviations** (e.g., `StrEnum` over `(str, Enum)`): note in the commit message body and in the PR body's "Spec deviations" section. No spec doc needed.
- **Material deviations** (changing a phase's exit criteria, skipping a task, swapping a library): create or append to a phase spec deviation log under [docs/superpowers/specs/](docs/superpowers/specs/). Phase 0.5 uses `2026-05-11-ci-cd-scaffolding-design.md §17`; later phases get their own files when needed.

### When NOT to use this methodology

- **Phases with only 1–2 independent tasks** — parallel-subagent overhead exceeds the coordination cost. Fall back to serial-in-main-conversation TDD inside the worktree.
- **One-off fixes outside a phase** — direct branch (no worktree, no subagents), no TDD ceremony for trivial doc/config changes.
- **Panel-review-fix branches** — those follow the [Code review methodology](#code-review-methodology--go-to-strategy) flow (`chore/panel-review-fixes` naming, atomic per-concern commits, no subagent dispatch for the fixes themselves).
- **Phase 0, Phase 0.5, Phase 1** — already shipped or merged.

For everything matching "implement phase N" where N ≥ 2 — default to this full Superpowers flow.

## Code review methodology — go-to strategy

**When the user asks for a code review** (phrases like "review this", "panel review", "deep review", "review main", "rerun the review", "review the branch"), use the **20-lens parallel panel** described below. Do NOT default to `superpowers:requesting-code-review` (which uses 1 general-purpose agent with a 5-dimension rubric). The single-agent default is shallower; this project's convention is the panel.

### Why the panel

- **Specialization > breadth.** One general agent balancing security + tests + architecture + style spreads attention thin. 20 narrow lenses each go deep on one dimension.
- **Convergence is the strongest signal.** When N≥2 lenses independently flag the same item, that's higher confidence than any one lens's severity rating. Both Criticals shipped on this project came from convergence.
- **Same wall-clock as single-agent.** Subagents in one message run in parallel — 20 lenses finish in roughly the time the slowest takes.

### The 20 lenses

Always dispatch all 20. Each lens is scoped to one dimension with explicit "out of scope" guards so reviewers stay deep, not broad.

| # | Lens | Focus | Out of scope (handled by other lenses) |
|---|---|---|---|
| 01 | Phase plan adherence | Does committed code match `docs/plan.md` + `docs/superpowers/plans/*` + spec deviation log §17? | Code quality, CI YAML, tests |
| 02 | Commit-message coverage | For each commit, does diff deliver what message claims? Squash commit faithfulness? | Plan itself; CI YAML internals |
| 03 | Scope creep across phases | Did each PR stay within its declared scope (per its spec/title)? | Quality of in-scope code |
| 04 | Type safety & static analysis | mypy strictness, type-hint completeness, `py.typed`, `ANN`/`TCH` ruff coverage | Tests, CI execution, docs |
| 05 | Error handling & exception flow | Bare `except`, swallowed errors, missing `set -euo pipefail`, error wrapping discipline | Types, naming, docs |
| 06 | Naming & API surface | Name clarity, `__all__` correctness, public/private boundaries, dist vs import name | Types, error handling |
| 07 | Dead code & premature abstraction | Unused symbols, stubs without anchors, over-engineering | Style, names |
| 08 | Idiomatic Python 3.13 + ruff config | Modern idioms, ruff rule family coverage, ruff/CI version alignment | Type completeness, naming |
| 09 | Package layout & imports | `src/` layout, hatchling config, import order, circular imports | Module internals |
| 10 | Security & secrets | Hardcoded creds, `.secrets.baseline`, supply-chain (action pinning, lockfile hashes), CodeQL coverage | General CI YAML, dep mgmt |
| 11 | CI workflow correctness | Workflow YAML validity, action pinning, permissions, triggers, concurrency | dependabot.yml; pre-commit; automation gotchas |
| 12 | Dependency management | `pyproject.toml`, `uv.lock`, `dependabot.yml`, `.python-version` consistency | CI YAML; security |
| 13 | Test coverage & meaningfulness | Real-behavior vs mock tests, tautologies, assertion strength | Test infra; CI; determinism |
| 14 | Pytest infrastructure | `[tool.pytest.ini_options]`, `pythonpath`, `conftest.py`, fixtures | What tests assert; CI |
| 15 | CI test execution | Tests actually run? Right matrix? Coverage collected? JUnit output? | Test content; pytest infra |
| 16 | Test isolation & determinism | Order-independence, `tmp_path` usage, env/time/random discipline | Coverage; CI; infra |
| 17 | Documentation completeness | README, plan/spec accuracy, design-doc drift, docstrings, LICENSE | Quality of described things |
| 18 | Pre-commit hooks & local DX | `.pre-commit-config.yaml`, hook/CI parity, hook pinning, README install instructions | CI workflows; repo hygiene |
| 19 | Repository hygiene | `.gitignore`, `.gitattributes`, `.editorconfig`, CODEOWNERS, `.python-version` | Source code; workflows |
| 20 | Workflow/automation gotchas | Dependabot automerge logic, lockfile-sync races, CodeQL config, branch-protection assumptions | General CI correctness; deps |

### Dispatch mechanics

- **Subagent type:** `general-purpose` for every lens. Do **NOT** use `feature-forge:code-reviewer` or any other specialized agent — keep all 20 uniform.
- **Model:** `sonnet` for all lenses.
- **Parallelism:** every dispatch carries `run_in_background: true`. All 20 `Agent` tool calls in a **single assistant message** for true concurrency.
- **Prompt template per lens** (substitute `{LENS_NAME}`, `{FOCUS}`, `{FILES_HINT}`, `{OUT_OF_SCOPE}`, `{BASE_SHA}`, `{HEAD_SHA}`):

```
You are a focused code reviewer in a 20-agent panel reviewing the
`contract-data-extraction` repo at /Users/cosminneamtiu/Work/contract-data-extraction.

**Your lens (stay rigidly within it):** {LENS_NAME} — {FOCUS}

**Files most relevant:** {FILES_HINT}

**Out of scope (other panel members cover these):** {OUT_OF_SCOPE}

Git range: {BASE_SHA} (base) .. {HEAD_SHA} (head). Use `git diff {BASE_SHA}..{HEAD_SHA}` and `Read` to inspect.

Apply the superpowers reviewer rubric (Plan alignment / Code quality / Architecture / Testing / Production readiness) ONLY through your lens. 3-tier severity: Critical (broken/security/data-loss), Important (architecture/missing/test gaps), Minor (style/polish).

**Output (strict format, used by synthesizer):**

### Lens: {LENS_NAME}

### Strengths
- [bullets, specific. "None observed within this lens" if none.]

### Issues

#### Critical
- [file:line] issue — why — how to fix
[or "None within this lens."]

#### Important
[same or "None within this lens."]

#### Minor
[same or "None within this lens."]

### Lens Assessment
**Ship-ready within this lens?** Yes | No | With fixes
**Reasoning:** [1 sentence]

Rules: Don't stretch outside your lens. Don't pad findings. Don't manufacture Critical. Bootstrap scaffolding is mostly Minor.
```

- **Multi-pass reviews:** for a pass-N review (re-running the panel after a previous round's fixes merged), each prompt gets an additional context block: *"This is pass-N. PR #X merged hardening from the prior review. Accepted deviations are recorded in spec §17. Note specifically what is STILL outstanding, NEWLY problematic, or accepted-deferred. Don't re-flag items §17 acknowledges."* Output format adds a "Delta from pass N-1" section with Resolved / Persisting / New.

### The synthesizer pass — never delegate

After all 20 lens reports return, **the synthesis is done in the main conversation, not by a subagent.** Reasons:
1. The user benefits from seeing the synthesis happen in-conversation, not as another tool result.
2. Subagent delegation would hide the re-ranking judgment that's the whole point.
3. The 20 reports collectively fit in main context; a synthesizer agent would add a roundtrip for no real benefit.

**Synthesizer rules:**

1. **Demote aggressively.** Each lens feels pressure to surface at least one Important. With 20 lenses that means ~20 raw Importants. Most need re-ranking to Minor in the global picture. Don't preserve every lens's vote.
2. **Promote convergence.** When ≥2 lenses independently flag the same item, treat it as **load-bearing regardless of individual severities reported**. Convergence is the strongest signal a multi-agent review produces. In this project: the CodeQL `@v4` pin (3-lens convergence in pass 1) and the dependabot `update-types` ecosystem asymmetry (4-lens convergence in pass 2) were both promoted to Critical/Important via convergence.
3. **Inter-lens disagreement: pick a side, explain why.** Don't average, don't punt to the user. Example from this project: Pass-1 Lens 06 said add `__all__: list[str] = []`; Pass-2 Lens 07 called it premature. The synthesizer correctly chose Lens 07 because empty `__all__` actively masks future symbols — a quiet bug-by-construction outweighs an explicit-gate benefit.
4. **Reversing a prior fix is correct when new evidence justifies it.** If lens N now contradicts a fix from a prior round, undo the prior fix. Don't anchor.
5. **The synthesis report structure — strict order; this is what the user reads.** Do not deviate from this order; do not collapse categories; do not skip the per-deferred-item justification length requirement.

   1. **Per-lens verdicts table.** One row per lens: lens number, lens name, verdict (Yes / No / With fixes), and per-severity finding counts. This is the cold-pickup signal — what the panel said at a glance. **No finding details in this table** — those belong in the four sections below.

   2. **Objective fixes (auto-applied).** Findings where no reasonable reader would dispute the item needs fixing. Auto-apply this category. Includes:
      - Convergent findings (≥2 lenses agree on the same item)
      - State-tracking errors in docs (stale claims about CI state, branch protection, infra)
      - Doc hygiene (per the cosmetic-fixes-always-apply rule)
      - Defense-in-depth tightenings with zero current violations
      - Single-lens findings whose substance is uncontested by any other lens (silence ≠ disagreement)

      For each item: file:line, one-line reason, commit SHA where applied.

   3. **Headbutting findings (synthesizer-decided).** Where ≥2 lenses contradict each other on a factual or design call. Do NOT punt to the user; pick a side. For each item: which lenses disagree, the substance of the disagreement, the side I picked (or "both wrong → third option"), and a one-sentence rationale for the call. Applied automatically with the decision recorded in the commit message.

   4. **Deferred (justified) — split into two sub-categories:**

      **4a. Deferred — waiting on a later phase.** Findings that will naturally resurface when the dependent phase code lands, and applying them now means inventing scaffolding (fake consumers, hypothetical threat models, unused config knobs) with no real callsite. Each gets a 3–4 sentence justification, but the justification should name the specific later phase / specific dependency that unblocks the item. These items have a built-in re-trigger.

      **4b. Deferred — other reasons.** Findings deferred because the cost-benefit doesn't work today, the synthesizer can't resolve them without out-of-band info (e.g., a `gh api` call), they're cosmetic and non-load-bearing, or they conflict with a project rule (e.g., "prefer new commit over amend on shared branches"). Each gets a 3–4 sentence justification walking through the specific cost-benefit. **These items will NOT auto-resurface** — a future panel pass needs to explicitly decide to re-take them, so the justification is more load-bearing than for 4a.

      For both sub-categories: not a one-liner; not "Phase 5 will handle it" as a bare statement. The paragraph IS the deferred item's audit trail — a future panel pass that re-flags the same item should be able to read this paragraph and either agree with the deferral or explicitly counter it.

   5. **For user decision (last).** Findings where the project-context judgment call belongs to the user — subjective design choices, naming preferences, scope renegotiations, anything where I could decide either way and reasonable readers could disagree with my call. For each item, include my recommendation based on project context. Then **explicitly ASK the user**: "do you want to decide each of these, or are you OK with me deciding based on project context?" Do NOT decide unilaterally on user-decision items. Do NOT skip the ask.

   The order is non-negotiable: **1. Verdicts → 2. Objective → 3. Headbutting → 4a. Deferred (later phase) → 4b. Deferred (other reasons) → 5. For user decision.** Verdicts first because they're the at-a-glance signal. Objective is largest and most skimmable. Headbutting is the synthesizer's real value-add. Deferred-4a items have a built-in re-trigger; deferred-4b items don't, so the justification carries more weight. User-decision is last because it pauses the flow.

   **Apply-first-then-report execution order — STRICT.** The 5 sections describe the *content* of the report; the *execution* order is different. After the panel returns, the synthesizer:

   1. **Drafts the full report internally** (not shown to the user yet) with all 5/6 categories populated.
   2. **Auto-applies every item in section 2 (Objective fixes)** — atomic per-concern commits, full local verification gate after the batch.
   3. **Auto-applies every item in section 3 (Headbutting findings)** the synthesizer has decided. Only items routed to section 5 (User decision) wait for user input; everything in 2 and 3 is already a decision the synthesizer made, so applying is automatic.
   4. **Pushes the resulting commits to the PR.**
   5. **Presents the full report to the user** with section 2 + 3 already showing commit SHAs as confirmation of what landed, section 4a/4b as deferred-with-rationale, section 5 as the only open ask.

   The user receives a report that is partly a confirmation log ("here's what already happened") and partly a forward ask ("here are the items I held for your call"). They do NOT receive a planning document asking for permission on every Objective item — that loop is wasted; the rules already decided. See [memory/feedback_apply_then_report.md](../../.claude/projects/-Users-cosminneamtiu-Work-contract-data-extraction/memory/feedback_apply_then_report.md).

6. **Skip the synthesized report if asked to go straight to triage.** When the user says "evaluate implementation relevance" or "what's worth fixing", jump straight to the triage matrix below.

### Triage rules — what gets fixed now

This is the **most opinionated** part of the methodology and where the prior single-agent default goes wrong. The default leans conservative ("defer to next phase"); this project's standard is the opposite.

**ALWAYS APPLY (fix-now bucket):**

- ✅ **Convergent findings** (≥2 lenses agree)
- ✅ **Active risks today** (auto-merge gaps, security holes, supply-chain pins, broken plumbing)
- ✅ **EVERY cosmetic fix, without exception, no matter how small.** Doc sync, typos in spec/plan, sample/canonical-reference updates after live divergence, new spec deviation-log sections, version-comment annotations on pinned SHAs, missing one-line code comments, type-alias re-export hints, dependency version-floor additions even if the lockfile pins exact versions today, additional pre-commit hooks that duplicate the verification gate, style refactors of 2-arm `if/else` to `match` statements. **A one-character typo or a one-line annotation IS worth fixing — code quality is non-negotiable and the change being minimal is not a reason to defer.** See [memory/feedback_cosmetic_fixes_apply.md](../../.claude/projects/-Users-cosminneamtiu-Work-contract-data-extraction/memory/feedback_cosmetic_fixes_apply.md). Cosmetic items NEVER appear in the Deferred section of a synthesis report; if a synthesizer routes a cosmetic item to Deferred it has made a categorization error.
- ✅ **Defense-in-depth tightenings** even if the lens called them "not a current defect" (e.g., explicit `permissions: {}` blocks, preventive ruff/mypy rules that don't false-positive on current code)
- ✅ **Reversing prior-round fixes** when a later lens shows them wrong

**DEFER ONLY (narrow bucket):**

- ⏳ Work that **needs later-phase code to exist** to be meaningful:
  - Real behavior-asserting tests (waiting for production code)
  - Coverage gate `--cov` enforcement (waiting for non-stub coverage)
  - mypy → pre-push stage (waiting for codebase growth where pre-commit slowness bites)
  - JUnit XML / test-results artifacts (waiting for tests that produce signal)
  - Python version matrix (waiting for cross-version requirements)
  - ruff `PERF` rules (waiting for loops to lint)
- ⏳ User-excluded items (explicitly named by the user as "skip this")

**SKIP (true non-options):**

- 🚫 Historical immutable items — already-merged commit messages on shared branches (can't be rewritten without destructive ops on `main`)
- 🚫 Genuinely impossible mechanical changes

**Do NOT defer:**

- ❌ "Doc hygiene" / "cosmetic" / "low-priority" — these are fix-now.
- ❌ "Premature" preemptive tightenings whose current cost is 1–3 lines — fix-now.
- ❌ "Not a current defect" defense-in-depth — fix-now.
- ❌ "Will land naturally with the next phase anyway" — if it's a 1-line fix today, fix it today.

### Implementation flow

**The default: review runs on the CURRENT branch — everything built in the current phase. Fixes land on the CURRENT branch.** This is true for both the auto-fired phase-PR self-review and any manual "review this PR" / "review the branch" invocation. The diff under review is `origin/main..HEAD` — i.e., every commit the current branch added on top of `main`, which IS the phase's full body of work. The 20 lenses see the whole phase as a unit; the synthesizer's fix-now items become commits on the same branch you are currently on. **Do NOT cut a separate branch.**

**The exception — only when the user explicitly says "review against main," "review main," or "review the current state of main":** the panel is being run on already-merged code, the diff under review is `<some-base-on-main>..origin/main`, and there is no working branch to put fixes on. In that case, follow the numbered steps below — cut `chore/panel-review-fixes` from `main`, apply fixes there, open a separate PR. This is the *standalone* review pattern Phase 0.5 used after PR #2 merged.

The numbered steps below apply ONLY to the "review against main" exception. For everything else (phase-PR self-review, "review this PR," "panel review the branch"), the fixes go on the current branch — no new branch needed; you skip directly to "apply fixes per the triage matrix" and follow the per-commit + per-PR conventions in [§ Conventional commits + PR conventions](#conventional-commits--pr-conventions).

1. **Cut a new branch from `main`.** Naming: `chore/panel-review-fixes` for first pass, `chore/panel-review-fixes-pass-N` for subsequent. Never work directly on `main`.
2. **Apply fixes.** Use Edit/Write directly. For grouped doc updates, use `replace_all: true` only when the pattern is genuinely identical across sites. For inter-related fixes, prefer atomic per-concern commits over one large commit.
3. **Verify locally — the gate below must be fully green before commit.**
4. **Commit in logical groups** with conventional-commits prefixes (`fix`, `feat`, `ci`, `chore`, `docs`, `test`, `build`, `refactor`). One concern per commit. Use HEREDOC for multi-line messages. Always include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
5. **Push + open PR via `gh pr create`.** PR body must list: items applied (by commit), items explicitly NOT in this PR (with rationale), items permanently skipped (with rationale), local verification checklist (checked), CI verification checklist (unchecked, fires on the PR).
6. **Do NOT merge locally.** User merges via GitHub UI. See [memory/feedback_pr_workflow.md](../../.claude/projects/-Users-cosminneamtiu-Work-contract-data-extraction/memory/feedback_pr_workflow.md).
7. **Update memory** with significant new project state (PR landed, ruleset configured, etc.) — but only what's surprising or non-obvious. Routine PR landings already live in git history; memory captures *interpretive* state.

### Verification gate (all must pass before commit)

Run these locally, in order. If any fails, fix before proceeding — do not commit on a yellow gate.

```bash
unset VIRTUAL_ENV  # in case the wrong venv is active
uv lock --check                           # no lockfile drift
uv run ruff check src tests               # lint
uv run ruff format --check src tests      # format
uv run mypy src tests                     # type check
uv run pytest -q                          # tests
uv run pip-audit --skip-editable          # CVE scan (note: --strict deferred; see spec §17.2)
uv run pre-commit run --all-files         # all hooks
```

For changes touching package metadata (`__init__.py`, `py.typed`, `LICENSE`, `pyproject.toml`'s `[project]`), additionally:

```bash
uv build --wheel
unzip -l dist/extraction_service-0.1.0-py3-none-any.whl | grep -E "(py.typed|LICENSE|__init__|__main__)"
rm -rf dist/
```

This catches PEP 561 / license inclusion regressions that the test gate alone misses.

## Conventional commits + PR conventions

- **Subject line:** `<type>(<scope>): <subject>`. Type ∈ `fix|feat|ci|chore|docs|test|build|refactor`. Subject in imperative mood.
- **Squash type rule:** when squashing a PR, the squash type should match the **highest-impact constituent type** per conventional-commits precedence (`feat` > `fix` > `chore`). If a PR contains a `fix(security)` sub-commit, the squash subject should not be typed `chore`.
- **Subject parenthetical (squash):** should reference all material constituents, not a subset. If a PR adds a `LICENSE` and a `py.typed` marker, the subject must mention them.
- **HEREDOC for multi-line messages** to preserve formatting. Always include the `Co-Authored-By` footer.
- **PR body required sections:** Summary, What's in this PR (per commit), What's NOT in this PR (deferred items + rationale), What's permanently skipped, Test plan (local checked, CI unchecked).

## Project state notes (project-specific guardrails)

- **Default branch is `main`.** Confirmed; no `master`.
- **Auto-merge is armed** for Dependabot patch/minor bumps across pip, github-actions, and pre-commit ecosystems. A major bump requires explicit review (per `update-types: [patch, minor]` filters on every group).
- **Branch protection is live.** Required status checks: `backend-checks`, `darwin-checks`, `CodeQL / Analyze (python)`, `CodeQL / Analyze (actions)`. `gh pr merge --auto` waits for all four.
- **Lockfile sync workflow is live and armed.** PAT is set in the Dependabot secret store (see memory/project_repo_setup_state.md); `vars.DEPENDABOT_LOCKFILE_SYNC_ENABLED = "true"` gates it. An intentional placeholder mirror in the Actions store satisfies VSCode IDE validation — do not delete that mirror.
- **README is the only docs file the user has restricted.** Do not edit it without explicit permission — even for items the panel review flags as belonging in README (e.g., "add `pre-commit install` instruction").
- **Deviations from the original spec land in `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md §17`.** Append a new `§17.N` subsection per pass; do not retroactively rewrite earlier subsections.

## Where things live

- Architecture + phase plan: [docs/plan.md](docs/plan.md)
- Phase 0.5 CI/CD design: [docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md](docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md)
- Phase 0.5 implementation plan (historical record): [docs/superpowers/plans/2026-05-11-ci-cd-scaffolding.md](docs/superpowers/plans/2026-05-11-ci-cd-scaffolding.md)
- Accepted deviations log: spec §17 (each pass appends `§17.N`)
- Memory (auto-loaded each session): `~/.claude/projects/-Users-cosminneamtiu-Work-contract-data-extraction/memory/`
- This file: [CLAUDE.md](CLAUDE.md) — loaded automatically each session

## When NOT to use the 20-lens panel

- **Trivial single-file PRs** where the user explicitly asks for "a quick review" — use `superpowers:requesting-code-review` (single agent) instead.
- **Pre-merge sanity check on tiny changes** — single-agent review suffices.
- **Cloud-billed deep review requested** — that's `/ultrareview`, not this. The user triggers it explicitly when they want it.

For everything else — "review", "panel review", "deep review", "code review", "review the branch / PR / state" — default to the 20-lens panel.
