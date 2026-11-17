# D-1043 The EDC connector is on master, and it takes only answers that say they are de-identified

- **Task:** E-EDCB-1 (the owner's ruling D-1060, relayed by the integrator; first of four cards)
- **PR:** this branch (`agent/E-EDCB-1-edc-connector`)
- **Date:** 2026-11-17
- **Status:** proposed (merges on green CI)
- **Builds on:** D-1041 and D-1042 (#813's records), D-852 (REDCap 13 supported), D-853 (EDC-018), D-1060, D-1061

## Decision

1. **#813 comes onto master through lane E.** This branch merges #813 (`d34feee5`, written outside the lanes) into
   current master. The owner's branch is not pushed to. #813 is closed when this card merges (D-1061).
   - #813's D-915 and D-916 were held on master by other decisions, so they are D-1041 and D-1042.
   - The external-EDC code stays in `services/edc_backend/` and `services/console/edc_door.py`, apart from the eCRF
     module `services/edc/`.
2. **Fitted to master.**
   - `rc_bridge/client.py` keeps EDC-018's configurable timeout and its one wait on a rate limit, and adds #813's
     loopback address, declared host and file upload. A file upload counts as a write, so it is never sent twice.
   - The study link has accepted REDCap 13 since D-852. The backend's accepted majors are the study link's own
     (13 to 17).
   - Two of #813's tests expected the study link to refuse 13. They now check that both accept 13 and both refuse 12.
   - The DATA index is regenerated.
3. **Only de-identified answers are taken (D-1060).**
   - `ToolClient.call` refuses any tool answer whose `deidentified` is not exactly JSON `true`: false, missing, the
     string `"true"`, 1 or a list are all refused.
   - Nothing of a refused answer is passed on or put in the error.
   - There is no switch to take an identified answer.
   - The rule holds for a confirmed write as for a read.
4. **The firewall (D-1060).** This card was written only from #813 and #895 and the behaviour their tests and fixtures
   record. Nothing was read from the EDC's repository, and nothing of lane E's REDCap notes is in it.

Not in this card:
- the three process-local stores moving to the database (E-EDCB-2);
- the token exchange's bindings, CSRF on the tool route and the event secret's rotation (E-EDCB-3);
- the connection status on `/admin/edc` (E-EDCB-4).
