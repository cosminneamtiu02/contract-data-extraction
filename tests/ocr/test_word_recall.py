"""Unit tests for the word_recall metric function in tests/ocr/_metrics.py.

These tests pin the contract of the word_recall metric that underpins every
slow real-OCR baseline-comparison test in test_docling_engine.py.  Without
them, the empty-baseline sentinel (a non-obvious edge case: empty baseline
→ return 1.0, treated as "trivially perfect" so the assertion passes
regardless of OCR output) could silently flip from 1.0 to 0.0 if a future
contributor decides "empty baseline = unknown = zero recall" reads more
naturally — and every slow OCR test in the suite would silently change from
passing to failing.
"""

from __future__ import annotations

from ._metrics import word_recall


def test_word_recall_returns_one_for_empty_baseline() -> None:
    """Empty baseline string returns 1.0 (the empty-baseline sentinel).

    The docstring documents this as "nothing to recall against → trivially
    perfect".  The sentinel exists so callers can safely pass an empty
    baseline (e.g., when no ground-truth file exists yet) without the
    comparison test failing spuriously.
    """
    assert word_recall("", "any ocr output") == 1.0


def test_word_recall_is_case_insensitive() -> None:
    """Comparison is case-insensitive: upper- and lower-case of the same word match."""
    assert word_recall("Mietvertrag Vereinbarung", "mietvertrag VEREINBARUNG") == 1.0


def test_word_recall_filters_short_words() -> None:
    """Words shorter than min_word_len (default 4) are ignored in both baseline and output.

    German conjunctions / prepositions (und, der, die, das) have 3 or fewer
    characters and carry no diagnostic value for OCR quality.  They must not
    count toward the denominator.
    """
    # "und" (3), "der" (3), "die" (3), "das" (3) — all below threshold
    # "Mietvertrag" (11) — above threshold, present in OCR output
    assert word_recall("und der die das Mietvertrag", "Mietvertrag") == 1.0


def test_word_recall_returns_zero_when_no_overlap() -> None:
    """All baseline long-words missing from OCR output → recall 0.0."""
    assert word_recall("Grundschuld Gläubiger", "unrelated content here") == 0.0


def test_word_recall_returns_partial_ratio_for_partial_overlap() -> None:
    """2 out of 4 baseline long-words present in OCR output → recall 0.5."""
    result = word_recall(
        "Mietvertrag Vereinbarung Hauskredit Wuestenrot",
        "Mietvertrag Vereinbarung",
    )
    assert result == 0.5


def test_word_recall_respects_custom_min_word_len() -> None:
    """Custom min_word_len threshold changes which words count toward the denominator.

    With min_word_len=2, baseline_words = {"vertrag", "und", "der"} (3 words).
    OCR output contains "vertrag" and "und" but not "der".
    Expected recall = 2 / 3 ≈ 0.6667.
    """
    result = word_recall("Vertrag und der", "Vertrag und", min_word_len=2)
    assert abs(result - 2 / 3) < 1e-9


def test_word_recall_handles_unicode_diacritics() -> None:
    """German diacritics (ä, ö, ü) are preserved through the lowercase + regex pipeline.

    Python 3's \\w matches Unicode word characters by default, so umlaut
    letters are treated as ordinary word characters rather than being stripped.
    This is the property that makes the metric work on German contract text.
    """
    assert word_recall("Gläubiger Übersicht", "gläubiger übersicht") == 1.0
