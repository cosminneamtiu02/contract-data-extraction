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
