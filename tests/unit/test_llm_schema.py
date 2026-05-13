"""Tests for JSON-schema validation of LLM-extracted data (plan §6.5 task 3.3).

``validate_extracted_data`` runs ``jsonschema.validate`` and wraps any
``jsonschema.ValidationError`` in the domain-layer ``SchemaInvalidError``,
preserving the error chain (``raise ... from e``) and including the failing
field path in the message. Malformed schemas (``jsonschema.SchemaError``) are
NOT wrapped — those are startup-time configuration errors, not runtime data
errors, and must surface verbatim.
"""

import pytest


def test_valid_extracted_data_passes() -> None:
    from extraction_service.llm.schema import validate_extracted_data

    schema = {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
        "required": ["amount"],
    }
    # Must return None silently with no exception raised.
    validate_extracted_data({"amount": 42.0}, schema)


def test_invalid_extracted_data_raises_schema_invalid() -> None:
    from extraction_service.domain.errors import SchemaInvalidError
    from extraction_service.llm.schema import validate_extracted_data

    schema = {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
        "required": ["amount"],
    }
    with pytest.raises(SchemaInvalidError):
        validate_extracted_data({"amount": "not-a-number"}, schema)


def test_type_mismatch_raises_schema_invalid_error() -> None:
    from extraction_service.domain.errors import SchemaInvalidError
    from extraction_service.llm.schema import validate_extracted_data

    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    with pytest.raises(SchemaInvalidError):
        validate_extracted_data({"name": 123}, schema)


def test_missing_required_field_raises_schema_invalid_error() -> None:
    from extraction_service.domain.errors import SchemaInvalidError
    from extraction_service.llm.schema import validate_extracted_data

    schema = {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
        "required": ["amount"],
    }
    with pytest.raises(SchemaInvalidError):
        validate_extracted_data({}, schema)


def test_nested_error_includes_field_path_in_message() -> None:
    from extraction_service.domain.errors import SchemaInvalidError
    from extraction_service.llm.schema import validate_extracted_data

    schema = {
        "type": "object",
        "properties": {
            "contract": {
                "type": "object",
                "properties": {"amount": {"type": "number"}},
                "required": ["amount"],
            }
        },
        "required": ["contract"],
    }
    with pytest.raises(SchemaInvalidError) as exc_info:
        validate_extracted_data({"contract": {"amount": "not-a-number"}}, schema)
    # The message must include the failing field path so callers can debug.
    assert "contract" in str(exc_info.value)


def test_schema_error_on_malformed_schema_is_not_wrapped() -> None:
    import jsonschema

    from extraction_service.llm.schema import validate_extracted_data

    # A schema with an invalid type value triggers jsonschema.SchemaError —
    # this must propagate verbatim, NOT be wrapped in SchemaInvalidError.
    malformed_schema = {"type": "not-a-valid-type"}
    with pytest.raises(jsonschema.SchemaError):
        validate_extracted_data({"any": "data"}, malformed_schema)


def test_schema_error_chain_preserves_original_exception() -> None:
    import jsonschema

    from extraction_service.domain.errors import SchemaInvalidError
    from extraction_service.llm.schema import validate_extracted_data

    schema = {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]}
    with pytest.raises(SchemaInvalidError) as exc_info:
        validate_extracted_data({"x": "wrong"}, schema)
    # The __cause__ must be a jsonschema.ValidationError (raise ... from e).
    assert isinstance(exc_info.value.__cause__, jsonschema.ValidationError)


def test_validate_extracted_data_nested_array_index_field_path() -> None:
    """``_format_path`` handles the common string-then-integer branch.

    The private helper's main branch produces ``"parties[0].name"``-style
    paths: a string key followed by an integer index appended via
    ``parts[-1] = f"{parts[-1]}[{item}]"``. The companion test
    ``test_validate_extracted_data_root_array_field_path`` covers the
    leading-integer branch (root-level array); this test covers the
    paired branch by validating an object containing an array of records
    against a schema requiring each record's ``name`` field, with the
    second record missing ``name``. The resulting error message must
    contain ``"parties[1]"`` — both the string key AND the bracketed
    index in the documented combined form.
    """
    from extraction_service.domain.errors import SchemaInvalidError
    from extraction_service.llm.schema import validate_extracted_data

    schema = {
        "type": "object",
        "properties": {
            "parties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        "required": ["parties"],
    }
    data = {"parties": [{"name": "ok"}, {}]}

    with pytest.raises(SchemaInvalidError) as exc_info:
        validate_extracted_data(data, schema)

    assert "parties[1]" in str(exc_info.value)


def test_validate_extracted_data_root_array_field_path() -> None:
    """``_format_path`` handles root-level array indices (leading integer).

    The private helper has two branches: ``str``-then-``[int]`` (the common
    case, e.g. ``contract.parties[0].name``) and ``[int]`` at the very start
    (root-level array, no preceding string key). Phase-3 domain schemas
    happen to be all-object-rooted, so the leading-integer branch was never
    exercised. This test fires the branch by validating an array of records
    against a root-array schema, then asserts the resulting error message
    includes a bracketed-integer prefix (``[1]``) — confirming the
    ``else: parts.append(f"[{item}]")`` arm reached the message string.

    The ``cast`` is deliberate: ``validate_extracted_data``'s ``data``
    parameter is typed ``dict[str, Any]`` because in Phase 3 the LLM output
    is always a dict per ``OllamaLlmClient.extract``'s return type. The
    underlying ``jsonschema.validate`` accepts any JSON-shaped value, and
    this test exercises a private code-path that fires only on non-dict
    inputs — hence the type override at the test seam.
    """
    from typing import Any, cast

    from extraction_service.domain.errors import SchemaInvalidError
    from extraction_service.llm.schema import validate_extracted_data

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    }
    data = [{"name": "ok"}, {}]  # second element missing "name"

    with pytest.raises(SchemaInvalidError) as exc_info:
        validate_extracted_data(cast("dict[str, Any]", data), schema)

    assert "[1]" in str(exc_info.value)
