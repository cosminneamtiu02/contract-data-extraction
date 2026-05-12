# Phase 0.5 — CI/CD Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the GitHub-side gates (CI, CodeQL, Dependabot auto-merge, Dependabot lockfile sync), a macOS arm64 smoke job, Dependabot config, CODEOWNERS, secret-scanning baseline, and supporting housekeeping files — all on the `phase-0.5-ci-cd` branch as a single follow-up PR after the just-merged Phase 0.

**Architecture:** Single-package Python (uv) project, no monorepo plumbing. Workflows call `uv run …` directly (no Taskfile indirection). Two parallel CI jobs (ubuntu + macos-15 smoke). CodeQL matrix produces `Analyze (python)` and `Analyze (actions)` status checks. Dependabot auto-merge + lockfile-sync run on PR events with kill-switch repo variables. Source of truth: [docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md](../specs/2026-05-11-ci-cd-scaffolding-design.md).

**Tech Stack:** GitHub Actions, `astral-sh/setup-uv@v8`, `actions/checkout@v6`, `github/codeql-action@v4`, pip-audit, detect-secrets, pre-commit-hooks, Dependabot v2.

**Working directory for ALL tasks:** `/Users/cosminneamtiu/Work/contract-data-extraction/.worktrees/phase-0.5-ci-cd/`

---

## File Structure

```
.github/
  CODEOWNERS                                  # 1 line: *  @cosminneamtiu02
  dependabot.yml                              # pip + github-actions + pre-commit ecosystems
  actions/
    read-python-version/action.yml            # composite — reads .python-version → step output (python-version)
  workflows/
    ci.yml                                    # backend-checks (ubuntu-24.04) + darwin-checks (macos-15)
    codeql.yml                                # matrix: language ∈ {python, actions}
    dependabot-automerge.yml                  # gh pr merge --auto --squash
    dependabot-lockfile-sync.yml              # uv lock → commit → force-with-lease push

.editorconfig                                 # charset/eol/indent rules
.gitattributes                                # text=auto eol=lf + binary types + uv.lock collapse
.secrets.baseline                             # detect-secrets baseline (generated locally)

# modified
.gitignore                                    # expand from 19 → ~30 lines
.pre-commit-config.yaml                       # append detect-secrets + pre-commit-hooks suite
pyproject.toml                                # add pip-audit + detect-secrets to dev deps
uv.lock                                       # regenerated after pyproject change
```

---

## Task 1: Add `pip-audit` + `detect-secrets` to dev deps

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups].dev` block, lines ~29-39)
- Regenerate: `uv.lock`

- [ ] **Step 1.1: Edit `pyproject.toml` — add two dev deps**

Append to the `[dependency-groups].dev` list (after `"pre-commit>=4.0",`):

```toml
    "pip-audit>=2.7",
    "detect-secrets>=1.5",
```

- [ ] **Step 1.2: Regenerate the lockfile**

Run: `uv lock`
Expected: `uv.lock` updated; ~2 new resolved entries plus their transitives.

- [ ] **Step 1.3: Verify the dev install still works**

Run: `uv sync --frozen --dev && uv run python -c "import pip_audit, detect_secrets; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 1.4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(deps): add pip-audit and detect-secrets to dev group"
```

---

## Task 2: Generate `.secrets.baseline`

**Files:**
- Create: `.secrets.baseline`

- [ ] **Step 2.1: Scan and write baseline**

Run: `uv run detect-secrets scan > .secrets.baseline`
Expected: a JSON file with plugin metadata and an empty `results` map.

- [ ] **Step 2.2: Verify the baseline is valid JSON and has no findings**

Run: `python -c "import json; b = json.load(open('.secrets.baseline')); print('results:', b.get('results', {}))"`
Expected: `results: {}`

- [ ] **Step 2.3: Commit**

```bash
git add .secrets.baseline
git commit -m "chore: add detect-secrets baseline (empty)"
```

---

## Task 3: Add `.editorconfig` and `.gitattributes`

**Files:**
- Create: `.editorconfig`
- Create: `.gitattributes`

- [ ] **Step 3.1: Write `.editorconfig`**

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

- [ ] **Step 3.2: Write `.gitattributes`**

```gitattributes
# Normalize line endings
* text=auto eol=lf

# Binary files
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.pdf binary
*.onnx binary

# Lock files (collapse in PR diffs; tracked but not human-reviewed)
uv.lock linguist-generated=true -diff
```

- [ ] **Step 3.3: Renormalize and commit**

Run: `git add --renormalize .`
Run: `git status` — should show no staged changes if all existing files are already lf.
Run: `git add .editorconfig .gitattributes && git commit -m "chore: add editorconfig and gitattributes"`

---

## Task 4: Expand `.gitignore`

**Files:**
- Modify: `.gitignore` (append new sections)

- [ ] **Step 4.1: Append entries**

Open `.gitignore` and append:

```gitignore

# Local environment
.env.*
!.env.example

# Additional tooling caches
.import_linter_cache/

# OS
Thumbs.db

# Logs
*.log

# Claude Code per-machine state (transcripts, worktrees, etc.)
.claude/

# IDE — keep dir ignored but allow checked-in shared editor settings
.vscode/*
!.vscode/extensions.json
!.vscode/settings.json
```

- [ ] **Step 4.2: Verify nothing currently tracked was just newly ignored**

Run: `git status --ignored | head -40`
Expected: ignored entries listed; no `Changes not staged for commit` for previously tracked files.

- [ ] **Step 4.3: Commit**

```bash
git add .gitignore
git commit -m "chore: expand .gitignore (env, caches, IDE allowlist, .claude)"
```

---

## Task 5: Extend `.pre-commit-config.yaml`

**Files:**
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 5.1: Append remote-repo hooks**

The existing file is local-hook-only. Append after the closing of the `local` `hooks:` block:

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

- [ ] **Step 5.2: Install pre-commit hook locally**

Run: `uv run pre-commit install`
Expected: `pre-commit installed at .git/hooks/pre-commit`

- [ ] **Step 5.3: Run all hooks across the repo**

Run: `uv run pre-commit run --all-files`
Expected: every hook reports `Passed` (or `Skipped` for hooks that match no files). If `trailing-whitespace` or `end-of-file-fixer` find offenders, they auto-fix; re-stage and re-run.

If hooks made fixes, run: `git add -A && uv run pre-commit run --all-files` again until green.

- [ ] **Step 5.4: Commit (including any auto-fixes)**

```bash
git add .pre-commit-config.yaml
# also re-add any files that auto-fixers touched
git add -u
git commit -m "build(pre-commit): add detect-secrets and pre-commit-hooks"
```

---

## Task 6: `.github/CODEOWNERS` + composite action

**Files:**
- Create: `.github/CODEOWNERS`
- Create: `.github/actions/read-python-version/action.yml`

- [ ] **Step 6.1: Write CODEOWNERS**

```
# Single-line ownership rule. One-line insurance against a future
# main-protection ruleset toggle to require_code_owner_review: true.
*    @cosminneamtiu02
```

- [ ] **Step 6.2: Write the composite action**

Create `.github/actions/read-python-version/action.yml`:

```yaml
name: Read Python version from .python-version
description: >
  Reads the project's pinned Python interpreter version from .python-version
  at the repo root and emits it as the python-version step output.
  Callers should give this step an id (e.g. id: pyver) and reference the value
  through the step's outputs.python-version. set -euo pipefail plus an
  empty-string check turns a missing or empty .python-version into a loud
  error annotation rather than a silent unpinned interpreter.
  working-directory:. is REQUIRED because a calling job may set a job-level
  defaults.run.working-directory to a subdirectory; .python-version only
  exists at the repo root. Action descriptions are parsed for template
  expressions, so the literal $-curly expression syntax is elided here.

outputs:
  python-version:
    description: The Python interpreter version read from .python-version.
    value: ${{ steps.read.outputs.python-version }}

runs:
  using: composite
  steps:
    - name: Read .python-version
      id: read
      working-directory: .
      shell: bash
      run: |
        set -euo pipefail
        v=$(tr -d '[:space:]' < .python-version)
        [ -n "$v" ] || { echo "::error::.python-version is empty or missing"; exit 1; }
        echo "python-version=$v" >> "$GITHUB_OUTPUT"
```

- [ ] **Step 6.3: Pre-commit + commit**

Run: `uv run pre-commit run --files .github/CODEOWNERS .github/actions/read-python-version/action.yml`
Expected: passes (check-yaml validates action.yml).

```bash
git add .github/CODEOWNERS .github/actions/read-python-version/action.yml
git commit -m "ci: add CODEOWNERS and read-python-version composite action"
```

---

## Task 7: `.github/dependabot.yml`

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 7.1: Write the file**

```yaml
# Dependabot configuration for the contract-data-extraction project.
#
# Scope: pip (single workspace at /), github-actions, pre-commit.
# Groups batch interlocking package updates into atomic PRs:
#   - fastapi-stack: fastapi + starlette + uvicorn + standard transitives
#   - pydantic:      pydantic + pydantic-settings (lockstep releases)
#   - pytest:        pytest + plugins (aligned releases)
#   - dev-tools:     ruff + mypy + pip-audit + detect-secrets + types-* + hatchling + pyyaml
#   - runtime-singletons: structlog + httpx + ollama + jsonschema
#   - ml-stack:      docling + rapidocr-onnxruntime + modelscope (heavy transitive trees)
#
# update-types filters intentionally omitted so MAJOR bumps stay grouped.

version: 2
updates:
  - package-ecosystem: pip
    directory: /
    target-branch: main
    schedule:
      interval: weekly
    open-pull-requests-limit: 5
    rebase-strategy: auto
    commit-message:
      prefix: "chore(deps)"
      include: scope
    labels:
      - dependencies
    groups:
      fastapi-stack:
        patterns:
          - "fastapi"
          - "starlette"
          - "uvicorn*"
          - "httptools"
          - "uvloop"
          - "watchfiles"
      pydantic:
        patterns:
          - "pydantic"
          - "pydantic-settings"
      pytest:
        patterns:
          - "pytest"
          - "pytest-*"
      dev-tools:
        patterns:
          - "ruff"
          - "mypy"
          - "pip-audit"
          - "detect-secrets"
          - "types-*"
          - "hatchling"
          - "pyyaml"
      runtime-singletons:
        patterns:
          - "structlog"
          - "httpx"
          - "ollama"
          - "jsonschema"
      ml-stack:
        patterns:
          - "docling"
          - "rapidocr-onnxruntime"
          - "modelscope"

  - package-ecosystem: github-actions
    directory: /
    target-branch: main
    schedule:
      interval: weekly
    open-pull-requests-limit: 5
    rebase-strategy: auto
    commit-message:
      prefix: "chore(deps)"
      include: scope
    labels:
      - dependencies
    groups:
      github-actions-stack:
        patterns:
          - "actions/*"
          - "astral-sh/*"
          - "github/codeql-action/*"

  - package-ecosystem: pre-commit
    directory: /
    target-branch: main
    schedule:
      interval: daily
    open-pull-requests-limit: 1
    rebase-strategy: auto
    commit-message:
      prefix: "chore(deps)"
      include: scope
    labels:
      - dependencies
    groups:
      pre-commit-tools:
        patterns:
          - "*"
```

- [ ] **Step 7.2: Validate YAML + commit**

Run: `uv run pre-commit run --files .github/dependabot.yml`
Expected: check-yaml passes.

```bash
git add .github/dependabot.yml
git commit -m "ci: add Dependabot config (pip + github-actions + pre-commit, grouped)"
```

---

## Task 8: `.github/workflows/ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 8.1: Write the workflow**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  # PR runs share a group keyed on the PR ref so a force-push cancels the
  # stale older run. push:main runs are keyed by SHA so back-to-back
  # squash-merges don't cancel earlier post-merge canary runs — the
  # invariant "main is always known-green" requires every commit on main
  # to keep its CI record.
  group: ci-${{ github.ref }}-${{ github.event_name == 'push' && github.sha || 'pr' }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  backend-checks:
    # Pin to the current major rather than `ubuntu-latest` so a GitHub
    # auto-bump to a future major doesn't silently shift the runner image.
    # Dependabot's github-actions ecosystem will surface major bumps via PR.
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          # CI only verifies (never pushes). Strip the persisted GITHUB_TOKEN
          # from the cloned repo's .git/config to remove unused write surface.
          persist-credentials: false

      - id: pyver
        uses: ./.github/actions/read-python-version

      - name: Install uv
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0
        with:
          enable-cache: true
          cache-dependency-glob: uv.lock
          # Authenticated GitHub API requests pull uv interpreter downloads
          # under the 5000/hr per-token rate limit instead of the shared
          # 60/hr unauthenticated pool. macOS runners share an outbound IP
          # pool that frequently exhausts the unauthenticated bucket; same
          # rationale applies to ubuntu when it lands on a hot IP.
          github-token: ${{ secrets.GITHUB_TOKEN }}
          python-version: ${{ steps.pyver.outputs.python-version }}

      - name: Install dependencies
        run: uv sync --frozen --dev

      - name: Lockfile freshness check
        run: uv lock --check

      - name: Lint
        run: uv run ruff check src tests

      - name: Format check
        run: uv run ruff format --check src tests

      - name: Type check
        run: uv run mypy src tests

      - name: Tests
        run: uv run pytest -q

      - name: Dependency CVE scan
        # Strict mode: any advisory on any pinned dep fails CI. Escape hatches
        # if a real CVE blocks merge: (a) `--ignore-vuln <GHSA-id>` with a
        # comment and time-bound, or (b) bump the dep's minimum version in
        # pyproject.toml to the fixed release.
        run: uv run pip-audit --strict

      - name: Secret scan
        # Symmetric with the pre-commit detect-secrets hook so a Dependabot-
        # bypass push (e.g., the lockfile-sync workflow's automated commit)
        # cannot land a leaked secret on main without surfacing.
        run: |
          set -euo pipefail
          git ls-files | grep -vF '.secrets.baseline' | \
            xargs uv run detect-secrets-hook --baseline .secrets.baseline

  darwin-checks:
    # macOS arm64 is the production target (Mac Mini M4). This job verifies
    # wheel resolution + import succeed there before merge.
    runs-on: macos-15
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          persist-credentials: false

      - id: pyver
        uses: ./.github/actions/read-python-version

      - name: Install uv
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0
        with:
          enable-cache: true
          cache-dependency-glob: uv.lock
          github-token: ${{ secrets.GITHUB_TOKEN }}
          python-version: ${{ steps.pyver.outputs.python-version }}

      - name: Install dependencies
        run: uv sync --frozen --dev

      - name: Smoke tests (import + entrypoint)
        # Smoke-only — catches arm64 wheel resolution failures for docling,
        # rapidocr-onnxruntime, modelscope, and any future native-extension
        # dep before it bites in production.
        run: uv run pytest -q tests/test_smoke.py
```

- [ ] **Step 8.2: Validate**

Run: `uv run pre-commit run --files .github/workflows/ci.yml`
Expected: check-yaml passes.

- [ ] **Step 8.3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add CI workflow (ubuntu backend-checks + macos-15 darwin smoke)"
```

---

## Task 9: `.github/workflows/codeql.yml`

**Files:**
- Create: `.github/workflows/codeql.yml`

- [ ] **Step 9.1: Write the workflow**

```yaml
name: CodeQL

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  schedule:
    # Weekly Monday 06:00 UTC — catches newly-published query rules even
    # when no PRs land that week.
    - cron: '0 6 * * 1'

permissions:
  contents: read

concurrency:
  group: codeql-${{ github.ref }}-${{ github.event_name == 'push' && github.sha || 'pr' }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  analyze:
    name: Analyze (${{ matrix.language }})
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    permissions:
      # Required for SARIF upload to the Security tab.
      security-events: write
      # CodeQL reads workflow run metadata.
      actions: read
      contents: read
    strategy:
      fail-fast: false
      matrix:
        language: [python, actions]
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          persist-credentials: false

      - name: Initialize CodeQL
        uses: github/codeql-action/init@v4
        with:
          languages: ${{ matrix.language }}
          # Default query suite ("security"). No paths-ignore on day one;
          # revisit if signal-to-noise becomes problematic.

      - name: Perform CodeQL analysis
        uses: github/codeql-action/analyze@v4
        with:
          category: "/language:${{ matrix.language }}"
```

- [ ] **Step 9.2: Validate + commit**

Run: `uv run pre-commit run --files .github/workflows/codeql.yml`
Expected: passes.

```bash
git add .github/workflows/codeql.yml
git commit -m "ci: add CodeQL workflow (python + actions matrix)"
```

---

## Task 10: `.github/workflows/dependabot-automerge.yml`

**Files:**
- Create: `.github/workflows/dependabot-automerge.yml`

- [ ] **Step 10.1: Write the workflow**

```yaml
# Auto-merge Dependabot PRs once all required status checks pass.
#
# Kill switch:
#   gh variable set DEPENDABOT_AUTOMERGE_ENABLED --body "true"   # arm
#   gh variable set DEPENDABOT_AUTOMERGE_ENABLED --body "false"  # disarm
#
# `gh pr merge --auto --squash` is only safe when the main branch ruleset
# has required status checks. Without them, --auto has nothing to wait for
# and merges immediately, even if CI is red. Required checks (set on the
# ruleset, NOT here): backend-checks, darwin-checks, CodeQL / Analyze (python),
# CodeQL / Analyze (actions).

name: Dependabot auto-merge

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]

permissions:
  contents: read

concurrency:
  # A new synchronize event supersedes the pending merge-intent attempt
  # from the previous event.
  group: dependabot-automerge-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  automerge:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      # Job-level scopes minted only when the if: evaluates true. `gh pr
      # merge --auto` calls the enablePullRequestAutoMerge GraphQL mutation
      # which requires BOTH contents:write AND pull-requests:write.
      contents: write
      pull-requests: write
    # Check the PR author from the event payload (stays `dependabot[bot]`
    # for the PR's lifetime). github.actor flips to whoever triggered the
    # current event — e.g., a human clicking "Update branch" — which would
    # cause an incorrect skip.
    if: >
      github.event.pull_request.user.login == 'dependabot[bot]' &&
      github.event.pull_request.draft == false &&
      vars.DEPENDABOT_AUTOMERGE_ENABLED == 'true'
    steps:
      - name: Enable auto-merge
        run: gh pr merge --auto --squash "$PR_URL"
        env:
          PR_URL: ${{ github.event.pull_request.html_url }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 10.2: Validate + commit**

Run: `uv run pre-commit run --files .github/workflows/dependabot-automerge.yml`
Expected: passes.

```bash
git add .github/workflows/dependabot-automerge.yml
git commit -m "ci: add Dependabot auto-merge workflow (kill-switch armed via repo var)"
```

---

## Task 11: `.github/workflows/dependabot-lockfile-sync.yml`

**Files:**
- Create: `.github/workflows/dependabot-lockfile-sync.yml`

- [ ] **Step 11.1: Write the workflow**

```yaml
# Regenerate uv.lock on Dependabot PRs.
#
# WHY: Dependabot's uv support has a known parity bug with its pnpm
# equivalent: it bumps pyproject.toml but does not regenerate uv.lock.
# `uv sync --dev` papers over the gap at runtime, but the committed
# lockfile drifts. CI's `uv lock --check` step would then fail every
# Dependabot PR. This workflow detects the drift, runs `uv lock`, and
# pushes the fix back to the PR branch.
#
# SETUP (one-time, after this lands on main):
#   1. Create a fine-grained PAT scoped to this repo with:
#         Contents: Read and write only (no Pull requests scope — the workflow performs git operations only; see spec §4.4 / §17.10 for the post-implementation correction)
#   2. gh secret set DEPENDABOT_LOCKFILE_SYNC_PAT --app dependabot --body "<PAT>"
#      (--app dependabot is REQUIRED: Dependabot-triggered workflows only
#       read secrets from the Dependabot store.)
#   3. gh variable set DEPENDABOT_LOCKFILE_SYNC_ENABLED --body "true"
#
# Until step 3, the workflow runs on every PR but no-ops cleanly.
#
# WHY A PAT (not GITHUB_TOKEN): pushes authenticated by GITHUB_TOKEN do
# NOT trigger new workflow runs (anti-recursion protection). Without a
# PAT, the lockfile-fix push would advance the PR head but no CI would
# fire, leaving required status checks attached to the old, broken
# commit. A PAT looks like a normal user and re-triggers CI normally.

name: Dependabot lockfile sync

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]

permissions:
  contents: read

concurrency:
  # The `action` suffix segregates `opened` from `synchronize` so an
  # unrelated sync doesn't cancel the regenerator that fired on initial
  # open.
  group: dependabot-lockfile-sync-${{ github.event.pull_request.number }}-${{ github.event.action }}
  cancel-in-progress: true

jobs:
  sync:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    if: >
      github.event.pull_request.user.login == 'dependabot[bot]' &&
      github.event.pull_request.draft == false &&
      vars.DEPENDABOT_LOCKFILE_SYNC_ENABLED == 'true'
    steps:
      - name: Verify PAT is configured
        env:
          PAT: ${{ secrets.DEPENDABOT_LOCKFILE_SYNC_PAT }}
        run: |
          set -euo pipefail
          if [ -z "$PAT" ]; then
            echo "::error::DEPENDABOT_LOCKFILE_SYNC_PAT secret is not set, but DEPENDABOT_LOCKFILE_SYNC_ENABLED variable is 'true'. Either create a fine-grained PAT (Contents: Read and write only (no Pull requests scope; see spec §4.4 / §17.10)) and save it as DEPENDABOT_LOCKFILE_SYNC_PAT in the Dependabot secret store, or disarm with: gh variable set DEPENDABOT_LOCKFILE_SYNC_ENABLED --body 'false'"
            exit 1
          fi

      - name: Checkout PR branch
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          ref: ${{ github.event.pull_request.head.ref }}
          # Shallow fetch sized for typical Dependabot rebase chains. A
          # fail-safe further down surfaces a clear "bump fetch-depth"
          # error if a PR's ancestry runs deeper.
          fetch-depth: 50
          token: ${{ secrets.DEPENDABOT_LOCKFILE_SYNC_PAT }}

      - id: pyver
        uses: ./.github/actions/read-python-version

      - name: Guard against self-triggered loops
        id: loop_guard
        run: |
          set -euo pipefail
          LAST_AUTHOR=$(git log -1 --format='%ae' HEAD)
          LAST_SUBJECT=$(git log -1 --format='%s' HEAD)
          echo "Last commit author email: $LAST_AUTHOR"
          echo "Last commit subject: $LAST_SUBJECT"
          # Two independent guards: the user-id check is the fast path,
          # the commit-subject check is the durable fallback.
          if echo "$LAST_AUTHOR" | grep -qF "41898282+github-actions"; then
            echo "Last commit is from github-actions[bot]; skipping."
            echo "skip=true" >> "$GITHUB_OUTPUT"
          elif echo "$LAST_SUBJECT" | grep -qF "chore(deps): regenerate lockfile after dependabot bump"; then
            echo "Last commit subject matches this workflow's own message; skipping."
            echo "skip=true" >> "$GITHUB_OUTPUT"
          else
            echo "skip=false" >> "$GITHUB_OUTPUT"
          fi

      - name: Detect if pyproject.toml changed
        id: changed
        if: steps.loop_guard.outputs.skip != 'true'
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          set -euo pipefail
          echo "Diffing $BASE_SHA..$HEAD_SHA"

          if ! git rev-parse --verify "$BASE_SHA" >/dev/null 2>&1; then
            echo "::error::base SHA $BASE_SHA not present in fetched history; bump fetch-depth on the checkout step."
            exit 1
          fi
          if ! git rev-parse --verify "$HEAD_SHA" >/dev/null 2>&1; then
            echo "::error::head SHA $HEAD_SHA not present in fetched history; bump fetch-depth on the checkout step."
            exit 1
          fi

          CHANGED=$(git diff --name-only "$BASE_SHA" "$HEAD_SHA")
          echo "Changed files:"
          echo "$CHANGED"

          NEEDS_UV=false
          if echo "$CHANGED" | grep -qE '^pyproject\.toml$'; then
            NEEDS_UV=true
          fi

          echo "needs_uv=$NEEDS_UV" >> "$GITHUB_OUTPUT"

          if [ "$NEEDS_UV" = "false" ]; then
            echo "pyproject.toml not changed; nothing to regenerate."
          fi

      - name: Set up uv
        if: steps.loop_guard.outputs.skip != 'true' && steps.changed.outputs.needs_uv == 'true'
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0
        with:
          enable-cache: true
          cache-dependency-glob: uv.lock
          python-version: ${{ steps.pyver.outputs.python-version }}
          github-token: ${{ secrets.GITHUB_TOKEN }}

      - name: Regenerate uv.lock
        if: steps.loop_guard.outputs.skip != 'true' && steps.changed.outputs.needs_uv == 'true'
        run: uv lock

      - name: Commit and push lockfile update
        if: steps.loop_guard.outputs.skip != 'true'
        env:
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          HEAD_REF: ${{ github.event.pull_request.head.ref }}
          # Pin C locale so the non-fast-forward discriminator below lands
          # the English error message regardless of runner-image LANG.
          LANG: C
          LC_ALL: C
        run: |
          set -euo pipefail
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          if [ -f uv.lock ]; then
            git add uv.lock
          fi

          if git diff --cached --quiet; then
            echo "No lockfile changes to commit."
            exit 0
          fi

          echo "Lockfile changes:"
          git diff --cached --stat

          git commit \
            -m "chore(deps): regenerate lockfile after dependabot bump" \
            -m "Automated follow-up commit from .github/workflows/dependabot-lockfile-sync.yml."

          # `--force-with-lease=<ref>:<sha>` bounds the push to the same
          # head this run started from. If Dependabot rebases the PR
          # mid-execution, the lease check fails and the push is rejected.
          push_status=0
          push_output=$(git push --force-with-lease="$HEAD_REF:$HEAD_SHA" 2>&1) || push_status=$?
          if [ "$push_status" != 0 ]; then
            if echo "$push_output" | grep -qE "non-fast-forward|stale info"; then
              echo "Concurrent push or upstream rebase detected; another lockfile-sync run will reconcile."
              exit 0
            fi
            echo "$push_output"
            exit "$push_status"
          fi
          echo "$push_output"
```

- [ ] **Step 11.2: Validate + commit**

Run: `uv run pre-commit run --files .github/workflows/dependabot-lockfile-sync.yml`
Expected: passes.

```bash
git add .github/workflows/dependabot-lockfile-sync.yml
git commit -m "ci: add Dependabot lockfile-sync workflow"
```

---

## Task 12: Final local verification

**Files:** none modified — verification only.

- [ ] **Step 12.1: Full pre-commit dry-run**

Run: `uv run pre-commit run --all-files`
Expected: all hooks pass.

- [ ] **Step 12.2: Repeat the CI gate locally**

Run, in order:
```bash
uv sync --frozen --dev
uv lock --check
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src tests
uv run pytest -q
uv run pip-audit --strict
git ls-files | grep -vF '.secrets.baseline' | xargs uv run detect-secrets-hook --baseline .secrets.baseline
```
Expected: every command exits 0.

If `pip-audit` reports advisories: bump the affected dep in `pyproject.toml` to a fixed release (preferred), or add `--ignore-vuln <GHSA-id>` to the CI step with a comment and a follow-up issue.

- [ ] **Step 12.3: Push the branch**

```bash
git push -u origin phase-0.5-ci-cd
```

---

## Task 13: Open the PR

**Files:** none — PR creation only.

- [ ] **Step 13.1: Open the PR via gh**

```bash
gh pr create --base main --head phase-0.5-ci-cd \
  --title "feat(phase-0.5): CI/CD scaffolding" \
  --body "$(cat <<'EOF'
## Summary

Stand up the GitHub-side gates for the project. Adds:

- **CI** (`.github/workflows/ci.yml`) — backend-checks on ubuntu-24.04 (lint / format / type / test / lockfile-freshness / pip-audit strict / detect-secrets) + darwin-checks on macos-15 (smoke import test, verifies arm64 wheel resolution for the production target).
- **CodeQL** (`.github/workflows/codeql.yml`) — matrix analysis for python and actions; status checks named \`CodeQL / Analyze (python)\` and \`CodeQL / Analyze (actions)\`.
- **Dependabot auto-merge** (`.github/workflows/dependabot-automerge.yml`) — squash-merges passing Dependabot PRs; armed by repo variable.
- **Dependabot lockfile sync** (`.github/workflows/dependabot-lockfile-sync.yml`) — regenerates \`uv.lock\` when Dependabot bumps \`pyproject.toml\` and pushes the fix back to the PR branch via PAT.
- **Composite action** (`.github/actions/read-python-version/action.yml`) — single source of truth for the Python version pin across all workflows.
- **Dependabot config** (`.github/dependabot.yml`) — pip + github-actions + pre-commit ecosystems, grouped to avoid cascade conflicts.
- **CODEOWNERS** — single-line ownership rule.
- **detect-secrets baseline** + **pre-commit suite** (detect-secrets, trailing-whitespace, end-of-file-fixer, check-yaml, check-json, check-added-large-files, detect-private-key).
- **pip-audit** and **detect-secrets** added to \`[dependency-groups].dev\`.
- **.editorconfig** and **.gitattributes** — line-ending / charset / lock-file diff-collapse rules.
- **.gitignore** expansion — \`.env.*\`, \`.claude/\`, VS Code allowlist, etc.

Source-of-truth design at \`docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md\`. Step-by-step plan at \`docs/superpowers/plans/2026-05-11-ci-cd-scaffolding.md\`.

## Post-merge operator setup (REQUIRED)

After this PR merges, configure the following:

1. **Branch ruleset on \`main\`** — require status checks:
   - \`backend-checks\`
   - \`darwin-checks\`
   - \`CodeQL / Analyze (python)\`
   - \`CodeQL / Analyze (actions)\`
2. **Repo setting** — \"Allow GitHub Actions to create and approve pull requests\" → enabled.
3. **Arm auto-merge:** \`gh variable set DEPENDABOT_AUTOMERGE_ENABLED --body \"true\"\`
4. **Set up lockfile sync** (one-time, requires PAT creation):
   - Create a fine-grained PAT scoped to this repo with Contents: Read and write only (no Pull requests scope; see spec §4.4 / §17.10).
   - \`gh secret set DEPENDABOT_LOCKFILE_SYNC_PAT --app dependabot --body \"<PAT>\"\`
   - \`gh variable set DEPENDABOT_LOCKFILE_SYNC_ENABLED --body \"true\"\`

Until step 1 lands, \`gh pr merge --auto\` would merge immediately on red CI (no required checks to wait for). Do not arm auto-merge before the ruleset is in place.

## Test plan

- [x] \`uv sync --frozen --dev\` succeeds with the new dev deps
- [x] \`uv run pre-commit run --all-files\` passes (including new detect-secrets + pre-commit-hooks suite)
- [x] \`uv run pip-audit --strict\` clean on current pins
- [x] \`uv run detect-secrets-hook --baseline .secrets.baseline\` clean on all tracked files
- [x] \`uv lock --check\` reports no drift
- [x] All workflow YAML passes \`check-yaml\` pre-commit hook
- [ ] CI runs all 4 required status checks on this PR (verification happens once the PR opens)

## What is intentionally NOT in this PR

- No \`CLAUDE.md\` — user-deferred
- No \`Taskfile.yml\` — workflows call \`uv run\` directly
- No \`import-linter\` — deferred to a later phase
- No coverage gate in CI — \`pyproject.toml\` keeps \`fail_under=80\` for local \`pytest --cov\`, but CI runs \`pytest -q\` (no \`--cov\`) until domain code exists
- No \`automerge.md\` operational doc — rationale lives inline in the workflow comments
- No CodeQL \`paths-ignore\` — analyzer scans everything on day one

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 13.2: Report the PR URL back to the user.**

---

## Self-review checklist (already run by the planner, captured here for audit)

- ✅ Spec coverage: each of spec §3-§14 has a corresponding task.
- ✅ No placeholders ("TBD", "TODO", "fill in").
- ✅ Type/file-name consistency: `read-python-version` referenced consistently; secret-baseline path `.secrets.baseline` used consistently; workflow filenames match spec inventory.
- ✅ Each step has exact commands or full code blocks.
- ✅ Frequent commits — 11 implementation commits + verification step + push + PR.
