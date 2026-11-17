# D-991 the code systems loaded at install reach the services that read them

- **Task:** TERM-VOL (lane D), found by lane H in TERM-2 (#936), given by the integrator on #639
- **PR:** this branch (`agent/TERM-VOL-the-services-read-the-loaded-tables`)
- **Date:** 2026-11-17
- **Status:** accepted
- **Builds on:** D-858 and D-1028 (TERM-1: install-time loading), D-1113 to D-1116 (TERM-2), D-562 (the host check's
  doctor mounts)

## Context

TERM-1 and TERM-2 load code systems into `TB_TERMINOLOGY_DIR` (default `/data/terminology`). No compose service
mounted that folder, so a table loaded on a real box was read by nothing, and D-1028's install-time loading did
nothing there.

## Decision

1. **A named volume, `tb-terminology`, read-only in its readers.** It is mounted at `/data/terminology:ro` in the
   services that read the loaded tables at run time, meaning code that builds a `Terminology(...)` or imports the
   resolver:
   - criteria-compiler (the overlay and the resolver);
   - orchestrator (`feas_compute`, and `sitesetup` through `setup_api`);
   - console (`resolver.current_release`).

   The other packages that import the mapper take only constants: matching (`SYSTEMS`, `YJ_STEM`, `FAMILY_EXT`) and
   omop (the shipped tables' folder). The adapter names `sitesetup.mapping.suggest` only in a docstring. No compose
   service mounts the volume writable. The mount is in the base `docker-compose.yml`, so every overlay that extends it
   (secrets, the GPU files, test) gets it, since compose merges service volumes by target.
2. **One writer: `deploy/terminology.sh`.** It runs `python -m tools.terminology_install <args>` in the box's Python
   image (`TB_IMAGE`, default `trialbox-py:1.0.0`, for the loader's pyarrow), with:
   - `--network none`;
   - the volume read-write at `/data/terminology` (`TB_TERMINOLOGY_DIR`);
   - the site's staging folder `deploy/site/terminology` read-only at `/stage`.

   It refuses when the volume does not exist yet, since the box's first `compose up` creates it.
   `docs/handover/OFFLINE-MEDIA.md` now gives the loading commands through it.
3. **The doctor sees what the services see.** The host check's doctor (`deploy/check_host.sh`) and the rehearsal's
   doctor mount the volume read-only, so the `terminology` line reports the loaded tables.
4. **The installer makes the staging folder** `deploy/site/terminology`, beside `deploy/site/mapping`.
5. **A backup takes the volume** (`terminology` in `backup.DEFAULT_DIRS` and `update.BACKUP_VOLUMES`), so a restored
   box reads the tables it had loaded. Without it, the doctor's line would be FAIL until the site's IT loaded them
   again. The tables are encrypted to the hospital's key like everything else in a `.tbbak`. A box updated from a
   release without the volume gets it from the update's `compose up`.
6. **The box rehearsal proves it** in a new step, `terminology`, after `doctor`:
   - a synthetic site list (two made-up local codes) is staged and loaded through `deploy/terminology.sh`;
   - criteria-compiler, orchestrator and console each read `site_rehearsal` with its two rows from their mount, and
     none can write there;
   - the doctor's `terminology` line names it.

## Test

`tests/unit/test_terminology_volume.py`:
- every reader mounts the volume read-only;
- the readers are exactly the services whose code reads the tables (a new reader fails until its service is named);
- no compose file mounts it writable;
- the wrapper is the one writer, as described above;
- the host check's doctor mounts it read-only;
- the installer makes the staging folder;
- a backup takes the volume;
- the rehearsal step loads at install and looks in every reader, failing a reader that can write.
