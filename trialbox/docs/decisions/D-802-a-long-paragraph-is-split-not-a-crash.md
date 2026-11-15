# D-802 A paragraph longer than a page is split, never a crash

- **Task:** blocker 11 of lane G's dry run (the FEAS report PDF crashes on a long paragraph)
- **PR:** this branch (`agent/NEW-UX-2b-long-paragraph`), from master
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-687 (UX-002: the reports' glyph fallback, `reports.common.Paragraph`)

## Context

D-687 made every report paragraph go through `reports.common.Paragraph`, which wraps the text in the glyph fallback
(a character the main font lacks is drawn in the other family). reportlab splits a paragraph that does not fit the
frame by building the pieces through the paragraph's own class, with no text (the fragments are already laid out).
`with_fallback(None, ...)` failed (`'NoneType' object has no attribute 'isascii'`, `common.py:124`): any paragraph
longer than a page crashed the PDF. Lane G's dry run met it in the FEAS report. Shown by tests before the change.

## Decision

1. **Only a text is wrapped in the glyph fallback.** The pieces reportlab builds when it splits a paragraph carry
   their laid-out fragments, the fallback already in them, and are passed to reportlab as they are.

## Evidence

`tests/unit/test_report_long_paragraph.py`: a paragraph longer than a page, in English words, Japanese, Chinese and
mixed with characters only the fallback family has, is split over pages; the split pieces of a paragraph with a
fallback character. All five failed before the change (`common.py:124: AttributeError`). The existing glyph-fallback
tests of the three reports still pass.
