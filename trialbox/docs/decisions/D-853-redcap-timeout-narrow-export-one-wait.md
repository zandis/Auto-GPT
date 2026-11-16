# D-853 The REDCap client's timeout is a setting, a rate limit is waited on once, the send exports only its records

- **Task:** EDC-018 (deep review 2026-11-12, Medium; wave 6, now unfrozen by D-527)
- **PR:** this branch (`agent/EDC-018-redcap-timeout-narrow-export`)
- **Date:** 2026-11-16
- **Status:** proposed (merges on green CI)
- **Builds on:** NEW-EDC-7 (the error register), D-521 (REDCap 13.7's rate limit seen), STD-060

## Decision

1. **Timeout.** One REDCap API call may take `TB_REDCAP_TIMEOUT_S` seconds (default 30, was a fixed 10): a hospital
   proxy or a large project is slow. A value that is not a positive number falls back to 30.
2. **One wait, never a loop.** A call REDCap refuses for its rate limit (429, refused before it was read) waits once,
   as long as REDCap's `Retry-After` says (at most 30 s; 5 s when it names none), and is sent again. A 503 is waited
   on again only for a call that writes nothing: a write may have been applied. A second refusal is `RC-RATE`. On
   REDCap 13.7 a burst past the limit gets the client's address banned, so the client never retries more than once.
3. **The send's export.** The lookup of the screening numbers reads the id and the key of every record, no longer
   every sent item of every record; the items are read only for the records the send touches (as before).
4. **Status.** The EDC paths answer a REDCap error with the client register's status (`RC-RATE` 503, `RC-FORBIDDEN`
   403); they said 409 for anything but `RC-UPSTREAM`.
5. Class B (the prefill path, `services/edc/`): no change to who sees patient data, so no adversarial review in the
   build phase (D-511).
