# D-1460 An update cut short after its check is finished forward, never rolled back (H-132)

- **Task:** lane H, card H-132 (the integrator's ruling 7136669077, item 2; finding LR-10 of
  `docs/reviews/lifecycle-deep-review-2026-11-24.md`) · **Date:** 2026-11-24
- **Status:** proposed (row reserved; the integrator flips it when merged)
- **Builds on:** H-114 (a signal after the check finishes the checked release), D-17 (a reference-data failure
  leaves the healthy release in place)

## Decision

1. The update records the checked release (`installed.json`, `trust.json`) as soon as its check passes, before the
   reference data (`tools/trialbox/update.py`, `Updater.run`).
2. An update interrupted in `refdata` or `finish` (a kill, a power cut, a stopped unit) is finished forward by the
   same command that recovers every other step, `tools/apply_update.sh rollback <bundle>`: the full health check
   (the box's `check`, then every service its compose defines, "N of M"), one audit `update.applied` with
   `recovered`, the clean-up of the marker and the rollback point. The pre-update dump is never restored over a
   release that has served since its restart. Every step of it may run again with the same end.
3. A shortfall or a failed check stops in the named state `finish forward failed`: the marker stays, the audit is
   `update.finish_failed`, the message names the services and the command that tries again. Nothing is rolled back.
4. An update interrupted before its check keeps the full rollback. The reference-data load is not run again by the
   recovery; the audit names `python -m tb_common.refdata load`, as a failed load after the check already did.

## Why

After the check the box is in service and the reference-data load may run for hours. Rolling back there dropped
both databases and restored the dump taken before the update: every row written since the restart was lost without
a word (LR-10). `tools/update_drill.py` case 7 asserted that outcome; its assertion for these two steps is changed
on the same ruling (old and new posted on #639).

## Tests

`tests/unit/test_lifecycle_data_loss_h132.py` (`test_lr10_*`); `tools/update_drill.py` case 7.
