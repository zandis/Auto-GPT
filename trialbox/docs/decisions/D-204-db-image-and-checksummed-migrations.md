# D-204 The database image (Debian, pgvector, PGroonga) and checksummed migrations

**D-204 The box's PostgreSQL becomes a Debian image with pgvector and PGroonga, pinned in `deploy/images.lock`;
every store's schema versions are checksummed in `_schema_version` and a changed applied version is refused.**
Task T-104 (WS-03.1 rest, WS-14.2 part). PR: this branch (`agent/T-104-db-image-migrations`). Date 2026-11-09.
Status: proposed (in review). Trace: URS-STW-01, RSK-05, RSK-13; TST-GOLD-01, TST-OPS-03.

## Decision

* **Image.** `deploy/docker/db.Dockerfile`: `postgres:16-trixie` pinned by its multi-arch index digest, plus
  `postgresql-16-pgvector` 0.8.7 (PostgreSQL apt repository, already configured in the base image) and
  `postgresql-16-pgdg-pgroonga` 4.1.0 (Groonga apt repository), each by exact Debian version and held. The Groonga
  signing key is vendored (`deploy/docker/db.groonga-archive-keyring.asc`) and checked against its fingerprint in the
  build; no key is fetched. Built as `trialbox-postgres:16-1` (`make images`, context `deploy/docker`; the name keeps
  "postgres" so `tools/network_sheet.py` still knows its port, 5432, and the network sheet is unchanged); the compose `db`
  service keeps its name, port (unpublished, 5432 inside) and volume `db-pg`; only its `image:` line changed.
* **Trixie, not bookworm.** The card says `postgres:16-bookworm`. The Groonga repository publishes PGroonga 4.1.x
  only for trixie (bookworm stops at 4.0.6-1, checked 2026-11-09 in `dists/bookworm/main/binary-{amd64,arm64}`), and
  the 4.1.0 package needs glibc ≥ 2.38 (bookworm has 2.36), so bookworm and 4.1.x cannot both hold from the apt
  repositories. The version requirement wins: trixie is Debian stable, the base the Groonga project still builds for.
  Changing back is one ARG and two versions (bookworm: PGroonga 4.0.6-1, pgvector `0.8.x-1.pgdg12+1`) plus the lock.
* **Extensions: only in the image, never by a store.** `deploy/docker/db-init/20-extensions.sh` creates `vector` and
  `pgroonga` in `trialbox_wf`, schema `public`, as the superuser (neither is a trusted extension), on the first start
  of an empty volume, and fails that start on an image without them. No code creates an extension, so the test
  suite's local cluster (`tools/pglocal.py`, no pgvector, no PGroonga) and `e2e_simple` run as before. Stores keep
  `search_path` = their own schema; they reach the extensions qualified (`public.vector(768)`,
  `OPERATOR(public.<->)`, `OPERATOR(public.&@~)`), as the image test does as the non-superuser `trialbox` role.
  `tb_common.db.extensions(db)` lists what is installed; the backup drill checks the extensions present before the
  backup are there after the restore at the same versions (`--require-extensions` makes their absence a failure, for
  a run against the image).
* **`deploy/images.lock`** (JSON, `"format": "trialbox-images-lock/1"`) is the one record of what the box runs:
  `images.<name>` with `image` (the tag compose uses), `dockerfile`, `context`, `base.ref`, `base.digest`,
  `base.platforms`, `packages` (Debian package → exact version), `keys`, `extensions` (name → version the image must
  report) and `digest` (the built image's digest: null until the release build writes it; T-110 puts the same value
  in `release.json`, and T-111 refuses a bundle whose image digest differs). `tests/integration/test_db_image.py`
  keeps the lock, the Dockerfile's ARG defaults, the key and the compose line equal on every `make test`.
* **Migrations.** `_schema_version` (one per store, in the store's schema) gains `sha256` (hex SHA-256 of the
  script's UTF-8 text exactly as passed, no normalisation), `script_name` (`v001`... for a script in code, the file
  name for `migrate_dir`) and `backfilled`. `Database.migrate(versions)` runs in one transaction under a per-schema
  advisory lock: (1) rows from before D-204 are back-filled once from the scripts passed now (`backfilled = true`),
  without failing; (2) each applied version passed is compared, and a difference raises `MigrationChanged` (store,
  version, script name, recorded and current checksum) before anything is applied; (3) applied versions must be
  exactly `1..n`, and a list must number its scripts `1..n`, else `MigrationOrderError` (out of order);
  (4) new versions run and are recorded. `Database.migrate_dir(path)` reads `NNN_<name>.sql` (three digits, `001`
  first, no gap, no duplicate, no other `.sql` file). The same API is on `orchestrator.db_pg.PostgresBackend`.
* **Checksum API for T-105 and T-111** (in `libs/tb_common/db.py`): `script_sha256(text)`, `Migration(version,
  script, name)` with `.sha256`, `read_migration_dir(path)`, `Database.applied()` → `AppliedVersion(store, version,
  applied_at, sha256, script_name, backfilled)`, and the errors `MigrationError` ⊃ `MigrationChanged`,
  `MigrationOrderError` (all `DatabaseError`). A caller passing fewer versions than are applied is not refused by
  `migrate` (an older release, `migrate([])`): whether a downgrade is allowed is the update path's decision, from
  `applied()`.
* **The pin in the tests.** `tests/unit/test_migrations.py` holds the sha256 of every store's applied versions
  (19 stores). Editing an applied DDL string fails it (checked: one space added to `mail` version 1 fails with "store
  'mail': an applied migration's text changed (version 1)"); a new version is appended to the store's list and to
  the pin.

## Why

Checksums turn "a migration string was edited after it ran" from a silent divergence between boxes into a refused
start that names the store and the version (RSK-05, RSK-13). The back-fill is the one point where the code is trusted
without proof, once, before any site data. The extensions belong to the image because creating them needs the
superuser and must not be a precondition of the local test cluster.

## Consequences and open items

* A volume made by the earlier `postgres:16-alpine` image is not reused under the Debian image (musl and glibc
  collate differently, so text indexes could be wrong): dump and restore it (`trialbox backup` / `restore`), or start
  empty. No site holds data yet.
* `services/omop/schema.py` version 2 embeds the concept block (`TB_OMOP_CONCEPT_BLOCK`): changing the block after
  the first start is now refused as a changed migration, which is right (the sequence would not follow). T-105's
  block shrink (10 million to 1 million) must be a new OMOP version (`ALTER SEQUENCE`), not an edit of version 2.
* `tools/trialbox/update.py` still passes a bundle's `migrations/*.sql` (sorted) to `migrate`; T-111 moves it to
  `migrate_dir` with the `NNN_` rule (not changed here: outside this card).
* `deploy/topology_a/podman-compose.yml` still names the Alpine image; it is a separate topology, left to its card.
* PGroonga's and pgvector's apt repositories keep only recent builds: when a pinned version leaves the repository,
  the build fails loud and the lock and Dockerfile move together to the new version.
* The comment above the compose `db` image line (line 36) still says "Multi-arch index digest"; the card allows the
  image line only, so the line itself carries the pointer to `deploy/images.lock`. T-108 may fix the comment.
* pgBackRest (D-187, merged while this task ran) still has its own Alpine-based image, `deploy/pgbackrest/Dockerfile`,
  which says the Debian db image will carry pgBackRest and replace it. Not done here (that file belongs to the backup
  work): adding `pgbackrest` from the PostgreSQL apt repository to `deploy/docker/db.Dockerfile`, pinned in the lock,
  and retiring the Alpine file is the follow-up. The compose `db` settings of D-187 (`wal_compression=zstd`,
  `default_toast_compression=lz4`, data checksums) run unchanged on the Debian image.
