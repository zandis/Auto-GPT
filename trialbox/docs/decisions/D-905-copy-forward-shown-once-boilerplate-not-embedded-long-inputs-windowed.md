# D-905 A copied-forward note is shown once; boilerplate is not embedded; a long input is windowed

- **Task:** lane G's review of note processing (#639, 2026-11-15), card 3 (and item 2's windows); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** (1) the excerpt builder shows a note whose text equals a newer window note's (whitespace aside) once, as the newest copy; the older copies are neither shown nor counted as left out (`ExcerptSet.duplicates`), and an evidence sentence of a dropped copy is the kept copy's. (2) S2b does not embed a sentence that recurs in at least three notes of the window (a template line, a disclaimer); the judge still reads it. When every sentence is such, all are embedded. (3) S2b embeds a sentence longer than 500 characters as overlapping windows (100 characters overlap) and scores it by its best window, so the end of a long report is scored though the service cuts an input at its token cap (D-900).
- **Not here:** partial copy-forward (a note that repeats an older one and adds lines).
- **Test:** `tests/unit/test_copy_forward_and_boilerplate.py`.
