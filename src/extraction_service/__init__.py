"""extraction_service — local HTTP service for German legal contract extraction.

See docs/plan.md for the architecture and phase-by-phase development plan.
`__all__` is intentionally NOT declared at this phase: the package exposes no
public symbols yet, and an empty `__all__` would silently mask future symbols
from `from extraction_service import *` unless every contributor remembers to
update the list. Add `__all__` once there are real public exports to gate.
"""
