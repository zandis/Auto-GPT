# D-994 the box records the commit of the release it runs

- **Task:** INSTALLED-COMMIT (lane D), for H-15 finding F1; the integrator's yes on #639. Lane H's H-19 stacks on it.
- **PR:** this branch (`agent/INSTALLED-COMMIT-the-box-records-its-release-commit`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-633 (`dirty` in `installed.json`), D-734 and D-881 (the code a record names)

## Context

The qualification evidence gates name the code by a git sha; the integrator ruled they stay that way, with no image
id and no poc-profile exception. `release.json` carries the commit (`source.commit`, 40 hex, signed with the bundle),
but it lives only in the bundle's `meta/`. The installed box kept `bundle_id`, `manifest_sha256` and `dirty` in
`deploy/updates/installed.json`, but not the commit. A driver on the box therefore had nothing to pass the gates.

## Decision

1. `Updater._record` (`tools/trialbox/update.py`) is the one writer of `installed.json`, at a first install and at
   every update. It now also writes **`commit`** from the verified release record:
   - the release's `source.commit` when it is 40 lowercase hex;
   - otherwise `null` (none recorded, or anything else).

   A bundle with no release record leaves the key out, as before. `dirty` is written as before (D-633).
2. **What the gates take:** `commit` only when it is a 40-hex string **and** `dirty` is `false`. They refuse
   `dirty: true` (every rehearsal bundle, built `--allow-dirty`), `commit: null` and a missing `commit`, naming which.
   Never an image id: an image id names one image, not the release.
3. A box installed before this change has no `commit` key until its next update.

## Test

`tests/unit/test_installed_commit.py`:
- an update records the commit;
- a first install records it through the same writer;
- a dirty release records its commit and `dirty: true`;
- anything but 40 lowercase hex is recorded as `null` (cases: none, empty, uppercase, 39 and 41 characters, a
  trailing space, a list, a number);
- a bundle without a release record leaves the key out.

`tests/unit/test_release_dirty_refused.py` is unchanged and passes.
