# D-1122 Equal after a restore by the runbook alone: what each store must show

- **Task:** lane H, card H-33 (was lane V's V-9; the integrator: "backup, wipe every volume, restore by the runbook
  alone, timed; compare stores, the chain's head, the opt-out list, pinned rule sets and sign-in")
- **Date:** 2026-11-18
- **Status:** accepted

## Context

`make backup-drill` (`tools/backup_drill.py`) proves in process that a restore puts the rows and files back. It does
not follow the restore page, it does not run on the box's shape (compose, its volumes, its services), and it does
not say how long a restore takes. RUNBOOK §22 says no restore has been measured. H-33 asks for a box backed up as
§5 says, every volume wiped, restored by §5's restore page alone with the clock running, then compared store by
store. "Equal" needs a meaning for each store, because the restore itself writes (its audit events, the hold), the
backup leaves some files out on purpose, and a service that starts again writes its own rows.

## Decision

1. **The box.** The compose test stack on the machine's own Docker (`make up-test`: the stub model, synthetic site
   A), with `deploy/.env` naming its compose files and profiles as an installed box's does, TOTP on. **Wipe every
   volume** is `docker compose down --volumes` (every named volume of the project) and the bind-mounted object folder
   emptied. The release folder (`deploy/`, its `.env`, `secrets/`, `site/`) stays: a box whose data disks were lost
   and whose release was reinstalled the same.
2. **The night's work** fills every store the box has through its own doors: the ingest (lake, FHIR store), five
   accounts (the four roles of the card and the steward) each with an authenticator, a SCREEN by mail on the pinned
   rule set (`GZQO` 1.0.0, seeded approved on a TEST box), the steward's opt-out of a listed patient, a second SCREEN
   (the patient withheld), a rule set pasted by the coordinator, named to its PI by the steward and approved by the
   investigator, and the set-up's uploads (two charts pasted, the IT dump and the PI's sheet).
3. **The backup** as §5's Backup paragraph says: `backup-keygen` once, the targets in `deploy/.env`, `backup-nightly`
   run by hand.
4. **The follower** (`tools/restore_drill.py`) walks the restore page (the paragraph **Restore.** of §5 up to
   `## Secrets`) in order, from the hub's release folder `/opt/trialbox`, as root. Commands are found by H-22's rule
   (D-1136), imported, with one head added: `trialbox `. It supplies only what the page names: the backup file and
   the key (step 3), the pack folder (step 1), `TB_DB_ROLES_CMD` as the paragraph "Database roles after a restore"
   writes it, a line the restore prints for a person to run, and `python3 -m tools.trialbox migrate`. Step 2's
   "Start them again" has no command: the follower runs the inverse of the page's `stop`. Anything else is a
   **lift**, named in `LIFTS`, applied once, recorded, and the first lift of kind `page` is the verdict "the page
   alone did not restore the box". A lift of kind `machine` (the test stack in place of §1's reinstall; this stack's
   bind-mounted object folder) is not a finding.
5. **Equal, per store.**
   - **A database** (`trialbox_wf`, `hapi`): every table's row count and the hash of its rows' sorted hashes, equal.
     Allowed to differ, and listed with the counts: the restore's own rows (`audit.journal`, the hold flag
     `app.flag` and its events), the opted-out patient's rows the opt-out worker clears again after a restore
     (`orch.pool`, `orch.judged_pairs`; §5's own sentence), the EDC tables `migrate` makes where there were none, and
     the FHIR server's own batch and terminology tables it rewrites when it starts after the restore's row check.
     Any other difference is **unequal**.
   - **A volume**: every file's sha256 equal. Allowed to be missing: what the backup leaves out on purpose (the
     lake's spill, older NDJSON, older lake generations, its reader links and lock file).
   - **The audit chain**: the head moves on by the restore's own events; equal means every file of the chain before
     is the start of the same file after, and `tools/audit_verify.py` passes on the whole chain after.
   - **The opt-out list**: every event (patient, action, source, by, time) equal, and a SCREEN after the restore does
     not list the opted-out patient.
   - **The rule sets**: each rule set's approved version and the hash of its files equal, and a SCREEN after the
     restore runs on the same version as before.
   - **Sign-in**: each of the four roles signs in with its password and a fresh code after the restore; a session
     opened before the wipe must not work after it.
6. **A backup taken while a job runs**: the same wipe and restore from a backup the nightly took beside a running
   SCREEN (`TB_BACKUP_JOB_WAIT_S=0` here so it does not wait); the restore must list the job as failed, the job must
   not run again, and nobody is mailed for it a second time.
7. **The record and the findings.** The run record (`run.json`: times, lifts, the comparison, counts and hashes, no
   secret and no row) and `findings.json` (the register's `--add-from` form) sit in
   `docs/plan/measurements/restore-drill-2026-11-18/`; the page beside them is the account. Severity is the
   register's rule (High: a box that cannot be restored; Medium: a person slowed or misled, a document's claim not
   true; Low: wording). The runbook and the backup tool are lane D's. The card reports and fixes nothing.

## Consequences

- `make restore-drill` runs it where root and Docker are (about ten minutes); `tests/unit/test_restore_by_the_runbook.py`
  holds the follower, the comparison rules and the findings file on stand-ins.
- Not to be confused with T-730d's `trialbox restore-drill` (D-892, `tools/trialbox/restore_drill.py`), which
  restores a backup into scratch databases on a live box and leaves the box untouched. This drill wipes a test box
  and restores it by the page.
- The times are of the stub stack with 600 synthetic patients on one machine; they are not RUNBOOK §22's RTO.

## Not done

- A box whose keys differ: the test stack keeps its site keys in a host folder, not in the secrets volume, so the
  restore onto "new keys" would test the stack, not the product; not run.
- A box installed from the bundle (§1): the restore's step 1 ran as `make up-test`; H-22 and H-24 follow §1.
