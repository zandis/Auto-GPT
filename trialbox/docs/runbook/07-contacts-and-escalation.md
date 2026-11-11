# 7. Contacts and escalation

- Box contact: `settings.site.contact`. Vendor support: send `ingest_report.json`, `docker compose ps` and the failing
  job id, **never** patient lists or the pid map.
- Suspected PHI exposure: stop mail (`docker compose stop mail-gateway`), keep the box running for the audit, follow the
  hospital's incident procedure. The audit shows every output file, its sha256 and its recipients.
