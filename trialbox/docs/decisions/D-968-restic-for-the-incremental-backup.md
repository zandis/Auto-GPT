# D-968 restic for the incremental backup

- **Task:** PERF-010 (with PERF-011 and ENG-011), lane D. The owner's yes of 2026-11-16 was relayed on #639 by the
  integrator; the integrator's number for it, D-535, is already taken on master. Lane B2 advises on the consistent
  snapshot.
- **PR:** R1 `agent/PERF-010-R1-restic-pinned`; R2 to R4 follow, one PR each.
- **Date:** 2026-11-16
- **Status:** accepted (R1); R2 to R4 are written into this record as they land

## The ruling

restic does the incremental backup, on these conditions:

1. The repository password is a box key like the others. It is generated on the box and sealed under the KEK or TPM.
   It is never in a file in the clear and never in the support bundle. It is covered by the key ceremony's escrow
   shares (D-894), so the custodians can read a dead box's backups and no one else can.
2. The backup target holds ciphertext only.
3. Restore is rehearsed in the box rehearsal: back up, wipe, restore, compare.
4. restic is pinned by version and sha256 in the offline media and in the licence register.

## The plan (four cards)

- **R1, pin restic (this PR).** restic 0.19.1 goes into the `trialbox-py` image, which is the backup container. Each
  architecture's release file (`linux_amd64.bz2`, `linux_arm64.bz2`) is fetched through `tools/fetch_pinned.py` at
  the sha256 from restic's release `SHA256SUMS`. Python unpacks it, so no OS package is added (D-23). An architecture
  without a pin stops the build. The image rides in the signed bundle, so the offline media carries the pinned
  binary. The licence register gets a `software` kind and the row `restic` (BSD-2-Clause, the same version and both
  sums). `licence_register --check` fails when the register and the image's `ARG RESTIC_*` disagree, and a software
  row ships no path. NOTICE §7 names it.
- **R2, the password is a box key (landed: `agent/PERF-010-R2-restic-password-is-a-box-key`).**
  - `restic.key` is in `kek.PROTECTED` (and in `OPTIONAL`, since a box has none until its first incremental backup),
    so the custody report, `rotate-kek`, `doctor` and the key ceremony's record treat it like the other keys. It is in
    the inventory of `tools/keys.py`.
  - `python -m tools.keys restic-key` makes it, only under the KEK. A box without a KEK gets no key, and so no
    incremental backup: it keeps the single `.tbbak`. A plain `restic.key` is refused, both when making it and when
    opening it.
  - `tools/trialbox/restic_repo.py`:
    - `password()` opens it under the unsealed KEK.
    - `restic_env()` gives it to one restic process's environment only. It drops any `RESTIC_PASSWORD*` and
      `RESTIC_REPOSITORY*` from outside, so nothing else chooses the password or the repository.
    - `escrow_copy()` writes one file beside each repository, `trialbox-restic.key.json` (0600). It holds the
      wrapped key (KEK ciphertext) and what the custodians need to rebuild the KEK from their shares: back end, KEK id,
      share set id and threshold. It holds no salt, no custodian names and no share fingerprints.
      - It is written only when shares cover the KEK: a shamir KEK (the stewards' shares), or a TPM KEK whose escrow
        set (D-894) is of the current KEK.
      - A passphrase or KMS KEK has no custodians, so it gets no copy, and so no incremental backup. Its salt never
        leaves the box.
      - After `rotate-kek`, a TPM box keeps the old copy, which the old escrow shares still open, until
        `escrow-shares` is run again.
      - The same key re-wrapped replaces the copy. Another key is refused, because the repository's snapshots open
        only with the key they were made under.
      - The write never goes through a link: it refuses a link or a folder at the final name, writes a fresh random
        temporary name with `O_EXCL|O_NOFOLLOW`, renames it, and fsyncs the folder.
    - `open_from_target()` is the custodians' path: the target's file plus their shares (`kek_from_shares` or
      `kek_from_escrow`) give the password. Shares of another set or KEK are refused.
    - `make_key()` writes the key wrapped (`store_key` under the unsealed KEK) or not at all. It never takes
      `create_key_file`'s plain branch, so a locked or vanished KEK cannot produce a plain key.
    - `restic_env()` drops every `RESTIC_*` setting from outside, including the `copy` source's, before it sets the
      password.
  - The support bundle redacts a line that names `RESTIC_PASSWORD`. It cannot find the value by value, because the
    password exists only in restic's process environment. The secrets folders were already refused whole.
  - The adversarial review (D-311) found four defects in the first version: a write through a planted link, a plain
    key in a race, a stale escrow set after `rotate-kek`, and a passphrase KEK's salt on the target. All four are
    fixed and tested.
  - Who runs it: R3 calls `restic-key` from the nightly's host step before the first incremental backup, and mounts
    `/run/trialbox:ro` in the backup container so that `password()` can open the key there.
- **R3, the lake goes to restic.**
  - The lake's Parquet and DuckDB files go to `<target>/trialbox-restic/`. The other targets are filled with
    `restic copy`.
  - The `.tbbak` keeps the database dumps, the small folders and the host part, encrypted to the hospital's key. It
    also holds the lake manifest (path, size, sha256) and the restic snapshot id.
  - A restore checks restic's restored lake against that sealed manifest.
  - The snapshot rule waits on lane B2's answer on #639.
- **R4, the rehearsal.** `tools/rehearse_box/box.sh` gets a `backup-restore` step: back up, wipe, restore, compare.

What changes for the hospital: its private key alone no longer opens the lake. The KEK is also needed, either on the
box or rebuilt from the custodians' shares.

## Test

R1: `tests/unit/test_restic_pinned.py`:
- both architectures are pinned;
- the download goes through the pinned fetch, with no OS package and a refusal for any other architecture;
- the register row matches the image;
- the check names a version or a sum that differs, and an image with no pin;
- a software row ships no path;
- the whole register check passes.

The image build in CI runs `restic version` after the unpack.

R2: `tests/unit/test_restic_password.py`:
- the key is protected and in the inventory;
- it is made wrapped, at 0600, kept on a second run, and only its fingerprint is printed;
- a box without a KEK, or with its KEK locked, gets no key at all;
- a plain key is refused, and a locked box cannot open it;
- the password goes only into restic's environment, and every outside `RESTIC_*` is dropped;
- the stewards' shares open the repository from the target alone (one file, 0600, no password, no salt);
- a TPM KEK gets no copy before its escrow shares; with them the custodians open it, and their names stay on the box;
- after `rotate-kek` the old copy is kept until new escrow shares, then the new shares open it and the old do not;
- a passphrase KEK gets no copy;
- another key is refused and the copy kept;
- a link at the final or the old temporary name is never written through;
- the support bundle redacts the name.
