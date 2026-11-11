# 6. Audit, retention, updates

- **Audit.** Append-only daily JSONL, each line hashed with the one before (`tb_common/audit.py`); a torn line is
  repaired, never hidden (D-127). `tools/audit_verify.py` checks it. Archived nightly, compressed and verified;
  never deleted; 10 years on the box (D-138).
- **Retention** by country (wizard defaults, D-138): service logs 365 days; mail logs 5 years in Japan (医師法 §24),
  7 years in Taiwan (醫療法 §70); outputs 365 days; attachments 90 days; snapshots 3 nightly and 36 month-ends.
  Every deletion is audited with the object's sha256.
- **Updates.** Offline, signed (Ed25519), never automatic; verified in a container with no network; tampered,
  unsigned, foreign-key, path-traversal and symlink bundles are refused; backup and rollback point first (D-77,
  D-138). Not done: anti-rollback, key id and expiry in the manifest (review F-15).
- **Backups** are encrypted to a key the box does not hold (D-126).
