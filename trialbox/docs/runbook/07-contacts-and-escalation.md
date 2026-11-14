# 7. Contacts and escalation

**Reader:** the box owner.

- Box contact: `settings.site.contact`. Vendor support: send `ingest_report.json`, `docker compose ps` and the failing
  job id, **never** patient lists or the pid map.
- Suspected PHI exposure: stop mail (`docker compose stop mail-gateway`), keep the box running for the audit, follow the
  hospital's incident procedure. The audit shows every output file, its sha256 and its recipients.
- The incident plan (severity, roles, clocks, the six cases, the first-hour commands, notice templates in ja and
  zh-TW): `docs/plan/sites/incident-response.md` (T-318). Aimedics tells the hospital within 1 hour for S1.
- Who answers, when, how fast, and the supervised remote session: §21. A lost or stolen box: the lost-box list of
  §23, the same day. The sheet to keep by the box: `docs/plan/sites/support-sheet.md` (en, ja, zh-TW).
