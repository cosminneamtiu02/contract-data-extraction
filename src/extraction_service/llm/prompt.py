"""Prompt template renderer for the LLM extraction stage (plan §6.5 task 3.2).

``PromptTemplate`` reads a UTF-8 text file from disk exactly once at
construction time and caches the raw template string. Subsequent calls to
``render`` substitute two named placeholders via ``str.format``:

- ``{ocr_text}`` — the OCR-extracted contract text passed in by the caller.
- ``{schema_json}`` — the domain schema serialised via ``json.dumps(...,
  indent=2)`` so the LLM receives readable JSON.

**Important:** Python's ``str.format`` interprets every ``{...}`` sequence as
a placeholder. Template files that include literal curly braces (for example,
JSON examples in few-shot sections) MUST escape them as ``{{`` and ``}}``.
For instance::

    Respond in JSON like this: {{{{\"field\": \"value\"}}}}

renders to::

    Respond in JSON like this: {{"field": "value"}}

**Error handling:** ``FileNotFoundError`` and ``OSError`` from
``Path.read_text`` are intentionally propagated to the caller — consistent
with the ``load_run_config`` convention in
:mod:`extraction_service.config.run_config`. No wrapping, no logging.
"""

import json
from pathlib import Path
from typing import Any


class PromptTemplate:
    """Reads a prompt template from disk once; renders it per-call.

    Parameters
    ----------
    path:
        Filesystem path to the UTF-8 template file. ``FileNotFoundError`` /
        ``OSError`` are propagated directly if the file cannot be read.
    """

    __slots__ = ("_template",)

    def __init__(self, path: Path) -> None:
        # Read once at construction — subsequent render() calls use the cached
        # string without any further I/O, keeping per-call latency predictable.
        self._template: str = path.read_text(encoding="utf-8")

    def render(self, *, ocr_text: str, domain_schema: dict[str, Any]) -> str:
        """Substitute ``{ocr_text}`` and ``{schema_json}`` in the template.

        Parameters
        ----------
        ocr_text:
            Raw text produced by the OCR stage.
        domain_schema:
            JSON-Schema-shaped dict describing the extraction target. Serialised
            to indented JSON internally; the caller does not need to pre-serialise
            it.

        Returns
        -------
        str
            The rendered prompt string ready to send to the LLM.
        """
        schema_json = json.dumps(domain_schema, indent=2)
        return self._template.format(ocr_text=ocr_text, schema_json=schema_json)
