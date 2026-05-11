# CLAUDE.md

Operating manual for Claude Code (and any compatible AI assistant) working on `contract-data-extraction`. Loads automatically at session start.

## Project context

Local single-process HTTP service that ingests scanned German legal contracts, OCRs all text (body, watermarks, logos, stamps), and uses Gemma 4 E2B via Ollama to extract structured JSON. Python 3.13, `uv`-managed, ruff + mypy strict, FastAPI + asyncio. Target hardware: Mac Mini M4, 16 GB.

Read [docs/plan.md](docs/plan.md) for the full architecture and phase-by-phase plan. Phase progress lives in commits and in [docs/superpowers/specs/](docs/superpowers/specs/).

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
5. **The unified report format:**
   - Strengths (cross-lens consensus, deduplicated)
   - Issues grouped by promoted severity (Critical / Important / Minor)
   - Per-lens summary table with verdicts (Yes / No / With fixes)
   - Recommendations + final assessment
6. **Skip the synthesized report if asked to go straight to triage.** When the user says "evaluate implementation relevance" or "what's worth fixing", jump straight to the triage matrix below.

### Triage rules — what gets fixed now

This is the **most opinionated** part of the methodology and where the prior single-agent default goes wrong. The default leans conservative ("defer to next phase"); this project's standard is the opposite.

**ALWAYS APPLY (fix-now bucket):**

- ✅ **Convergent findings** (≥2 lenses agree)
- ✅ **Active risks today** (auto-merge gaps, security holes, supply-chain pins, broken plumbing)
- ✅ **Cosmetic fixes** — doc sync, typos in spec/plan, sample/canonical-reference updates after live divergence, new spec deviation-log sections recording the current PR's items. **Per user feedback (see [memory/feedback_cosmetic_fixes_apply.md](../../.claude/projects/-Users-cosminneamtiu-Work-contract-data-extraction/memory/feedback_cosmetic_fixes_apply.md)): "cosmetic fixes always need to be applied."**
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
- **Lockfile sync workflow is configured** but currently disarmed pending PAT setup. Symbolic `vars.DEPENDABOT_LOCKFILE_SYNC_ENABLED` gates it.
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
