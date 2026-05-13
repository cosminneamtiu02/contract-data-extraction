"""Tests for the prompt template renderer (plan §6.5 task 3.2).

``PromptTemplate`` reads a template file from disk exactly once at construction
time and exposes a ``render`` method that substitutes two placeholders:

- ``{ocr_text}`` — the raw OCR-extracted contract text.
- ``{schema_json}`` — ``json.dumps(domain_schema, indent=2)`` so the LLM sees
  readable JSON.

Because the implementation uses Python's ``str.format``, template authors MUST
escape literal curly braces (e.g., JSON example blocks) as ``{{`` and ``}}``
-- otherwise ``str.format`` will raise ``KeyError`` at render time.
"""

import json
from pathlib import Path


def test_prompt_renders_with_ocr_text_and_schema(tmp_path: Path) -> None:
    from extraction_service.llm.prompt import PromptTemplate

    template_path = tmp_path / "test_template.txt"
    template_path.write_text("OCR text: {ocr_text}\nSchema:\n{schema_json}", encoding="utf-8")
    pt = PromptTemplate(template_path)
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    result = pt.render(ocr_text="contract body", domain_schema=schema)

    assert result == f"OCR text: contract body\nSchema:\n{json.dumps(schema, indent=2)}"


def test_prompt_substitutes_ocr_text(tmp_path: Path) -> None:
    from extraction_service.llm.prompt import PromptTemplate

    template_path = tmp_path / "tmpl.txt"
    template_path.write_text("TEXT={ocr_text}", encoding="utf-8")
    pt = PromptTemplate(template_path)

    result = pt.render(ocr_text="hello contract", domain_schema={})

    assert "hello contract" in result


def test_prompt_substitutes_schema_json(tmp_path: Path) -> None:
    from extraction_service.llm.prompt import PromptTemplate

    template_path = tmp_path / "tmpl.txt"
    template_path.write_text("SCHEMA={schema_json}", encoding="utf-8")
    pt = PromptTemplate(template_path)
    schema = {"key": "value"}

    result = pt.render(ocr_text="", domain_schema=schema)

    assert json.dumps(schema, indent=2) in result


def test_prompt_renders_schema_as_pretty_json(tmp_path: Path) -> None:
    from extraction_service.llm.prompt import PromptTemplate

    template_path = tmp_path / "tmpl.txt"
    template_path.write_text("{schema_json}", encoding="utf-8")
    pt = PromptTemplate(template_path)
    schema = {"a": 1, "b": [2, 3]}

    result = pt.render(ocr_text="", domain_schema=schema)

    assert result == json.dumps(schema, indent=2)


def test_prompt_template_loaded_once_not_on_every_render(tmp_path: Path) -> None:
    """Template content is captured at construction; later disk mutations do not
    affect subsequent ``render`` calls."""
    from extraction_service.llm.prompt import PromptTemplate

    template_path = tmp_path / "tmpl.txt"
    template_path.write_text("first: {ocr_text}", encoding="utf-8")
    pt = PromptTemplate(template_path)

    # Mutate the file on disk after construction.
    template_path.write_text("second: {ocr_text}", encoding="utf-8")
    result = pt.render(ocr_text="x", domain_schema={})

    assert result.startswith("first:")


def test_missing_template_file_raises_file_not_found_error(tmp_path: Path) -> None:
    import pytest

    from extraction_service.llm.prompt import PromptTemplate

    with pytest.raises(FileNotFoundError):
        PromptTemplate(tmp_path / "nonexistent.txt")


def test_prompt_handles_escaped_braces_in_template(tmp_path: Path) -> None:
    """Template authors escape literal ``{`` / ``}`` as ``{{`` / ``}}`` so that
    JSON example blocks survive ``str.format`` without raising ``KeyError``."""
    from extraction_service.llm.prompt import PromptTemplate

    template_path = tmp_path / "tmpl.txt"
    # {{key}} renders as literal {key} in the output.
    template_path.write_text("Example: {{{{key}}}}\nOCR: {ocr_text}", encoding="utf-8")
    pt = PromptTemplate(template_path)

    result = pt.render(ocr_text="data", domain_schema={})

    assert "{{key}}" in result
