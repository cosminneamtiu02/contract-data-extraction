"""Unit tests for run-config YAML loader (Task 1.7).

The run config is a per-deployment YAML pointed at by ``EXTRACTION_RUN_CONFIG``.
Per docs/plan.md §4.7 the service must "fail fast on missing/invalid config"
at startup — these tests enforce that contract: missing required fields raise,
unknown fields raise (typo guard), numeric constraints reject bad values.

The schema uses ``extra="forbid"`` on every sub-model so a misspelled key like
``ocr.engien`` surfaces at boot, not at first OCR call.
"""

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from extraction_service.config.run_config import RunConfig, load_run_config


def _write_yaml(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "run.yaml"
    cfg.write_text(dedent(body))
    return cfg


_MINIMAL_YAML = """\
llm:
  prompt_template_path: /tmp/prompt.txt
paths:
  domain_model_path: /tmp/schema.json
"""


def test_load_minimal_valid_yaml_returns_run_config(tmp_path: Path) -> None:
    cfg = _write_yaml(tmp_path, _MINIMAL_YAML)

    run_config = load_run_config(cfg)

    assert isinstance(run_config, RunConfig)
    assert run_config.llm.prompt_template_path == Path("/tmp/prompt.txt")
    assert run_config.paths.domain_model_path == Path("/tmp/schema.json")


def test_load_minimal_yaml_uses_documented_defaults_for_omitted_sections(
    tmp_path: Path,
) -> None:
    cfg = _write_yaml(tmp_path, _MINIMAL_YAML)

    run_config = load_run_config(cfg)

    assert run_config.ocr.engine == "docling"
    assert run_config.ocr.force_full_page_ocr is True
    assert run_config.ocr.timeout_seconds == 60
    assert run_config.llm.timeout_seconds == 60
    assert run_config.retry.retry_on == ["llm_failed", "schema_invalid"]


def test_load_full_yaml_overrides_defaults(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path,
        """\
        ocr:
          engine: docling
          force_full_page_ocr: false
          timeout_seconds: 120
        llm:
          prompt_template_path: /tmp/prompt.txt
          timeout_seconds: 90
        retry:
          retry_on:
            - context_overflow
        paths:
          domain_model_path: /tmp/schema.json
        """,
    )

    run_config = load_run_config(cfg)

    assert run_config.ocr.force_full_page_ocr is False
    assert run_config.ocr.timeout_seconds == 120
    assert run_config.llm.timeout_seconds == 90
    assert run_config.retry.retry_on == ["context_overflow"]


def test_load_yaml_raises_when_required_section_missing(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path,
        """\
        llm:
          prompt_template_path: /tmp/prompt.txt
        """,
    )

    with pytest.raises(ValidationError):
        load_run_config(cfg)


def test_load_yaml_raises_when_required_field_missing(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path,
        """\
        llm:
          timeout_seconds: 90
        paths:
          domain_model_path: /tmp/schema.json
        """,
    )

    with pytest.raises(ValidationError):
        load_run_config(cfg)


def test_load_yaml_raises_on_unknown_top_level_field(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path,
        """\
        llm:
          prompt_template_path: /tmp/prompt.txt
        paths:
          domain_model_path: /tmp/schema.json
        unknown_section:
          some_value: 42
        """,
    )

    with pytest.raises(ValidationError):
        load_run_config(cfg)


def test_load_yaml_raises_on_misspelled_field_in_subsection(tmp_path: Path) -> None:
    """Typo guard: ``engien`` vs ``engine`` must not silently get dropped."""
    cfg = _write_yaml(
        tmp_path,
        """\
        ocr:
          engien: docling
        llm:
          prompt_template_path: /tmp/prompt.txt
        paths:
          domain_model_path: /tmp/schema.json
        """,
    )

    with pytest.raises(ValidationError):
        load_run_config(cfg)


def test_load_run_config_raises_when_file_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"

    with pytest.raises(FileNotFoundError):
        load_run_config(missing)


def test_load_yaml_rejects_retry_on_code_that_is_not_a_known_error_code(
    tmp_path: Path,
) -> None:
    """retry_on entries must mirror ExtractionError.code values; typos raise at boot."""
    cfg = _write_yaml(
        tmp_path,
        """\
        llm:
          prompt_template_path: /tmp/prompt.txt
        retry:
          retry_on:
            - llm_faild
        paths:
          domain_model_path: /tmp/schema.json
        """,
    )

    with pytest.raises(ValidationError):
        load_run_config(cfg)


def test_load_yaml_accepts_all_documented_retry_codes(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path,
        """\
        llm:
          prompt_template_path: /tmp/prompt.txt
        retry:
          retry_on:
            - ocr_engine_failed
            - ocr_empty_output
            - llm_failed
            - context_overflow
            - schema_invalid
        paths:
          domain_model_path: /tmp/schema.json
        """,
    )

    run_config = load_run_config(cfg)

    assert run_config.retry.retry_on == [
        "ocr_engine_failed",
        "ocr_empty_output",
        "llm_failed",
        "context_overflow",
        "schema_invalid",
    ]
