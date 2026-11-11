# D-380 Roles from the matrix: steward, privacy office, monitor grant, an administrator without patient rows

- **Task:** T-102b (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4; second third of T-102)
- **PR:** this branch (`agent/T-102b-roles`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-023, CR-024 (second third), FIT-022, FIT-002 (grant half), ROLE-005, ROLE-008, ROLE-009, ROLE-010
  (the part outside break-glass), ROLE-011, ROLE-015, ROLE-018, DATA-025. Builds on D-280 (fix group) and D-366
  (T-102a).

## Context

D-280 took the patient rights from the administrator and added the steward. It left the registers kept by
coordinators too, an investigator who acts as PI while the log names none (ROLE-008), CRO and SMO accounts that see
every study when no study is typed (ROLE-011), IRB dates any SMO coordinator or the administrator can set silently
(ROLE-015), no privacy-office role and no monitor (ROLE-009, FIT-002), and role descriptions and a menu written by
hand that promise pages the role cannot open (ROLE-018). T-102a found the steward's item catalogue (`/data/items`)
open to the administrator and closed to the steward.

## Decision

1. **Privacy office.** `privacy` is a console role (`auth.ROLES`, the matrix, `/ops/users`, `console.cli add-user`,
   the SSO and OIDC maps). It starts on the opt-out register.
2. **Registers.** The matrix rows `optout.keep` and `staff.keep` grant the steward and the privacy office, and
   nobody else: not a coordinator (hospital or SMO), not the administrator. Lifting an opt-out needs a written reason
   of at least 10 characters (page and API); the reason is in the audit event.
3. **Delegation bootstrap closed.** The investigator's `unlogged` cells are gone from the `task.*` rows, and the
   console's standing names as PI only the PI the log names. While a study's log names no PI, nobody acts as PI: no
   candidate list, no mark, no approval, no run. The steward writes the PI entry from the signed log
   (`delegation.name_pi`); the logged PI keeps the log after that (`delegation.keep`).
4. **Study scope.** An SMO account (affiliation `smo`) and a CRO account (affiliation `cro` or role `cro`) must name
   their studies: `/ops/users` and `UserStore.set_scope` refuse an empty list. An account stored without one sees no
   study (`auth.NO_STUDY` stands for "none"; the orchestrator's actor scope gets it too).
5. **IRB dates.** `irb.edit`: a hospital coordinator or the logged PI; never an SMO or CRO account, never the
   administrator. An approval date needs its approval number; a change to a saved record needs a reason of at least
   10 characters; the API body is the whole record; `console.irb` holds the old values, the new ones, the changed
   fields and the reason. The approach overrides (pseudonyms) on the IRB page show only to a patient-level reader.
6. **Monitor grant (FIT-002, grant half).** Not a role: a `monitor` entry of a study's delegation log names a CRO
   account of the study, the visit dates (an end date is required) and the monitoring-visit id. The logged PI or the
   steward writes it (`monitor.grant`). Under it, `/studies/{rs}/monitor/{record}` and its `/api/v1` twin show one
   subject read-only, without the pseudonym, and only when it is enrolled (`authz.monitor_may_see`: enrolled, on
   study, completed, or withdrawn after an enrolment). A candidate or a screen failure is refused; each view and each
   refusal is audited with the visit id. The matrix gains the condition `monitor`.
7. **The administrator without patient rows.** Besides D-280: the audit trail hides pseudonyms from a reader
   without `audit.ids` (the administrator), the IRB page hides the overrides, the staff directory and the item
   catalogue are no longer the administrator's, and the EDC cells of administrator, steward and privacy office are
   `false` (they never hold a study task). A test walks every page and API the administrator may open after
   patient-level activity and finds no pseudonym.
8. **Generated descriptions and menu (ROLE-018).** `authz.role_rights(role)` lists the rows a role may take; the
   role descriptions on `/ops/users` are built from it with one translated label per row or row group
   (`console.i18n_roles`). The menu asks `permit` for the items that have a row (SAE, registers, break-glass,
   accounts, item catalogue), and a study-scoped account sees no runs, cascade, mailbox or audit links (the routes
   already refuse it).
9. **`/data/items`** is the steward's (`items.view`).

## Chosen against

- A sixth global `monitor` role: FIT-002 asks for a grant per study and visit; a CRO account with no grant keeps its
  aggregate-only rights.
- A new table for monitor grants: the delegation log already holds an account, a study, dates and a reference, with
  its history and the monthly comparison.
- Keeping the bootstrap behind a site switch: any doctor could claim an unclaimed study (ROLE-008).

## Not in this card

T-102c: the remaining inline role checks move to `permit` (page and API parity, ROLE-017); the menu's other items.
T-309: break-glass for a non-admin reader; the steward's weekly review of opt-out lifts. T-505b: the demo seeds a PI
entry per demo study (ROLE-008's seed half). T-211c: the audit browser restricted to privacy office and steward.
A confirmation sheet and a source-document reference for an opt-out lift (ROLE-005's remainder), the monitor's EDC
trail and source-reference sheet, and the time box checked against visit dates kept elsewhere.
