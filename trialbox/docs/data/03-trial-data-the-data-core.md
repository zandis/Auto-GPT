# 3. Trial data: the data core

TrialBox's own data lives in schema `datacore` of `trialbox_wf` (D-123, D-126):

- **Forms** are FHIR Questionnaires. A REDCap data dictionary or one of the seven built-in forms becomes one.
  Identifier fields of a dictionary are dropped.
- **Answers** are rows, one per study, record, event and field, with who changed it and when; every change is in
  `history`. FHIR QuestionnaireResponse is an export, made on request.
- **The record key** is one rule: the screening number first, else the pseudonym (the chart number turned into the
  HMAC pseudonym at import), else the row is refused and listed with its place in the source, never guessed.
- **Ownership** is per field: TrialBox or one source. A source-owned change is taken. A TrialBox-owned field is pushed
  when it changed. A different value on the other side is a **conflict**: listed once, never forced, closed by a
  person (keep TrialBox's or take the source's), and the trail kept.
- **Sync** runs at 03:00 and on a button. Pages: Sources, Trial-record differences (`/studies/<study>/conflicts`;
  named "Conflicts" before T-201, FIT-018), Forms; the same calls under `/api/v1`.
- **Exports:** CDISC ODM 1.3, REDCap CSV and XLSX (D-129). An ODM export re-imports into the REDCap simulator with
  every value equal (`e2e_simple` stage 10).
- **Adverse events and CDISC scope** ([D-396](../decisions/D-396-ae-grading-cdash-ie-ds.md)). AE terms are kept as
  written (CDASH `AETERM`); MedDRA coding is done by the sponsor or the data centre, not by TrialBox. An oncology study
  names its CTCAE version (5.0 or 6.0) when it adds the built-in forms, and each AE then records a CTCAE grade 1 to 5
  with that version. The CDISC export (`export.cdisc.odm.xml`) is the ODM with CDASH tags on the built-in items and
  CDASH IE rows (the criterion a screen failure did not meet) and DS rows (consent, screen failure, completion,
  withdrawal) from the screening log. CDASH covers DM, VS, LB, MH, CM, SV, AE, IE and DS here; EX, SDTM datasets,
  Define-XML and CDISC Controlled Terminology files are out of scope.
- **Imports and the sponsor's words** ([D-435](../decisions/D-435-odm-import-sponsor-readers.md)). An ODM 1.3 file
  (`POST /studies/<study>/edc/import/odm`) becomes open EDC drafts that cite the file (sha256 and the place of each
  value); a person confirms and signs them as any draft, and nothing is signed by the import. The file is read with
  expat (no DTD, no entity), bounded (`TB_EDC_ODM_MAX_BYTES`), decoded by D-215, and refused whole with a named
  `odm.*` reason (duplicate OIDs or values, repeat keys, items outside the map, a value its field refuses, an unknown
  subject). The sponsor's layout (`/studies/<study>/sponsor/layout`, table `sponsor_layout`) names the screening
  log's columns in the sponsor's words (`screening-log.xlsx?layout=sponsor`) and how to read the sponsor's weekly
  CSV (`TB_SPONSOR_WEEKLY_MAX_BYTES`): `/sponsor/weekly` proposes lifecycle steps, `/sponsor/weekly/confirm` takes
  the ones a person confirms (source `sponsor_weekly`). Nothing is written to the sponsor's EDC.

**REDCap.** Attach a project on the study's set-up page (guided; variable names are read from the dictionary). The
screening write-back fills three fields on TrialBox's own instrument (`tb_screen_date`, `tb_status`,
`tb_status_date`) and never a field REDCap owns; modes `off`, `existing`, `create`. A blank never erases a value
(`overwriteBehavior=normal`). The site's REDCap builder creates the instrument from the dictionary in
`services/rc_sim/fixtures/`. Evidence: `tests/unit/test_rc_writeback.py`, `tests/unit/test_datacore.py`,
`e2e_simple` stages 8 and 9.

**Schema versions and the database image** ([D-204](../decisions/D-204-db-image-and-checksummed-migrations.md)). Every
store's schema versions are whole scripts, append-only, recorded in the store's own `_schema_version` with the
script's sha256 and name (`migrate`, and `migrate_dir` for `NNN_<name>.sql` files, in `libs/tb_common/db.py`); a
changed applied script stops the store at start with `MigrationChanged` naming the store and the version, and a gap
in the versions is refused. Rows from before D-204 are back-filled once (`backfilled = true`), and only when the code
still carries the script of the baseline shipped with it (`libs/tb_common/migration_baseline.py`). So a schema change
is always a new version, never an edit, and `tests/unit/test_migrations.py` pins every store's checksums. The box's
PostgreSQL is `deploy/docker/db.Dockerfile`: Debian `postgres:16` with pgvector and PGroonga, base digest and package
versions pinned in `deploy/images.lock`; `deploy/docker/db-init/` creates both extensions in `trialbox_wf` (schema
`public`, owned by `trialbox` so a restore as `trialbox` re-creates them; reached as `public.vector`,
`OPERATOR(public.&@~)` from a store's schema) on the first start of an empty volume, and `tb-db-check` in the image
says whether they are there. A volume made by the earlier Alpine image is dumped and restored into the new image, not reused (the C
library's collation differs).
