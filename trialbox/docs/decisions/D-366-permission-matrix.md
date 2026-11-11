# D-366 One permission function over a permission matrix

- **Task:** T-102a (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4; first third of T-102)
- **PR:** this branch (`agent/T-102a-permit`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-024 (first third), ROLE-009 (model half). Takes the place of the reservation D-302 (the integrator gave
  this card D-366).

## Context

Who may do what was spread over seven role tables and helpers in `tb_common.authz` (`ROLE_COMMANDS`,
`INVESTIGATOR_RUNS`, `ROLE_STUDY_TASKS`, `edc_allowed`, `ROLE_SAE_ACTIONS`, `ROLE_ADMIN_ACTIONS`, break-glass
constants) and six role properties of `console.auth.User` that compared the role by hand (CR-024, P-30). There was no
one function to ask and no table to read (ROLE-009).

## Decision

1. **The matrix is data.** `libs/tb_common/authz_matrix.yaml` lists the console roles (equal to
   `console.auth.ROLES`) and every action with one cell per role. A cell is `true`, `false` or a list of conditions on
   the account's standing in the study: `pi`, `task:<t>`, `logged_pi`, `logged_tick`, `unlogged`. The file is checked
   at load: total, known conditions only; a broken matrix stops the service at import.
2. **One function.** `tb_common.authz.permit(role, action, standing) -> Decision` reads it. Pure: no audit, no I/O;
   the caller audits. A role or an action not in the matrix is refused. The `Decision` names its basis (`role`, the
   condition that granted, or why it refused) for the caller's audit event.
3. **Wrappers, same answers.** `can_request`, `role_allowed`, `study_tasks`, `edc_allowed`, `edc_role_may`,
   `sae_allowed`, `admin_allowed` and the `User` properties `can_request`, `can_view_phi`, `can_reveal`, `can_mark`,
   `can_approve`, `aggregate_only` are thin wrappers over `permit`. Their old tables are read from the matrix at
   import, for the callers that list them. A test compares every wrapper with the rule before T-102a over every role
   and every standing, so D-280 (the administrator has no patient row; break-glass; the steward) and T-512 (the PI's
   runs, the `run` tick) hold unchanged. T-512's `INVESTIGATOR_RUNS` is now the investigator cells of the
   `command.*` rows; a different answer to Q-04 is a change to those cells.
4. **Three wrappers deprecated.** `study_tasks`, `edc_allowed` and `edc_role_may` keep their present callers
   (`console.team`, `console.edc_pages`, `orchestrator.edc_api`); a test fails when another module calls them. New
   code calls `permit`.
5. **The role x route matrix is a test.** `tests/console/test_role_route_matrix.py` walks every console route as
   every role (TB-DR-02b §4's form, a steward column added) and compares the answers with the committed design table
   `tests/console/data/role_route_matrix.md`; a route whose guard is one matrix row must refuse exactly the roles
   `permit` refuses. A meant change regenerates the table in the same PR.

## Chosen against

- A matrix in Python: data can be listed, diffed and turned into the role pages (T-102b) without reading code.
- Moving the call sites now: that is T-102c (54 inline checks, one PR per page group). Here only the helpers move.
- Unknown roles kept as before in `edc_allowed` (an unknown role with the `enter_data` task was let in): `permit`
  refuses any role not in the matrix. No caller passes such a role.

## Not in this card

T-102b: the privacy-office and monitor roles, the IT administrator, opt-out and staff registers kept only by steward
or privacy, generated role descriptions and menus. T-102c: the call sites, the grep test for inline role checks,
page and API parity (ROLE-017). T-309: `console.breakglass` asks `permit` for its `breakglass.*` rows (the rows are
here; the page still checks the role itself).
