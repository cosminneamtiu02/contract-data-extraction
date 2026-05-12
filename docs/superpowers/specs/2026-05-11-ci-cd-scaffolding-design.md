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
    read-python-version/action.yml          # composite — reads .python-version → step output (python-version)
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
4. **Loop guard.** Inspect `git log -1 HEAD`. Skip the rest of the run if last commit author email matches `41898282+github-actions` OR last commit subject matches `chore(deps): regenerate lockfile after dependabot bump`. Two independent guards: the user-id check is the fast path; the commit-subject check is the durable fallback. Either match short-circuits — prevents recursion when our own push fires the next `synchronize` event.
5. **Detect manifest change.** `git diff --name-only $BASE_SHA $HEAD_SHA` looking for `pyproject.toml`. Fail-safe: if either SHA is missing from history (fetch-depth too shallow on a long-history PR), emit `::error::` with a "bump fetch-depth" message rather than silently no-op'ing.
6. **Set up uv** (only if manifest changed; same setup-uv action + version pin as CI).
7. **Regenerate lockfile.** `uv lock` at repo root.
8. **Commit and push.** Stage `uv.lock` only; bail out cleanly if no diff. Otherwise commit with the canonical message (matches the loop-guard subject pattern), push with `--force-with-lease="$HEAD_REF:$HEAD_SHA"` — bounded to the exact head this run started from so a mid-flight `@dependabot rebase` rejects our stale push instead of clobbering the new manifest.
9. **Push-error discrimination.** Capture push stderr. If it matches `non-fast-forward|stale info`, treat as a benign concurrent-push collision (another sync run beat us; the PR head already has the correct lockfile) and exit 0. Any other failure (auth/scope/network) propagates as a real workflow error. Locale-pin via `LANG=C` `LC_ALL=C` so a future runner image with non-English defaults doesn't localize the error and silently break the discriminator.

**PAT setup (one-time, post-merge).** Fine-grained PAT scoped to this repo: `Contents: Read and write` only. (No `Pull requests` scope — the workflow performs `actions/checkout` + `git push` and never calls the GitHub PRs API; see §17.10 for the post-implementation correction.) Stored as a **Dependabot** secret (not Actions secret) named `DEPENDABOT_LOCKFILE_SYNC_PAT`:
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
   - Create fine-grained PAT (`Contents: Read and write` only — no `Pull requests` scope; see §4.4 / §17.10), then `gh secret set DEPENDABOT_LOCKFILE_SYNC_PAT --app dependabot --body "<PAT>"` and `gh variable set DEPENDABOT_LOCKFILE_SYNC_ENABLED --body "true"`.
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
- ~~`CLAUDE.md` (user-deferred; revisit when collaboration patterns crystallize).~~ **Resolved** in §17.6.
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

### 17.5. Pass-2 panel re-run on post-#3 main (`chore/panel-review-fixes-pass-2`)

A second pass of the 20-agent panel against `main` after PR #3 merged surfaced one substantive convergent finding and several doc/code cleanups. Items landed on the `chore/panel-review-fixes-pass-2` branch:

- **Dependabot `update-types` consistency.** PR #3 applied `update-types: [patch, minor]` only to pip groups. Pass-2 lenses 01, 10, 12, 20 independently flagged that `github-actions-stack` and `pre-commit-tools` groups were left exposed to the same major-bump auto-merge gap. Filter now applied to all three ecosystems.
- **`hypothesis` Dependabot grouping.** Was ungrouped (no `update-types` guard at all); now in the `pytest` group.
- **Spec/plan doc accuracy.** Stale `$GITHUB_ENV` references in spec §3 inventory comment, plan Task 6.2 code block, plan Task 8.1/8.2/11.1 call-sites, and the plan file-structure header — all updated to match the actual `$GITHUB_OUTPUT` implementation. `docs/plan.md §5.1` pyproject sample updated to include `license` / `license-files`, `warn_unreachable`, `pip-audit`, `detect-secrets`, and the `PT` ruff family.
- **§4.4 typo.** Loop-guard description said `"chore(deps): regenerate lockfiles after dependabot bump"` (plural); implementation uses singular `lockfile`. Spec aligned to singular.
- **`__all__: list[str] = []` removed from `__init__.py`.** PR #3 added it on Pass-1 Lens 06's recommendation; Pass-2 Lens 07 flagged it as premature — an empty `__all__` silently masks symbols added later unless someone updates the list. Docstring now documents the deliberate omission until real public exports exist.
- **`PT` (flake8-pytest-style) ruff rule family added.** Cheap to add against the current 2-test suite; would have produced a noisy retroactive diff once tests grow.
- **`test_smoke.py` tautology comments.** Module docstring now records that the assertions are intentionally tautological at this phase, preventing re-litigation on future review cycles.
- **`permissions: {}` on `dependabot-lockfile-sync.yml` sync job.** Defense-in-depth: this job authenticates pushes via the PAT, not GITHUB_TOKEN; the explicit empty block makes that intent explicit and prevents inheritance by future steps.

### 17.6. `CLAUDE.md` — operating manual for Claude Code

The original `§16` deferral ("CLAUDE.md — user-deferred; revisit when collaboration patterns crystallize") is now resolved. After two panel-review rounds (PRs #3 and #4), the project has a stable, opinionated code-review methodology — the 20-lens parallel panel — plus a set of triage rules and verification conventions that future sessions (and future contributors) should not have to re-derive. [`CLAUDE.md`](../../../CLAUDE.md) at repo root codifies:

- Project context (one paragraph, pointers to deeper docs)
- The 20-lens panel: roster, dispatch mechanics, per-lens prompt template, multi-pass review framing
- Synthesizer rules: demote-aggressively, promote-convergence, inter-lens-disagreement-resolution, reverse-prior-fixes-when-justified
- Triage rules: **cosmetic-always-applies**, narrow defer bucket (only "needs later-phase code to exist" qualifies), explicit skip cases
- Implementation flow: branch-from-main → fix → verify → conventional-commit groups → PR → no local merge
- Verification gate: exact local commands that must pass before commit, including wheel-build inspection when package metadata changes
- Project-state guardrails: README is user-restricted, deviation log goes in spec §17, default branch is `main`
- When NOT to use the panel (trivial PRs → single-agent review; cloud-billed deep reviews → `/ultrareview`)

`CLAUDE.md` is loaded automatically by Claude Code at session start. Other AI assistants with similar conventions (`AGENTS.md`, `GEMINI.md`) can read the same file; this project does not maintain separate copies.

### 17.7. IDE warning silenced via placeholder Actions-store secret

The VSCode GitHub Actions extension (`github.vscode-github-actions`) raises a permanent "Context access might be invalid: DEPENDABOT_LOCKFILE_SYNC_PAT" diagnostic on both references in [`.github/workflows/dependabot-lockfile-sync.yml`](../../../.github/workflows/dependabot-lockfile-sync.yml) (lines 60, 76). The diagnostic is correct in the narrow sense that the secret is not in the **Actions** secret store — it lives in the **Dependabot** secret store, which is the only store visible to `pull_request` workflows triggered by `dependabot[bot]`. The extension does not query the Dependabot store and offers no inline-suppression mechanism (upstream: [github/vscode-github-actions#108](https://github.com/github/vscode-github-actions/issues/108) and duplicates).

Accepted workaround: seed a same-named placeholder secret in the Actions store. The placeholder value is non-functional (any push attempting to use it would fail authentication loudly — an intentional failure mode that would surface store-routing bugs immediately rather than masking them). At runtime the workflow continues to read the real PAT from the Dependabot store; the Actions-store value is never read.

- Operational step (one-time): `gh secret set DEPENDABOT_LOCKFILE_SYNC_PAT --body "<placeholder>"` (Actions store, no `--app dependabot` flag).
- Workflow header documents the duplication so a future maintainer doesn't mistake the Actions-store entry for a live secret or remove it as redundant.
- Rotation discipline: when the real Dependabot-store PAT is rotated, the Actions-store placeholder does NOT need rotation — it carries no live credential value.

### 17.8. Phase 1 panel re-run (post-PR-#8-merge into `phase-1-domain`)

Recorded after the 20-lens panel was re-run against `phase-1-domain` at the post-#8-merge state (range `0bed324..70527da`) on 2026-05-12. This pass produced the following changes against `phase-1-domain` itself (not a separate `chore/panel-review-fixes-*` branch — per the strengthened cosmetic-always rule, all in-scope fixes land on the active phase branch when the panel is run as a phase-PR self-review).

**Plan / spec deviations introduced or acknowledged in this pass:**

- **Exception class names gain the `Error` suffix.** Plan §4.13's original class names — `OcrEmptyOutput`, `ContextOverflow`, `SchemaInvalid` — drop the `Error` suffix. The Phase 1 re-run's Lens 08 (Idiomatic Python + ruff `N`) flagged this as a PEP 8 / N818 violation. User decision: rename to `OcrEmptyOutputError`, `ContextOverflowError`, `SchemaInvalidError` rather than `extend-ignore = ["N818"]`. The plan text in §4.13 has been updated in-place to match the renamed classes; the §6.5 / §6.6 task-table prose references the new names too. This is a *retroactive plan-doc update*, not a deviation log of code-vs-plan drift.

- **`StageRecord.extracted: dict[str, Any] | None` field added in Phase 1.** Plan §6.3 task 1.3's spec for `StageRecord` enumerates `state, started_at, completed_at, duration_ms, error` — no `extracted`. Lens 01 (plan adherence) flagged that the field belongs to Phase 4 task 4.5's worker output and was added early. Rationale for landing it in Phase 1: plan §3.2 explicitly says "Orchestrator reads `data_parsing.extracted` when `overall_status == 'done'`" — the slot is a plan-architecture commitment regardless of which phase populates it. Adding the field as `dict[str, Any] | None = None` costs nothing today and avoids a breaking schema change when Phase 4 worker code lands. Field is typed at the IO boundary per CLAUDE.md project-wide best practice.

- **`RetryOnCode` Literal duplicates `ExtractionError.code` values intentionally.** `extraction_service.config.run_config.py` declares a `Literal["ocr_engine_failed", "ocr_empty_output", "llm_failed", "context_overflow", "schema_invalid"]` mirroring the concrete `ExtractionError.code` class attributes. Two design intents: (a) avoid a `config → domain` import dependency that would couple business config to domain code; (b) surface YAML-side typos at boot via Pydantic. A consistency test (`test_retry_on_code_literal_mirrors_concrete_extraction_error_codes`) walks `ExtractionError.__subclasses__()` and asserts no drift. The base-class sentinel `"extraction_error"` is intentionally excluded from the Literal — it is never a concrete retry trigger.

- **`RetryConfig.retry_on` rejects OCR codes via `@field_validator`.** Per plan §3.3 OCR errors are deterministic on the input and never retried. The Literal *includes* the two OCR codes for type-completeness (a consumer might want to log them); the validator is the semantic guard ensuring `retry_on: [ocr_engine_failed]` raises `ValidationError` at boot.

- **`StageRecord.fail(error, now=None)` → `fail(now=None, *, error)` for signature symmetry with `complete()`.** Lens 06 (Naming & API surface) flagged that `fail()`'s positional-`error`-first signature differed from `complete(now=None, *, extracted=None)`. The new symmetric signature prevents Phase 4 worker call sites from accidentally transposing `now` and `error` when the three transition methods appear close together.

- **`tests/fakes/` and `config/` example directories absent.** Plan §5's project-layout diagram lists `tests/fakes/{fake_ocr.py, fake_ollama.py}` and `config/{run_config.example.yaml, domain_model.example.json, extraction_prompt.example.txt}`. Both are assigned to later phases (fakes to Phase 2.2 + Phase 3.x; example configs to Phase 6.6). Phase 1 ships without scaffolding placeholders — the "no premature abstraction" rule outweighs filetree-diagram precision.

**Methodology / `CLAUDE.md` additions in this pass:**

- "Phase development methodology — go-to strategy (Superpowers flow)" section added (worktree + parallel subagent dispatch + automatic 20-lens self-review + PR-as-handoff).
- "Apply-first-then-report execution order" subsection added to the synthesizer rules: section 2 (Objective) and section 3 (Headbutting) auto-apply *before* the report is shown to the user, so the report is a confirmation log with commit SHAs rather than a planning document asking permission.
- Synthesis report restructured into 6 strict-order sections (Verdicts → Objective → Headbutting → 4a Deferred-later-phase → 4b Deferred-other → User decision).
- Cosmetic-fixes-always-apply rule strengthened: explicitly enumerates the kinds of items that count and adds "cosmetic items NEVER appear in Deferred" as a hard rule.
- Ruff `select` extended with `EM`, `TRY`, `TCH`, `N`, `S` rule families. Test per-file-ignores: `ARG`, `EM101`, `TRY003`, `S101`, `S108`.
- `[tool.pytest.ini_options]` gains `markers = []` (pre-empt `--strict-markers` footgun) and `filterwarnings = ["error::DeprecationWarning"]` (forward-looking DeprecationWarning gate).
- `[tool.hatch.build.targets.wheel]` gains `exclude = ["**/__pycache__"]`.
- `tests/conftest.py` added (autouse `_reset_structlog_state` fixture, promoted `isolated_env` from test_settings.py).

**State changes captured here for memory parity:**

- Lockfile-sync workflow state was previously described as "configured but currently disarmed pending PAT setup" in CLAUDE.md. As of 2026-05-12 it is live and armed (PAT set in Dependabot store; `vars.DEPENDABOT_LOCKFILE_SYNC_ENABLED = "true"`).

### 17.9. Phase 1 panel third pass (fresh review, treat-prior-rounds-as-nonexistent)

Recorded after a third 20-lens panel against `phase-1-domain` at the post-`10a91dc`-commit state on 2026-05-12, run with each lens instructed to treat prior reviews as nonexistent. Synthesizer applied a senior-developer judgment filter on top of the cosmetic-always-apply rule (per user direction: "what seems as a forced or unnecessary finding isn't implemented"), demoting items where the cost-benefit was upside-down. Diff range under review: `0bed324..10a91dc` (33 files, 2006 insertions); the third-pass fixes themselves land in commits `6b07e68..` on the same branch.

**Plan / spec deviations introduced or acknowledged in this pass:**

- **`# type: ignore` rationale comments retrofitted across eight sites.** Project rule in CLAUDE.md requires every ignore to carry a one-line same-line rationale. Lens 04 (Type safety) + Lens 08 (Idiomatic Python + ruff) convergently flagged that 3 prop-decorator ignores in `domain/record.py` + `domain/stage.py` and 5 misc/call-arg ignores in `test_domain_job.py` + `test_domain_stage.py` were lacking the rationale comment. All eight retrofitted with cause-specific reasoning (Pydantic @computed_field/@property stacking, intentional frozen-model mutation tests, intentional required-field-omission tests). No behavior change.

- **`assert_never` exhaustiveness guard removed from `configure_logging`.** A `case _ as unreachable: assert_never(unreachable)` arm guarded a 2-arm `Literal["development", "production"]` `match`. Two reviewers disagreed (Lens 04 endorsed it as "correct and tight"; Lens 07 called it ceremony with no payoff). Synthesizer ruled for Lens 07: mypy enforces match exhaustiveness on a closed 2-arm Literal without `assert_never`, and the `case _` arm cannot execute for any type-checked caller. The `from typing import assert_never` import was also dropped. The guard remains the right move on large/growing Literals; a 2-value mode toggle never grows past "we already test both cases".

- **`src/extraction_service/config/domain_model.py:5` stale class name.** Module docstring referenced `SchemaInvalid` (the pre-rename name); the class was renamed to `SchemaInvalidError` in commit `387cc84` per §17.8. Convergent finding from Lens 06 + Lens 17. Docstring updated to match the live class.

- **`docs/plan.md §6.3` goal sentence corrected.** Original wording: "All immutable types (`ContractJob`, `ContractRecord`, stage state machine)". §3.5 requires `ContractRecord` to be mutable so workers can reassign stage fields under the lock — the plan was internally contradictory. The goal sentence now matches §3.5's architectural commitment.

- **`docs/plan.md §6.3 Task 1.2 GREEN cell` updated to `StrEnum`.** Original cell said `class StageState(str, Enum)`; CLAUDE.md treats the older form as global shorthand, but a phase-implementor subagent reads the task-table cell literally. Cell updated to match the live `StrEnum` implementation with a one-line rationale embedded.

- **`docs/plan.md §5` tests/unit filetree updated.** Replaced the non-existent `test_stage_record.py` with the real Phase 1 test files (`test_domain_errors`, `test_domain_job`, `test_domain_model`, `test_domain_record`, `test_domain_stage`, `test_logging`). Kept the Phase 3+ prospective entries for the §5 forward-view purpose.

- **`docs/plan.md §5.1` pyproject.toml snapshot annotated.** Rather than copy-paste the live `pyproject.toml` into the plan (which would then re-drift on the next ruff/pytest tightening), prepended a header note pointing readers to the live file and to §17.8 for the formal deviation list.

- **Two test invariants tightened.** `test_stage_record_complete_sets_completed_at_and_computes_duration_ms` and `test_stage_record_fail_sets_state_completed_at_and_error` previously asserted `duration_ms == N` but only implicitly tested `started_at` preservation through `complete()` / `fail()`. Added explicit `assert finished.started_at == T0` (and `failed.started_at == T0`) so a future refactor that resets `started_at` on transition would fail loudly instead of transitively. Lens 13 Important.

- **New test: `test_stage_field_inside_contract_record_remains_frozen`.** §3.5's worker contract requires `record.ocr = record.ocr.start(...)` as the only legal mutation path. A worker doing `record.ocr.state = IN_PROGRESS` would bypass the asyncio.Lock — the new test verifies that path raises `ValidationError` because the inner `StageRecord` is frozen even when reached through the mutable `ContractRecord` parent. Lens 13 Important.

- **`test_retry_on_code_literal_mirrors_concrete_extraction_error_codes` drift-guard comment rewritten.** The previous comment said "intermediates like OcrError / LlmError carry their own codes too, but for this test we capture every subclass that has explicitly overridden .code." The word "but" implied intermediates were excluded — they were not, because `cls.__dict__.get("code")` includes them. A future reader could be misled into thinking intermediate-class code removals were safe. Lens 05 Important.

- **`Settings.model_config` pins `env_file_encoding="utf-8"`.** pydantic-settings defaults env_file_encoding to None, which resolves to the platform locale charset — on a non-UTF-8 server locale, non-ASCII bytes in `.env` would mis-decode or raise. Forward-looking 1-keyword hardening with inline justification. Lens 10 Minor.

- **`.github/dependabot.yml`: `pre-commit` added to `dev-tools` group.** `pre-commit` is in `[dependency-groups.dev]` as a pip package but was not in any Dependabot pip group, so a major `pre-commit` bump would arrive ungrouped and bypass the `update-types: [patch, minor]` major-bump filter that the file header documents as the intended posture. Lens 12 Important.

- **`.github/workflows/dependabot-lockfile-sync.yml` PAT scope comment corrected.** Setup comment requested `Pull requests: Read and write` PAT scope; the workflow performs only `actions/checkout` + `git push` and never calls the PRs API. Removed the over-permission line with an inline note explaining why. Lens 20 Minor.

- **`.gitattributes`: model-weight extensions binary-marked.** `.gguf`, `.safetensors`, `.pt`, `.pth`, `.bin` are gitignored at the pattern level, but if a small fixture ever slipped through `.gitignore` before being caught, git's `text=auto` would corrupt the bytes. Mirrored the established `.onnx binary` pattern. `*.ipynb text eol=lf` also added forward-looking for Phase 2+ OCR prototyping notebooks. Lens 19 Important + Minor.

- **`.gitignore`: clarifying comment for `data/` / `models/`.** A future contributor placing test fixtures under top-level `data/` would have them silently dropped. Added a comment noting that tracked fixtures live under `tests/fixtures/` (not ignored). Lens 19 Minor.

**Items the senior-dev filter dropped from the panel's recommendations (deferred or filtered out):**

- **Coverage `--cov-fail-under=80` enforcement in CI** (Lens 15 Important). Already documented as deferred in §17.2 until non-stub production code lands; resurfaces naturally in Phase 2.
- **JUnit XML output from pytest** (Lens 15 Minor). Forward-looking for Phase 2+ flake diagnosis; no current need.
- **`asyncio_mode = "auto"` explanatory comment** (Lens 14 Minor). Setting is unambiguous to pytest-asyncio users; commenting every config knob is over-documentation.
- **`hatchling>=N` floor in `[build-system].requires`** (Lens 12 Minor). uv lockfile pins the version; the ad-hoc `pip install` path is not a supported install method.
- **`hatchling exclude = ["**/__pycache__"]` removal** (Lens 09 Minor). The line is redundant with hatchling's default, but it was applied in §17.8 as defensive — reverting now adds churn for zero functional gain.
- **`isolated_env` autouse promotion** (Lens 16 Minor). Current opt-in pattern works; documentation gap is real but the convention can formalize when Phase 5 grows more `Settings`-constructing tests.
- **`record.py` Phase 5 forward-looking comment removal** (Lens 03 Minor). Lens itself acknowledged the comment is "the right form" with a clear handoff pointer; removing it would lose a useful breadcrumb.
- **Invalid-transition / empty-retry-on / env-var-precedence tests** (Lens 13 Minor x3). Over-specifying behavior the plan doesn't claim, or testing third-party library behavior, or low-signal documentation-by-test.
- **Three commit messages that claim "memory updated"** (Lens 02 Important). Immutable historical commits on a shared branch — re-writing requires destructive ops the user has not authorized.

**Item routed to user decision then applied per user direction:**

- **Renamed `src/extraction_service/logging.py` → `src/extraction_service/log_config.py`** (Lens 06 Minor). The original module name shadowed the stdlib `logging` module from inside the `extraction_service` package — any sibling module that wrote `import logging` would have resolved to the project file, not the stdlib. The synthesizer initially routed this to user-decision (no actual shadowing today; senior-dev judgment was "defer to Phase 5"). User opted to pre-empt: "for user decision: fix". The rename touched the source file, the test file (`tests/unit/test_logging.py` → `tests/unit/test_log_config.py` for naming symmetry), the test-file import statement, `tests/conftest.py`'s docstring reference, and three plan.md sections (§5 source tree, §5 tests/unit tree, §6.3 Task 1.9 file path). The new name matches the project's existing `_config` naming convention (`run_config.py`, `domain_model.py`).

### 17.10. Phase 1 panel fourth pass (loop-mode start)

Recorded after the 20-lens panel was re-run against `phase-1-domain` at `9eb7ddf` on 2026-05-12 in **loop mode** — the user's standing direction from this point forward: each subsequent review iteration self-decides the user-decision tier per the senior-dev judgment filter codified in CLAUDE.md and continues until a pass produces zero commits. Commits `c433158..` on the same branch land the pass-4 fixes.

**Applied per senior-dev filter:**

- **Three-lens convergence (strongest signal of the pass)**: `src/extraction_service/domain/__init__.py:8` still referenced `logging.py` after the pass-3 rename. Lens 01 + Lens 09 + Lens 17 all flagged it independently. The pass-3 rename commit (`86b0bf8`) propagated the new name through `tests/conftest.py`, the test file itself, and three `docs/plan.md` sections, but missed the domain-package orientation docstring. Fixed in commit `c433158`.

- **`docs/plan.md §6.3 Task 1.9` RED-test column updated**: the pre-rename function-name predictions (`test_logging_emits_json_in_production_mode`, `test_logging_pretty_in_dev`) never existed in the live test file (`tests/unit/test_log_config.py` uses `test_configure_logging_*` names). Updated to live names so a phase-implementor agent following the task table doesn't hunt for non-existent tests.

- **`encoding="utf-8"` pinned on `path.open()` in `config/run_config.py` and `config/domain_model.py`** (Lens 10). Extends the pattern established in `Settings.env_file_encoding` (commit `0e0c04b`, §17.9) to the other two filesystem-boundary readers. For a German-contract service, locale-dependent decoding of non-ASCII field names is a real failure mode, not preemption.

- **Documentation hardening in `config/run_config.py`, `domain/stage.py`, `domain/errors.py`** (3× Lens 05). `_DEFAULT_RETRY_ON` now carries an inline rationale for omitting `context_overflow` (deterministic on input_size × context_window — retrying without changing one of those reproduces the failure). `stage.py` module docstring states explicitly that transition methods are unguarded against invalid orderings because Phase 4 workers own the sequencing under their lock. `errors.py` docstring corrected: Phase 3 retry policy keys off the `code`-string membership in `RetryConfig.retry_on`, NOT `isinstance(e, LlmError)` — the previous wording would have misled Phase 3 implementors.

- **Test hardening** (Lens 13): split `test_contract_job_raises_when_required_field_missing` into three tests (per project's "one assertion target per test" rule); added `test_overall_status_is_failed_when_intake_failed` to close a derivation-coverage gap. 86 → 89 tests.

- **Pytest infrastructure** (Lens 14, Lens 16):
  - `addopts` extended with `--import-mode=importlib` (pytest 9.0.3 doesn't accept `import_mode` as an ini key). With `tests/__init__.py` files present, the default `prepend` mode can cause dual-import + silent fixture-identity bugs when a test file is invoked directly. `importlib` mode imports each module once under a stable name.
  - `filterwarnings` extended with `error::pytest.PytestUnraisableExceptionWarning`. Mirrors the existing `error::DeprecationWarning` rigor; forward-looking for Phase 2-4 worker async-task leakage.
  - `tests/conftest.py` `isolated_env` switched from a static 10-name `_EXTRACTION_ENV_VARS` tuple to a dynamic `os.environ` prefix scan over `EXTRACTION_`. A future Phase 5+ Settings field auto-extends the clear set with no conftest maintenance.

- **Automation hygiene** (Lens 11, Lens 12, Lens 19, Lens 20):
  - `.github/dependabot.yml` header comment summary line for `dev-tools` group appended with `pre-commit` (was stale after §17.9's pre-commit addition).
  - `.github/dependabot.yml` `github-actions-stack` patterns gained a `"*"` catch-all so future actions from new namespaces (docker/*, hashicorp/*, etc.) cannot arrive as ungrouped PRs bypassing the major-bump filter.
  - `.github/workflows/dependabot-lockfile-sync.yml` line 79 error message synced to the corrected SETUP block (Pull requests scope no longer mentioned; the workflow never calls the PRs API).
  - `.github/workflows/dependabot-lockfile-sync.yml` setup-uv `github-token` comment rewritten to teach the correct `permissions: {}` semantics: the block grants zero scopes; the secret is still injected as a string for use as an authenticated-identity rate-limit anchor, not for API writes.
  - `.gitignore` `.vscode/` carve-out comment corrected — the files don't exist yet; the rules are forward-looking stubs, not records of existing shared artifacts.

**Items the senior-dev filter dropped from the panel's recommendations:**

- **`assert_never` re-add in `log_config.py`** (Lens 07). The pass-3 removal (commit `ad1755d`) is in `§17.9`; Lens 07 in pass-4 recommended adding it back on the "untyped caller could raise UnboundLocalError" hypothetical. The codified senior-dev filter's first explicit drop category is exactly this: exhaustiveness guards on closed Literals where the type system already enforces correctness. The "untyped caller" failure mode requires a `cast(Any, ...)` bypass or external code; the project is mypy-strict throughout with no untyped internal callers, and no such bypass exists. Re-versioning a prior-pass decision requires new evidence, not a different stylistic vote.

- **`StageError` rename to `StageFailure`** (Lens 06 Important). The plan deliberately names the data structure `StageError` (§3.2 references "stage.error"; §6.3 Task 1.3 spec lists the field as `error`). Phase 4 worker code does not yet exist, so the predicted confusion at call sites is hypothetical. Blast radius: ≥5 files plus plan + spec edits. Cost-benefit is upside-down today; revisit if Phase 4 actually demonstrates the confusion.

- **`pydantic.mypy` plugin compatibility check** (Lens 04 Important). Lens correctly observed that the plugin is environment-sensitive on mypy 2.1.0 compiled binaries — but ALSO confirmed the plugin IS working in the project's locked environment (`frozen-model attribute-assignment detection is confirmed`). The proposed gate (`python -c "import pydantic.mypy"`) would FAIL on the project's own lockfile per the lens's own diagnosis, so adding the gate would break CI. The plugin works; the failure mode is hypothetical for unsupported environments.

- **`# type: ignore[prop-decorator]` rationale-comment deduplication** (Lens 04 Minor). Lens suggested moving the rationale to a module-level docstring with shorter inline pointers. The project rule is "one-line rationale on the same line", which the current form satisfies. Indirection through "see module docstring" trades local readability for non-local context — the wrong direction.

- **`darwin-checks` running only the smoke test** (Lens 15 Minor). The current scope is an intentional triage call (arm64 wheel-resolution coverage only); the workflow comment signals awareness; broadening to unit tests would add no signal at Phase 1's pure-Python scope.

- **Pre-commit external repos pinned by tag, not SHA** (Lens 18 Minor). Pre-commit community convention is tag-based pinning (managed by `pre-commit autoupdate`); the project's CI SHA-pinning convention applies to GitHub Actions, where mutability semantics differ. Mixing the two pinning styles is appropriate.

- **`ruff-check` / `ruff-format` pre-commit hooks staged-files-only** (Lens 18 Minor). Standard pre-commit DX vs. full-tree CI tradeoff; CI catches anything the staged scope misses.

- **`ruff>=0.9` floor inline comment** (Lens 08 Minor). The lockfile pins 0.15.x; the floor is wide because all selected rule families are stable by 0.9. An inline comment would be cargo cult.

- **`_now_or_default` helper extraction** (Lens 08 Minor). Four occurrences of `x if x is not None else datetime.now(UTC)` is not enough to justify an abstraction.

- **`log_level` / `log_cli` pytest settings** (Lens 14 Minor). Matches defaults; adding settings that mirror defaults is config inflation.

- **`PathsConfig` single-field-wrapper consolidation** (Lens 07 Minor). The lens itself acknowledged the sub-model is fine because operators write `paths:` as a YAML section and Phase 3 will add more path-typed fields under that key.

- **Empty-YAML / invalid-transition / env-var-precedence tests** (Lens 13 Minor x2). Speculative tests for absence-of-behavior the plan does not claim — over-specification.

- **Commit-message stylistic re-versioning on historical commits** (Lens 02 Minor). Immutable history on shared branch.

- **README install instruction drift** (implied by multiple lenses, never raised). README is user-restricted by project convention.

**Loop mode operating posture (new this pass):**

- The user-decision tier is now self-decided in loop mode. No user ask between panel iterations.
- The loop terminates when a pass produces zero commits.
- Per-pass commits cluster the lens-derived findings by concern: docs fixes, config hardenings, test improvements, automation hygiene, and a `§17.N` deviation log each iteration.

### 17.11. Phase 1 panel fifth pass (loop iteration 2, first parallel fix-dispatch)

Recorded after the 20-lens panel was re-run against `phase-1-domain` at `4813be0` on 2026-05-12 in loop mode. This pass was the **first execution of the parallel fix-dispatch pattern** codified in commit `4813be0` immediately after pass 4: 12 non-overlapping panel-derived fixes were dispatched as 12 concurrent `Agent` subagents in a single assistant message, each owning a disjoint file set, with the synthesizer running the verification gate and applying the spec-deviation entry as a final sequential layer.

**Layer A (12 parallel-dispatched fixes):**

- `0b24a5f` docs(config): expand `load_run_config` docstring with `FileNotFoundError` + `yaml.YAMLError` propagation (Lens 05 Minor).
- `030ff21` docs(errors): tighten `ContextOverflowError` docstring — "OCR output" → "OCR-produced text" to avoid the LlmError-vs-OcrError reader confusion (Lens 06 Minor).
- `5f7a27b` test(errors): rename `test_inheritance_chain` → `test_concrete_error_classes_inherit_from_correct_parents` (Lens 06 + Lens 13 convergent; project convention "test names describe behavior, not implementation").
- `3abe0b7` test: pin `encoding="utf-8"` on all 5 `path.write_text` calls in test fixtures — symmetrical with pass-4 reader pins (Lens 10 Minor).
- `4489109` test(record): cover `ContractRecord.fresh()` no-arg default-now path + hoist `timedelta` to module-level imports (Lens 13 Important + Lens 16 Minor; asymmetric coverage gap vs the existing `StageRecord.start()` parallel test).
- `66862a4` test(log_config): cover `merge_contextvars` in development renderer mode AND switch `structlog.types.Processor` → `structlog.typing.Processor` (Lens 13 Minor + Lens 04 Minor; the source rename landed in the same commit as the dev-mode test due to a parallel-agent file-ownership overlap — both fixes are still correctly applied).
- `fc077eb` chore(deps,test-infra): bump `pytest-asyncio>=0.24` → `>=1.0` and pin `asyncio_default_fixture_loop_scope = "function"` (Lens 14 Important + Minor; prevents the first Phase 2 async fixture from breaking collection under `error::DeprecationWarning`).
- `2020b0c` chore(deps): refresh `uv.lock` after the floor bump (companion to `fc077eb`).
- `d838a3a` docs(plan): update §4.13 code snippet to show `ClassVar[str]` + concrete sentinel codes (Lens 17 Minor; the snippet had drifted from the live `errors.py` ClassVar refinement).
- `c088a6c` chore: correct `.gitignore` comment about `tests/fixtures/` protection (Lens 19 Minor; my pass-3 comment overstated the protection — model-weight extensions `*.bin/.pt/.pth/.gguf/.safetensors` DO ignore files inside `tests/fixtures/`).
- `cc0f7ad` chore: add `max_line_length = 100` to `.editorconfig` (Lens 19 Minor; ties editor-ruler to CI `ruff line-length`).

**Layer B (sequential, this commit):**

- `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md` §4.4 line 203 and §14 line 409: PAT scope text synced to remove "Pull requests: Read and write" — workflow + error message were corrected in pass 4 (§17.9) but the spec body wasn't synced (Lens 20 Minor).
- This `§17.11` entry itself, recording the Layer A SHAs.

**Items the senior-dev filter dropped from the panel's recommendations:**

- **`StageError` rename to `StageFailure`** — already deferred to Phase 4 in §17.10; not re-raised this pass (no new evidence).
- **`pytest-asyncio` major version drift had been speculative; resolved.** Lens 14's pass-5 finding was applied (`fc077eb` + `2020b0c`).
- **`max_retries` config-surface split (RetryConfig vs Settings)** — Lens 05 acknowledged this as "probably intentional" per the plan; Phase 3 retry executor concern, not a Phase 1 defect.
- **`test_inheritance_chain` tautology argument** (Lens 13 Minor x1) — addressed via Lens 06's rename; the parametrize cases are retained because `ContextOverflowError → LlmError` IS load-bearing for Phase 3 retry dispatch.
- **`log_config.py` `# type: ignore[prop-decorator]` rationale-comment deduplication** (Lens 04 Minor) — already deferred in §17.9; the current per-site form is correct.
- **`darwin-checks` running only smoke** (Lens 15 Minor) — intentional triage call; revisit at Phase 2 (already deferred in §17.10).
- **Pre-commit external repos tag-pinned not SHA-pinned** (Lens 18 Minor) — already deferred in §17.9 / §17.10; community convention for trusted-maintainer repos.
- **Spec body §2 line 28 `master` branch reference** (Lens 17 Minor) — historical record of the command that was actually run; rewriting would falsify the audit trail.
- **`workflow_dispatch` concurrency formula** (Lens 11 Minor) — pre-dates the diff range; lens itself flagged "for awareness only".
- **Stale `.pyc` files in local `__pycache__`** (Lens 09 Minor) — local artifact; never committed.
- **Spec §17 missing entry for pip-audit pre-commit hook** (Lens 18 Minor) — §17 records deviations from spec, not every routine addition.
- **`hatchling>=N` build-system floor** (Lens 12 Minor) — already deferred in §17.9.
- **`httpx` ungrouped comment-header annotation** (Lens 12 Minor) — Lens itself said "no functional issue".
- **`/tmp/` fixture path sentinels in `test_run_config.py`** (Lens 16 Minor) — Lens said "no test will fail".
- **Real-wall-clock test for `StageRecord.start()` default** (Lens 16 Minor) — Lens itself said "not a current defect" and "deliberately non-assertive".
- **Original 17 ruff families lacking rationale comments** (Lens 08 Minor) — comment inflation; the families are well-known.
- **`_now_or_default` helper extraction** (Lens 08 Minor) — already deferred in §17.9.
- **`ruff>=0.9` floor inline comment** (Lens 08 Minor) — already deferred in §17.9.
- **`hatchling exclude = ["**/__pycache__"]` removal** (Lens 09 Minor) — already deferred in §17.9.
- **`pythonpath = ["src"]` in pytest config** (Lens 09 Minor) — duplicates the supported `uv run` editable-install path.
- **`isolated_env` explicit `scope="function"` declaration** (Lens 14 Minor) — function-scope is the implicit default; explicit declaration is documentation-via-redundancy.
- **`asyncio_default_fixture_loop_scope` documentation tightening beyond what's already inline** — applied as part of `fc077eb`'s comment.
- **Commit-message stylistic re-versioning on historical commits** (Lens 02 Minor x3) — immutable history.
- **README install / `.gitignore` vscode existence rephrases** — README is user-restricted; .vscode comment was corrected in pass 4.

**Process learning from this pass (relevant to the parallel fix-dispatch pattern):**

- 12 parallel agents was the right call wall-clock-wise: dispatched in ~30 seconds; all reports received within ~8 minutes (slower agents on doc/config files dominated the latency).
- Two of the 12 agents (A11 for `log_config.py` source rename, A12 for `test_domain_job.py` rationale tightening) reported "fix already in HEAD" rather than producing their own commits. Investigation: `66862a4` (A6's commit) and `c088a6c` (A9's commit) had already applied those changes as side effects, indicating an agent file-ownership overflow. The branch state is correct (all 12 fixes landed), but the future iteration of the dispatch prompt should add an explicit `git diff --cached` self-check before commit to enforce file-ownership rigor.
- The `§17.N` entry's "Layer B" sequential placement is correct: every Layer A SHA must be known before the audit-trail entry can be written. Trying to parallelize that would race the SHA references.

**Loop-mode status:** Pass 5 produced 13 commits (12 Layer A + 1 Layer B). The loop continues to pass 6 against the new HEAD.

### 17.12. Phase 1 panel sixth pass (loop iteration 3, strong-convergence signal)

Recorded after the 20-lens panel was re-run against `phase-1-domain` at `26b4f24` on 2026-05-12 in loop mode. Pass 6 shows **strong convergence**: 16/20 lenses returned Ship-ready Yes (up from 10/20 in pass 5 and ~5/20 in pass 4). The remaining 4 With-fixes lenses each surfaced 1-2 substantive items that survived the senior-dev filter — no Critical, no convergent ≥2-lens findings.

**Pass 6 totals: 10 fix-now items (4 Important / 6 Minor / 0 Critical) across 9 commits (8 Layer A + 1 ruff-format companion + this Layer B entry).**

**Ship-ready verdicts:** 16/20 Yes, 4/20 With fixes (Lens 01, Lens 07, Lens 17, Lens 02-historical).

**Layer A (7 parallel-dispatched fix-agents):**

- `c5f3de9` docs(plan): sync §6.3 task 1.1, 1.6, 1.9 RED-test names to live test names (Lens 01 Minor + Lens 17 Minor) — same factual-drift pattern as the pass-4 task-1.9 fix; phase-implementor subagents reading the table now get accurate test names.
- `f54df7c` chore: add `[*.toml]` section to `.editorconfig` with `indent_size = 4` (Lens 19 Minor) — follows the existing per-filetype section pattern.
- `80dd5c0` fix(config): correct `PathsConfig` docstring + tighten `_OCR_RETRY_CODES_REJECTED` type (Lens 07 Important + Minor) — the docstring claimed PathsConfig would grow with prompt-template paths but those already live in `LlmConfig`; rewrote to point future growth at genuinely unhoused paths. Type tightened from `frozenset[str]` to `frozenset[RetryOnCode]` for static guarantee.
- `13316fc` docs(claude): qualify "When NOT to use" bullet 3 + expand per-pass loop-mode status format (Lens 17 Important + user-directed methodology improvement) — bullet 3 said "no subagent dispatch for fixes themselves" but the Parallel fix-dispatch pattern explicitly dispatches subagents in loop mode; qualified the bullet to apply only to standalone "review against main" runs. Per-pass status format now mandates severity-bucketed fix count (Critical / Important / Minor) AND ship-ready verdict count (e.g., "16/20 Yes, 4/20 With fixes") so the user gets a quality + convergence signal at-a-glance between passes.
- `2ee3252` fix(types): honest `cast(dict[str, Any], json.load(f))` in `load_domain_model` (Lens 04 Important) — `json.load` returns `Any`; the previous local annotation was an unverified cast. The cast makes the narrowing explicit and the inline comment names `Draft202012Validator.check_schema` as the runtime guard for non-object schemas. Ruff's TC006 enforced the string-quoted form `cast("dict[str, Any]", ...)`.
- `e25e752` chore(pre-commit): pin `minimum_pre_commit_version: "4.0"` (Lens 18 Minor) — first-run DX win; matches the `pre-commit>=4.0` dev dep floor.
- `a641208` docs(plan): sync 3 stale "Pull requests: Read and write" PAT scope references in `docs/superpowers/plans/2026-05-11-ci-cd-scaffolding.md` (Lens 20 Minor) — completes the multi-pass PAT-scope sync (workflow header + error message + spec §4.4/§14 corrected in prior passes; the historical plan doc was the last surface).

**Layer A companion (ruff format):**

- `adca278` chore(format): ruff format split the lengthened `_OCR_RETRY_CODES_REJECTED` line over 100 chars after the type-tightening in `80dd5c0`. Pure format, no semantic change.

**Layer B (sequential, this commit):** this `§17.12` entry.

**Items the senior-dev filter dropped from the panel's recommendations:**

- **`assert_never` re-add proposed by Lens 07 in pass 4** — Lens 07 in pass 6 did NOT re-flag it (the explicit prompt-level guard against re-raising it was respected).
- **`StageError` rename to `StageFailure`** (Lens 06 implicit) — pass-6 Lens 06 did NOT re-raise this either; the §17.10 deferral held.
- **CLAUDE.md "When NOT to use" bullet 4 staleness** (Lens 17 Important) — bullet says "Phase 1 — already complete or in-review"; in-review IS accurate. Lens itself noted "Minor in isolation". No change needed.
- **`OcrError` intermediate-class code inheritance footgun** (Lens 05 Important) — Phase 4 implementation concern; risk is hypothetical until Phase 4 worker code exists.
- **`StageError.code` Literal tightening** (Lens 05 Minor) — preemption for Phase 4; current `str` field is correct at the IO boundary.
- **`now_or_default` helper extraction** (Lens 08 Important) — already deferred in §17.9; same finding re-raised; re-versioning a prior decision requires new evidence (none provided).
- **`ruff>=0.9` floor bump to `>=0.15`** (Lens 08 Minor) — already deferred in §17.9; lockfile is source of truth, ad-hoc `pip install` is not supported.
- **`asyncio_default_test_loop_scope` explicit set** (Lens 14 Minor) — defaults to "function" with NO DeprecationWarning when absent (verified by Lens 14 itself); no Phase 2 collection-break risk like the fixture-scope variant.
- **Explicit `scope="function"` on `_reset_structlog_state` and `isolated_env`** (Lens 14 + 16 Minor) — function-scope is the implicit default; explicit declaration is documentation-via-redundancy (already deferred in §17.11).
- **`pythonpath = ["src"]` in pytest config** (Lens 09 Minor) — already deferred in §17.11; duplicates the supported `uv run` editable install path.
- **Stale `.pyc` in local `__pycache__`** (Lens 09 Minor) — local artifact, never committed; lens itself says "no code change needed".
- **`hatchling exclude = ["**/__pycache__"]` redundancy** (Lens 09 Minor) — already deferred in §17.9.
- **`ContextOverflowError` docstring re-rewording** (Lens 06 Minor) — polish-of-polish on a pass-5 fix (commit `030ff21`).
- **`Mode` type alias extraction** (Lens 06 Minor) — explicit Phase 5 deferred-4a; the wiring callsite (`Settings.mode` → `configure_logging`) is when the alias pays off.
- **`PathsConfig` plural-name pre-evaluation** (Lens 06 Minor) — explicit Phase 3/4 deferral by the lens itself ("flag for re-evaluation then").
- **`getattr(self, name)` in record.py untyped** (Lens 04 Minor) — current pattern works, mypy is green; `match name:` rewrite is more verbose with no static-analysis gain.
- **`renderer: structlog.typing.Processor` annotation clarity comment** (Lens 04 Minor) — comment inflation; the type IS a structural callable, no annotation issue.
- **Test bundles (`test_stage_state_str_coerces_to_value`, `test_stage_record_defaults_to_pending_*`, `test_fresh_contract_record_with_default_now_*`)** (Lens 13 ×3 Minor) — "one assertion target per test" rule is about one logical invariant; multiple-example values for the same invariant is parametrize-style coverage, not bundling of different behaviors.
- **`load_run_config` empty-YAML docstring case** (Lens 10 Minor) — docstring already covers it via "ValidationError on schema violations"; empty file → missing required fields → ValidationError.
- **`/tmp/` paths in test_run_config fixtures** (Lens 10 + 16 Minor) — already noted "no test will fail" in §17.11.
- **Pre-commit tag-vs-SHA pinning** (Lens 10 Minor) — already deferred in §17.9 / §17.10 / §17.11; community convention.
- **`backend-checks` / `darwin-checks` timeout / coverage / JUnit XML / matrix** (Lens 15 Minor ×3) — already deferred in §17.2 / §17.9 / §17.10 / §17.11 as Phase 2+ concerns.
- **Spec §17 missing entry for pip-audit pre-commit hook** (Lens 18 Minor in pass 4; same finding still surfacing) — §17 records deviations from spec, not routine additions; already addressed in pass-5 synthesizer note.
- **Workflow_dispatch concurrency** (Lens 11 Minor) — pre-dates the diff range; lens itself flagged "for awareness only".
- **Historical commit-message stylistic corrections** (Lens 02 multiple Minor) — immutable shared-branch history; lens itself acknowledged "nothing requires rewriting history".
- **Hardcoded test runner timeouts, comment annotations on common-knowledge config** (Lens 11 + 15) — comment inflation per the senior-dev filter.
- **`httpx` and `pre-commit` documentation-comment clarifications in dependabot.yml** (Lens 12 Minor ×2) — comment inflation; the configurations are correct.
- **`types-jsonschema>=4.26` floor tightening to locked-version** (Lens 12 Minor) — stub-floor reasoning is "mirror runtime floors not locked versions"; current state matches the stated convention.

**Process learning from this pass:**

- The senior-dev filter has settled into a stable steady-state. ~80% of the panel's raw findings are filtered out; the remaining ~20% are substantive fixes that survive multiple criteria (factual drift, defense-in-depth that mirrors established project patterns, real coverage gaps).
- Convergence count dropped this pass: 0 multi-lens convergent findings (passes 4 and 5 had 2-3 each on `logging.py` rename, `SchemaInvalid` stale ref, etc.). With those one-time multi-lens-visible items resolved, the panel is now in cleanup mode.
- Parallel fix-dispatch wall-clock: 7 agents in parallel completed in ~5 minutes total. Comparable to the 12-agent parallel dispatch in pass 5. The ruff-format companion (`adca278`) was added in the main conversation after Layer A — pattern: line-length boundary crossings from type-annotation tightenings need a post-Layer-A format pass.

**Loop-mode status:** Pass 6: 9 commits applied; 10 fixes (0 Critical / 4 Important / 6 Minor); 16/20 Ship-ready Yes, 4/20 With fixes; ~25 panel recommendations filtered out; new HEAD post Layer B. **Loop continues to pass 7 against the new HEAD.**

### 17.13. Phase 1 panel seventh pass (loop iteration 4)

Recorded after the 20-lens panel was re-run against `phase-1-domain` at `2c430ae` on 2026-05-12 in loop mode. Pass 7 surfaced a fresh wave of small substantive items — the senior-dev filter still passing through real defects after the strong-convergence pass 6.

**Pass 7 totals: 9 fix-now items (5 Important / 4 Minor / 0 Critical) across 8 commits (6 Layer A + 1 lockfile companion + this Layer B entry).**

**Ship-ready verdicts:** 12/20 Yes, 8/20 With fixes.

**Layer A (6 parallel-dispatched fix-agents):**

- `be7e1db` feat(domain): re-export `OverallStatus`, `StageName` from `domain/__init__.py` (Lens 09 Important) — record.py comment declared them as Phase 5 HTTP response surface but the natural `from extraction_service.domain import OverallStatus` import path raised ImportError. Closed the discovery gap before Phase 5 needs the path.
- `9d4e3a1` docs(workflows): sync IDE NOTE line-number references (Lens 11 Minor) — pass-4 commit `de1bb9f` added a 9-line rationale block above the actual PAT references, shifting their line numbers. The IDE NOTE comment's `(lines 60, 76)` was stale; corrected to current `(lines 75, 91)`.
- `3e09216` chore(pyproject): mypy floor + pytest comment + coverage comment + BLE ruff family (Lens 12 Important + Lens 14 Minor + Lens 15 Important + Lens 05 Important — 4 findings bundled on one file):
  - `mypy>=1.13` → `mypy>=2.0` (one major behind locked 2.1.0; mypy 2.0 introduced breaking strict-mode flag semantics; mirrors the pass-5 pytest-asyncio floor fix)
  - "pytest 9.x" → "pytest 9.0.x" in import-mode comment (9.1+ added `import_mode` as ini option)
  - Inline comment on `fail_under = 80` documenting the §17.2 deferral (config is inert without `--cov` in CI; prevents false-confidence reading)
  - `BLE` added to ruff `select` (plan §7 "no silent exception catches" rule had no linter arm; zero current violations + real Phase 2-6 coverage)
- `0ec44de` docs(plan): complete §6.3 RED-test name sweep (Lens 01 Important + Lens 17 Minor) — pass-6 commit `c5f3de9` synced tasks 1.1/1.6/1.9; tasks 1.2-1.8 were left with plan-time predicted names. Completed the sweep across all six remaining task rows.
- `3184fd5` chore: document `.env.example` forward-looking stub in `.gitignore` (Lens 19 Minor) — mirrors the `.vscode/` carve-out comment pattern; gives contributors a signal that the rule is intentional scaffolding.
- `b1731a8` docs(claude): generalize parallel fix-dispatch template (Lens 17 Important) — template inside Loop mode section hardcoded "Phase 1 review pass-N" and "phase-1-domain" branch; Phase 2 self-review would have dispatched agents with "Phase 1 review" in their prompts. Replaced with `Phase N` and `<phase-branch>` placeholders.

**Layer A companion (uv.lock):**

- `c525a27` chore(deps): refresh `uv.lock` after the mypy floor bump (resolved version unchanged at 2.1.0; metadata regeneration only).

**Layer B (sequential, this commit):** this `§17.13` entry.

**Items the senior-dev filter dropped from the panel's recommendations:**

- **Add base `ExtractionError` instance-test for sentinel code** (Lens 05 Minor) — subclass test already exercises the same mechanism; base test is symmetric belt-and-suspenders.
- **5 PositiveInt rejection tests for Settings** (Lens 13 Minor) — port test already anchors the PositiveInt boundary behavior; adding 5 more re-tests the same Pydantic mechanism.
- **Lower-bound assertion on real-clock tests** (Lens 16 Important) — already deferred in §17.11 with explicit "deliberately non-assertive" rationale.
- **`_VALID_SCHEMA` module-level dict immutability tightening** (Lens 16 Minor) — lens itself said "no current test mutates it"; preemption for hypothetical future test misuse.
- **`LoggingMode` type alias extraction** (Lens 06 Important) — already deferred to Phase 5 in §17.11 (natural wiring callsite).
- **Single-value `Literal["docling"]` widening** (Lens 03 Important) — Phase 2 widens when adding the second engine; current single-value form is plan-compliant.
- **`OcrError` intermediate-class code inheritance footgun** (Lens 05 Important, re-raised from prior passes) — Phase 4 implementation concern.
- **`_write_json` test helper unused `name` parameter** (Lens 07 Minor) — borderline YAGNI churn in test code.
- **`lambda: list(_DEFAULT_RETRY_ON)` → `_DEFAULT_RETRY_ON.copy`** (Lens 08 Minor) — intentional style (explicit copy via `list(...)` is equally idiomatic).
- **Drift-guard test type-narrowing with `isinstance`** (Lens 04 Minor) — polish-of-polish on test introspection; no runtime consequence.
- **`Mode` alias in shared module** (Lens 06 Important) — already deferred to Phase 5 in §17.11.
- **`asyncio_default_test_loop_scope` explicit setting** (Lens 14 Minor, re-raised) — already deferred (no DeprecationWarning when absent, unlike fixture-scope counterpart).
- **`hypothesis` not yet exercised** (Lens 15 Minor) — beyond Phase 1 scope; dev dep available when Phase 2+ needs property-based tests.
- **`darwin-checks` `--dev` install** (Lens 15 Minor) — marginal CI optimization.
- **CLAUDE.md "When NOT to use" bullet 4 "in-review" wording** (Lens 17 Important) — current wording IS accurate; Phase 1 is in-review.
- **`structlog.typing.Processor` annotation comment for clarity** (Lens 04 Minor, re-raised) — comment inflation.
- **`Mode` alias inline drift-prevention** (Lens 06 Important) — re-versioning §17.11 deferral; no new evidence.
- **`getattr(self, name)` `match` rewrite** (Lens 04 Minor) — current pattern works, mypy is green; rewrite is more verbose with no static-analysis gain.
- **README quick-start `pre-commit install`** (Lens 18 Minor) — README user-restricted.
- **CI `pre-commit run --all-files` single-step parity** (Lens 18 Minor) — intentional architectural tradeoff (clean per-tool CI annotations).
- **Pre-commit external repo SHA pinning** (Lens 18, re-raised) — already deferred; community convention.
- **`workflow_dispatch` concurrency formula** (Lens 11 Minor, re-raised) — predates the diff range; lens flagged "for awareness only".
- **lockfile-sync cancel-in-progress on synchronize** (Lens 20 Minor) — lens-acknowledged designed behavior; no code change needed.
- **setup-uv cache-key pre-regen lockfile staleness** (Lens 20 Minor) — lens-acknowledged "current risk: none".
- **Historical commit-message stylistic items (66862a4 + c088a6c silent passengers)** (Lens 02 ×2 Minor) — immutable history.
- **§17 missing entry for pip-audit hook routine addition** (Lens 18, re-raised) — already addressed; §17 records deviations, not routine additions.

**Process note:** Pass 7 surfaced 9 fix-now items where pass 6 had 10 — convergence is asymptotic, not strictly monotonic. Each pass tends to find a handful of items the prior pass's lens prompts didn't specifically guard against (this pass: `mypy>=1.13` floor staleness, parallel-dispatch template hardcoding, the §6.3 task-row-sweep completion). Two of these were the synthesizer's own pass-6 additions to the codebase that became findings the moment they landed.

**Loop-mode status:** Pass 7: 8 commits applied; 9 fixes (0 Critical / 5 Important / 4 Minor); 12/20 Ship-ready Yes, 8/20 With fixes; ~26 panel recommendations filtered out; new HEAD post Layer B. **Loop continues to pass 8 against the new HEAD (iteration 5 of 5 — pass 8 will hit the max-cap if it produces non-zero commits).**
