# D-570 The real installer is rehearsed: the box rehearsal runs again, and runs in CI

- **Task:** OPS-004 (TB-PLAN-07 v7.2, `docs/plan/33-plan-v7.md`, wave 1, lane D; finding OPS-004 of
  `docs/reviews/2026-11-12-deep-review/12-maintenance-operations.md`)
- **PR:** this branch (`agent/OPS-004-real-installer-rehearsal`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-176 and D-177 (the box-install rehearsal: the real `deploy/install.sh` in a clean Ubuntu
  container, stand-ins where the GPU would be), D-340 (no bundle without its release gates), D-367 (the host tree),
  D-566 (on a box the backup step is a FAIL line)
- **Read by:** every card that changes `deploy/install.sh`; lane G (what only a real card proves)

## Context

`make rehearse-box` is the one place the real installer runs end to end, and it is in no workflow. The deep review
found by reading that it could not pass. A run shows it stopped earlier than that, in its own preparation, and
said nothing: the rehearsal had rotted while the product moved.

## Decision

1. **The rehearsal is made to run again, one stop at a time, by running it.** Each stop is fixed where it is
   wrong: in the rehearsal when the rehearsal fell behind the product, in the product when the installer is wrong.
   The pull request lists every stop, in the order met.
2. **A step that fails stops the rehearsal by name.** `set -e` does not act inside a step (it runs in an `if`), so
   a failed pull or a bundle that was not built is checked explicitly.
3. **The release record matches a saved image on either Docker image store.** The gates name an image by Docker's
   image id: the config digest on the classic store, the index digest on the containerd store. A `docker save`
   archive holding one image is known by its config digest and by the digests of its `index.json`; the gate record
   may name either. An image the gates did not pass is refused as before.
4. **The rehearsal runs in the nightly workflow**, and its report is kept with the run.

## Consequences

- An install defect is met in CI the night it is merged, not at a site.
- What the rehearsal cannot prove stays lane G's: a real card, real weights, the vendor's record.
- No new setting, no limit, no new store.
