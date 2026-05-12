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
from typing import Any, cast

from jsonschema.validators import Draft202012Validator


def load_domain_model(path: Path) -> dict[str, Any]:
    """Load and meta-validate a JSON Schema document from disk.

    Propagates (intentionally — failures here must crash at startup, not
    silently fall through into request handling):

    - ``FileNotFoundError``: ``path`` does not exist on disk.
    - ``json.JSONDecodeError``: file contents are not valid JSON.
    - ``jsonschema.exceptions.SchemaError``: JSON is structurally valid
      but does not conform to JSON Schema (e.g., an array or integer at
      the top level, or a malformed ``$schema``/``type`` declaration).
      Note: Draft 2020-12 also accepts boolean schemas (``true``/``false``)
      at the top level, so those values pass meta-validation rather than
      raising.
    """
    # Pin UTF-8 explicitly: a server running a non-UTF-8 locale would silently
    # mis-decode non-ASCII characters in JSON string values (German field
    # names, descriptions). Matches the encoding pin on Settings.env_file.
    with path.open(encoding="utf-8") as f:
        # json.load returns Any; cast to the JSON Schema shape (always an
        # object at the top level per the JSON Schema spec). If the cast is
        # wrong, Draft202012Validator.check_schema below catches it at runtime
        # with a meaningful SchemaError, not a silent type-mismatch downstream.
        schema = cast("dict[str, Any]", json.load(f))
    Draft202012Validator.check_schema(schema)
    return schema
