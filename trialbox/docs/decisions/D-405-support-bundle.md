# D-405 The support bundle: what goes in, what never does, and how it is kept free of patient data

- **Task:** T-209b, support bundle (part b of T-209; `docs/plan/28-master-plan-v6.md` §6.2, the original row in
  `docs/reviews/2026-11-09-assessment-and-tasks.md` T-209)
- **PR:** this branch (`agent/T-209b-support-bundle`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** R-61 / D-23 / MR-074 (no PHI-free support bundle); the bundle half of WS-17.4 and of IT pack §A.8
  (ITP-051)
- **Builds on:** D-178 (the operations snapshot), D-203 (the data-handling scan), D-379 (T-209a: box health),
  D-390 (RUNBOOK §21, the support model)

## Context

RUNBOOK §21 asked the administrator to send `ops status` and `doctor` by hand. Nothing collected the versions, the
update history, the logs, the disks and the audit check together, and nothing redacted `deploy/.env` before it was
sent. A support person who asks for "the logs" could receive an unscrubbed PostgreSQL or HAPI log (OPS-035).

## Decision

1. **One command.** `trialbox support-bundle --out DIR` (`tools/support_bundle.py`) writes
   `trialbox-support-<UTC time>.tar.gz`, 0600, with a `MANIFEST.json` (every file, its sha256 and source; what was
   left out and why; what the scrubber and the scan changed, as counts and pattern ids, never a value).
2. **What goes in.** The operations snapshot (versions, updates, backups by name, secrets by name and age), the
   host's health checks (D-379), the release identity, the last 400 update-history lines, `deploy/.env` with every
   secret-like value redacted, the audit chain's verification (counts and errors only), the output of `doctor
   --json`, `check_host.sh`, `docker compose config` (redacted), `compose ps`, restart counts, `df -h` and
   `nvidia-smi`, the last three collected log days of TrialBox's own services, and any text file named with
   `--add`.
3. **What never goes in.** `/data` and every Docker volume, the secrets folder, keys and tokens, backups, rollback
   dumps, the audit chain itself, the lake, the pid map, `settings.yaml` (it holds the site's contacts), and the
   logs of PostgreSQL, HAPI FHIR and vLLM. The service logs are an allowlist of TrialBox's own services, not a
   denylist. An `--add` path in a refused place (resolved, so a link counts as its target) stops the bundle before
   anything is read.
4. **Kept free of patient data in three steps.** The logs and added files pass the log scrubber
   (`tb_common.logging`) and the site's `mrn_regex`. Then the data-handling scan (`tools.data_scan`) reads every
   file, and each line it flags is replaced by a marker; the run prints which file and which pattern. Last, the
   finished archive is scanned again: a hit there, or a file the scan cannot read, means no bundle is written.
5. **No new setting.** The tool reads `TB_LOG_DIR`, `TB_AUDIT_HOST_DIR`, `TB_BACKUP_TARGETS` and the other paths
   already in `deploy/.env`.

## Consequences

- A ticket carries one file that support can read without a screen share, and the hospital can check it with
  `python -m tools.data_scan <file>` before it is sent.
- A line removed by the scan is lost for diagnosis; the manifest says how many and why.
- Not built here: a `support.bundle` audit event, the admin-page button (T-209c) and the opt-in heartbeat (Q-16).
- Dropped (D-311): no named reviewer for the allowlist.
