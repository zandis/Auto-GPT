# D-968 restic for the incremental backup

- **Task:** PERF-010 (with PERF-011 and ENG-011), lane D. The owner's yes of 2026-11-16 was relayed on #639 by the
  integrator as D-535 and recorded as D-1035 (PR #897). Lane B2 advises on the consistent
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
- **R3a, the restic runner (landed: `agent/PERF-010-R3a-the-restic-runner`).** `restic_repo.Repo` is one
  repository, `<target>/trialbox-restic`, under the box's password:
  - `ensure()` makes it when the target has none and refuses one that the box's password does not open (exit 12).
  - `ensure(like=first)` makes each other target's repository with the first's chunker parameters
    (`init --from-repo --copy-chunker-params`), so `restic copy` deduplicates them the same.
  - `backup()` takes exactly the listed files (`--files-from-verbatim`, from the lake's root) and returns the
    snapshot id. An incomplete snapshot (exit 3: a listed file could not be read) fails it.
  - `copy_from()`, `forget(keep=N)`, `prune()`, `snapshot_ids()` and `restore()` do what their names say.
    `restored_root()` says where a restore puts the files, since restic keeps absolute paths.
  - The password reaches restic through `restic_env()` only. It is never in an argument list, and an error message
    has it replaced if restic ever echoed it.
  - The command is `TB_RESTIC` (default `restic`, the image's pinned binary).
  - The tests use a stand-in (`tests/fixtures/restic/fake_restic.py`) with restic's subcommands and exit codes; the
    real binary runs in the box rehearsal (R4).
- **R3b, the lake goes to restic (landed: `agent/PERF-010-R3b-the-lake-goes-to-restic`).**
  - `backup(..., restic_secrets=<secrets folder>)` (CLI `trialbox backup --restic`) starts by opening the password
    under the unsealed KEK. It then writes the escrow file to every target and makes or opens each target's
    repository. A KEK not covered by shares, a locked KEK or a missing key stops it here, before anything is written.
  - The lake's served files (`db/`, `parquet/`) go to the first target's repository. This happens under the lake's
    lock, which is held until restic has read them.
    - Under the lock, each sidecar goes into the sealed `.tbbak`. Each served file's sha256 (from its sidecar, else
      read once) and size go into `manifest["restic"]`, with the snapshot id and the lake's root.
    - Exactly those files are given to restic. A listing that changed fails the backup.
    - The rest of the lake (NDJSON, the vector store, the site inputs) and every other folder stay in the sealed
      file, as before.
  - After the sealed file is written and copied, every other target's repository gets the snapshot by `restic copy`.
    `forget --keep-last <keep>` applies to the snapshots as `keep` applies to the files.
  - On restore, `unpack`, `verify` and `restore` take the password. The CLI's `--restic-from-box` gives the box's
    own key; `--restic-share FILE`, one per share, gives the custodians' shares with the file beside the
    repository.
    - The snapshot is restored beside the unpacked tree.
    - Every file is checked against the sealed manifest (sha256 and size, nothing missing, nothing extra) before it is
      put where the tar would have put it. The rest of the restore is unchanged.
    - Without a password the lake is not given, and the message says how to open it.
  - A backup without `--restic` is unchanged.
  - Lane B2: the lock is held for restic's whole read, which is safe whatever the answer. A served file is never
    written in place (D-755), so a later card may let the lock go after the listing and retry a vanished file.
  - The adversarial review (D-311) found seven defects, all fixed and tested:
    - **A wrong sidecar no longer passes.** Every served file is read and hashed under the lock and must match its
      sidecar, as on the path without restic, so a rotted file fails the backup tonight. Each file's (size, mtime)
      must hold until restic has read it.
    - **A failed copy no longer leaves a bad target.** Each other target's repository receives the snapshot
      (`restic copy`) before that target gets its sealed file and sidecar. A failed copy leaves that target with
      nothing for the night, and the first target stays whole.
    - **A failed night no longer cost a needed snapshot.** A failed night left a snapshot that `--keep-last` counted.
      Now each kept file has `<name>.tbbak.restic` beside it (the id of the snapshot it needs; no secret), and
      `forget_except` keeps exactly the snapshots those files name. A run that fails before its sealed file is
      complete forgets its snapshot at once.
    - **Space is freed.** Every `forget` is `--prune`.
    - **The restore drill works on a restic backup.** It reads the sealed part (`lake_from_restic=False`); it checks
      the databases.
    - **A dead-box restore works on other hosts.** The recorded root is taken as recorded on the restoring machine
      and not resolved again, so a Mac's `/var` is no longer a problem. A root that is not a plain absolute path is
      refused.
    - **Boxes can share a NAS.** The repository folder and the escrow file carry the site:
      `trialbox-restic-<site>`, `trialbox-restic-<site>.key.json`.
    - The review also found three ways a forged or tampered backup could misplace files, and all are closed:
      - The manifest is encrypted to the hospital's key but not signed, so every restic path in it must be a plain
        relative path under `db/` or `parquet/`, and the repository a plain folder name.
      - A restored file must be a regular file, never a link.
      - restic gets no inherited `$PWD`.
- **R3c, the nightly wiring (next).** The host step runs `tools.keys restic-key`. The backup container mounts
  `/run/trialbox:ro` and runs `backup --restic` when the box has a KEK the shares cover; otherwise it says why and
  keeps the single file. A weekly `prune`.
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

R3a: `tests/unit/test_restic_runner.py`:
- a new target gets a repository and a second run keeps it;
- a repository under another password is refused, and the error names no password;
- backup takes exactly the listed files and restores them;
- a vanished file fails the backup;
- the other targets are copies made with the first's chunker;
- forget keeps the newest;
- the password is never in an argument list;
- outside restic settings choose nothing;
- a missing restic is said plainly.

R3b: `tests/unit/test_backup_restic.py` (a real PostgreSQL, the stand-in restic, a shamir box):
- the lake's bulk goes to restic and the rest stays sealed, with a repository and an escrow file on each target;
- a restore checks restic's files against the sealed manifest and passes the lake's check;
- the second target restores alone;
- the custodians' shares open it without the box;
- without the password the lake is not given;
- a changed file in the repository fails the restore, named;
- the keep applies to the snapshots;
- a KEK without shares writes nothing;
- the lake's lock is held for restic's whole read (a swap waits);
- without restic nothing changes;
- the command line (`backup --restic`; `backup-verify` with the box's key, with two shares, and refused with none or
  one);
- from the review:
  - a file that differs from its sidecar fails the backup, and nothing goes to restic;
  - a failed copy leaves no file on that target, and the first stays whole;
  - with keep=2, a failed night leaves no snapshot and night 1 still restores;
  - every forget prunes;
  - each site has its own repository and escrow file on a shared target;
  - a forged restic record writes nothing;
  - the recorded root is not resolved again;
  - a restored link is refused.
