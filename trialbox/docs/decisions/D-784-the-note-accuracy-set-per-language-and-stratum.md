# D-784 The note accuracy set per language and stratum, scored per model and for the pair

- **Task:** NEW-LLM-6, step 1 (deep review 2026-11-12, LLM-006 and LLM-009)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-14
- **Status:** reserved
- **Builds on:** D-117 (the pair canary), D-478 (the pair decides only when both models agree), D-479 (one excerpt builder)

## Decision

The go-live evidence for note answers is `tools/accuracy_set.py`'s set, run through the box's gateway, and no longer
the canary or one template study.

- **The set.** Per language (ja, zh-TW, en) and stratum, from seed 20261114: at least 200 gold exclusions and 200
  decided gold non-exclusions (plan 37, "NEW-LLM-6 gold"; 8,723 cases), over 15 criterion types (7 conditions, 4
  dated events, 4 lab thresholds; inclusion and exclusion). The strata are `plain`, `long` (one note longer than the
  whole excerpt budget, in lines of one to three sentences, cut by `matching.excerpts.build` around the line the
  retrieval would hit: the judge given a retrieval hit), `negation`, `family` (a relative's condition alone is gold
  `unknown`), `era` (和暦 in ja, 民國 in zh-TW), `window` (events at least 15 days from the window's edge, in a note of
  the index date) and `lab` (the threshold itself included). Routine sentences that would contradict a criterion are
  left out of its cases. Criteria and note questions are in English, as the compiler writes them;
  notes are in the site's language. It is regenerated and pinned by `eval/accuracy/MANIFEST.json` (seed, size,
  sha256, counts); it is not committed.
- **A wrong exclusion.** An answer that makes the patient ineligible when the gold answer does not: "met" on an
  exclusion criterion, or "not met" on an inclusion criterion, where the gold is the other answer or `unknown`. An
  `unknown` answer is never one: it goes to review.
- **The report.** Per model, for the pair (`tb_common.pair.combine`: floor, one-model check, verifier asked only
  for a decided judge answer) and for the product (the pair under the rule of a cut record, D-276): accuracy with a Wilson interval per language and stratum; wrong and
  missed exclusions with the exact (Clopper–Pearson) one-sided 95 % upper bound over the answered cases, and no bound
  for a cell with more than 10 % of its cases unanswered; per language a ten-bin confidence
  table of the decided answers with its expected calibration error; and, at the floors 0.5 to 0.9, the decided
  answers, the wrong ones, the wrong exclusions and the unknown rate.
- **Only the gateway counts.** `run` builds the judge and the verifier as the orchestrator does, with the gateway's
  swap and release on one GPU, and asks each case as the canary does (`judge` prompt, product parser), keeping the
  confidence and who answered (served name and build). The runs are lane G's (plan 37); lane A2 supplies the gold
  and reviews the calibration table.

## Changes

- 2026-11-15: the set's sha256 moved with D-786 (the excerpt builder splits English sentences); its counts did not.

## Not changed

The canary and its gate (`orchestrator.selftest`) are unchanged. Labels for MedTxt-CR (real Japanese case reports),
notes from a clinician-style generator that is not a template, and paraphrased injection (LLM-011) are later steps of
NEW-LLM-6. No confidence floor is set here: the report gives the numbers a floor is chosen from (NEW-LLM-9).

## Test

`tests/unit/test_accuracy_set.py`.
