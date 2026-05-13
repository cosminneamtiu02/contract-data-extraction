"""Tests that pin FakeOcrEngine's contract against OcrEngine Protocol.

The most load-bearing test is `test_fake_ocr_engine_satisfies_ocr_engine_protocol`,
which asserts isinstance(FakeOcrEngine(), OcrEngine) returns True against the
@runtime_checkable Protocol. Without this, a signature drift in FakeOcrEngine.extract
(parameter rename, return type change, sync/async flip) would silently break the
Phase 4/5 dependency-injection seam before those phases exist to catch it.
"""

from __future__ import annotations

from extraction_service.ocr.base import OcrEngine
from tests.fakes.fake_ocr import FakeOcrEngine


def test_fake_ocr_engine_satisfies_ocr_engine_protocol() -> None:
    assert isinstance(FakeOcrEngine(), OcrEngine)


async def test_fake_ocr_engine_default_text() -> None:
    result = await FakeOcrEngine().extract(b"irrelevant")
    assert result.text == "fake ocr text"


async def test_fake_ocr_engine_configurable_text() -> None:
    result = await FakeOcrEngine(text="custom text").extract(b"irrelevant")
    assert result.text == "custom text"


async def test_fake_ocr_engine_configurable_page_count() -> None:
    result = await FakeOcrEngine(page_count=7).extract(b"irrelevant")
    assert result.page_count == 7


async def test_fake_ocr_engine_configurable_engine_name() -> None:
    result = await FakeOcrEngine(engine_name="custom").extract(b"irrelevant")
    assert result.engine_name == "custom"


async def test_fake_ocr_engine_ignores_pdf_bytes() -> None:
    engine = FakeOcrEngine(text="fixed")
    result_a = await engine.extract(b"payload-one")
    result_b = await engine.extract(b"completely-different-payload")
    assert result_a == result_b
