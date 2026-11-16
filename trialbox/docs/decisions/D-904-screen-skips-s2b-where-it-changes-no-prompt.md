# D-904 SCREEN skips S2b where it changes no prompt

- **Task:** lane G's review of note processing (#639, 2026-11-15), card 1; **Date:** 2026-11-15; **Status:** reserved
- **Decision:** with `CascadeConfig.s2b_when_fits` False (SCREEN's setting), a zero-hit pair the judge reads anyway (no absence semantics, not the index sweep) goes to the judge without S2b when every note of its window with text fits the excerpt budget: the builder then shows every note in full by date, so the ranking would change nothing the models read. The prompts are byte for byte the same; the embedding (about 600 to 900 s of a 1,275 s job on the box) is not done. S2b still runs when the window does not fit, for the index sweep (its score decides a rescue) and wherever absence semantics hold. `metrics.s2b_skipped_fit` counts the pairs; the in-run judge cache keys such a pair by all its window sentences.
- **Test:** `tests/unit/test_s2b_skipped_when_the_window_fits.py`.
