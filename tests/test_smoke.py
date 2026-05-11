"""Smoke test for the extraction_service package layout."""


def test_extraction_service_is_importable() -> None:
    import extraction_service

    assert extraction_service.__name__ == "extraction_service"


def test_extraction_service_main_entrypoint_is_callable() -> None:
    from extraction_service.__main__ import main

    assert callable(main)
