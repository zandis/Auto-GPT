# D-1108 a set with nothing screened, or no verdict, is "not scored", with the reason; tcga scores the pathology figure

- **Task:** lane H, card H-3 (the scorer; launch P1b's tcga, #639 2026-11-16T11:18:56Z)
- **PR:** this branch (`claude/lane-h-3-scorer`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** Gate C of 2026-11-15 (a set that answered nobody has no figure, never a 0 %)

## Context

Launch P1b's tcga was "not scored" because the protocol filter named `G2TCGA-BRCA` while the set's ids carry the
tag (`Gm2TCGA-BRCA`). The scorer's only rule was "no gold row answered". It had no figure of its own for the
pathology set. PoC-1's claim on b266f9b7 is: "on 500 public pathology reports the pair excluded 384 of 450, with 0
wrong exclusions, and lost 0 of 50 eligible patients". That is the pair level over the one protocol screened (BRCA,
500 reports: 50 eligible, 450 not).

## Decision

1. A set is "not scored", with the reason in `not_scored_because`, never passed and never left out, when: its
   `answers.json` is missing ("the set did not run"); none of its protocols screened ("0 of N protocols screened",
   with the count per status); or SCREEN answered patients but gave no verdict and excluded none. The Gate C rule
   (no gold row answered) stays.
2. tcga's score has a `pathology` block, always present. Over the protocols screened, it gives `reports` (distinct
   reports answered), `ineligible_excluded` (n of N gold-ineligible pairs), `wrong_exclusions` (k of the box's
   exclusions) and `eligible_lost` (n of N gold-eligible pairs), each with its exact interval, and the sentence of the
   PoC-1 figure. Not scored, it says why. A run whose answers name rulesets the set does not have says so (a wrong
   prefix or tag).

## Test

`tests/unit/test_h3_scorer_2026_11_17.py`: a two-protocol tcga set built with the tag `m2` scores the three
numbers; the PoC-1 counts give the PoC-1 sentence word for word; answers under `G2TCGA-BRCA` are "0 of 2 protocols
screened" and name the stray id; no `answers.json`, or no verdict, is "not scored".
