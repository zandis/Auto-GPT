# D-210 Update safety: marker, preflight, anti-rollback, key rotation, compatibility table

**D-210 An update is refused before it changes anything unless its compatibility table, release sequence, keys,
expiry, image digests and free space all check out; once it starts, a marker on disk names the bundle and the step
until a completed apply or a completed rollback removes it, and an interrupted update is rolled back by one command.**
Task T-111 (WS-14.2). PR #83 (`agent/T-111-update-safety`), on master after T-104 (PR #89, D-204). D-210 is the
number TB-ASSESS-01 reserved for T-111 (`docs/decisions/REGISTRY.md`). Date 2026-11-10.
Status: proposed (in review). Trace: URS-ADM-15, RSK-32; TST-OPS-04. Closes MR-058, MR-064 to MR-067 (review part 05
rows D-11 to D-14, D-16 to D-18; D-15 in part, see "Not done").

## Decision

* **Manifest 1.2.0** (`schemas/update_manifest.schema.json`). Required: `release_seq` (integer, monotonic),
  `min_installed_version` (the lowest installed `release_seq` the bundle applies over), `key_id` (`ed25519:` + the
  first 16 hex of the sha256 of the raw public key), `not_after`, `compat_sha256`, and `size` on every file. Optional:
  `release_sha256`, `images_lock_sha256`, `rotation`. `tools/sign_bundle.py` writes them (`--release-seq` is required
  on its command line; `key_id` is computed from the signing key).
* **Before any payload is read or staged** (`tools/verify_update.py`): regular members only, safe paths, no
  duplicates; the signature is tried with each trusted key before the manifest is parsed, and `key_id` must name the
  key that verified it; schema; `not_after` (and `created_at` ≤ `not_after`); the rotation; `release_seq` above the
  installed one; `min_installed_version`; `compat.json` (sha256 bound by the manifest, for this bundle id) against
  `deploy/updates/installed.json`; `release.json` against `images.lock`; every size; the free space to stage (payloads
  + 5 %). Payloads are then hashed while copied from the same open tar, each to `<path>.part` created exclusively and
  renamed only when all hashes matched; a payload path ending in `.part`, or one used as a folder by another, is
  refused (the rename could otherwise swap files).
* **Trust.** At most two keys. `deploy/updates/trust.json` is the trust once it exists (`--pubkey` and
  `TB_VENDOR_PUBKEY` are then ignored); before that, `deploy/keys/vendor_ed25519.pub` and, if present,
  `vendor_ed25519.next.pub`, written to `trust.json` by the first completed update. A **rotation bundle** is signed by
  a trusted key and adds one key (`add_key_id`, `add_public_key`) and may retire one; it is refused if it would leave
  three keys, re-add a retired key, or has been applied before (its manifest sha256 is recorded: accepted once, never
  as a downgrade). A retired key signs nothing again.
* **Anti-rollback.** `release_seq` ≤ the installed one is refused; `tools/apply_update.sh --allow-downgrade REASON`
  (a non-empty reason, no environment variable) lets it through, and the update writes `update.downgrade` (from, to,
  reason) to the audit log before its backup. `min_installed_version` is never overridden. A schema newer than the
  bundle knows is a compatibility refusal, never overridden either: old code on a newer schema is what D-13 warned of.
* **Compatibility table** (`compat.json`, `trialbox-update-compat/1`, in the bundle, sha256 in the signed manifest):
  rows of acceptable installed states, columns `schema` ({store: {min, max}}), `vocabulary_release`, `model_pin`,
  `prompt_registry` (each `"*"` or a list), and an optional `provides` written to `installed.json` after the update.
  The verifier compares it with the recorded state; the update compares it again under its lock, before the backup,
  with the schema versions read from the database (`_schema_version` per schema, T-104). A column the box does not
  record is not compared and says so in the notes: this is how the prompt registry (T-101, not merged) is wired —
  compared as soon as an update records `prompt_registry`, with no code change.
* **Images.** A bundle with an image payload or a `release.json` must carry `release.json` (provisional until T-110:
  `{"release_seq", "images": {name: {"image", "digest"}}}`) and an `images.lock` (the release's; else the box's
  `deploy/images.lock`). Every image named in either must be in both with the same reference and the same
  `sha256:` digest; **a null or missing digest is refused** (never "nothing to compare"). With T-104's lock as it
  is today (`db.digest` null) every image bundle is refused until T-110's release build pins it.
* **The update path** (`tools/trialbox/update.py`): under an `flock` on `deploy/updates/.lock`, refused while
  `IN_PROGRESS.json` exists; **preflight** (compat with the live schema, release sequence, the backup key and target,
  the box's own checks — the in-process box compares the bundle's migrations with `Database.applied()` checksums and
  refuses fewer scripts than applied versions — and free space per file system with the bytes needed and free); a
  refused preflight writes nothing (no marker, no history line, no service stopped). Then the **marker** (created
  exclusively, rewritten atomically at each step: `backup`, `rollback point`, `apply`, `migrate and restart`,
  `rulesets`, `check`, `refdata`, `finish`), backup, rollback point (images tagged, models kept, both database dumps
  **sealed** with AES-256-GCM under a random per-update key in the 0700 rollback folder, the rulesets repository's refs
  recorded and `main` tagged `trialbox-update/<bundle>-before`, `installed.json`/`trust.json` copied), apply, migrate
  (`Database.migrate_dir` on the in-process box), rulesets, check. **Reference data is its own step after the check**:
  one transaction; its failure leaves the healthy release, keeps the pack in `deploy/refdata/pending` and is in the
  `update.applied` detail. `finish` writes `installed.json` and `trust.json`, audits `update.applied`, removes the
  marker, then deletes the rollback point (dumps and key) and any left-over one.
* **Failures.** Backup or rollback point failed: the services `backup` stopped are started again
  (`docker compose start`), which completes the rollback, and the marker goes. Apply to check failed: everything is
  put back (images, models, databases, the rulesets refs, the state files), checked, `update.rolled_back` audited, the
  marker and the dumps go. The rollback itself failed: the marker stays (`status` says so; restore from the backup).
* **The compose box's database restore** is one `psql` transaction: first everything the database's role owns that
  a later release could have added (its schemas but `public` and an extension's, its relations in `public`), then the
  dump's own script (`pg_restore --clean --if-exists -f`, a 0600 file in the container, deleted after). `pg_restore
  --clean` alone drops only what the dump holds, so a table a migration added to a schema of the dump blocked `DROP
  SCHEMA` and the rollback failed (found by the drill's database-image case on 2026-11-10). Any error rolls the whole
  restore back, and a `pg_restore` that fails never hands `psql` a cut-off script.
* **Interrupted** (power cut, `kill -9`): `tools/apply_update.sh status` (= `python3 -m tools.update_status`) reads
  the marker and the lock: bundle, step, steps done, running or interrupted, rebooted since. `tools/apply_update.sh
  rollback <bundle>` rolls back from `point.json` (written after the rollback point and before every model file it
  overwrites), or only restarts the services when it stopped earlier, audits `update.rolled_back` with
  `recovered: true` and removes the marker. `python3 -m tools.update_status check` exits 3 while a marker exists, for
  a start guard. `clean` removes left-over rollback points.
* **Plaintext dumps.** None stays after a finished update or rollback: dumps are sealed right after the backup has
  read them, decrypted only to a 0600 file for `pg_restore` and deleted after it; `TB_UPDATE_KEEP_ROLLBACK` is gone.
  Without the `cryptography` package (a bare host `python3`) a compose box's dump stays plaintext (0600, 0700 folder)
  until the update completes, and is deleted then; the rollback point records `dump_encryption`.
* **The drill** (`tools/update_drill.py`) adds: older release refused and the audited downgrade; compat refusal by the
  verifier and the preflight; disk full; `kill -9` at each of the eight steps (status names the step and bundle, a
  second update is refused, rollback restores release, models, database and data, the stores start); no plaintext
  dump after a finished update; and a database-image case: the compose box's exact `pg_dump` / `pg_restore` of an
  unprefixed `trialbox_wf` on `trialbox-postgres:16-1` with the `db-init` extensions, after the "new release" added
  a table to a schema of the dump, a new schema and a table in `public`; the database restarts with exactly the
  dump's data and extensions (reported `SKIP`, not passed, without Docker or the image).

## Why

The update path is the one moment the hospital's box is changed by the vendor; its failure modes (half-applied
images after a power cut, a full disk mid-restore, a stolen older bundle, a key that cannot be retired, plaintext PHI
dumps left behind) were the High findings of the platform review. Checking everything that can be checked before the
first change, and leaving one durable record of what was half done, turns each into a refusal or one command.

## Not done (and where it goes)

* `deploy/install.sh` and the systemd unit do not yet call `tools.update_status check` before starting the stack
  (files owned by T-108 / install); the guard exists and exits 3.
* `TB_SKIP_AUDIT` (install.sh's load-only path) still skips the backup and rollback point on a running box; the
  load-only path now checks the marker and the release sequence and records `installed.json`.
* `tools/make_bundle.sh` and `deploy/gcp/demo-vm-update.sh` build image bundles without `release.json`; such bundles
  are now refused until T-110's release build writes `release.json` and pins `images.lock` digests.
* `max_locks_per_transaction` for the one-transaction restore of HAPI's many tables (review D-15), the
  refdata bind mount instead of `docker compose cp` (D-17), pruning `rollback-*` image tags (D-12).
* The compose and demo boxes' new commands (`compose run` of the rulesets snippet, the `psql` size and schema reads)
  are tested against a fake runner only; the database-image case of the drill runs the dump/restore for real.
