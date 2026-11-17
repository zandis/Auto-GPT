# D-1064 A benchmark pair whose own labels contradict each other is set aside and listed, never relabelled

- **Task:** the integrator's ruling on lane H's question (PR #639, 2026-11-17, card H-4)
- **Date:** 2026-11-17
- **Status:** accepted

## Ruling

1. Where a public benchmark's pair label conflicts with the same physicians' criterion labels for that pair, answer
   key v2 marks the pair `conflicted`. It is not relabelled.
2. The target "no eligible patient excluded" is read on key v2 without the conflicted pairs. Every report prints,
   beside that figure, the figure on the key as published and the conflicted pairs by id with the reason.
3. The mark is a property of the key, the same for every run: the scorer's own gold rule (an inclusion the
   physicians labelled "not included", or an exclusion they labelled "excluded", for that patient in that trial).
   On launch P1b's sigir gold it marks six pairs (lane H's table on PR #639, 2026-11-17), not only the two the
   replay first showed. For each conflicted pair the report also says what the box answered and on which
   criterion; a box that excludes one on a line the physicians did not label is a finding to trace.
4. A target is met only by a launch. The offline replay's cause-level figures decide whether a launch is worth its
   cost; they are never quoted as a result.

## Where the wording comes from

The integrator's reply to lane H of 2026-11-17.

## Used by

`tools/public_accuracy/replay.py` and the answer key v2 (D-1104, D-1111, D-1112); the confirming launch.
