# D-868 The reveal ledger and the not-matched sample keep their rows, not the patient (ERASE-C)

- **Task:** ERASE-C, lane C2's backlog after the PoC freeze. Two owed stores whose rows count for something: the adversarial review of D-798 kept them out of a plain delete. · **Date:** 2026-11-16
- **Decision:** at an opt-out the opt-out worker's `owed_tables` clear keeps each row and replaces its pseudonym with a random `erased:` token:
  - `team.candidate_views`, the reveal cap's ledger. The cap counts a person's rows, and each row says who saw an identity and when; both still hold. The patient's own disclosure report reads the audit log (D-771), not this table.
  - `tuned.tuned_patients`, the PI's weekly sample of patients not matched. A reviewed week is never drawn again while it has rows, so its size stays. The not-matched page counts an `erased:` row as removed, as it already did for an opted-out pseudonym, and the answer path refuses it (the pseudonym pattern).
- **The adversarial review (mostly SOUND):** a sample row also held the PI's free-text note, which the audit log can link back to the patient; the note goes with the pseudonym. The token unlinks the row in its own table only: the kept audit log still holds the link (D-771), on purpose. The study's totals on the not-matched page still count an erased row, as they counted an opted-out patient's row before.
- **Why:** the registry asked for "a clear that keeps both" (the cap and who saw) and "a clear that does not redraw a reviewed week's sample". The owed list goes from 49 to 47 on master (this card alone).
- **Moved tests:** `tests/unit/test_optout_clears_the_owed_tables.py` held these two as never touched (`KEPT_OWED`). They move to `TOKENIZED`: the row stays, the patient is not in it.
- **Held by:** `tests/unit/test_the_views_and_the_sample_keep_their_counts.py`, synthetic data only (failing output on master kept: `erasec-fail.txt`).
