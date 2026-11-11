# D-411 Privacy documents per site and the incident plan: severity, clocks, the vendor's hour, the memo slot

- **Task:** T-318, privacy documents, incident plan, one-pager (`docs/plan/28-master-plan-v6.md` §6.2, wave 3; the
  original row in `docs/reviews/2026-11-09-assessment-and-tasks.md` T-318)
- **PR:** this branch (`agent/T-318-privacy-docs`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** OPS-041; CR-096 (incident plan); REG-007 (filing); REG-009 (filing)
- **Replaces:** the reservation D-260 of TB-ASSESS-01 for T-318 (unused)
- **Builds on:** D-311 (no development gates), D-390 (RUNBOOK §21 to §25), D-405 (the support bundle)

## Context

RUNBOOK §7 had one incident bullet ("stop mail"). The plan named the notification clocks (TB-PLAN-05 §9.3) but no
document carried a severity scale, roles, a first-hour list or the six cases of OPS-041. The privacy documents of
WS-13.6 did not exist; the opt-out notices described only counting and listing (REG-009); the legal-basis memo was
planned but card T-646 is struck by D-311 B26.

## Decision

1. **The incident plan is one site document** (`docs/plan/sites/incident-response.md`, TB-SITE-11), in English with
   the severity scale, roles, clocks, six cases and notice template repeated in Japanese and Traditional Chinese.
2. **Four severities, S1 to S4.** S1: patient data left or may have left the hospital's control, or someone controls
   an administrator, steward or host account. When unsure, rate higher; only the hospital's incident lead lowers.
3. **The vendor's clock (C1).** Aimedics tells the hospital within 1 hour of knowing for S1, within 24 hours for S2
   and S3, the next working day for S4. One hour because CGMH's own clock under 資通安全管理法 is one hour.
4. **The hospital is the controller and sends every legal notice** (C2 to C9). Aimedics never notifies a regulator, a
   patient or the press. The legal clocks are the plan's reading, marked "counsel confirms"; nothing waits for counsel.
5. **The six cases** are OPS-041's: privacy breach, lost or stolen box, compromised account, model misbehaviour, data
   corruption, platform incident on the shared host.
6. **Privacy documents live in `docs/plan/sites/privacy/`**, one file per document with a part per site the hospital
   fills; filled copies with names stay at the hospital.
7. **The legal-basis memo is a slot** (`legal-basis-memo.md`) with a filing table. Counsel's signature is a dropped
   gate (D-311 B26).
8. **The one-pager is rendered, not stored** (`tools/onepager.py`), from the site's `settings.yaml` and the
   intended-use statement, so it cannot drift from the box; a rendered page names the site and is kept by the site.
9. **The opt-out notice is rewritten** with eight numbered lines N1 to N8 covering every function REG-009 lists; it
   is not published before the opt-out worker (T-206a, T-206b) passes its test.

## Consequences

- `tests/unit/test_privacy_docs.py` fails if a case, a severity, a role or a clock row is missing from any language,
  or a notice line is missing from any language.
- TB-PLAN-05 §9.3 becomes a pointer to `appi-pdpa-mapping.md` at the plan's next version (not edited here).
- Closing a whole site and decommissioning the box stay with T-628; this card's destruction procedure covers
  study-level lists, removable media and a disk taken out of service.
