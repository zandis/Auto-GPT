# Synthetic fixtures of tools/public_accuracy

Written by hand for the unit tests (`tests/unit/test_public_accuracy.py`). Every patient, trial, protocol number and
sentence here is made up; none is copied from TREC, SIGIR, the Taiwan FDA list, jRCT or Chia. The files only have the
shapes of those sources (qrels lines, topic XML, the TFDA CSV columns, a jRCT page cell, a Chia brat pair).

`p1b_sigir_outcomes.json` is the exception: it is made from launch P1b's stored `answers.json` of the SIGIR 2016 set
(run `box-20261116T074927Z-3b2f5e38`; the SIGIR 2016 collection is CC BY-SA 4.0, Koopman and Zuccon, CSIRO, as
redistributed by NCBI TrialGPT: see `eval/criterion_ml/NOTICE.md`). It keeps
only each protocol's stored job states, errors and outcome (the box's own messages); the ruleset ids are renamed
`SP001` to `SP103` and NCT numbers removed. No patient, draft or verdict is in it. Used by
`tests/unit/test_h3_scorer_2026_11_17.py` (card H-3).
