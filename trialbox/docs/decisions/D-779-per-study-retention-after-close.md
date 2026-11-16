# D-779 A closed study's files are kept for its own period after the close

- **Task:** NEW-LIFE-10 / T-305c, the second half that D-765 left open (LIFE-009, old LIFE-027); the code-complete sprint, item 3 · **Date:** 2026-11-15
- **The period:** the close form asks for the years to keep the study's files after the close: 1 to 30, prefilled with `STUDY_YEARS_AFTER_CLOSE` (5; Japan's 臨床研究法施行規則 keeps records five years from a study's end, and a sponsor's contract may ask more). The years are stored on the close row (`site.study_state.keep_years`, added by an additive migration) and audited; the state page says until when.
- **RETENTION:** a closed study's attachments, outputs, pool and marks are held until the close day plus its period. A close recorded before this change keeps the default; a close that cannot be read is held. After the period, the configured ages apply. The night's report counts `held_after_close`.
- **Unchanged:** D-765's hold while the study runs; "no recorded state" is not a study; ClinicalTrials.gov's cache and jobs of no study keep their ages.
- **Held by:** `tests/unit/test_per_study_retention_after_close.py`. D-765's pinned `test_a_closed_study_goes_by_the_ages_again` now closes the study in 2015, past the period. This is a deliberate move.
