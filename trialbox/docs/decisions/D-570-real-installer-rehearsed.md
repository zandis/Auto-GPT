# D-570 The box rehearsal is run again: five stops fixed, two named for the next card

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

1. **The rehearsal is brought back by running it, one stop at a time.** Each stop is fixed where it is wrong: in
   the rehearsal when the rehearsal fell behind the product, in the product when the installer is wrong.
2. **A step that fails stops the rehearsal by name.** `set -e` does not act inside a step (it runs in an `if`), so
   a failed pull and a bundle that was not built are checked explicitly. Before this the media step said `ok`
   with no bundle, and the failure showed three steps later as "no such bundle".
3. **The release record matches a saved image on either Docker image store.** The gates name an image by Docker's
   image id: the config digest on the classic store, the index digest on the containerd store. A `docker save`
   archive holding exactly one image is known by its config digest and by each digest of its `index.json` whose
   blob in the archive leads to that config (the blob's bytes hash to its name; an index names a manifest, the
   manifest names the config). The gate record may name either, and the image's SBOM is found under either.
   `index.json` is text, so a digest written into it by hand, a digest whose blob is missing, and the digest of
   another image name nothing. An untagged second image counts as a second image: the archive is then known by
   its config digest only, and the build's "one image per archive" refuses it. An image the gates did not pass is
   refused as before.
4. **Every container `install.sh` starts on `deploy/`, and the doctor of `check_host.sh` it ends with, also
   gets the release tree.** After an install from a bundle
   the shipped files under `deploy/` are links into `../current` (`tools/host_tree.py`). Mounted alone, `deploy/`
   shows them dangling: the installer stopped at the measured record (`/d/measured/...: No such file`), and the
   image lock and the compose files had the same shape. The tree is mounted where the links point.
5. The rehearsal's compose rendering names the site's time zone (D-315 made it required), and its GPU stand-in
   answers the compute capability query the installer makes.

## Not done here: the two stops that are left (card OPS-004b)

With the above the real `install.sh` runs in PRODUCTION inside the rehearsal's clean container through the bundle,
the settings, the secrets, the measured record and TLS, and stops when it starts the stack. Two things stand
between it and "TrialBox is running", and neither is a small fix:

- **The placeholder weights are refused.** Since T-012b a pin must be the registry's expected manifest and a
  champion needs a qualification record that qualifies PRODUCTION, which synthetic weights never do. The
  rehearsal was written when the install pinned a champion from any folder; its steps `doctor`, `served` and
  `screen` expect that. A rehearsal in PRODUCTION can prove that the installer ends with the expected FAIL list
  and a healthy stack; the steps that route to the pair need a rehearsal release (its own registry and record)
  or a second phase in TEST.
- **The installer wants every pinned third-party image on the box**, by the variables of `deploy/image-pins.json`:
  Caddy and Authelia (the TLS answers bring their overlay) and the model server, which the stand-ins replace. The
  rehearsal's bundle carries the base file's images only, and cannot carry the model server image. The pin check
  has to look at what compose will run with the override applied, or the rehearsal's bundle has to be made from
  the same file set as the install.

**The same mount shape elsewhere, not fixed here** (read, not run): `tools/trialbox/update.py` (the update's
`doctor --serving` and `--weights`), `tools/trialbox/ops.py` (the console's network sheet), `deploy/check_weights.sh`,
`deploy/box-install.sh` and `tools/rehearse_box/box.sh`. Each starts a container on `deploy/` alone; on a box
installed from a bundle the shipped files it reads there are links. They go with OPS-004b, where the rehearsal
will reach them.

Until both stops are done the rehearsal is not in the nightly workflow: a nightly job that is red every night hides the
next real stop.

## Consequences

- Five defects are gone, two of them the product's: a release could not be bundled on a containerd-store host, and
  an installer run from a bundle could not read its own shipped files from a container.
- The rehearsal still ends at step `install`. OPS-004 is not finished by this card.
- What the rehearsal cannot prove stays lane G's: a real card, real weights, the vendor's record.
- No new setting, no limit, no new store.
