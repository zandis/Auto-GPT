# D-1064 A benchmark pair whose own labels contradict each other is set aside and listed, never relabelled

- **Task:** the integrator's ruling on lane H's question (PR #639, 2026-11-17, card H-4)
- **Date:** 2026-11-17
- **Status:** accepted

## Ruling

1. Where a public benchmark's pair label conflicts with the same physicians' criterion labels for that pair, answer
   key v2 marks the pair `conflicted`. It is not relabelled.
2. The target "no eligible patient excluded" is read on key v2 without the conflicted pairs. Every report prints,
   beside that figure, the figure on the key as published and the conflicted pairs by id with the reason.
3. On launch P1b's artefacts the conflicted pairs are `sigir-201413` with `NCT00163709` and `sigir-20142` with
   `NCT00711399`.
4. A target is met only by a launch. The offline replay's cause-level figures decide whether a launch is worth its
   cost; they are never quoted as a result.

## Where the wording comes from

The integrator's reply to lane H of 2026-11-17.

## Used by

`tools/public_accuracy/replay.py` and the answer key v2 (D-1104, D-1111, D-1112); the confirming launch.
