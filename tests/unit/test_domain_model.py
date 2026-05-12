"""Unit tests for domain-model JSON Schema loader (Task 1.8).

``load_domain_model`` reads the user-supplied JSON Schema that the LLM stage
will validate extracted data against (docs/plan.md §3.2, §4.13's
``SchemaInvalid``). The loader runs meta-validation via the ``jsonschema``
library so a malformed schema crashes the service at boot, not after every
contract goes through OCR.
"""

import json
from pathlib import Path

import pytest
from jsonschema.exceptions import SchemaError

from extraction_service.config.domain_model import load_domain_model

_VALID_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "contract_number": {"type": "string"},
        "parties": {"type": "array", "items": {"type": "string"}},
        "amount_eur": {"type": "number", "minimum": 0},
    },
    "required": ["contract_number"],
}


def _write_json(tmp_path: Path, payload: object, name: str = "schema.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_valid_json_schema_returns_dict(tmp_path: Path) -> None:
    schema_path = _write_json(tmp_path, _VALID_SCHEMA)

    loaded = load_domain_model(schema_path)

    assert loaded == _VALID_SCHEMA


def test_load_round_trips_to_an_independent_dict(tmp_path: Path) -> None:
    schema_path = _write_json(tmp_path, _VALID_SCHEMA)

    loaded = load_domain_model(schema_path)
    loaded["new_key"] = "mutated"

    # The on-disk schema is untouched and a fresh load returns the original.
    fresh = load_domain_model(schema_path)
    assert "new_key" not in fresh


def test_load_raises_schema_error_on_invalid_meta_schema(tmp_path: Path) -> None:
    invalid_schema = {"type": "not_a_real_json_schema_type"}
    schema_path = _write_json(tmp_path, invalid_schema)

    with pytest.raises(SchemaError):
        load_domain_model(schema_path)


def test_load_raises_schema_error_when_required_is_not_a_list(tmp_path: Path) -> None:
    """``required`` must be an array per JSON Schema spec; a string is invalid."""
    invalid_schema = {"type": "object", "required": "contract_number"}
    schema_path = _write_json(tmp_path, invalid_schema)

    with pytest.raises(SchemaError):
        load_domain_model(schema_path)


def test_load_raises_when_file_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"

    with pytest.raises(FileNotFoundError):
        load_domain_model(missing)


def test_load_raises_when_file_is_not_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not valid json,,,", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_domain_model(path)
