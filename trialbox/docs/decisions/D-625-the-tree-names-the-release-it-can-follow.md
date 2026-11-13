# D-625 A release's tree names the oldest release it can be applied over, and signing holds it to that

- **Task:** UPDATE-MINSEQ (from lane C2's review of #390 on top of #433, 2026-11-13)
- **PR:** this branch (`agent/UPDATE-MINSEQ-the-tree-names-its-floor`), on top of #433
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-210 (`release_seq` and `min_installed_version` in the bundle manifest), D-620 and D-624 (a
  release's own steps, `pre-start` and `db-up`)

## Context

D-620 and D-624 both end with the same sentence: a release that adds a step names, as its
`min_installed_version`, a release that has the command, so that an older box is refused before anything
changes. Nothing held a release to it. `tools/sign_bundle.py` takes `--min-installed` from the person who signs,
with 0 as the default, and the tree that needs the floor has no way to say so. A box on a release with
`pre-start` and without `db-up` would take such a bundle, run its own older commands, and fail at a health
check and roll back, where it should have been refused first.

## Decision

1. `tools/trialbox/prestart.py` holds `MIN_INSTALLED_SEQ`: the lowest `release_seq` a box may be at to take this
   tree by update. It is 0 until a release has reached a box; no box has one on 2026-11-13.
2. Signing reads it from the bundle's own payload. `sign_bundle.build` opens each payload of kind `host`, reads
   `tools/trialbox/prestart.py` in it, and refuses to sign when the bundle's `min_installed_version` is below the
   tree's `MIN_INSTALLED_SEQ`. A host tree without the file, or without the name, asks for nothing. A value it
   cannot read is refused.
3. One test pins the names of the steps in `STEPS` and `DB_STEPS` together with `MIN_INSTALLED_SEQ`. A card that
   adds, removes or renames a step fails it and reads there what to decide: whether a box in the field could be
   on a release without that step's command, and if so which `release_seq` first had it.

## Consequences

- The floor travels with the code that needs it; the person who signs cannot forget it, and can still set a
  higher one.
- The first release that reaches a box needs no floor. The card after it that adds a step sets the number.
- The box's side is unchanged: the verifier and the updater already refuse a box below `min_installed_version`.
