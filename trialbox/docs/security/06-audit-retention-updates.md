# 6. Audit, retention, updates

- **Audit.** Append-only daily JSONL, each line hashed with the one before (`tb_common/audit.py`); a torn line is
  repaired, never hidden (D-127). `tools/audit_verify.py` checks it. Archived nightly, compressed and verified;
  never deleted; 10 years on the box (D-138).
- **One audit writer** (D-394, CR-042). The services cannot write the chain. They call `audit.append` in the trial
  database, which adds a row to the append-only `audit.journal` with the database role that sent it; no service role
  may insert, read, change or delete a journal row, and a trigger refuses changes and deletes to everyone. The
  `audit-writer` container alone mounts the audit volume read-write and copies the journal into the chain, in order.
- **Reading the audit** (D-451, ROLE-013). The console's `/audit` is the privacy office's and the steward's only
  (matrix row `audit.browse`); everyone else gets 403, audited. It reads the chain read-only, filtered and paged by a
  cursor in the reader (a day file outside the period is not opened); one patient's report lists every event that
  names a pseudonym and joins in no name or chart number; its CSV goes through the same guard. Every search, report
  and download is an event with its filter (`console.audit_search`, `console.audit_report`), never the result. "Verify
  the chain" calls `tb_common.audit.verify` with the off-box signed heads, as `tools/audit_verify.py --heads` does,
  and records `console.audit_verify`.
- **Retention** by country (wizard defaults, D-138): service logs 365 days; mail logs 5 years in Japan (医師法 §24),
  7 years in Taiwan (醫療法 §70); outputs 365 days; attachments 90 days; snapshots 3 nightly and 36 month-ends.
  A deleted job file is audited with its sha256 (`retention.deleted`), deleted mail-log rows by count
  (`retention.mail`); the host's service-log folders past `logs_days` are deleted with no audit event (finding
  H10G3-01, `docs/handover/security-page-2026-11-18/findings.json`).
- **Updates.** Offline, signed (Ed25519), never automatic: an operator runs `tools/apply_update.sh` (D-77, D-138,
  D-210). The bundle is verified before anything is staged (`tools/verify_update.py`), with the host's python3 when it
  has `cryptography`, else in a container with no network. Refused: a tampered or unsigned bundle, a key the box does
  not trust, a `key_id` that does not name the signing key, a bundle past its `not_after`, a `release_seq` not above
  the installed one (anti-rollback: only `--allow-downgrade REASON` lets it through, audited as `update.downgrade`),
  and a member that is not a regular file or has an absolute or `..` path. Backup and rollback point first (D-126);
  `--no-backup` skips the backup on a DEV, TEST or VALIDATION box, and on a PRODUCTION box only with
  `--no-backup-reason REASON`, audited as `update.backup_skipped` (D-1321).
- **Backups** are encrypted to a key the box does not hold (D-126).
