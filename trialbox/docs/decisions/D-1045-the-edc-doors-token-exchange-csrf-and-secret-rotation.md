# D-1045 The EDC door binds a code to its client and redirect, checks CSRF on tool calls, and rotates its event secret

- **Task:** E-EDCB-3 (the owner's ruling D-1060, relayed by the integrator; third of four cards)
- **PR:** this branch (`agent/E-EDCB-3-edc-token-csrf-rotation`), stacked on E-EDCB-2
- **Date:** 2026-11-17
- **Status:** proposed (merges on green CI)
- **Builds on:** D-1042, D-1043, D-1044, D-1033

## Decision

1. **A code is bound to its client and its redirect.**
   - `oidc.authorize_redirect` records the client id and the redirect a code is issued for (the columns of D-1044).
   - `POST /api/edc/oidc/token` needs `client_id`, `client_secret` and `redirect_uri`, through the new
     `oidc.redeem(code, client, redirect_uri)`.
   - A wrong client id or secret is 401, refused before the code is touched.
   - A missing redirect, or one that is not the code's own (even one on the allowed list), is 400 `invalid_grant`.
     The code is spent by that attempt.
   - Comparisons are constant-time.
2. **CSRF on tool calls.** `POST /api/edc/tools` needs the session's CSRF token (`X-CSRF`), as the map's `PUT` and
   the confirmation already did. Without it the answer is 400 and nothing is held or sent.
3. **The event secret rotates.** `TB_EDC_EVENT_SECRET` holds one secret, or `current,previous`.
   - While it holds two, a signature under either is accepted. Both are always computed, so the time taken does not
     say which one matched. A third value is not read.
   - `docs/data/13` ("Changing the event secret") gives the steps: set `new,old`, change the EDC, wait for its outbox
     to drain, then set `new` alone. From then on the old secret is 401.
4. **#895's hand-off is on master.**
   - `docs/data/14-edc-integration-handoff.md` and `AGENTS.md` come from #895.
   - The open gap it named (codes in memory) is marked closed by D-1044.
   - Its checklist is brought up to date.
   - Its link to the EDC's private repository is replaced by the repository's name.
   - Both state the firewall of D-1060.
5. **A question for the owner, through the integrator (D-1060).** #895 reported that the EDC's contract test redeems
   a code. If the EDC's client does not send `redirect_uri` at `/token`, item 1 refuses it (400) until it does. The
   code's binding is what the owner asked for, so TrialBox does not relax it.
