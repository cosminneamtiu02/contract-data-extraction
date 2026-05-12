"""Smoke tests for the extraction_service package layout.

These assertions are intentionally tautological — they verify only that the
package installs cleanly and that the `extraction-service` entry point is
callable. They remain as package-layout sentinels: the real
behavior-asserting test suite for Phase 1 lives under ``tests/unit/`` (see
docs/plan.md §6.3 task rows 1.1-1.9). Phases 2+ extend the unit suite under
``tests/`` subdirectories (ocr/, pipeline/, http/) without growing the
smoke set.
"""


def test_extraction_service_is_importable() -> None:
    import extraction_service

    assert extraction_service.__name__ == "extraction_service"


def test_extraction_service_main_entrypoint_is_callable() -> None:
    from extraction_service.__main__ import main

    assert callable(main)
