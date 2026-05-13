"""JSON-schema validation for LLM-extracted data (plan §6.5 task 3.3).

``validate_extracted_data`` is the thin adapter between ``jsonschema`` and the
extraction-service domain error layer. It wraps ``jsonschema.ValidationError``
(runtime data error) in ``SchemaInvalidError`` so Phase 4 callers can catch a
single domain type. ``jsonschema.SchemaError`` (malformed schema — startup-time
configuration error) is intentionally NOT caught here; it must propagate
verbatim so misconfigured validators surface loudly at boot, not silently at
runtime.
"""

from collections.abc import Sequence
from typing import Any

import jsonschema

from extraction_service.domain.errors import SchemaInvalidError


def _format_path(path: Sequence[str | int]) -> str:
    """Format a ``jsonschema`` absolute_path as a human-readable string.

    Examples:
        []                              -> "(root)"
        ["contract"]                    -> "contract"
        ["parties", 0, "name"]          -> "parties[0].name"
    """
    if not path:
        return "(root)"
    parts: list[str] = []
    for item in path:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(item)
    return ".".join(parts)


def validate_extracted_data(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate *data* against *schema* using JSON Schema.

    Args:
        data: The LLM-extracted payload to validate.
        schema: A JSON Schema dict describing the expected structure.

    Returns:
        ``None`` on success.

    Raises:
        SchemaInvalidError: When *data* does not conform to *schema*.
            The original ``jsonschema.ValidationError`` is chained via
            ``__cause__`` (``raise ... from e``).
        jsonschema.SchemaError: When *schema* itself is malformed.
            Propagates verbatim — this is a startup-time configuration
            error, not a runtime data error.
    """
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        field_path = _format_path(e.absolute_path)
        msg = f"Schema validation failed at '{field_path}': {e.message}"
        raise SchemaInvalidError(msg) from e
