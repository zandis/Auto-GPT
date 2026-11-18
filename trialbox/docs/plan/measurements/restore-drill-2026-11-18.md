# Restore by the runbook alone, timed and compared, 2026-11-18 (card H-33, D-1122)

**Reader:** the integrator, lane D (who own the backup tool, the restore and RUNBOOK §5 and §22) and lane V (who keep
the findings register).

## The answer

- **Where it ran:** the compose test stack (`make up-test`: the stub model, synthetic site A, 600 patients) on this
  machine's own Docker (29.10.0, compose 5.7.1), started inside the session's container. Not a box installed from a
  bundle, not the reference workstation.
- **Did the restore page alone restore the box?** **No.** The first command stops (`trialbox: command not found`).
  After four lifts the page names nowhere (H33-01 to H33-04) and two lifts for this machine, the page's steps
  restored the box to a healthy stack and the restore ended `complete`.
- **Time:** **132.9 s** from the first command of the page to every service healthy: the reinstall stand-in 60.7 s,
  `stop` 2.8 s, `restore` 7.5 s, `migrate` 12.6 s, `start` 14.9 s, the health wait about 32 s. The backup took
  8.4 s (15.5 MB). The second scenario (below) restored in 136.4 s.
- **Stores:** every store **equal** by D-1122: 115 of 134 tables of the trial database and 57 of 60 of the FHIR
  store's byte-for-byte equal, every other table changed only as D-1122 names; every file of nine volumes equal; the
  lake's three missing files are those the backup leaves out.
- **The audit chain:** head `b6a85f56…` (279 lines) before, `5b53034b…` (282 lines) after: the same three files
  grown by the restore's own events; `tools/audit_verify.py` passes on the whole chain before and after.
- **Opt-outs:** the one event is equal; the opted-out patient is still withheld (17 listed, not the patient).
- **Pinned rule sets:** nine rule sets (the eight shipped and the one approved in the console), each at version
  1.0.0 with the same files; the SCREEN after the restore ran on GZQO 1.0.0 as before.
- **Sign-in:** all four roles sign in after the restore with their password and a fresh code. **But the sessions
  opened before the wipe still work after it** (H33-05).

Ten findings: 2 High, 4 Medium, 4 Low, all lane D (the table at the end; `restore-drill-2026-11-18/findings.json` in
the register's `--add-from` form).

## Where it ran, and what "wipe every volume" means here

| | |
| --- | --- |
| Machine | the session's cloud container, Docker 29.10.0 started in it, compose 5.7.1; no GPU, no TPM, no systemd |
| Box | the compose test stack (`deploy/docker-compose.yml` + `docker-compose.test.yml`, profiles `stub` and `test`), named in `deploy/.env` by `COMPOSE_FILE` and `COMPOSE_PROFILES` as an installed box names its files; `TB_ENV=TEST`; `TB_CONSOLE_MFA=totp` |
| Images | `make images` at master `a4aa0be1` (`trialbox-py`, `trialbox-jvm`, `trialbox-postgres:16-1`), the third-party images by their pinned digests |
| Code | master `a4aa0be1` plus this card's tool (`run.json`'s `head` is the commit the run started from) |
| Wipe every volume | `docker compose --project-directory deploy down --volumes --remove-orphans` (the eleven named volumes: `db-pg`, `console-data`, `objects-data`, `lake-data`, `audit-data`, `orch-data`, `rulesets-data`, `mail-data`, `tb-secrets`, `tb-terminology`, `traces-data`), then `docker volume rm` of any left (the backup job's `trialbox_tb-secrets`, which compose does not own), and the bind-mounted object folder `deploy/.objects` emptied. Checked after: no volume and no object left |
| Not wiped | the release folder: `deploy/` with its `.env`, `secrets/backup.pub`, `site/`; the test stack's host keys in `.cache/test-secrets`; Mailpit's mail (the test sink, outside the box) goes with its container |

The night's work before the backup, each through the box's own doors: the ingest of synthetic site A (lake and FHIR
store, 18,580 resources); five accounts (`admin`, `coordinator`, `investigator`, `viewer`, and a `steward` to keep the
opt-out register), each with an authenticator; a SCREEN by mail on the pinned rule set GZQO 1.0.0 (18 listed, the list
mailed as an encrypted file with its password mail); the steward's opt-out of one listed patient on `/site/opt-outs`; a
second SCREEN (17 listed, the patient withheld); a study's criteria pasted by the coordinator, drafted by the stub,
named to its PI by the steward and approved by the investigator (rule set SITE5B 1.0.0); the set-up's uploads (two
charts pasted, the IT dump and the PI's sheet uploaded). The stack has no OMOP schema and no vector store (the test
stack's embed service holds none); the mail volume stays empty (the box sends; the outbox is in the database).

## What was followed

The restore page is RUNBOOK §5 from **Restore.** (`docs/runbook/05-updates-backup-restore-secrets.md:175`) to
`## Secrets`, at master `a4aa0be1`. `python -m tools.restore_drill extract` lists its 17 commands by H-22's rule
(D-1136, imported) with one head added, `trialbox `. The path the follower walks (`python -m tools.restore_drill
plan`): the preamble's `backup-verify`; step 1, reinstall; step 2, stop all but `db`; step 3, the restore; the line
the restore prints for the role script, when it prints one; `python3 -m tools.trialbox migrate` (the paragraph
"Database roles after a restore"); and step 2's "Start them again". Steps 4 to 6 say what the restore does and
prints; the follower reads the restore's output for them.

The follower supplied only what the page names: the newest backup on the off-box target and the key "from the
envelope" (here `/media/usb/trialbox-backup.key`, the path §5's `backup-keygen` line writes it to), the pack folder
`deploy/refdata/loaded` (empty: the backup named no pack), and `TB_DB_ROLES_CMD` as the "Database roles" paragraph
writes it. The backup before it was taken as §5's Backup paragraph says: `backup-keygen` once, `TB_BACKUP_TARGETS`
(two folders, one marked `.trialbox-offbox`) in `deploy/.env`, `backup-nightly` by hand.

## The follow, command by command (run C)

| # | Step | The page's command | As run | Exit | Seconds | Lift after it |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | preamble | `trialbox backup-verify <file> --key <private key>` | as written | 127 | 0.0 | `trialbox-command` |
| 2 | preamble | the same | `python3 -m tools.trialbox backup-verify …` | 1 | 0.1 | `host-python` |
| 3 | preamble | the same | the same, the release's Python first on PATH | 0 | 0.6 | – |
| 4 | 1 | "Reinstall (§1) and put each `<pack_id>.tar` in `deploy/refdata/loaded`" | `make up-test` | 0 | 60.7 | (machine) `reinstall-test-stack` |
| 5 | 2 | `docker compose stop $(docker compose ps --services \| grep -vx db)` | as written, from `/opt/trialbox` | 1 | 0.2 | `compose-project` |
| 6 | 2 | the same | with `--project-directory deploy` in both | 0 | 2.8 | (machine) `objects-bind` |
| 7 | 3 | `trialbox restore <file> --key <private key> --yes [--refdata <folder>]` | `python3 -m tools.trialbox restore … --yes --refdata deploy/refdata/loaded`, `TB_DB_ROLES_CMD` set | 1 | 1.1 | `restore-db-url` |
| 8 | 3 | the same | with `TB_DB_URL` and `TB_HAPI_DB_URL` on the stack's published port | 0 | 7.5 | – |
| 9 | Database roles | `python3 -m tools.trialbox migrate` | as written | 0 | 12.6 | – |
| 10 | 2 | "Start them again after the restore." (no command) | `docker compose --project-directory deploy start` | 0 | 14.9 | – |

The restore printed `complete: true`, `service_roles: applied`, `to_reapply: []`, `optouts_after_backup: counted, 0`,
`jobs_failed: []`, `hold: released`, and kept the box it replaced in `deploy/pre-restore` (the drill removes that copy
after each run). The lifts, from `tools/restore_drill.py` `LIFTS`:

| Lift | Kind | What it supplied | Where that is said |
| --- | --- | --- | --- |
| `trialbox-command` | page | `python3 -m tools.trialbox <sub>` for `trialbox <sub>` | §5's Backup paragraph; no `trialbox` program exists |
| `host-python` | page | a python3 with the release's packages (here its virtual environment) | the tool's own `ModuleNotFoundError` |
| `compose-project` | page | `--project-directory deploy` | §5's other compose lines; H22-compose-cwd-unstated |
| `restore-db-url` | page | `TB_DB_URL`, `TB_HAPI_DB_URL` naming databases the host reaches | the restore's own message; `tools/trialbox/backup.py`'s opening |
| `reinstall-test-stack` | machine | `make up-test` for §1's install | D-1122: §1 is H-22's card |
| `objects-bind` | machine | `TB_BACKUP_DIRS` with `objects` at `deploy/.objects` | only the test stack binds the object volume to a folder; run 2 of this card restored the objects under the volume's mount point, where the bind hid them |

## The comparison (run C)

D-1122 says what equal means; "changed as D-1122 names" lists each table with its rows before and after.

| Store | Before | After | Equal? |
| --- | --- | --- | --- |
| database `trialbox_wf` | 120 tables, 1,866 rows | 134 tables, 1,875 rows: 115 equal; 14 EDC tables made by `migrate` (8 rows in `edc._schema_version`, the rest empty); `audit.journal` 279 → 280 and `app.flag_event` 9 → 11 (the restore's events and its hold); `orch.pool` 18 → 17 and `orch.judged_pairs` 30 → 29 (the opted-out patient's rows, cleared again after the restore as §5 says) | **yes** |
| database `hapi` (FHIR store) | 60 tables, 303,027 rows | 57 equal; `bt2_work_chunk` 81 → 84, `bt2_job_instance` 3 → 3 (another hash), `trm_valueset` 6 → 3: the FHIR server's own batch and terminology work when it starts, after the restore's own row check passed | **yes** |
| volume `audit-data` | 3 files | the same 3, each grown from the same start | **yes** |
| volume `console-data` (the TOTP key) | 1 file | 1, equal | **yes** |
| volume `lake-data` | 80 files | 78: 77 equal; missing the older generation `db/gen/…g1.duckdb`, a reader link `db/.open/…` and `.rebuild.lock`, all left out by the backup (H33-09); one new reader link | **yes** |
| volume `objects-data` (uploads, job inputs and outputs) | 30 files | 30, equal | **yes** |
| volume `orch-data` | 48 files | 48, equal | **yes** |
| volume `rulesets-data` | 609 files | 609, equal | **yes** |
| volumes `mail-data`, `tb-secrets`, `tb-terminology`, `traces-data` | 0 files each | 0 each | **yes** (empty on this stack) |
| the audit chain's head | `b6a85f56…`, 279 lines | `5b53034b…`, 282 lines; the chain before is the start of the chain after; `audit_verify` passes | **yes** |
| the opt-out list | 1 event | the same event | **yes**; the SCREEN after lists 17, not the patient |
| the approved rule sets | 9 at 1.0.0, files hashed | the same | **yes**; the SCREEN after ran on GZQO 1.0.0 |
| the accounts | 5 (row hash each) | the same 5 | **yes** |
| sign-in, four roles | each signs in with password and code | each signs in with password and a fresh code | **yes** |
| a session from before the wipe | open (4) | **still works** (4 of 4: `/account` answers 200) | **no**: H33-05 |

Each run of the card keeps the same shape: run A (before the wipe removed the backup job's left-over volume by name)
gave the same comparison, 127.5 s for the restore and the same four old sessions answering 200. The record of run C
is `restore-drill-2026-11-18/run.json` (counts and hashes only; no password, key, code, cookie, row or pseudonym).

## A backup taken while a job runs (run C, part B)

The stub was slowed to 2 s an answer and a SCREEN sent by mail. While it ran, `backup-nightly` was run with
`TB_BACKUP_JOB_WAIT_S=0` (§5: the nightly waits up to 6 h for a running job, then goes on; the drill does not wait).
`deploy/site/backup-last.json` recorded the job beside it (`beside_jobs`: 1 SCREEN, waited 0.3 s). The job then
finished and its list was mailed once. Every volume was wiped again and the restore followed by the page again (the
same six lifts), 136.4 s to a healthy box. The restore listed the job under `jobs_failed`, the job reads `failed`
after the restore (it was `running` in the backup), the orchestrator did not run it again in the next 60 s, and no
second list mail went out. §5 step 6 holds as written. One thing for the reader: the job's list had in fact been
mailed before the wipe, and the box now calls that job failed ("Ask the requester to send a request again if it is
still wanted"); nothing tells the requester the earlier list was complete.

## Findings

Severity is the register's rule (`docs/handover/findings-register.md`): High, a box that cannot be restored; Medium, a
person slowed or misled, or a document's claim not true; Low, wording. The owning lane of the runbook and the backup
tool is D.

| Id | Step | The page says | What happened | Expected, and its source | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- |
| H33-01 | preamble, step 3 | "`trialbox restore <file> --key <private key> --yes [--refdata <folder>]`" (§5:188) | `bash: trialbox: command not found` (127) for `backup-verify` and `restore`; the working form `python3 -m tools.trialbox` is only in §5's Backup paragraph | a command the host runs as written; the hub (commands from `/opt/trialbox` as root) | Medium | D |
| H33-02 | preamble, step 3 | "To see which pack: `trialbox backup-verify <file> --key <private key>` lists it" (§5:177) | `ModuleNotFoundError: No module named 'zstandard'` on a python3 with §1's host packages (PyYAML, cryptography); psycopg, which the restore's row check uses, is missing too. Shown on this machine's python3, not on Ubuntu 24.04 itself | the host §1 step 1 prepares runs the page's commands, or the page says where they run; §1:96, `pyproject.toml` | **High** | D |
| H33-03 | step 2 | "`docker compose stop $(docker compose ps --services \| grep -vx db)`" (§5:184) | `no configuration file provided: not found` from `/opt/trialbox`, nothing stopped | every service but `db` stopped; §5's other compose lines; H22-compose-cwd-unstated | Medium | D |
| H33-04 | step 3 | "`trialbox restore <file> --key <private key> --yes [--refdata <folder>]`" (§5:188) | `restore: TB_DB_URL is not set: nothing to back up from the database`; `deploy/.env`'s URL names the host `db`, which only the compose network resolves, and the box's compose file publishes no database port. With both URLs on the test stack's published port the restore ran and ended complete | the page names what the restore needs to reach the databases, or the restore finds them as `backup-nightly` does (`docker compose exec db`); the restore's message, `tools/trialbox/backup.py`'s opening | **High** | D |
| H33-05 | after the restore | "Each database is emptied, restored and its rows checked before any folder moves" (§5:192) | four console sessions opened before the backup answer 200 after the restore (it took about two minutes, inside the 10-minute idle limit) | a restored box has no session from before; card H-33; D-279 (a new password ends every session) | Medium | D |
| H33-06 | step 3 | "`TB_DB_ROLES_CMD="docker compose --project-directory deploy exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh"`" (§5:244) | named only in the paragraph after the six steps; the follower read ahead and set it (`service_roles: applied`); a restore without it was not run (a TEST box) | what step 3 needs is in step 3; the paragraph itself ("Without it a PRODUCTION restore ends NOT complete (exit 4)") | Medium (hypothesis) | D |
| H33-07 | step 2 | "Start them again after the restore." (§5:187) | no command; the follower ran `docker compose --project-directory deploy start` after `migrate`, every service healthy | the command, and that the role script and `migrate` come first; §5's own later paragraph | Low | D |
| H33-08 | steps 4 to 6 | "4. **Events after the backup (D-455).**" (§5:201) | two step 4s (§5:198 and §5:201) | one number per step | Low | D |
| H33-09 | the comparison | "the lake's `tmp/` spill and half-built snapshots" (§5:84) | the older lake generation, a reader link and the lock file are not back; `backup-verify` lists the first two as excluded; §5's list does not name them | the page's list of what is left out matches the manifest's | Low | D |
| H33-10 | §22 around the restore | "**Drill (T-213b):** `test_runbook_22_restore_timed` (Docker drill: …" (§22:9) | no test of that name, nor `test_runbook_22_replacing_hardware`, exists; the names are only in the runbook and the two tabletop records | a drill the page names exists, or the page says it does not yet; plan 8 §8c | Medium | D |

Not findings, for the record:

- RUNBOOK §22 says "No restore has been measured yet". This card measures one, on the stub stack with 600 synthetic
  patients on one machine: 132.9 s from the page's first command to a healthy box, of which the restore command
  itself is 7.5 s. It is not §22's RTO (a reinstall from the bundle, the 50,000-patient set, the hospital's share).
- Before the backup the box still held the opted-out patient's rows in `orch.pool` and `orch.judged_pairs` (the
  opt-out had been recorded a minute earlier); after the restore they were cleared, as §5 says the worker does.
- Every restore keeps the box it replaced in `deploy/pre-restore` (its default `--keep-to`), inside the release
  folder; in this checkout that folder is not git-ignored, so the drill removes it after each run.

## Could not be run here

- **A box installed from the bundle (§1).** Step 1's reinstall ran as `make up-test`. H-22 and H-24 follow §1.
- **A box whose keys differ.** What the pages say: §5 step 3 refuses a backup of another site unless `--other-site`;
  §5 step 5 says that on "a new machine, or a box with no register" the opt-outs recorded after the backup are
  `unknown` and must be entered again from the office's records; §22 "Replacing hardware" says the new box unseals
  the old box's KEK from the stewards' shares or the passphrase (§23), since a TPM-sealed KEK only unseals on its own
  board. The test stack keeps its site keys in a host folder (`.cache/test-secrets`), not in the secrets volume, and
  has no KEK, so a restore onto "other keys" here would test the stack, not the product. Not run.
- **PRODUCTION.** The box ran `TB_ENV=TEST`: the off-box target rule, the alert route and the PRODUCTION-only
  "NOT complete" of a restore without `TB_DB_ROLES_CMD` (H33-06) were not exercised.
- **Ubuntu 24.04 as the host.** H33-02 is shown on this machine's python3; the clean host image of the box
  rehearsal was not built for this card.
- **WAL archiving and a point-in-time restore** (§5 steps 1 to 5 of "Point-in-time restore"): off on the test stack.
- **The vendor reference pack.** The test stack loads none; the backup named none, so step 1's pack and step 4's
  missing pack were not exercised.
- **OMOP and the vector store:** neither exists on the test stack.

## Run it again

`make restore-drill` (root, Docker, `make images` first; about 11 minutes): it sets the stack's names in
`deploy/.env`, links `/opt/trialbox` to the checkout when that path is free, does the night, the backup, the wipe,
the follow and the comparison, then part B, and writes the record to `RESTORE_DRILL_OUT`. `python -m
tools.restore_drill compare <record>` prints the comparison table. `tests/unit/test_restore_drill.py` holds the
follower, the comparison rules and this page's findings file on stand-ins.
