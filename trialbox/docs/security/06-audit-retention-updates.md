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
  Every deletion is audited with the object's sha256.
- **Updates.** Offline, signed (Ed25519), never automatic; verified in a container with no network; tampered,
  unsigned, foreign-key, path-traversal and symlink bundles are refused; backup and rollback point first (D-77,
  D-138). Not done: anti-rollback, key id and expiry in the manifest (review F-15).
- **Backups** are encrypted to a key the box does not hold (D-126).
