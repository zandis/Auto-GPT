# D-1041 An EDC backend selects REDCap or an internal API

- **Task:** REDCap connection for a site on 13.7, and a door for an internal EDC built elsewhere
- **Date:** 2026-11-16
- **Status:** proposed

## Decision

1. `services/edc_backend` is the door. `TB_EDC_BACKEND=redcap` calls the hospital's REDCap.
   `TB_EDC_BACKEND=internal` calls a service that exposes the same documented `/api/`. Unset, `connect()` returns
   nothing and the study link, the data core and the demo are unchanged.
2. The study-link check (`RedcapClient.check_version`) accepts majors 13 to 17 since RC13-F (D-852, the owner's
   D-1024; #813 was written when it was 14 to 17). The new door accepts
   13 to 17, because the methods it calls are on 13.7. The page is not switched over in this change.
3. Plain `http://` stays refused, except loopback for the internal service. The egress guard is unchanged.
   Identifier fields are blanked on export unless the caller says to keep them. Tokens and record values are not
   logged.
4. The internal service is out of this repository. rea (https://github.com/morluto/rea) is not a dependency:
   REDCap's API is documented, and its source is not ours to read or ship.
