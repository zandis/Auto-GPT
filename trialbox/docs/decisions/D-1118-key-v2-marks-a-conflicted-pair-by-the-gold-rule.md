# D-1118 key v2 marks a conflicted pair by the rule read from the gold, and an exclusion on another line is a finding

- **Task:** lane H, card H-6 (D-1064 in the key, the scorer and the replay; the integrator's ruling on lane H's
  question, PR #639, 2026-11-17 05:56 UTC: "all 6, by the gold rule")
- **PR:** this branch (`claude/lane-h-6-conflicted-pairs`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1064 (a pair whose own labels contradict each other is set aside and listed), D-1104 (the answer
  key's versions), D-1107 (the scorer's S1), D-1117 (the replay meets no target)

## Context

D-1064 has key v2 mark `conflicted` a pair whose label conflicts with the same physicians' criterion labels, and the
target read without those pairs. On launch P1b's sigir gold, the rule taken from the gold marks 6 eligible pairs. D-1064's
item 3 named 2, the ones the replay showed. The integrator ruled that the mark must be a property of the key, the
same for every run, so all 6 are marked. As a guard, a box that excludes a conflicted pair on a line the physicians did
not label as excluding is a finding to trace, not set aside silently.

## Decision

1. **The rule** (`tools/public_accuracy/key.py`: `conflicted`, `criterion_says_excluded`, `EXCLUDING`). A pair is
   conflicted when its label is `eligible` and the same physicians' criterion labels for that patient in that trial
   exclude the patient: an inclusion `not included` or an exclusion `excluded`. The scorer's S1 uses the same
   definition (`score.criterion_says_excluded` and `score.BLOCK_RIGHT` are the key's). Only eligible pairs are
   marked. "Would consider" does not claim every criterion met, so an excluding label does not contradict it, and the
   target reads eligible pairs only. On P1b's sigir gold, 10 such "would consider" pairs stay unmarked.
2. **Where the mark lives.** A v2 build writes `gold/conflicted.json`, a new file, so key v1 keeps its bytes and its
   pinned hashes; v1 marks nothing. A folder that states v2 without the file has the marks computed by the same rule.
   The replay's offline v2 of a stored v1 gold writes the file by the rule and checks it against MANIFEST.json's list
   for the run. MANIFEST.json lists P1b's 6 marks under v2, each with the reason D-1064. `key-diff` lists a mark as a
   v1 to v2 difference: `eligible` becomes `eligible, conflicted`, never another label.
3. **The scorer** (schema 3). Per language it adds `eligible_lost_without_conflicted`, the target's reading, and
   `conflicted_pairs`; `eligible_lost` stays the figure on the key as published. It also adds `pairs.conflicted`, each
   marked pair by id with:
   - the criterion labels that exclude it;
   - the box's answer (excluded, review, included or not answered);
   - the lines it blocked on or left open on.

   `pairs.conflicted_excluded_on_another_line` lists the marked pairs the box excluded on a line that those labels
   do not exclude on: same text, or both about age, as S1 matches. The driver's score summary carries both lists.
4. **The replay.** On key v2, the eligible target's numerator and denominator are read without the conflicted pairs.
   `with_conflicted` gives the figure with them, and `conflicted` and `conflicted_excluded_on_another_line` are given
   per set and summed. The printout lists each conflicted pair with the box's answer at each level, and then
   "Findings to trace" per level.

## On launch P1b

| Key v2 | Level (a) | Level (b) |
| --- | --- | --- |
| Without the conflicted pairs (the target's reading) | 6 of 350 | 0 of 350 |
| With them (as published) | 9 of 356 | 2 of 356 |

The 6 are sigir-201410 x NCT02097186, sigir-201413 x NCT00163709, sigir-201418 x NCT01260883, sigir-20142 x
NCT00711399, sigir-201425 x NCT00282269 and sigir-201429 x NCT00703417. There is one finding to trace, at level (a):
sigir-201418 x NCT01260883, excluded on the placed age line "Aged 0.17 years or older" (B1, B2), not on the renal line
its labels exclude on.

## Test

`tests/unit/test_h6_conflicted_pairs_2026_11_17.py` covers:
- the rule on synthetic pairs;
- the shared definition;
- the P1b slice's mark;
- the manifest's 6;
- a v2 build writing the marks while v1 writes none;
- the marks computed when the file is absent;
- `key-diff`'s row;
- the scorer's figures, list and finding;
- the driver's summary.

`tests/unit/test_h4_replay_2026_11_17.py` checks the slice's conflicted pair and its finding at level (a), and its
review at (b). `tests/unit/test_h2_answer_key_versions.py` still pins key v1's bytes.
