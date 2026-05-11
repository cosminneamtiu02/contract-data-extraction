"""Smoke tests for the extraction_service package layout.

These assertions are intentionally tautological at this phase — they verify
only that the package installs and that the entry point is callable. Real
behavior-asserting tests land alongside the production code starting in
Phase 1 (see docs/plan.md §6.3).
"""


def test_extraction_service_is_importable() -> None:
    import extraction_service

    assert extraction_service.__name__ == "extraction_service"


def test_extraction_service_main_entrypoint_is_callable() -> None:
    from extraction_service.__main__ import main

    assert callable(main)
