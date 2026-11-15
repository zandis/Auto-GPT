# D-788 A ruleset of note criteria only is screened

- **Task:** A-NOTES-ONLY (lane G's dry run of public sets, defect 4, #593 2026-11-14)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-103 (the SCREEN cascade)

## Decision

The cascade no longer refuses a ruleset with no coded (structured or mixed) criterion at S1, when it has a note
inclusion or exclusion. The generated SQL lists each in-scope patient alive at each index date (with no trailing
comma when there is no criterion); every such patient passes S1 at its latest index date, and the note criteria
decide. In screening (one index date) removing the coded criteria changes no note outcome of a patient they let
through (the test compares the two runs on the synthetic fixture with a judge that gives decided answers). With
month-end index dates (FEAS-style runs) the latest month-end is used, so the note window can differ.

Guards (the review of this card):

- a ruleset where nothing decides (no coded and no note inclusion or exclusion: all human, or empty) is still
  refused; otherwise every patient read "high" with no evidence;
- such a run needs a pair budget (`max_pairs`, the cascade's `max_llm_items`): SCREEN's default is no budget, and
  every patient goes to the models;
- with nothing coded, a patient is "strong" only on a judged "met" (S3 or S4), never on absence alone.

No decision or test had named the refusal; it came with the first cascade. A public protocol that compiles to note
criteria only was refused outright, which blocks such sets in R4.

## Not changed

The scale gate (D-471) is a nightly test, not a guard at run time; the pair budget above is the run-time bound. FEAS
still refuses a ruleset with no structured criterion: it counts coded criteria only.

## Test

`tests/unit/test_notes_only_ruleset.py`.
