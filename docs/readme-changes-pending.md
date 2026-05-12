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
