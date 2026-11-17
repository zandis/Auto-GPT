# D-996 the install runbook's first command runs from the USB stick

- **Task:** H-22 card 1 (lane D): lane H's findings 1, 2, 3, 4 and 6 to 12 of the install runbook followed alone
  (D-1136, #993); the integrator's rulings (a) and (c) on #639
- **PR:** this branch (`agent/H22-INSTALL-the-runbook-installs-from-the-stick`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-367 (the host tree in the signed bundle), D-382 (T-632: the one command), D-966 (`box-prepare.sh`,
  the box media's signed unpack), D-210 (the manifest's signature)

## Context

Lane H followed RUNBOOK §1 alone on a clean Ubuntu host. The install did not happen:

- **Finding 1.** The one command, `sudo deploy/install.sh ...` from `/opt/trialbox`, found no `deploy/install.sh`.
  Nothing in §1 or the hub says how the release's host tree (`files/trialbox-host.tar` in the bundle) gets there.
- **Finding 2.** The vendor key was placed at step 6, but the installer needs it at its first step.
- **Finding 4.** `make_bundle.sh` wrote the checksum sidecar with the vendor's `--out` path, while `install.sh`
  checks it by bare name from the stick: "bundle checksum mismatch". The box rehearsal did not see this because its
  media was the vendor's own output folder.
- **Findings 3 and 6 to 12.** The text slowed the reader: `--mode stub` with `--tier`, the unnamed questions, the
  unnamed packages, where the answers folder goes, the feed folder's first export, `python` on Ubuntu 24.04, the
  compose project folder, and where the ingest report is.

## Decision

1. **A signed bootstrap beside the bundle (ruling (c)).** `make_bundle.sh` copies `deploy/bootstrap.sh` beside the
   bundle as `trialbox-bootstrap.sh`, with `.sig`. The `.sig` is the vendor key's raw Ed25519 signature, written by
   the new `sign_bundle.py sign-file`.
   - **The first command.** §1's first command checks that signature with `openssl pkeyutl -verify -rawin`, as
     `box-prepare.sh` checks the box media, and then runs the bootstrap, in one line.
   - **What the bootstrap does.** It uses only tar, base64, openssl, sha256sum and python3's standard library:
     - it verifies the bundle's `manifest.json.sig` with the key given out of band;
     - it checks the host tree against the signed sha256;
     - it unpacks the tree to `/opt/trialbox`, beside the folder and then moved whole, never over a folder that
       holds anything else;
     - it places the key where the installer's first step looks for it;
     - it runs that tree's `deploy/install.sh` with the bundle and the options after `--`.
   - **Running it again.** A second run keeps the tree and runs the installer again, so an install that stopped is
     run again by the same command. A different key already on the box is refused.
2. **The key is an argument of the first command (finding 2).** Step 6 now says the command placed it.
3. **Bare-named sidecars (ruling (a), finding 4).** `make_bundle.sh` writes the sidecar from the bundle's own
   folder. It names the bundle, the bootstrap and its `.sig`, each bare.
   - `install.sh` checks only the bundle's own line, so a stick that carries just the bundle and its sidecar still
     checks.
   - A sidecar that does not name the bundle bare is refused in plain words: one from before this change names the
     vendor's path.
4. **The rehearsal sees it.** The rehearsal's vendor side builds in `$W/vendor/dist`, then moves the four files to
   the media and removes the folder. In both variants the install runs from a path that is not the vendor's, as on
   a site's stick, at no extra CI time. A new step, `bootstrap`, runs §1's first command as written on that media:
   - openssl checks the signature;
   - the bootstrap unpacks into an empty stand-in for `/opt/trialbox`;
   - the tree's installer runs its check-only mode (`--ctgov-check`, with no network probe).

   The rehearsal's clean host gets `openssl`, which Ubuntu Server has and the Docker base image does not.
5. **§1's text (findings 3 and 6 to 12):**
   - `--mode stub` takes the place of `--tier`;
   - the installer's questions are named, with `--yes` for an install that asks nothing;
   - step 1 names the packages;
   - the answers folder goes to `/root/site` and is given by full path;
   - the feed folder holds the first export before the command;
   - step 4 runs the mapping check in the release's Python image;
   - step 7 uses `--project-directory deploy` and reads the report through the adapter.

   Finding 5 (a PRODUCTION box in stub mode) is card 2.

## Tests

- `tests/unit/test_install_bootstrap.py`, 14 tests:
  - the bootstrap: unpacks, re-runs, refuses another key, refuses a swapped host tree, refuses a foreign folder,
    refuses a different key already on the box, checks usage and root, and needs only what a bare Ubuntu has;
  - `sign-file` checked by openssl;
  - make_bundle's bootstrap and bare sidecars;
  - the sidecar checked from another mount, and an old sidecar refused;
  - the rehearsal's wiring.
- `tests/unit/test_runbook_install_commands.py`: the first command runs as written on a signed bundle of the
  checkout's host tree, up to the installer's host step. Steps 4 and 7 have runners.
- Lane H's `tests/unit/test_runbook_install_follow.py` and `findings.json`: each fixed finding is taken out in this
  pull request.
