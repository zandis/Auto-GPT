# D-1046 `/admin/edc` shows the state of the connection to the owner's EDC

- **Task:** E-EDCB-4 (the owner's ruling D-1060, relayed by the integrator; fourth of four cards)
- **PR:** this branch (`agent/E-EDCB-4-admin-edc-status`), stacked on E-EDCB-3
- **Date:** 2026-11-17
- **Status:** proposed (merges on green CI)
- **Builds on:** D-1042, D-1043, D-1044, D-1045

## Decision

1. **A "Connection" panel at the top of `/admin/edc`**, in en, zh-TW and ja. It says one of these:
   - the EDC's tool URL or token is not set;
   - the EDC did not answer, or refused `GET /api/v1/capabilities` under TrialBox's tool token;
   - it is reachable, and the `trialbox` module is on or off.

   One capabilities read happens per page view, through the same client as the tool calls, and is closed at once.
   The role check is unchanged (`redcap.connection`; another role gets 403).
2. **The EDC's pending and dead-letter counts are not guessed.**
   - #895 names the EDC's status endpoint (`GET /api/v1/trialbox/status`), but neither it nor #813 records the
     answer's shape.
   - The firewall (D-1060) allows no other source. Lane E asked the owner, through the integrator, for the URL, the
     credential and the field names.
   - Until then the panel says the EDC has not reported them. `tools.connection_status` returns `pending` and
     `dead_letter` as None.
   - A small follow-up fills them in from the answer the owner gives, with a test on a recorded example.
3. `tools.http_client()` is the one place the door makes its HTTP client, so a test gives it a mock transport. The
   tool calls use it too.
