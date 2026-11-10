# D-204 The database image (Debian, pgvector, PGroonga) and checksummed migrations

**D-204 The box's PostgreSQL becomes a Debian image with pgvector and PGroonga, pinned in `deploy/images.lock`;
every store's schema versions are checksummed in `_schema_version` against a baseline shipped with the code, and a
changed applied version is refused.** Task T-104 (WS-03.1 rest, WS-14.2 part). PR: this branch
(`agent/T-104-db-image-migrations`). Date 2026-11-09/10. Status: proposed (in review; the trixie base accepted by the
integrator 2026-11-10). Trace: URS-STW-01, RSK-05, RSK-13; TST-GOLD-01, TST-OPS-03. This file sits in
`docs/decisions/` as the task brief asks; the integrator moves or indexes it once T-002 lands.

## Decision

* **Image.** `deploy/docker/db.Dockerfile`: `postgres:16-trixie` pinned by its multi-arch index digest, plus
  `postgresql-16-pgvector` 0.8.7 (PostgreSQL apt repository, already configured in the base image),
  `postgresql-16-pgdg-pgroonga` 4.1.0 and its library `libgroonga0` 16.1.5 (Groonga apt repository), each installed
  at its exact Debian version, checked and held. The Groonga signing key is vendored
  (`deploy/docker/db.groonga-archive-keyring.asc`); the build checks it holds exactly one key and that its fingerprint
  is the pinned one; no key is fetched. Built as `trialbox-postgres:16-1` (`make images`, context `deploy/docker`; the
  name keeps "postgres" so `tools/network_sheet.py` still knows its port, 5432, and the network sheet is unchanged);
  the compose `db` service keeps its name, port (unpublished, 5432 inside) and volume `db-pg`; only its `image:` line
  changed. `make images` gained one `docker build` line for it (and `images-multiarch` one `buildx` line): the
  Makefile is outside the card's list, but without it nothing builds the image the compose line names.
* **Trixie, not bookworm (accepted).** The card said `postgres:16-bookworm`. The Groonga repository publishes PGroonga
  4.1.x only for trixie (bookworm stops at 4.0.6-1, checked 2026-11-09 in `dists/bookworm/main/binary-{amd64,arm64}`),
  and the 4.1.0 package needs glibc ≥ 2.38 (bookworm has 2.36), so bookworm and 4.1.x cannot both hold from the apt
  repositories. The version requirement wins: trixie is Debian stable, the base the Groonga project still builds for.
* **Extensions: trusted, created by and owned by `trialbox`, only in the image.** Neither pgvector nor PGroonga ships
  as a trusted extension. The image appends `trusted = true` to both control files, and
  `deploy/docker/db-init/20-extensions.sh` creates them in `trialbox_wf`, schema `public`, after `SET ROLE trialbox`,
  so the database owner owns them. Why: a backup or rollback dump of the whole `trialbox_wf` (no `tb_prefix`, as on
  a box) contains both extensions, and the restore runs as `trialbox` with `pg_restore --clean --if-exists
  --single-transaction` (`tools/trialbox/backup.py`, `tools/trialbox/update.py`); owned by the superuser, that
  restore stops with "must be owner of extension vector" and a rollback leaves a stopped box (review finding B1, shown
  by `test_superuser_owned_extensions_would_break_that_restore`). Trade-off: any role with CREATE on a database of
  this server can create the two extensions; on the box that is `trialbox` (owner of `trialbox_wf`) and `hapi`
  (superuser anyway), and the extensions' install scripts are the packaged ones at the pinned versions. The
  extensions are never created by a store, so the test suite's local cluster (`tools/pglocal.py`, without them) and
  `e2e_simple` run as before. Stores keep `search_path` = their own schema and reach them qualified
  (`public.vector(768)`, `OPERATOR(public.<->)`, `OPERATOR(public.&@~)`).
* **Readiness.** The image carries `/usr/local/bin/tb-db-check` (`deploy/docker/db.healthcheck.sh`): server up,
  `trialbox_wf` there, both extensions installed. A volume whose first start failed in db-init (the container then
  restarts and skips init) or an old volume that never ran `20-extensions.sh` keeps failing it.
  `tb_common.db.require_extensions(db)` is the same check from Python (start-up, `doctor`). Wiring it is not in this
  card (the compose healthcheck line and `doctor` belong to T-108 and T-113): the compose `db` healthcheck should
  become `["CMD", "tb-db-check"]`.
* **`deploy/images.lock`** (JSON, `"format": "trialbox-images-lock/1"`) is the one record of what the box runs:
  `images.<name>` with `image` (the tag compose uses), `dockerfile`, `context`, `base.ref`, `base.digest`,
  `base.platforms`, `packages` (Debian package → exact version), `keys`, `extensions` (name → version the image must
  report), `trusted_extensions`, `healthcheck` and `digest` (the built image's digest).
  `tests/integration/test_db_image.py` keeps the lock, the Dockerfile's ARG defaults, the key and the compose line
  equal on every `make test`.
* **Migrations.** `_schema_version` (one per store, in the store's schema) gains `sha256` (hex SHA-256 of the
  script's UTF-8 text exactly as passed), `script_name` (`v001`... for a script in code, the file name for
  `migrate_dir`), `backfilled` and `backfilled_at`. `Database.migrate(versions)` runs in one transaction under a
  per-schema advisory lock: (1) applied versions must be exactly `1..n`, and a list must number its scripts `1..n`,
  else `MigrationOrderError`; (2) a row from before D-204 (no checksum) is back-filled, logged, only when the script
  the code passes for it has the store's checksum in the **D-204 baseline** (`libs/tb_common/migration_baseline.py`,
  frozen, 20 stores; the scratch twins `omop_<hash>` and `orch_rerun_<hex>` share their store's entry); otherwise
  `MigrationChanged`, so a box that skips straight to a release with an edited past DDL is refused instead of
  recording the edit; a store without a baseline (a test's schema, the update path's `release`) is back-filled from
  the code, logged; (3) once every row carries a checksum the table is marked (`COMMENT ON TABLE _schema_version`),
  and a row without one appearing later (an old release applying a version, a hand edit) is refused with
  `MigrationError`; restoring a pre-D-204 dump brings back an unmarked table, back-filled against the baseline again;
  (4) each applied version passed is compared, and a difference raises `MigrationChanged` (store, version, script
  name, recorded and current checksum) before anything is applied; (5) new versions run and are recorded.
  `Database.migrate_dir(path)` reads `NNN_<name>.sql` (three digits, `001` first, no gap, no duplicate, plain files
  only: a link or a folder is refused, as is any other `.sql`/`.SQL` or `NNN_` entry; a file that is not UTF-8
  raises `MigrationError` naming the store). The same API is on `orchestrator.db_pg.PostgresBackend`.
* **Checksum API for T-105 and T-111** (in `libs/tb_common/db.py`): `script_sha256(text)`, `Migration(version,
  script, name)` with `.sha256`, `read_migration_dir(path, store)`, `Database.migrate_dir(path)`, `Database.store`
  (the name given to `connect`), `Database.applied()` → `AppliedVersion(store, version, applied_at, sha256,
  script_name, backfilled, backfilled_at)`, `extensions(db)`, `require_extensions(db)`, and the errors
  `MigrationError` ⊃ `MigrationChanged`, `MigrationOrderError` (all `DatabaseError`). A caller passing fewer versions
  than are applied is not refused by `migrate` (an older release, `migrate([])`): whether a downgrade is allowed is
  the update path's decision, from `applied()`.
* **The pin in the tests.** `tests/unit/test_migrations.py` checks every store's versions against the baseline plus
  `ADDED` (versions after D-204), and that every file that migrates a store is listed (a new store fails the test
  until it is pinned). Editing an applied DDL string fails it (checked: one space added to `mail` version 1 fails
  with "store 'mail': an applied migration's text changed (version 1)").

## Why

Checksums turn "a migration string was edited after it ran" from a silent divergence between boxes into a refused
start that names the store and the version (RSK-05, RSK-13). Shipping the baseline removes the one point where the
code was trusted without proof. The extensions belong to the image and to the database owner because a restore must
be able to drop and re-create everything in the dump as the box's own role.

## Consequences and open items

* **The built image is not digest-pinned yet** (review finding M5): the compose line names a local tag and
  `images.db.digest` is null, where the Alpine line it replaces named a registry digest. The release build (T-110)
  writes the digest; until then the update path must refuse a bundle while it is null (T-111).
* A volume made by the earlier `postgres:16-alpine` image is not reused under the Debian image (musl and glibc
  collate differently, so text indexes could be wrong): dump and restore it, or start empty. No site holds data yet.
* `services/omop/schema.py` version 2 embeds the concept block (`TB_OMOP_CONCEPT_BLOCK`): changing the block after
  the first start is now refused as a changed migration, which is right. T-105's block shrink must be a new OMOP
  version (`ALTER SEQUENCE`), not an edit of version 2.
* `tools/trialbox/update.py` still passes a bundle's `migrations/*.sql` (sorted) to `migrate`; T-111 moves it to
  `migrate_dir` with the `NNN_` rule (not changed here: outside this card).
* pgBackRest (D-187) keeps its own Alpine-based image, `deploy/pgbackrest/Dockerfile`, which says the Debian db image
  will carry pgBackRest; not done here (the backup work owns it): add `pgbackrest` from the PostgreSQL apt repository
  to `deploy/docker/db.Dockerfile`, pinned in the lock, and retire the Alpine file. The D-187 compose settings
  (`wal_compression=zstd`, `default_toast_compression=lz4`, data checksums) run unchanged on the Debian image.
* `deploy/topology_a/podman-compose.yml` still names the Alpine image; the comment above the compose `db` image line
  still says "Multi-arch index digest" (the card allows the image line only).
* PGroonga's and pgvector's apt repositories keep only recent builds: when a pinned version leaves the repository,
  the build fails loud and the lock and the Dockerfile move together.
