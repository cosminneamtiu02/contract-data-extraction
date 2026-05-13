# README pending changes (queue)

This file accumulates **proposed README edits** surfaced by panel reviews,
automated tooling, or other review processes. **README is user-restricted**
per [CLAUDE.md §Project state notes](../CLAUDE.md) — Claude (and any
automated reviewer) must NOT edit `README.md` directly. Instead, write
proposed edits here.

When the user is ready to apply the accumulated changes, they will read
this file, edit `README.md` in one pass, and either delete processed
entries below or empty this file entirely.

**Format per entry:**

```
### YYYY-MM-DD — <short title>

**Source:** <what surfaced this — e.g., "Panel cycle-3 pass-1, Lens 17 Minor">
**Affected README section:** <which heading/lines>
**Issue:** <what's currently in README that's wrong/drifted/missing>
**Proposed change:** <concrete new text or a description of the edit>
**Rationale:** <why this is worth applying>
```

---

## Pending entries

### 2026-05-12 — Label Phase 6 directory entries in Layout section

**Source:** Panel cycle-3 pass-1 standalone review against `origin/main`,
Lens 17 (Documentation completeness, Minor). Recorded in `docs/superpowers/specs/2026-05-11-ci-cd-scaffolding-design.md §17.19` as routed to this file.

**Affected README section:** `## Layout` (current lines 20–27 of `README.md`).

**Issue:** The Layout section lists three directories — `config/`, `scripts/`,
`ops/` — that do not yet exist in the repo. They are Phase 6 artifacts per
`docs/plan.md §6.8`. A contributor reading the README looks for these and
finds nothing. Equivalent drift in `docs/plan.md §5` was fixed in the same
pass-1 batch (commit `60b0829`); the README has the same issue, but README
is user-restricted so the same change is queued here instead of applied.

**Proposed change:** Add a `(Phase 6 — not yet created)` qualifier to each
of the three lines, matching the precedent used in `docs/plan.md §5`:

```markdown
- `src/extraction_service/` — the service package
- `tests/` — unit, pipeline, http, ocr, and golden tests
- `config/` — sample run configs and JSON schemas (Phase 6 — not yet created)
- `scripts/` — operational scripts (prewarm, validation, benchmark) (Phase 6 — not yet created)
- `ops/` — deployment helpers (Phase 6 — not yet created)
- `docs/plan.md` — locked architecture + development plan
```

Alternative: remove the three lines entirely until the directories land, then
re-add them in the Phase 6 PR. Either approach is acceptable; the qualifier
approach matches what was done in `docs/plan.md §5`.

**Rationale:** Prevents contributors from looking for non-existent
directories. Drift between docs and the live filesystem is a substantive
cosmetic concern (CLAUDE.md "doc sync after a live divergence" criterion),
not a stylistic preference. The qualifier is reversible — the Phase 6 PR
that creates these directories will naturally remove the `(Phase 6 — not yet created)` annotation.

---

### 2026-05-13 — "golden tests" wording on `tests/` line is pre-§17.3

**Source:** Panel cycle-2 of the post-merge phase-2-ocr review loop, Lens 17
(Documentation completeness, Minor). Spec deviation log entry for this
cycle lives at `docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md §17.11` (cycle-2 audit), which routes this item here.

**Affected README section:** `## Layout` (the `tests/` bullet — current line
21 of `README.md`).

**Issue:** The bullet reads `tests/ — unit, pipeline, http, ocr, and golden tests`. The word "golden tests" implies committed snapshot files in the test
tree. Phase 2 spec deviation §17.3 explicitly replaced that strategy: real
OCR tests now run against local sample PDFs resolved via
`$EXTRACTION_OCR_SAMPLES_DIR`, which are gitignored and never committed. A
contributor following the "golden tests" wording will look for a `tests/golden/` directory or similar and find nothing.

**Proposed change:** Replace the `tests/` line with wording that reflects the
post-§17.3 strategy. Two acceptable forms:

```markdown
- `tests/` — unit, pipeline, http, and ocr tests (real-OCR tests parametrise over local sample PDFs from `$EXTRACTION_OCR_SAMPLES_DIR`, gitignored)
```

or, terser:

```markdown
- `tests/` — unit, pipeline, http, and ocr tests
```

(The terser form simply drops the now-misleading "golden tests" label without
naming the env-var mechanism — the env var is documented in
`docs/superpowers/specs/2026-05-12-phase-2-ocr-spec-deviations.md §17.3`.)

**Rationale:** "golden tests" was accurate at the time the README was written
(pre-Phase-2). After §17.3, the term is misleading drift. Same "doc sync
after divergence" criterion as the Phase 6 directory qualifiers above.

---

### 2026-05-13 — Mention Ollama runtime prerequisite in Quick start

**Source:** Panel single-cycle pass3 standalone review against `origin/main`,
Lens 17 (Documentation completeness, Minor). Routed to this file per CLAUDE.md
`feedback-readme-queue`.

**Affected README section:** `## Quick start` (or wherever the runnable
instructions live — currently the section listing `uv sync`, `uv run pytest`,
etc.).

**Issue:** README's Quick start instructions describe `uv sync && uv run pytest && uv run ruff check && uv run mypy` — all of which work without Ollama installed because no test in the current suite hits a real Ollama (the LLM layer uses `FakeOllamaClient` exclusively). However, a contributor following Quick start to completion has no signal that **Ollama itself must be installed locally and the `gemma4:e2b-it-q4_K_M` model pulled** before the service can do useful work. This is also tracked as Phase 6 task 6.6 ("README with run instructions") and 6.8 (idle-shutdown caveat).

**Proposed change:** Add a sub-section under Quick start (or as a separate
"Runtime prerequisites" section) along the lines of:

```markdown
### Runtime prerequisites

The service calls a local **Ollama** instance at `http://127.0.0.1:11434` for
LLM extraction. Install Ollama from <https://ollama.com> and pull the model:

    ollama pull gemma4:e2b-it-q4_K_M

The repo's test suite uses fake clients and does NOT require Ollama to be
running; this prerequisite applies only when running the service against real
contracts.
```

**Rationale:** Catches the "I followed Quick start and tests pass — why doesn't
the service work?" failure mode. Convergent with Phase 6 task 6.6 in the plan;
adding the line now (queued for the user's next README pass) front-loads the
information without waiting for the full Phase 6 README rewrite.

---

### 2026-05-13 — Add LICENSE pointer (MIT) to README

**Source:** Panel single-cycle pass3 standalone review against `origin/main`,
Lens 17 (Documentation completeness, Minor). Routed to this file per CLAUDE.md
`feedback-readme-queue`.

**Affected README section:** End of file (new short "License" section), OR
inline reference under an existing section.

**Issue:** `LICENSE` is present in the repo root (MIT, dated 2026, owner Cosmin
Neamtiu) and is correctly referenced in `pyproject.toml` via
`license-files = ["LICENSE"]`. README does not mention the license anywhere —
no SPDX comment, no "See LICENSE" line, no licensing badge.

**Proposed change:** Add a brief "License" section to README:

```markdown
## License

MIT — see [`LICENSE`](LICENSE) for the full text.
```

Alternative: an SPDX-style annotation in README's frontmatter:
`<!-- SPDX-License-Identifier: MIT -->`.

**Rationale:** Standard GitHub convention. Most consumers (incl. linters,
SPDX scanners, GitHub's own license-detection UI) read both `LICENSE` and the
README. Surfacing the license string from README is a 2-line addition with
zero downside.

---
