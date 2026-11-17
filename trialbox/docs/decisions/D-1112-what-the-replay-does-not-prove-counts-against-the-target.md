# D-1112 what the replay cannot show fixed counts against the target, and a set it has no verdicts for is never a pass

- **Task:** lane H, card H-4 (the offline replay of launch P1b)
- **PR:** this branch (`claude/lane-h-4-replay`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1111 (the replay's two levels), D-1107, D-1108

## Context

The replay answers part of each target. Saying "met" where it only knows a part would let an offline figure stand in
for the confirming launch.

## Decision

1. **Protocols failing (target 3).** At level (b) a failed protocol counts as no longer failing only when the step it
   failed at was re-run as far as it runs offline and the cause the review named is gone ("cause-level", said beside
   the figure). A protocol not re-run (no stored model reply, a time budget) or one that still fails counts as
   failing. Both shares are given, failed before or in SCREEN (the scorer's target, D-1107) and failed before SCREEN.
   A budget cut is not attempted.
2. **Eligible patients wrongly excluded (target 1).** The figure is given on both keys and both levels. Pair level is
   used where the set has eligibility labels; criterion level is used where it has none (JMED: a row "not excluded"
   that the box blocked). It is met only when nothing was wrongly excluded and something was answered.
3. **The pathology figure (target 2).** A run with no tcga set, or one the scorer cannot score, is "not scored" with
   the reason, and the target is not met. A run kept as counts only (PoC-1's `sets-<commit>.json`) is read back with
   `--pathology-run` and compared with the claim. It is labelled "read, not re-scored", since its answers and gold were
   not kept, and it does not decide the target.

## Test

`tests/unit/test_h4_replay_2026_11_17.py`: tcga absent is "not scored" and not met; the stored PoC-1 counts are read
and match the claim without being called a reproduction; a failure not re-run stays in the numerator;
`--require-targets` exits 3 on the fixture run.
