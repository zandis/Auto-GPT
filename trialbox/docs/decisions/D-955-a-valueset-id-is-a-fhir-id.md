# D-955 A ValueSet id is a FHIR id

- **Task:** G1 of the integrator's second review of the P1b run (#639, 2026-11-16). `vs_resource_id` built `<ruleset>-<name>`, 14 plus up to 60 characters, and so made ids of up to 75 characters, such as NCT00163709's. The FHIR server refuses an id over 64 with HTTP 422. All 12 of the run's protocols with such an id failed: 14 equivalence 422s and 2 approve errors. None of the 63 that screened had one. **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** An id that would be longer than 64 characters, or that holds a character a FHIR id may not, keeps its first 55 characters (those characters made safe) and ends in a dash and 8 hex characters of the whole id's hash.
  - The result is a FHIR id, `[A-Za-z0-9.-]{1,64}`. It is stable, and two different names get different ids.
  - An id that fitted before is unchanged, and so are the shipped rulesets (`build_rulesets --check`).
  - The CQL reads the ValueSet's URL from the resource (`ValueSets.url`), so the library and the server agree.
- **Test:** `tests/unit/test_valueset_id_fits_fhir.py`: any ruleset with a 200-character concept, including CJK, gives a FHIR id.
