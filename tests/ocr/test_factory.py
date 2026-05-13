"""Tests for the OCR engine factory (plan §6.4 task 2.7).

The factory dispatches on ``run_config.ocr.engine`` (a closed ``Literal["docling"]``
today) and returns the matching ``OcrEngine`` implementation. Because the engine
field is a 1-arm closed Literal, there is no runtime ``raise on unknown`` path —
mypy proves exhaustiveness statically. When Phase 3+ adds a second engine value
to the Literal, the factory's ``match`` will fail to type-check until a new arm
lands, which is the right "you forgot the factory" hint.

The construct test stubs ``_build_default_converter`` via monkeypatch so the
heavyweight ``modelscope.snapshot_download`` does not run.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_factory_returns_docling_for_docling_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "extraction_service.ocr.docling_engine._build_default_converter",
        lambda _cfg: MagicMock(),
    )

    from extraction_service.config.run_config import (
        LlmConfig,
        OcrConfig,
        PathsConfig,
        RunConfig,
    )
    from extraction_service.ocr.docling_engine import DoclingOcrEngine
    from extraction_service.ocr.factory import build_ocr_engine

    run_config = RunConfig(
        ocr=OcrConfig(),
        llm=LlmConfig(prompt_template_path=Path("/prompt.txt"), timeout_seconds=60),
        paths=PathsConfig(domain_model_path=Path("/domain.json")),
    )

    engine = build_ocr_engine(run_config)

    assert isinstance(engine, DoclingOcrEngine)
