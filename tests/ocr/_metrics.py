"""OCR-quality metric helpers used by the slow real-OCR baseline tests.

This module is intentionally test-private (``_`` prefix on the filename per
the project's private-module convention). The functions here are utilities,
not pytest fixtures or hooks — they were previously defined inside
``tests/ocr/conftest.py`` but the convention conftest.py reserves is
"fixtures + hooks", and a plain helper function in that file confuses the
intent. Callers import explicitly from this module instead.
"""

from __future__ import annotations

import re


def word_recall(baseline: str, ocr_output: str, min_word_len: int = 4) -> float:
    """Word-level recall: |baseline_words ∩ ocr_words| / |baseline_words|.

    Computes case-insensitive set intersection over words at least
    ``min_word_len`` characters long, which filters out conjunctions /
    prepositions (in German: ``und``, ``der``, ``die``, ``das``) whose
    presence/absence has no diagnostic value for OCR quality. Score in
    [0, 1]; 1.0 means every long word in the baseline appears somewhere in
    the OCR output.

    Choice of metric (rather than full equality or Levenshtein on full text):
    OCR routinely splits hyphenated words at line breaks, merges spaces, and
    occasionally swaps similar glyphs (l/I, 0/O); a per-line or per-character
    metric fails on cosmetic differences that aren't real OCR misses.
    Word-set recall is robust to those and gives a single number that's
    debuggable when it fails (the failure can name which baseline words are
    missing from the OCR output).
    """
    pattern = rf"\w{{{min_word_len},}}"
    baseline_words = set(re.findall(pattern, baseline.lower()))
    ocr_words = set(re.findall(pattern, ocr_output.lower()))
    if not baseline_words:
        return 1.0  # nothing to recall against → trivially perfect
    return len(baseline_words & ocr_words) / len(baseline_words)
