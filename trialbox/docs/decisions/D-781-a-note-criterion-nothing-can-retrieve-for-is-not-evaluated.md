# D-781 A SCREEN note criterion nothing can retrieve for is "not evaluated", and the run says so

- **Task:** NEW-LLM-2, first step (deep review 2026-11-12, LLM-002)
- **PR:** #582 (merged with train 15)
- **Date:** 2026-11-14
- **Status:** merged
- **Builds on:** D-103 (the SCREEN cascade), D-449 (stored vectors for S2b)

## Decision

SCREEN sets `CascadeConfig.require_retrieval`. A note criterion with no lexicon term, no semantic embedder (none, or
the hash stub) and no stored vectors is unknown at S2 with the reason "not evaluated" (`Reason.NOT_EVALUATED`) and is
never sent to S2b or the judge: the patient goes to review, never out, never "high". `CascadeMetrics.no_retrieval`
counts the pairs per criterion in the run manifest and the screen summary. Before, the models read the first five
sentences of each note, and an exclusion stated further down could read "not present" with nothing left out. The
scale gate and the tools do not set the flag and keep their behaviour.

On the shipped rulesets with the hash embedder, AD-MAB's 4 and RA-JAK's 2 note criteria are "not evaluated" in
SCREEN; no other ruleset is affected. The goldens did not change.

## Not changed

The compile-time lexicon in the site's language (step 2) and SCREEN's use of the box's embed service (D-783) are later
steps. The weekly re-check's v1 evaluator has no such gate yet.

## Test

`tests/unit/test_no_retrieval_is_said.py`.
