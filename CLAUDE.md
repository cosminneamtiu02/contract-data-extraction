# CLAUDE.md

Operating manual for Claude Code on `contract-data-extraction`. Loads at session start. Rules only — see linked memory files for rationale, prior examples, and historical context.

## Project context

Local single-process HTTP service: scanned German legal contracts → OCR → Gemma 4 E2B (Ollama) → structured JSON. Python 3.13, `uv`-managed, ruff + mypy strict, FastAPI + asyncio. Target: Mac Mini M4, 16 GB. Phases 0, 0.5, 1, 2, 3 complete. See [docs/plan.md](docs/plan.md) for architecture and [docs/superpowers/specs/](docs/superpowers/specs/) for spec deviation log.

## Phase development — Superpowers flow (Phase 3+)

**Trigger phrases:** "implement Phase N", "begin phase X", "next phase", "proceed with phase X", "take main and work on phase X", "get to work on phase X", or "what's next" (when answer is next plan phase).

**Flow has two automatic phases:** (1) Development with TDD + worktree + parallel subagent dispatch; (2) Self-review with the 20-lens panel on the PR diff, synthesize, apply fix-now items, mark PR ready. User takes over only AFTER PR is marked ready.

**Parallel dispatch is the default for any layer with ≥2 file-disjoint tasks.** Design-nuance worries are NOT a reason to serialize — write nuance into the subagent prompt. Legitimate serial-fallback reasons: (a) layer has only 1 file-disjoint task, (b) all layer tasks share a file (forced serial), (c) WHOLE phase has ≤2 indep tasks across all layers (set-up cost > gain), (d) user asked for a different flow this time. See [[feedback-parallel-dispatch-default]].

### The flow

1. **Identify phase** in [docs/plan.md §6](docs/plan.md). Task table is the spec.
2. **Cut worktree:** `git fetch origin && git worktree add -b phase-N-<slug> .worktrees/phase-N-<slug> origin/main && cd .worktrees/phase-N-<slug>`. Branch names: `phase-1-domain`, `phase-2-ocr`, `phase-3-llm`, `phase-4-pipeline`, `phase-5-http`, `phase-6-hardening`.
3. **Build task dependency graph.** Per task: files-touched + plan-internal imports + same-file-with-peer (parallel-blocker). Group into **Layer A** (no peer overlap, no prior-task deps), **Layer B+** (deps resolved in earlier layers).
4. **TodoWrite** one todo per task + terminal todos for gate and PR-create.
5. **Per layer:** if ≥2 independent tasks, dispatch one `Agent` per task in **a single assistant message**, `subagent_type: general-purpose`, `model: sonnet`, NO `run_in_background` (wait before next layer). If 1 task, do it serially. Use the [§ Subagent dispatch template](#subagent-dispatch-template).
6. **Verification gate after each layer.** Red gate → fix in main conversation before next layer.
7. Repeat 5–6 for remaining layers.
8. **Final verification gate** on assembled branch.
9. `git push -u origin phase-N-<slug>` from worktree.
10. **PR as DRAFT:** `gh pr create --draft --title "feat(phase-N): <title>"` with [standard body](#conventional-commits--pr-conventions). Draft signals "in self-review."
11. **Fire 20-lens panel on PR diff** per [§ Code review methodology](#code-review-methodology). `BASE_SHA=origin/main`, `HEAD_SHA=<phase branch HEAD>`, all 20 in **one message**, `run_in_background: true`.
12. **Synthesize in main conversation** per [§ Synthesizer rules](#synthesizer-rules). Demote / promote-convergence / pick-side-on-disagreement / reverse-prior-fixes-on-new-evidence.
13. **Apply fix-now items** per [§ Triage rules](#triage-rules). Fixes land on the SAME phase branch (NOT a `chore/panel-review-fixes` branch — that's reserved for standalone "review against main"). Atomic per-concern commits. Update PR body's spec-deviations section; append to spec §17 for material deviations.
14. Re-run verification gate after fixes.
15. `git push origin phase-N-<slug>`.
16. `gh pr ready <PR#>`. Self-review pass done; PR deliverable.
17. **STOP. Handoff.** One message with PR URL + dev commits + self-review summary + spec deviations. **Never** `gh pr merge`, dispatch a second panel, push further commits, address CI failures, or respond to reviews without explicit instruction.

### Subagent dispatch template

Each Layer-A independent task gets a prompt with: worktree path (`cd` first, verify branch); plan reference (§6.N task table); task description; `FILES_OWNED` (read+write); `FILES_FORBIDDEN` (peer-owned this layer); rigid TDD workflow (failing test → confirm "feature missing" fail → minimum impl → tests pass → run [§ Verification gate](#verification-gate) → atomic commit with HEREDOC body + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` footer, ONE task = ONE commit, do NOT push); project conventions (binding): `frozen=True` Pydantic for value objects, `StrEnum` over `(str, Enum)`, `dict[str, Any]` only at IO boundaries, no `# type: ignore` without same-line rationale, test names describe behavior not implementation, one assertion target per test. Return: ≤200-word report — what implemented + commit SHA + deviations.

### Cross-layer reconciliation

After each layer, before the gate: if any agent reported a deviation affecting another's task (e.g., renamed symbol), update next layer's prompts. If two agents accidentally touched the same file (broken partitioning), inspect with `git diff`; rebase/squash; note in spec deviation log.

### Spec deviations

- **Minor** (e.g., `StrEnum` over `(str, Enum)`): commit body + PR "Spec deviations" section.
- **Material** (changing exit criteria, skipping a task, library swap): append a new `§17.N` subsection to the per-phase spec file under `docs/superpowers/specs/` (see the "Where things live" section for the current file roster; create a new file when a phase makes its first material deviation). Do NOT retroactively rewrite earlier subsections.

### When NOT to use the Superpowers flow

Phases whose ENTIRE task list has only 1–2 independent tasks across ALL layers (per-WHOLE-PHASE threshold, not per-layer — parallel overhead exceeds coordination cost; fall back to serial TDD in main convo inside worktree); one-off fixes outside a phase (direct branch, no worktree, no TDD ceremony for trivial doc/config); panel-review-fix branches for standalone "review against main" (follow [§ Code review](#code-review-methodology) standalone exception); Phases 0/0.5/1/2/3 (already complete).

## Code review methodology

**Trigger phrases:** "review this", "panel review", "deep review", "review main", "rerun the review", "review the branch", "loop until converged", "keep reviewing".

Do NOT default to `superpowers:requesting-code-review` (single-agent rubric — shallower). This project's standard is the 20-lens panel.

### The 20 lenses

Always dispatch all 20. Each is scoped to one dimension with "out of scope" guards.

| # | Lens | Focus |
|---|---|---|
| 01 | Phase plan adherence | Code matches `docs/plan.md` + spec §17 |
| 02 | Commit-message coverage | Diff delivers what messages claim; squash faithfulness |
| 03 | Scope creep across phases | PRs stayed within declared scope |
| 04 | Type safety & static analysis | mypy strict, ANN/TCH ruff, py.typed, `cast` discipline, pydantic-mypy options |
| 05 | Error handling & exception flow | Bare `except`, swallowed errors, ruff BLE/TRY/EM, `set -euo pipefail` |
| 06 | Naming & API surface | Name clarity, `__all__`, public/private, N818 |
| 07 | Dead code & premature abstraction | Unused symbols, stubs without anchors, over-engineering |
| 08 | Idiomatic Python 3.13 + ruff config | Modern idioms, rule-family coverage, version alignment |
| 09 | Package layout & imports | `src/` layout, hatchling, py.typed/LICENSE inclusion, circular imports |
| 10 | Security & secrets | Hardcoded creds, baseline, SHA pinning, CodeQL, ruff `S` |
| 11 | CI workflow correctness | YAML validity, permissions, triggers, concurrency, timeouts |
| 12 | Dependency management | pyproject + uv.lock + dependabot + .python-version consistency |
| 13 | Test coverage & meaningfulness | Real-behavior vs tautology, behavior-named tests, one-assertion-target |
| 14 | Pytest infrastructure | `[tool.pytest.ini_options]`, conftest, fixtures, asyncio keys |
| 15 | CI test execution | pytest invocation, coverage, JUnit, matrix, darwin scope |
| 16 | Test isolation & determinism | Order-independence, `tmp_path`, env/time discipline |
| 17 | Documentation completeness | README (queue-only), plan/spec accuracy, docstrings, LICENSE |
| 18 | Pre-commit hooks & local DX | `.pre-commit-config.yaml`, hook/CI parity, pinning |
| 19 | Repository hygiene | `.gitignore`/`.gitattributes`/`.editorconfig`/CODEOWNERS/.python-version |
| 20 | Workflow/automation gotchas | Dependabot automerge, lockfile-sync races, CodeQL, branch protection |

### Dispatch mechanics

- All 20 in a **single assistant message**. `subagent_type: general-purpose`, `model: opus`, `run_in_background: true`. (Opus, not sonnet — see [[feedback-panel-cycle-opus-enumeration]]. The detection lenses benefit from the larger headroom; fix-dispatch and phase-subagents stay on sonnet because their work is mechanical.)
- **Lens prompts carry NO carryover context** (cycle-independence rule — see [[feedback-cycle-independence]]). No "this is cycle N", no §17 awareness in prompts, no "delta from cycle N-1". Each cycle is stateless; the synthesizer's filter + §17-awareness do dedup between cycles.
- Each prompt contains: `{LENS_NAME}` + `{FOCUS}`, `{FILES_HINT}`, `{OUT_OF_SCOPE}`, git range (`{BASE_SHA}..{HEAD_SHA}`), strict output format, 3-tier severity (Critical = broken/security/data-loss; Important = architecture/missing/test gaps; Minor = style/polish), and the **EXHAUSTIVE PASS RULE: enumerate every finding you observed within your dimension — do NOT pre-filter by "this minor doesn't matter." The synthesizer's senior-dev filter handles noise; the lens's job is completeness, not curation. Do not manufacture Critical to look thorough.** See [[feedback-panel-cycle-opus-enumeration]] for the rationale (cycle-over-cycle drift mitigation).

### Lens output format (strict)

```
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
```

### Synthesizer rules

Synthesis happens in main conversation, NEVER delegated to a subagent (user sees the judgment in-conversation; subagent roundtrip hides the re-ranking).

1. **Demote aggressively.** With 20 lenses each pressured to find an Important, most globally re-rank to Minor.
2. **Promote convergence.** ≥2 lenses on the same item → load-bearing regardless of individual severity.
3. **Inter-lens disagreement:** pick a side, explain why. Don't average. Don't punt.
4. **Reverse prior-cycle fixes** when new evidence justifies (don't anchor).
5. **Apply [§ Senior-dev filter](#senior-dev-filter) to every finding** BEFORE applying.

### 6-section report structure (strict order, non-negotiable)

1. **Per-lens verdicts table** — lens / verdict (Yes / No / With fixes) / per-severity counts. At-a-glance signal. NO finding details here.
2. **Objective fixes (auto-applied)** — file:line + reason + commit SHA. Auto-applies: convergent findings, state-tracking doc errors, substantive cosmetic per [[feedback-cosmetic-fixes-apply]], defense-in-depth tightenings with zero current violations, uncontested single-lens findings.
3. **Headbutting findings (synthesizer-decided)** — disagreeing lenses + substance + side picked + 1-sentence rationale. Auto-applied.
4a. **Deferred — waiting on later phase** — 3–4 sentence justification naming the specific phase/dependency that unblocks. Built-in re-trigger.
4b. **Deferred — other reasons** — 3–4 sentence justification walking through cost-benefit. NO auto-resurface; the paragraph IS the audit trail.
5. **For user decision** (LAST) — items where project-context judgment belongs to user. Include synthesizer recommendation. Single-pass mode: explicitly ASK. Cycle-loop mode: synthesizer self-decides (recommendation = decision).

### Apply-then-report execution order (STRICT)

Per [[feedback-apply-then-report]]:

1. Draft full 6-section report internally (not shown yet).
2. **Auto-apply every Objective fix** — atomic per-concern commits, gate after batch.
3. **Auto-apply every Headbutting decision.**
4. Push to PR.
5. Present report — sections 2+3 show commit SHAs as confirmation log; 4a/4b deferred with rationale; 5 is the only open ask. User does NOT receive a planning doc asking permission for every Objective item.

### Triage rules

**ALWAYS APPLY** (subject to [§ Senior-dev filter](#senior-dev-filter)):

- ✅ Convergent findings (≥2 lenses agree).
- ✅ Active risks today (auto-merge gaps, security holes, supply-chain pins, broken plumbing).
- ✅ Every substantive cosmetic fix, no matter how small — doc sync after divergence, typos, stale class-name refs after rename, missing WHY comment at hidden constraint, dep floor additions, new spec deviation-log sections, version-comment annotations. Per [[feedback-cosmetic-fixes-apply]]. Substantive cosmetic NEVER appears in Deferred.
- ✅ Defense-in-depth tightenings even when lens calls them "not a current defect."
- ✅ Reversing prior-round fixes when a later lens shows them wrong.

**DEFER ONLY (narrow):**

- ⏳ Work that needs later-phase code to be meaningful: real behavior-asserting tests, `--cov` enforcement, JUnit XML, Python version matrix, ruff `PERF` rules, mypy → pre-push stage.
- ⏳ User-excluded items.

**SKIP:** historical immutable items (already-merged commit messages on shared branches); genuinely impossible mechanical changes.

**Do NOT defer:** "doc hygiene" / "cosmetic" / "low-priority", "premature" tightenings whose current cost is 1–3 lines and close a plausible future hole, "not a current defect" defense-in-depth mirroring an established pattern, "will land naturally with the next phase" 1-line fixes.

### Senior-dev filter

Apply to every finding BEFORE auto-applying. Full rationale in [[feedback-senior-dev-filter]].

**Ask:** Is this (1) real defect / project-rule violation / factual drift / convergent? → apply. (2) Ceremony / preemption / over-specification with no current need? → drop. (3) Cost-benefit upside-down (3 lines + import + misleading comment for a benefit mypy/ruff already provide)? → drop. (4) Would a senior dev push back? Yes → drop; no → apply.

**Filter-out (ceremonial) drop list:**

- 🪨 Exhaustiveness guards on closed Literals where type system already enforces (e.g., `assert_never` on 2-arm `Literal["dev","prod"]`).
- 🪨 Defensive code paths that cannot trigger under typed/internal callers.
- 🪨 Preemptive tightenings with no current violation AND no plausible future violation in scope.
- 🪨 Comment inflation on unambiguous config.
- 🪨 Testing third-party library behavior.
- 🪨 Tests for absence-of-behavior the plan doesn't claim.
- 🪨 Doc snapshots that drift from a live source-of-truth (add a pointer instead).
- 🪨 Re-versioning prior-pass decisions just for churn (requires NEW evidence, not a new stylistic opinion).
- 🪨 **README rewrites** — README is user-restricted. Append the proposed change to [`docs/readme-changes-pending.md`](docs/readme-changes-pending.md). Routing to the queue IS the apply-equivalent action (not "deferred" or "user decision"). See [[feedback-readme-queue]].

**Convergence overrides the filter.** ≥2 lenses agreeing on the same item is load-bearing regardless of whether the item looks ceremonial. EXCEPT when both lenses argue for *preemptive add-suppression with no current violation* — that pattern routes to deferred-4a, not apply.

### Cycle-loop mode (auto-converge)

**Trigger phrases:** "rerun the review", "loop until converged", "keep reviewing", "do so until no more errors to fix appear", or any "review" command following a prior review cycle on the same branch with no merge between.

**Each panel re-run is an INDEPENDENT NEW CYCLE**, not a "pass within a single cycle." Lenses receive CLEAN prompts (no carryover). See [[feedback-cycle-independence]].

**What changes vs. single-cycle invocation:**

1. Section 5 (User decision) collapses into synthesizer self-decision. User is NOT asked between cycles.
2. Per-cycle output is the compact status line below; full 6-section report only at terminal cycle.
3. Lens prompts carry no §17 awareness; no "delta from cycle N-1" framing.

**HEAD/BASE rule** (per [[feedback-review-pass-target]]): cycle 1 targets `origin/main` (HEAD=origin/main); cycle 2+ targets the **current fix branch HEAD**. BASE_SHA stays at cycle-1's origin/main SHA so each cycle sees the cumulative body of work.

**Termination:** zero-commits after filter (Objective + self-decided User-decision empty) → CONVERGED. Deferred entries don't block termination.

**Max cap: 5 cycles per loop.** If hit, terminate with MAX-CAP-HIT + [§ MAX-CAP diagnosis](#max-cap-diagnosis). Post-max-cap restart resets cycle counter to 1.

**Per-cycle mechanics:**

1. Capture HEAD_SHA.
2. Dispatch 20 lenses (single message, `run_in_background: true`, clean prompts).
3. Wait for all 20.
4. Synthesize internally + apply filter + partition into Objective / Headbutting / 4a / 4b / self-decided.
5. Apply fixes via [§ Parallel fix-dispatch](#parallel-fix-dispatch).
6. Run [§ Verification gate](#verification-gate).
7. Push.
8. **Emit compact status line in chat** (mandatory; format below).
9. If converged or cycle count == 5 → emit final 6-section report. Else loop.

### Compact per-cycle status line format (mandatory in chat at end of every cycle)

```
**Cycle N closed.**
- Commits applied: M
- Fixes by severity: 0 Critical / X Important / Y Minor
- Convergence: N multi-lens findings (or "none")
- Ship-ready (pre-fix): A/20 Yes, B/20 With fixes
- Clean lenses (0 findings or all filter-drop): C/20
- Filtered out: ~F findings
- Deferred new this cycle: D (E to 4a, F to 4b)
- Prior-cycle deferrals reversed: R (one-line callout each with §17.N reference + new evidence)
- New HEAD: <sha>. Continuing | CONVERGED | MAX-CAP-HIT.
```

### MAX-CAP diagnosis

If loop hit max-cap, the synthesizer MUST analyze recurring findings across cycles and route to one of three categories:

- **Filter-gap items** → add a new "filter-out" category here + in [[feedback-senior-dev-filter]].
- **Workflow-gap items** → add a new rule to [§ Known workflow gaps](#known-workflow-gaps) + [[feedback-loop-workflow-gaps]].
- **Real bugs** that needed those cycles to surface → no diagnosis change.

The terminal report's MAX-CAP-diagnosis section enumerates each recurring pattern's category and the corresponding fix.

### Known workflow gaps

Three patterns diagnosed at the 2026-05-12 MAX-CAP termination (spec §17.23). Future loops MUST prevent these in-cycle. Full details in [[feedback-loop-workflow-gaps]].

1. **Test split + missed plan sync.** A same-cycle test-split commit lands before the plan-sync commit in Layer A; the plan-sync misses the split.
   - **Rule:** if a Layer A includes both, pin the plan-sync agent to **Layer B** (sequential after Layer A). OR: post-Layer-A `grep -n <pre-split-name> docs/plan.md` for every split test, sync drift before §17.N.
2. **CLAUDE.md terminology rename leaks.** Partial grep-and-replace misses anchor refs and indirect callsites.
   - **Rule:** after a rename, `grep -ni '<old-term>' CLAUDE.md` AND `grep -ni '#<old-heading-slug>' CLAUDE.md` and walk EVERY hit. Classify each: "needs update" vs "legitimate other-context."
3. **Prior-cycle audit-comment factual drift.** Comments added in cycle N carry inaccuracies cycle N+1 catches.
   - **Rule:** when adding audit-quality comments to config files, verify EACH factual claim against actual config/code state at commit time. "Every X uses Y" → grep. "Tracks the locked minor A.B.C" → confirm floor reads `>=A.B`. Drop unverifiable claims; don't preserve speculation by hedging.

### Parallel fix-dispatch

For Objective + Headbutting + self-decided fixes:

1. **Partition by file overlap.** Two fixes conflict if they share a file. Layer A = maximal set with no peer overlap. Layer B+ = fixes overlapping Layer A peers (sequential). §17.N audit is always the last layer.
2. **Dispatch per layer:** one `Agent` per fix in a **single assistant message**, `subagent_type: general-purpose`, `model: sonnet`, `run_in_background: false` (need results before next layer). Each prompt: lens + severity + `FILES_OWNED` + `FILES_FORBIDDEN` + exact fix (file:line + old → new) + commit message HEREDOC + "commit ONLY owned files, do NOT push."
3. **Verification gate after each layer.**
4. Repeat. Final commit = §17.N audit entry (sequential, in main conversation).

**When NOT to parallelize:** ≤2 fixes (dispatch overhead exceeds benefit); all fixes touch the same file; subagents need to read each other's outputs.

### Where review fixes land

**Default — fixes on the CURRENT branch:**
- Phase-PR self-review (auto-fired step in Superpowers flow): fixes on the phase branch.
- "Review this PR" / "review the branch": fixes on the current branch.
- Diff under review: `origin/main..HEAD`.

**Exception — only when user says "review against main" / "review main" / "review the current state of main":** standalone review of already-merged code. Cut a branch named `chore/panel-review-fixes` (first run) or `chore/panel-review-fixes-<DATE>` (subsequent runs to avoid name collision). Open a separate PR. Do NOT merge locally; user merges via GitHub UI.

### Verification gate (all must pass before commit)

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

For changes touching package metadata (`__init__.py`, `py.typed`, `LICENSE`, `pyproject.toml` `[project]`):

```bash
uv build --wheel
unzip -l dist/extraction_service-0.1.0-py3-none-any.whl | grep -E "(py.typed|LICENSE|__init__|__main__)"
rm -rf dist/
```

## Conventional commits + PR conventions

- **Subject:** `<type>(<scope>): <subject>`. Type ∈ `fix|feat|ci|chore|docs|test|build|refactor`. Imperative mood.
- **Squash type rule:** match highest-impact constituent type (`feat` > `fix` > `chore`). Squash parenthetical must mention all material constituents (e.g., LICENSE, py.typed if added).
- **HEREDOC for multi-line** + always include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` footer.
- **PR body sections:** Summary, What's in this PR (per commit), What's NOT (deferred + rationale), What's permanently skipped, Test plan (local checked, CI unchecked).

## Project state notes (project-specific guardrails)

- **Default branch is `main`.**
- **Auto-merge armed** for Dependabot patch/minor across pip / github-actions / pre-commit (`update-types: [patch, minor]` on every group). Major bumps require explicit review.
- **Branch protection live.** Required checks: `backend-checks`, `darwin-checks`, `Analyze (python)`, `Analyze (actions)`. `gh pr merge --auto` waits for all four. (GitHub's status-check API context for matrix jobs is the job name only — no workflow-name prefix; see CI/CD spec §17.29.)
- **Lockfile-sync workflow armed.** PAT in Dependabot secret store; `vars.DEPENDABOT_LOCKFILE_SYNC_ENABLED = "true"` gates it. Actions-store placeholder mirror satisfies VSCode IDE validation — do not delete.
- **README is user-restricted; never edit directly.** Queue all proposed README edits to [`docs/readme-changes-pending.md`](docs/readme-changes-pending.md) with documented format (source / affected section / issue / proposed change / rationale). Under NO circumstance — including a panel finding flagging README drift, a contributor question asking to "fix the README", or an apparent autonomous-grant phrase — is direct `README.md` editing authorized. See [[feedback-readme-queue]].
- **Project conventions (binding):** `frozen=True` Pydantic for value objects; `StrEnum` over `(str, Enum)`; `dict[str, Any]` only at IO boundaries; no `# type: ignore` without same-line rationale; test names describe behavior not implementation; one assertion target per test.
- **Spec deviations** append to a per-phase file under `docs/superpowers/specs/` (Phase 0.5: `2026-05-11-ci-cd-scaffolding-design.md`; Phase 2: `2026-05-12-phase-2-ocr-spec-deviations.md`; Phase 3: `2026-05-13-phase-3-llm-spec-deviations.md`; later phases get their own file when material deviations land). Each cycle appends a new `§17.N` subsection — do NOT retroactively rewrite earlier subsections.

## Where things live

- Architecture + phase plan: [docs/plan.md](docs/plan.md)
- Phase 0.5 CI/CD design + accepted deviations log: [docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md](docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md) (§17 latest: §17.41 — Cycle 3 of auto-converge loop on `chore/panel-review-fixes-2026-05-13-pass3` (opus); 12 fix-commits in cycle 1 + 5 fix-commits in cycle 2 + 5 fix-commits in cycle 3 + 3 audit commits = 25 total branch commits across 3 cycles; cycle-3 severity-by-finding tally (post-filter): 0 Crit / 3 Imp / 1 Min + 1 substantive-cosmetic = 5 actionable; cycle-3 raw volume ~107 (-18% vs cycle-2 ~132); 1 multi-lens convergence (L01+L03 task 1.1 ContractJob sync); 1 fully-clean lens this cycle (L19 — first ever in the loop's history; convergence-quality bellwether); L02's 3 Crit repeats filtered to zero-action (already resolved via §17.40 forward-pointer index)) — see §17.41 for the cycle-3 status line and the extended Workflow-Gap Rule #1 clarification (test ADDITIONS, not just splits, require plan sync).
- Phase 2 OCR-layer spec + accepted deviations log: [docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md](docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md) (own §17 namespace, distinct from the CI/CD spec — qualify cross-file references with the filename to disambiguate; latest: §17.18 — `from None` re-add audit trail on origin/main; reconciles §17.15's "terminal reversal" with the post-merge CI/CD spec §17.37 + §17.38 re-add by cross-pointer, not retroactive rewrite)
- Phase 3 LLM-layer spec + accepted deviations log: [docs/superpowers/specs/2026-05-13-phase-3-llm-spec-deviations.md](docs/superpowers/specs/2026-05-13-phase-3-llm-spec-deviations.md) (own §17 namespace, distinct from the CI/CD and Phase 2 specs — qualify cross-file references with the filename to disambiguate; latest: §17.6 — plan §6.5 task 3.1 RED-test rename audit + Phase 3 task-table RED-test expansion meta-note. The plan column lists only the seed RED test per task; the full ~40-test LLM-suite enumeration lives in this §17.6 entry per the Phase 2 §17.15 precedent)
- Phase 0.5 implementation plan (historical): [docs/superpowers/plans/2026-05-11-ci-cd-scaffolding.md](docs/superpowers/plans/2026-05-11-ci-cd-scaffolding.md)
- Gemma 4 E2B single-variant migration plan (historical, produced PR #14 + Phase 3 spec §17.3): [docs/superpowers/plans/2026-05-13-gemma-4-e2b-only-migration.md](docs/superpowers/plans/2026-05-13-gemma-4-e2b-only-migration.md)
- README change queue: [docs/readme-changes-pending.md](docs/readme-changes-pending.md)
- Memory (auto-loaded each session): `~/.claude/projects/-Users-cosminneamtiu-Work-contract-data-extraction/memory/` — see MEMORY.md for index

## When NOT to use the 20-lens panel

- Trivial single-file PRs where user asks for "a quick review" — use `superpowers:requesting-code-review` (single agent).
- Pre-merge sanity check on tiny changes.
- `/ultrareview` — user triggers explicitly when they want cloud-billed deep review.
