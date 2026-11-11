# 5. Integration scenarios

From the 2026-11-05 catalogue (full text, with sources: `spec/archive/INTEGRATION_SCENARIOS.md`):

| Scenario | Data flow | Status |
| --- | --- | --- |
| A. Full hospital EMR | nightly export or views, one way in | built: CSV, CGRD views, SS-MIX2, FHIR bulk |
| B. A PI's own registry | periodic import | built: REDCap and sheets, two way |
| C. Consortium, multi-site | per-site boxes, aggregate tables only | COHORT tables and merge; no DP |
| D. Manual entry, referral letters, scans | one chart at a time | built: chart upload and proposed facts; OCR wired but not run on a real scan |
| E. Staged (manual first, EMR later) and air-gapped | start small | supported: a site can start with charts only; offline updates |
| F. Imaging, check-ups, claims, wearables, cloud, SMO or CRO boxes, research zones | other feeds | not built |

Gaps from that catalogue still open: no TOTP in the console; no erasure path for an opt-out (a delta night drops what
the source deleted since D-149, but a patient's facts are not removed from kept snapshots); no SMART Backend Services
client for live FHIR Bulk (the reader takes NDJSON from disk); an IQ/OQ/PQ package is a document, not code.
