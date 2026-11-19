# D-1326 Every accuracy report names its gold kind and never pools kinds (10G-38)

- **Task:** lane H, plan 10 row 10G-38 (review 20, item 20-15): every accuracy report names its gold kind and never
  pools them. · **Date:** 2026-11-19
- **Decision:**
  - Five gold kinds, the only values of a report's `gold_kind`: `physician`, `generated and checked`, `translated`,
    `structured truth`, `enrolment` (review 20 item 20-15 and §7.1). `None` where the repository's documents do not
    state the kind of a set: never guessed (the card's page lists them as open questions).
  - The kind of each set is written in one place, `tools/gold_kind.py`, with where the repository says it: MedTxt ja
    physician and MedTxt en translated; criterion_ml en physician and its ja, zh-TW and mixed renderings translated;
    SIGIR physician; JMED-Personas structured truth. TREC (2021 to 2023), TCGA, Chia, TFDA, jRCT, the notes-only sets
    and `eval/accuracy` are not stated.
  - The writers name it: `tools/public_accuracy` `score.json` (per set), `tools/medtxt_eval.py` (per language row),
    `tools/open_cohorts_eval.py` (per cohort), `tools/trec_ct_eval.py`, `tools/ad_eval.py` (its TREC part) and
    `tools/accuracy_set.py` reports.
  - A figure over more than one part needs every part to be of one stated kind. Otherwise the pooled figure is
    refused (`gold_kind.PoolingRefused`, the message names each part and its kind): in the replay's target 1
    (`tools/public_accuracy/replay.py` `figure`) the pooled numerator and denominator are None with `pooled_refused`,
    the per-set figures stand, and `by_gold_kind` sums only the sets of one stated kind. `within_target` (no set
    excluded an eligible patient) reads set by set and is unchanged.
  - Stored reports are not rewritten. A report without the field (all stored before this card) is read as
    `not stated` and never pooled.
- **Not decided here:** the kinds the documents leave open (the card's page); the ladder's "all sets" rows
  (`tools/public_accuracy/ladder.py`) are the decided share of cells, not a figure against gold, and are unchanged.
- **Held by:** `tests/unit/test_gold_kinds_never_pool.py`.
