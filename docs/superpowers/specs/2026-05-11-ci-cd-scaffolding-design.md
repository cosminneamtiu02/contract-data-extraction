# CI/CD Scaffolding — Phase 0.5 Design

**Date:** 2026-05-11
**Branch:** `phase-0.5-ci-cd`
**Worktree:** `.worktrees/phase-0.5-ci-cd/`
**Predecessor:** `phase-0-scaffolding` (historical note: this design doc was written before Phase 0 merged. Phase 0 has since merged via PR #1; the rebase noted in §2 below was performed before PR #2 opened.)
**Scope:** Bring the GitHub-side gates online (CI, CodeQL, Dependabot auto-merge, Dependabot lockfile sync), add the supporting Dependabot config, CODEOWNERS, secret-scanning baseline, editor/git-attribute housekeeping, and expand `.gitignore` + `.pre-commit-config.yaml`. No application code changes. No CLAUDE.md.

## 1. Goal and non-goals

**Goal.** Move the project from "passes `uv run pytest && ruff && mypy` locally" to "every PR is gated by a uniform, parallel CI run; security scanning is on; dependency updates flow through automated lockfile sync and automerge; the production target OS (macOS arm64) has a smoke check; secrets and CVEs are surfaced loudly."

**Non-goals.**
- **No application code** (no `src/extraction_service` changes).
- **No coverage gate in CI** — `pyproject.toml` already pins `fail_under = 80` for local `pytest --cov`, but CI runs `pytest` without `--cov` since Phase 0 only has smoke tests. A later phase re-enables the flag once domain code exists.
- **No CLAUDE.md** — deferred at user's request.
- **No Taskfile** — workflows call `uv run …` directly; one less indirection.
- **No `import-linter`** — architecture enforcement deferred.
- **No `automerge.md` operational document** — rationale lives inline in workflow comments.
- **No paths-ignore on CodeQL** — analyzer scans everything; revisit only if noisy/slow.
- **No `continue-on-error` on pip-audit** — strict CVE gate from day one.

## 2. Branch strategy and worktree lifecycle

The project uses a one-phase-per-worktree convention (see `docs/plan.md` §6.1). This phase is numbered `0.5` because it slots between scaffolding (Phase 0) and domain types (Phase 1) — the locked plan does not enumerate CI as a phase, and adding it to Phase 0 retrospectively would muddy that branch's already-complete history.

Concrete steps already taken:
1. Worktree created via `git worktree add -b phase-0.5-ci-cd .worktrees/phase-0.5-ci-cd master`.
2. This design doc lives at `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md` on the new branch, committed before any implementation files.

**Ordering requirement (load-bearing).** `phase-0-scaffolding` MUST merge to `main` before `phase-0.5-ci-cd`'s PR opens. The CI workflow defined here calls `uv run ruff check src tests` and `uv run mypy src tests`; without Phase 0's `src/extraction_service` and `tests/` directories on `main`, CI fails on a fresh PR with "no such directory" before any real check runs. Phase 0's merge gives `main` the source tree; phase-0.5 then rebases on top.

Rebase coupling (known, accepted): when `phase-0-scaffolding` merges to main, `phase-0.5-ci-cd` will have a divergent base. The rebase before its own PR is a single `git rebase origin/main` from inside the worktree — no merge conflicts expected since Phase 0 touches `pyproject.toml` / `src/` / `tests/` / existing `.pre-commit-config.yaml` and this phase only adds `.github/` + new top-level dotfiles. The `.pre-commit-config.yaml` and `pyproject.toml` edits are additive (different sections) and unlikely to collide; if they do, resolution is mechanical.

PR opens against main only after the rebase. Per user's PR-based phase integration policy (memory entry `feedback_pr_workflow.md`), no local merge.

## 3. File inventory

```
.github/
  CODEOWNERS                                # 1 line: *  @cosminneamtiu02
  dependabot.yml                            # pip + github-actions + pre-commit ecosystems
  actions/
    read-python-version/action.yml          # composite — reads .python-version → $GITHUB_ENV
  workflows/
    ci.yml                                  # backend-checks (ubuntu-24.04) + darwin-checks (macos-15)
    codeql.yml                              # matrix: language ∈ {python, actions}
    dependabot-automerge.yml                # gh pr merge --auto --squash
    dependabot-lockfile-sync.yml            # uv lock → commit → force-with-lease push

.editorconfig                               # utf-8 / lf / indent rules
.gitattributes                              # text=auto eol=lf + binary types + uv.lock collapse
.secrets.baseline                           # bootstrap baseline (regenerated locally)

# modified
.gitignore                                  # expand from 19 lines → ~30 lines
.pre-commit-config.yaml                     # add detect-secrets + pre-commit-hooks suite
pyproject.toml                              # add pip-audit + detect-secrets to dev deps

# new design doc (this file)
docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md
```

## 4. Workflow specifications

### 4.1 `ci.yml` — primary verification gate

**Triggers.** `pull_request: [main]`, `push: [main]`, `workflow_dispatch`. The push-to-main trigger preserves a "main is always known-green" canary run after every squash-merge; concurrency keys the group by `github.ref` plus `github.sha` on pushes so back-to-back squash-merges (during a busy Dependabot day) never cancel each other's post-merge canaries.

**Concurrency.**
```yaml
group: ci-${{ github.ref }}-${{ github.event_name == 'push' && github.sha || 'pr' }}
cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

**Workflow-level permissions.** `contents: read` only. No write surface.

**Job `backend-checks` on `ubuntu-24.04` (timeout: 10 min).** Pin to the major rather than `ubuntu-latest` so GitHub's image rollouts can't silently shift the runner under us; Dependabot's `github-actions` ecosystem will surface the bump as a PR.

Steps, in order:
1. `actions/checkout@<sha>` with `persist-credentials: false` — CI only verifies, never pushes, so we strip the persisted token from `.git/config`.
2. `./.github/actions/read-python-version` — composite action with `id: pyver`; emits `python-version` as a **step output** (see §5 for the API contract; the implementation uses `$GITHUB_OUTPUT` instead of the originally-specified `$GITHUB_ENV` — accepted deviation, see §17.1).
3. `astral-sh/setup-uv@<sha>` with `enable-cache: true`, `cache-dependency-glob: uv.lock`, `github-token: ${{ secrets.GITHUB_TOKEN }}` (authenticated rate limit), `python-version: ${{ steps.pyver.outputs.python-version }}`.
4. `uv sync --frozen --dev` — installs everything pinned in `uv.lock` plus the `dev` dependency group.
5. **Lockfile freshness:** `uv lock --check` — fails if `pyproject.toml` drifted from `uv.lock`. Symmetric with the `dependabot-lockfile-sync` workflow's role.
6. **Lint:** `uv run ruff check src tests`.
7. **Format check:** `uv run ruff format --check src tests`.
8. **Type check:** `uv run mypy src tests` (strict mode pinned in `pyproject.toml`).
9. **Tests:** `uv run pytest -q`. **No `--cov` flag** — coverage gate deferred until later phases.
10. **CVE scan:** `uv run pip-audit --skip-editable`. Default pip-audit fails CI on any CVE. **Accepted deviation from the original plan's `--strict`** (see §17.2): `--strict` also fails on unauditable packages, which trips on the local editable `extraction-service` package even with `--skip-editable` in some pip-audit versions. The default behavior still surfaces all CVEs; only the unauditable-package edge case is relaxed.
11. **Secret scan:** run `detect-secrets-hook --baseline .secrets.baseline <files>` against `git ls-files` minus the baseline itself. Symmetric with the pre-commit hook so a Dependabot-bypass commit (e.g., the lockfile-sync workflow's automated push) can't sneak a leaked secret onto main. Exact bash form is an implementation detail — anchor regex for the baseline-exclusion is the only subtle part, and `grep -F` is the safe primitive.

**Job `darwin-checks` on `macos-15` (timeout: 10 min).** macOS arm64 is the production target (Mac Mini M4); this job verifies wheel resolution + import succeed there before merge. The example's example-folder darwin job validates a launchd plist via `plutil`; this project has no plist yet, so the smoke-install variant is the right shape.

Steps:
1. `actions/checkout@<sha>` with `persist-credentials: false`.
2. `./.github/actions/read-python-version` (same composite).
3. `astral-sh/setup-uv@<sha>` (same pattern).
4. `uv sync --frozen --dev`.
5. `uv run pytest -q tests/test_smoke.py` — smoke-only. Imports the package, calls the `__main__.main` reference. Catches arm64 wheel resolution failures for `docling`, `rapidocr-onnxruntime`, `modelscope`, and any future native-extension dep before it bites in production.

**Cost note.** macOS minutes are billed at 10× ubuntu. ~30 sec of actual test time per run; the cost driver is `uv sync` resolution (~1–2 min cold, ~20 sec warm via the action's cache). Across ~20 PRs/month this is bounded but real.

### 4.2 `codeql.yml` — static analysis

**Triggers.** `pull_request: [main]`, `push: [main]`, `schedule: [cron: '0 6 * * 1']` (weekly Monday 06:00 UTC).

**Permissions (job-level).**
```yaml
actions: read
contents: read
security-events: write  # SARIF upload
```

**Matrix job `analyze`.**
```yaml
strategy:
  fail-fast: false
  matrix:
    language: [python, actions]
```

The matrix produces two status checks named `CodeQL / Analyze (python)` and `CodeQL / Analyze (actions)` — exactly the names the user listed.

Steps:
1. `actions/checkout@<sha>` (default config; CodeQL needs full history? — actually `fetch-depth: 0` is required for analysis context; will pin explicitly).
2. `github/codeql-action/init@<sha>` with `languages: ${{ matrix.language }}`. No custom query packs for now; default suite suffices for a fresh codebase.
3. (Skip `autobuild` — neither language requires compile; python is interpreted, actions are YAML.)
4. `github/codeql-action/analyze@<sha>` with `category: "/language:${{ matrix.language }}"`.

**No `paths-ignore`.** Per the user's confirmation, day-one CodeQL scans everything. If signal-to-noise drops, revisit with a paths-ignore for `docs/**` and `tests/**`.

### 4.3 `dependabot-automerge.yml` — squash-merge passing Dependabot PRs

**Triggers.** `pull_request: [opened, synchronize, reopened]` against main. No `workflow_dispatch` — the `user.login` guard is empty on dispatch and the job would silently skip; documenting a dead affordance invites incident-time confusion.

**Concurrency.**
```yaml
group: dependabot-automerge-${{ github.event.pull_request.number }}
cancel-in-progress: true
```

**Workflow-level permissions.** `contents: read`. Privileged scopes minted only on the job when the guards pass.

**Job `automerge` on `ubuntu-24.04` (timeout: 5 min).**

```yaml
permissions:
  contents: write
  pull-requests: write
if: github.event.pull_request.user.login == 'dependabot[bot]'
    && github.event.pull_request.draft == false
    && vars.DEPENDABOT_AUTOMERGE_ENABLED == 'true'
```

Single step:
```yaml
- run: gh pr merge --auto --squash "$PR_URL"
  env:
    PR_URL: ${{ github.event.pull_request.html_url }}
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**Two guards in series:**
1. Author guard reads `pull_request.user.login` (not `github.actor`) — `user.login` stays `dependabot[bot]` for the PR's lifetime regardless of who triggers individual events. `github.actor` flips to a human if they click "Update branch" in the UI, which would otherwise cause a skip on every human-triggered sync.
2. Kill-switch `vars.DEPENDABOT_AUTOMERGE_ENABLED == 'true'` — flipping this to `"false"` immediately disarms the job (the `permissions:` block isn't even minted, since the `if:` evaluates false), and the job-level scopes vanish on the next event.

**Required setup post-merge.**
1. Branch ruleset on `main` with required status checks: `backend-checks`, `darwin-checks`, `CodeQL / Analyze (python)`, `CodeQL / Analyze (actions)`. Without required checks, `gh pr merge --auto` has nothing to wait for and merges immediately even on red CI — exactly the incident that motivated the example's auto-merge guards.
2. Repo setting: "Allow GitHub Actions to create and approve pull requests" → enabled.
3. Repo variable: `gh variable set DEPENDABOT_AUTOMERGE_ENABLED --body "true"`.
4. Until step 3, the workflow runs but skips on every PR. Safe default.

### 4.4 `dependabot-lockfile-sync.yml` — regenerate `uv.lock` on Dependabot PRs

**Why this exists.** Dependabot's `uv` support has a known parity bug with its pnpm equivalent: when it bumps `pyproject.toml`, it does not regenerate `uv.lock`. `uv sync --dev` papers over the gap at runtime but the committed lockfile drifts. CI's `uv lock --check` step (§4.1.5) would then fail every Dependabot PR. This workflow detects the drift, runs `uv lock`, and pushes the fix back to the PR branch.

**Triggers.** `pull_request: [opened, synchronize, reopened]` against main.

**Concurrency.**
```yaml
group: dependabot-lockfile-sync-${{ github.event.pull_request.number }}-${{ github.event.action }}
cancel-in-progress: true
```

The `action` suffix segregates `opened` events from `synchronize` events so an unrelated sync doesn't cancel the regenerator that fired on the initial open.

**Job `sync` on `ubuntu-24.04` (timeout: 10 min).**

Guards: same author + kill-switch shape as automerge, except the var is `DEPENDABOT_LOCKFILE_SYNC_ENABLED`.

Steps:
1. **Verify PAT.** Read `DEPENDABOT_LOCKFILE_SYNC_PAT` from env; if empty, emit `::error::` with remediation instructions and exit 1. Without this, a missing PAT silently degrades to "the workflow runs but never pushes."
2. **Checkout PR branch** with `ref: ${{ github.event.pull_request.head.ref }}`, `fetch-depth: 50` (enough for typical Dependabot rebase chains; fail-safe checks for missing BASE/HEAD SHAs further down), `token: ${{ secrets.DEPENDABOT_LOCKFILE_SYNC_PAT }}`.
3. **Composite read-python-version** (same as CI).
4. **Loop guard.** Inspect `git log -1 HEAD`. Skip the rest of the run if last commit author email matches `41898282+github-actions` OR last commit subject matches `chore(deps): regenerate lockfiles after dependabot bump`. Two independent guards: the user-id check is the fast path; the commit-subject check is the durable fallback. Either match short-circuits — prevents recursion when our own push fires the next `synchronize` event.
5. **Detect manifest change.** `git diff --name-only $BASE_SHA $HEAD_SHA` looking for `pyproject.toml`. Fail-safe: if either SHA is missing from history (fetch-depth too shallow on a long-history PR), emit `::error::` with a "bump fetch-depth" message rather than silently no-op'ing.
6. **Set up uv** (only if manifest changed; same setup-uv action + version pin as CI).
7. **Regenerate lockfile.** `uv lock` at repo root.
8. **Commit and push.** Stage `uv.lock` only; bail out cleanly if no diff. Otherwise commit with the canonical message (matches the loop-guard subject pattern), push with `--force-with-lease="$HEAD_REF:$HEAD_SHA"` — bounded to the exact head this run started from so a mid-flight `@dependabot rebase` rejects our stale push instead of clobbering the new manifest.
9. **Push-error discrimination.** Capture push stderr. If it matches `non-fast-forward|stale info`, treat as a benign concurrent-push collision (another sync run beat us; the PR head already has the correct lockfile) and exit 0. Any other failure (auth/scope/network) propagates as a real workflow error. Locale-pin via `LANG=C` `LC_ALL=C` so a future runner image with non-English defaults doesn't localize the error and silently break the discriminator.

**PAT setup (one-time, post-merge).** Fine-grained PAT scoped to this repo: `Contents: Read and write` + `Pull requests: Read and write`. Stored as a **Dependabot** secret (not Actions secret) named `DEPENDABOT_LOCKFILE_SYNC_PAT`:
```bash
gh secret set DEPENDABOT_LOCKFILE_SYNC_PAT --app dependabot --body "<PAT>"
gh variable set DEPENDABOT_LOCKFILE_SYNC_ENABLED --body "true"
```
The `--app dependabot` flag is what targets the Dependabot store; Dependabot-triggered workflows can only read secrets from there (2021 supply-chain mitigation).

**Why a PAT (not `GITHUB_TOKEN`).** Pushes authenticated by `GITHUB_TOKEN` deliberately do **not** trigger new workflow runs (anti-recursion protection). Without a PAT, our lockfile-fix push would advance the PR's head but no CI would fire — leaving required status checks attached to the old, broken commit. The ruleset then refuses to merge it. PATs look like normal users and re-trigger CI normally.

## 5. Composite action: `.github/actions/read-python-version/action.yml`

Reads `.python-version` (single-line `3.13`) at repo root and emits `python-version` as a **step output**. Callers give the step an `id` (e.g., `id: pyver`) and reference `${{ steps.pyver.outputs.python-version }}`. Composite-action wrapping keeps the read logic (with `set -euo pipefail` and an explicit empty-string check) in one place; the three callsites (`ci.yml::backend-checks`, `ci.yml::darwin-checks`, `dependabot-lockfile-sync.yml::sync`) each reduce to a single `uses:` line.

> **API change from original plan (§17.1):** the original spec specified `$GITHUB_ENV` (writing `PYTHON_VERSION` as an env var). The implementation uses `$GITHUB_OUTPUT` instead. Step outputs are scoped to the calling job and the step they came from, whereas env vars persist for every subsequent step and could shadow a pre-existing `PYTHON_VERSION`. Accepted as a strict improvement.

`working-directory: .` is required because a calling job may set a job-level `defaults.run.working-directory` to a subdirectory in the future; `.python-version` lives at repo root.

## 6. `.github/dependabot.yml` ecosystems and groups

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    target-branch: main
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
    rebase-strategy: auto
    commit-message: { prefix: "chore(deps)", include: scope }
    labels: [dependencies]
    groups:
      fastapi-stack: { patterns: ["fastapi", "starlette", "uvicorn*", "httptools", "uvloop", "watchfiles"] }
      pydantic:      { patterns: ["pydantic", "pydantic-settings"] }
      pytest:        { patterns: ["pytest", "pytest-*"] }
      dev-tools:     { patterns: ["ruff", "mypy", "pip-audit", "types-*", "hatchling", "pyyaml", "detect-secrets"] }
      runtime-singletons: { patterns: ["structlog", "httpx", "ollama", "jsonschema"] }
      ml-stack:      { patterns: ["docling", "rapidocr-onnxruntime", "modelscope"] }

  - package-ecosystem: github-actions
    directory: /
    target-branch: main
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
    rebase-strategy: auto
    commit-message: { prefix: "chore(deps)", include: scope }
    labels: [dependencies]
    groups:
      github-actions-stack: { patterns: ["actions/*", "astral-sh/*", "github/codeql-action/*"] }

  - package-ecosystem: pre-commit
    directory: /
    target-branch: main
    schedule: { interval: daily }
    open-pull-requests-limit: 1
    rebase-strategy: auto
    commit-message: { prefix: "chore(deps)", include: scope }
    labels: [dependencies]
    groups:
      pre-commit-tools: { patterns: ["*"] }
```

**Group rationale, abridged.**
- `fastapi-stack` — fastapi + starlette + uvicorn share ASGI contract versions; transitives (`httptools`, `uvloop`, `watchfiles`) ride along so a uvicorn bump and its companions land atomically.
- `pydantic` — pydantic + pydantic-settings release in lockstep.
- `pytest` — pytest + plugins ship aligned releases; a mismatched plugin after a pytest bump fails first-CI-run.
- `dev-tools` — ruff / mypy / pip-audit / detect-secrets / `types-*` / hatchling / pyyaml — high churn, cascade-conflict prone on adjacent `pyproject.toml` lines.
- `runtime-singletons` — single-publisher runtime deps with no peer lockstep; grouped to avoid saturating the 5-PR limit during a busy release week.
- `ml-stack` — docling / rapidocr-onnxruntime / modelscope. These have heavy transitive trees and tend to release together; grouping them prevents 3 simultaneous solo PRs each pulling in ~50 transitives.
- `github-actions-stack` — all our action publishers in one group so adjacent-line bumps in one workflow YAML don't cascade-conflict.
- `pre-commit-tools` — daily cadence + group=all + open-PR cap 1 prevents stale + new PRs from doubling up on weekly cadence.

`update-types` filters intentionally omitted from every group so MAJOR bumps stay grouped; a major in one ecosystem without its sibling minor in the same PR re-opens the cascade-conflict surface that grouping closes.

## 7. CODEOWNERS

Single line: `*  @cosminneamtiu02`. Documented as one-line insurance against a future `require_code_owner_review: true` ruleset toggle — without the file, every PR would land in "no required reviewer" limbo if the toggle ever flipped.

## 8. `.gitignore` expansion

Current 19-line file gets these additions:

```gitignore
# Local environment
.env.*
!.env.example

# Tooling caches (additions to existing)
.import_linter_cache/

# OS (additions)
Thumbs.db

# Logs
*.log

# Claude Code per-machine state (transcripts, worktrees, etc.)
.claude/

# IDE — keep current ignore but allow checked-in shared editor settings
.vscode/*
!.vscode/extensions.json
!.vscode/settings.json
```

`.claude/` is added explicitly. `.idea/`, `.venv/`, `__pycache__/`, etc. stay from the existing file.

## 9. `.pre-commit-config.yaml` additions

> **Phase boundary note (§17.3):** the canonical owner of `.pre-commit-config.yaml` is Phase 0.6 (per `docs/plan.md §6.2 task 0.6`). Phase 0.5 deliberately extends that file with the `detect-secrets` and `pre-commit-hooks` blocks below because the symmetric secret-scan gate (local + CI) is part of Phase 0.5's CI/CD scope, not Phase 0.6's local DX scope. The file's full shape after Phase 0.5 is the union of Phase 0.6's initial three local hooks and Phase 0.5's two remote-repo blocks. This is a deliberate, acknowledged overlap, not scope creep.

Existing hooks (local `ruff check` / `ruff format --check` / `mypy`) stay as-is. Append two remote-repo blocks:

```yaml
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
      - id: check-added-large-files
        args: ["--maxkb=500"]
      - id: detect-private-key
```

`detect-private-key` is a filename+content match, complementary to `detect-secrets` (entropy/regex). Catches an empty `id_rsa` or a partial-paste `.pem` that lacks the standard BEGIN header — exactly the case the entropy scanner misses.

## 10. `pyproject.toml` dev-dependency additions

Append to `[dependency-groups].dev`:
```
"pip-audit>=2.7",
"detect-secrets>=1.5",
```

After the change, `uv lock` regenerates `uv.lock`, and that regenerated file is part of the same commit. CI's lockfile-freshness step then passes.

## 11. `.secrets.baseline` generation

```bash
uv run detect-secrets scan > .secrets.baseline
```
Run once locally after the dev deps are installed. Output is committed. The file is effectively empty for a fresh repo (just plugin metadata); future false positives are silenced via `uv run detect-secrets audit .secrets.baseline`.

## 12. `.editorconfig` and `.gitattributes`

Both ported verbatim from the example with the monorepo-specific paths removed:

`.editorconfig`:
```ini
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 4
insert_final_newline = true
trim_trailing_whitespace = true

[*.{yml,yaml,json}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false
```

`.gitattributes`:
```gitattributes
* text=auto eol=lf

*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.pdf binary
*.onnx binary

uv.lock linguist-generated=true -diff
```

`*.onnx` added because Phase 2 will commit sample model artifacts (per `docs/plan.md` §2.5). The collapse-on-diff for `uv.lock` keeps PR review lightweight.

## 13. Known risks and trade-offs

1. **First CI run may fail on a pinned-dep CVE.** Strict mode is intentional; expect a small bump-up cost on first PR. Two escape hatches if the failing dep can't be bumped immediately: (a) `pip-audit --ignore-vuln <GHSA-id>` in the CI step with a comment explaining the rationale and an expiry-date check, or (b) bump the dep's minimum in `pyproject.toml` to the fixed release. Prefer (b) when feasible; (a) is the bounded-time bridge.

2. **ML wheel resolution on `ubuntu-24.04`.** `modelscope`, `rapidocr-onnxruntime`, and `docling` ship linux-x86_64 wheels but their transitives (e.g., `onnxruntime`) sometimes lag a Python release. `uv.lock` should pin a resolvable set, and if not, that's a real signal — surface it pre-merge.

3. **Coverage gate deferred.** `pyproject.toml` keeps `fail_under = 80`; CI omits `--cov`. A `TODO` should land in a later phase to flip CI's pytest invocation to `pytest --cov`.

4. **Darwin runner cost.** macOS minutes are 10× ubuntu. Smoke test takes ~30 sec; `uv sync` cold ~1–2 min, warm ~20 sec. Budget impact bounded by setup-uv cache hit rate. Acceptable for the production-target-OS confidence.

5. **CodeQL latency.** First analyze on python ~5–10 min cold, ~2–5 min warm. Runs on every PR. Day-one no `paths-ignore` (per user). Revisit if it becomes the long-pole.

6. **Post-merge manual setup required.**
   - Branch ruleset on `main`: require `backend-checks`, `darwin-checks`, `CodeQL / Analyze (python)`, `CodeQL / Analyze (actions)`.
   - Repo setting: "Allow GitHub Actions to create and approve pull requests" → on.
   - `gh variable set DEPENDABOT_AUTOMERGE_ENABLED --body "true"`.
   - Create fine-grained PAT (Contents:RW, Pull requests:RW), then `gh secret set DEPENDABOT_LOCKFILE_SYNC_PAT --app dependabot --body "<PAT>"` and `gh variable set DEPENDABOT_LOCKFILE_SYNC_ENABLED --body "true"`.
   - Run `uv run detect-secrets scan > .secrets.baseline` locally once after dev-deps install; commit the baseline.

7. **Phase-0 rebase coupling.** Acknowledged in §2. Touched files don't overlap; rebase should be trivial.

8. **No `automerge.md` operational doc.** Rationale lives inline in the workflow YAML comments. If the workflow set grows enough that the inline rationale becomes unwieldy, a follow-up phase extracts it to `docs/automerge.md`.

## 14. Operator runbook (post-merge)

After phase-0.5 merges to main, run these once:

```bash
# 1. Configure branch protection (assumes ruleset name "main-protection")
gh api -X POST repos/:owner/:repo/rulesets -F name=main-protection -f target=branch \
    --raw-field "conditions[ref_name][include][]=refs/heads/main" \
    -f "rules[][type]=required_status_checks" \
    --raw-field "rules[0][parameters][required_status_checks][][context]=backend-checks" \
    --raw-field "rules[0][parameters][required_status_checks][][context]=darwin-checks" \
    --raw-field "rules[0][parameters][required_status_checks][][context]=CodeQL / Analyze (python)" \
    --raw-field "rules[0][parameters][required_status_checks][][context]=CodeQL / Analyze (actions)" \
    -F "rules[0][parameters][strict_required_status_checks_policy]=true"

# 2. Allow Actions to create/approve PRs
gh api -X PUT repos/:owner/:repo/actions/permissions/workflow -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true

# 3. Arm auto-merge
gh variable set DEPENDABOT_AUTOMERGE_ENABLED --body "true"

# 4. Set up lockfile sync (create PAT in GitHub UI first)
gh secret set DEPENDABOT_LOCKFILE_SYNC_PAT --app dependabot --body "<paste PAT>"
gh variable set DEPENDABOT_LOCKFILE_SYNC_ENABLED --body "true"
```

The exact ruleset-creation command may need tweaking after testing; the above is the shape, not gospel. Phase-0.5's exit criteria don't include "ruleset confirmed working" — that's an operator follow-up on main.

## 15. Test plan

Phase 0.5 is config-only — no application code to unit-test. Verification is operational:

1. **Local pre-commit dry run.** `uv run pre-commit run --all-files` — must pass after `.secrets.baseline` is generated.
2. **CI first-run on PR.** Push the branch, open PR against main. All five required checks (`backend-checks`, `darwin-checks`, `CodeQL / Analyze (python)`, `CodeQL / Analyze (actions)`) must run and report — the only acceptable failure mode is a real CVE flag (§13.1) or a real CodeQL finding, which would then be a Phase-0.5.1 follow-up.
3. **Auto-merge dry-run with a dummy PR.** After merge + post-merge setup (§14), wait for the first Dependabot PR and verify the auto-merge fires once all required checks go green. Until then, the workflows no-op.
4. **Lockfile sync dry-run.** Manually edit a dep in `pyproject.toml` on a branch, open PR, push, observe the regenerator commit landing on the branch.

## 16. Out of scope (explicit deferrals to future phases)

- Coverage gate in CI (re-enable `--cov` once domain code lands).
- `import-linter` architecture contracts (depends on domain layout, lands with Phase 1 or Phase 2).
- `automerge.md` operational doc (only if inline rationale becomes unwieldy).
- `CLAUDE.md` (user-deferred; revisit when collaboration patterns crystallize).
- E2E test job in CI (the locked plan §6.8 marks E2E as manual-only; honor that).
- `TEMPLATE_FRICTION.md`-style upstream-bug tracker (no template forks here).

## 17. Accepted deviations recorded post-implementation

These were identified by a 20-agent panel code review after Phase 0.5 merged. They are deliberate departures from this spec, accepted rather than reverted.

### 17.1. Composite action API: `$GITHUB_OUTPUT` instead of `$GITHUB_ENV`

The spec (§5) specified writing `PYTHON_VERSION` to `$GITHUB_ENV`. The implementation emits a step output `python-version` via `$GITHUB_OUTPUT`. Step outputs are scoped to the emitting step and the job that consumes them; env vars persist for every subsequent step and could shadow a pre-existing `PYTHON_VERSION`. The implementation is a strict improvement; the spec text in §4.1 and §5 has been updated to match.

### 17.2. CI pip-audit: `--skip-editable` instead of `--strict`

The spec (§4.1 step 10) specified `--strict`. The implementation uses `--skip-editable` without `--strict`. `--strict` also fails on unauditable packages; the local editable `extraction-service` package is unauditable by definition. Testing confirms `--strict --skip-editable` still fails on the editable package in current pip-audit versions. The default pip-audit behavior still surfaces all CVEs against pinned deps — only the unauditable-package edge case is relaxed. The strict CVE gate the spec required is preserved in substance.

### 17.3. Phase 0.5 extending Phase 0.6's `.pre-commit-config.yaml`

The locked plan (`docs/plan.md §6.2 task 0.6`) designates `.pre-commit-config.yaml` as Phase 0.6's artifact. Phase 0.5 additionally added the `detect-secrets` and `pre-commit-hooks` blocks (see §9) to provide symmetric local-and-CI secret-scan coverage. The overlap is deliberate: secret-scan tooling spans both phases' scopes (local DX + CI gates). Future readers tracing the file's history will see contributions from both phases — this note makes the boundary explicit.

### 17.4. Post-review hardening (separate branch)

The same panel review surfaced several additional issues that landed on the `chore/panel-review-fixes` branch as a follow-up:

- CodeQL action pinned to commit SHA (was mutable `@v4` tag)
- CodeQL `concurrency:` group disambiguated for `schedule` events
- Dependabot pip groups gated with `update-types: [patch, minor]` so major bumps require explicit human review (auto-merge guard)
- `dependabot-lockfile-sync.yml` commit step `if:` tightened to require `needs_uv == 'true'`
- `[tool.uv] dev-dependencies = []` removed (deprecated, produced warnings on every `uv` invocation)
- `ruff>=0.9` (was `>=0.7`; 0.9+ has complete Python 3.13 grammar coverage)
- ruff `C4` + `FURB` rule families added
- mypy `warn_unreachable = true` added
- `pyyaml` reclassified from `dev-tools` to `runtime-singletons` Dependabot group (it is a runtime dep)
- `__all__` declared in `src/extraction_service/__init__.py`; package docstring added
- `src/extraction_service/py.typed` marker added (PEP 561)
- `__main__.py` carries an anchor TODO referencing Phase 5 wiring
- `.gitattributes` `uv.lock merge=union` reduces lockfile conflict noise
- `check-toml` pre-commit hook added
- MIT `LICENSE` added; declared in pyproject `license` + `license-files`
