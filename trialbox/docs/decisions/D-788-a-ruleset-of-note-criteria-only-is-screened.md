# D-788 A ruleset of note criteria only is screened

- **Task:** A-NOTES-ONLY (lane G's dry run of public sets, defect 4, #593 2026-11-14)
- **PR:** see the REGISTRY row
- **Date:** 2026-11-15
- **Status:** reserved
- **Builds on:** D-103 (the SCREEN cascade)

## Decision

The cascade no longer refuses a ruleset with no coded (structured or mixed) criterion at S1. The generated SQL
still lists each in-scope patient alive at each index date; every such patient passes S1 at its latest index date,
and the note criteria decide, as they do for a patient the coded criteria let through. Removing the coded criteria
changes no note outcome of a patient they let through (the test compares the two runs on the synthetic fixture).

No decision or test had named the refusal; it came with the first cascade. A public protocol that compiles to note
criteria only was refused outright, which blocks such sets in R4.

## Not changed

The cost guards stay: the scale gate and `max_pairs` bound the judge calls of a protocol that sends every patient
to the note stage. FEAS still refuses a ruleset with no structured criterion: it counts coded criteria only.

## Test

`tests/unit/test_notes_only_ruleset.py`.
