# D-1075 A note that may speak against a criterion is said so, and those rows come last of their day

- **Task:** card INT-S-B (the page card of D-1072)
- **Date:** 2026-11-25
- **Status:** accepted (the owner's ruling of 2026-11-25: the record conflicts, the investigator decides, notes never exclude)

## Ruling

1. A patient whose note reading speaks against a criterion stays on the list. The investigator's page and the
   workbook print that criterion as "A note may speak against [criterion]. Not excluded. Please check." with every
   verified quote and its date, where they printed "unknown" with the reason `not_final`. The three languages of the
   console have the same sentence (`note.against` in `i18n_review.py`; the workbook reads the same table,
   `tb_common.verdict_word.NOTE_AGAINST`, in the report's language).
2. On the stored list, the weekly list and the run page, those review rows come last among the review rows of the
   same appointment day, and nowhere else: no other row moves, none is hidden or dropped, and who is on the list is
   what it was (`verdict_word.flagged_last`; the property test enumerates it).
3. A header line counts the patients: on the run page, on the weekly list, and in the workbook (below the table, so
   the table's header row and its rows keep their places).
4. The words say the patient is not excluded. `Not excluded.`, `None is excluded.`, `除外していません` and `未排除` are
   added to the wording lint's allowed phrases (`tb_common.wording.ALLOWED`): each denies the verdict that the lint's
   forbidden words (`excluded`, 除外, 排除) stand for, so the owner's sentence passes the lint as written. The
   forbidden list is not changed.

## What it changes in earlier records

Nothing in a status: the rows, tiers and `final`/`basis` fields are as D-1072 stores them. It reads the existing test
`tb_common.verdict_word.held_back(...) == "not_final"`. The CASE sheet and the NAV workbook are not changed by this card.
