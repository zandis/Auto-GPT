# D-425 Every console call site asks `permit`: no inline role check, no team fallback

- **Task:** T-102c (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5; last third of T-102)
- **PR:** this branch (`agent/T-102c-permit-migration`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-024 (last third), CR-018 (the delegation rule on sibling pages, long-term half), ROLE-017. Builds on
  D-366 (T-102a, one permission function) and D-380 (T-102b, roles).

## Context

T-102a put every role right in `authz_matrix.yaml` behind one function, `tb_common.authz.permit`. T-102b added the
roles. About 50 checks in the console pages still compared the role by name (`user.role == "cro"`,
`role in ("admin", "viewer", "coordinator")`), and the delegation rule had a fallback: while no team store was wired
(`h.may is None`), every investigator passed. The page and its API could disagree: the PI was refused
`/studies/{rs}/screening-log.xlsx` but read `/api/v1/studies/{rs}/screening-log`; the administrator downloaded the
XLSX (pseudonyms, screening numbers) that the page refused it (ROLE-017).

## Decision

1. **One question.** `console.home.Helpers.permit(user, action, rid)` reads the account's standing in study `rid`
   from the delegation log and asks `permit`. Pages and `/api/v1` ask it (or `permit` with a standing they already
   hold). No study, a study the account does not see, or no log store: no standing, so no condition holds.
2. **No team fallback.** `h.may` is gone. The delegation rule (`delegated_ok`) applies to the roles whose `task.*`
   cells are conditions in the matrix (`authz.conditional`), not to a role named in code.
3. **New rows** for the checks that had none: `report.sponsor_form` (CRO), `report.office` (admin, coordinator,
   viewer), `study.setup` (coordinator), `site.setup` (coordinator, admin), `sae.ack` (investigator),
   `delegation.check` (coordinator, the logged PI), `referral.answer` (coordinator, an investigator ticked for
   `refer`). Each gives the answer the inline check gave; their labels are in the three languages.
4. **Who may be on the log** is read from the matrix too: a PI or sub-investigator entry names an account whose
   `task.*` rows the log decides; a monitor entry names an account whose `monitor.read` row is a monitor grant.
5. **ROLE-017.** The screening-log page, its XLSX and `/api/v1/studies/{rs}/screening-log` ask one question
   (`Helpers.need_rows`: `phi.view`, then the delegation log). The logged PI now gets the XLSX; the administrator no
   longer does (D-280: no patient-level row). The research-office counts (page and XLSX) are one row,
   `report.office`; the PI is still refused them, because they count every study of the site.
6. **Held by a test.** `tests/unit/test_t102c_permit_sites.py` fails on any comparison of a role with an account
   role's name in `services/console`, and on a `may is None` fallback. `tests/console/test_role_route_matrix.py`
   holds page, XLSX and API to the same answer.

## Chosen against

- Changing the matrix cells of `phi.view` and `sae.view` to carry the delegation condition: the role properties of
  `User` are read without a study, and would answer "no" for every investigator.
- Giving the PI the research-office counts: they cover every study of the site, not the PI's own.

## Not in this card

- The orchestrator's own checks (`services/orchestrator`) and the deprecated wrappers `study_tasks`, `edc_allowed`,
  `edc_role_may` stay; their call sites move with the EDC and orchestrator cards.
