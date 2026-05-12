"""User-supplied JSON Schema loader.

The domain model is a JSON Schema document supplied by the caller and pointed
at by ``run_config.paths.domain_model_path``. The LLM stage validates extracted
data against it (docs/plan.md §3.2; ``SchemaInvalidError`` exception in §4.13).

``load_domain_model`` runs JSON Schema meta-validation via the ``jsonschema``
library so a malformed schema raises at startup, not on the first contract.
The return type is ``dict[str, Any]`` — this is an IO-boundary case where
``Any`` is explicitly accepted per docs/plan.md §7 ("`Any` is acceptable only
at IO boundaries").
"""

import json
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator


def load_domain_model(path: Path) -> dict[str, Any]:
    """Load and meta-validate a JSON Schema document from disk."""
    with path.open() as f:
        schema: dict[str, Any] = json.load(f)
    Draft202012Validator.check_schema(schema)
    return schema
