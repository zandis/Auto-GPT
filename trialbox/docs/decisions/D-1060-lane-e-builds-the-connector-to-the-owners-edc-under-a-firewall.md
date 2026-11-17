# D-1060 Lane E builds the connector to the owner's EDC, under a firewall

- **Task:** an owner's ruling, numbered by the integrator and relayed by the integrator
- **Date:** 2026-11-17
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-17)

## Ruling

1. The owner has an EDC of his own, a clean-room server with a REDCap-compatible API. TrialBox's side of the link is
   the connector in `services/edc_backend/` and `services/console/edc_door.py`. Lane E builds it.
2. Lane E has examined a licensed REDCap for the hospital's own server (D-1021). So lane E never reads, clones,
   writes to or comments on the EDC's repository; it writes connector code only from the connector's own pull
   requests and the HTTP behaviour their tests and fixtures record; and nothing of its REDCap examination goes into
   any text meant for the EDC side. A question about the EDC goes to the integrator, who passes it to the owner.
3. D-1034 holds: nothing of REDCap's specification enters the repository.
4. D-1033 holds: no REDCap data-entry-trigger receiver. `POST /api/edc/events/v1` is for the owner's EDC only.

## Where the wording comes from

The owner's "both as your advice" of 2026-11-17 in the integrator's session, on the integrator's two questions about
the integration brief for PR #813.

## Used by

D-1043 to D-1046 (lane E's cards E-EDCB-1 to E-EDCB-4).
