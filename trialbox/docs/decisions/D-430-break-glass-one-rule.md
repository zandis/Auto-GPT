# D-430 Break-glass to owner decision OD-5: one rule for every reader, every use on the steward's list

- **Task:** T-309 (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-309-break-glass`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-029 (rest), FIT-020, ROLE-010 (break-glass half). Builds on D-280 (fix group: the administrator's
  grant, the steward, the review) and D-425 (T-102c: every page asks `permit`).

*The problem.* D-280 built break-glass for the administrator only. Break-glass had been specified three ways
(FIT-020); the owner settled it in OD-5 and Q-20: a reason from a fixed list, one patient or one job, 60 minutes,
the steward reviews afterwards, no second person. The plan card asks for one rule for admin and non-admin readers.
The steward's list showed a count of uses, not the uses.

*The rule.* An account reads a study's patients by its own rights (`Helpers.reads`: the `phi.view` row, then the
delegation log) or, outside them, only under an open grant of its own for that patient or that job. The patient
page, the reveal (page, job page and candidate page share `home.apply_reveal`), the job page's rows and the CASE
sheet ask this one question. Who may hold a grant is the matrix row `breakglass.open`: the administrator and the
investigator (an investigator the study's log does not reach). A coordinator reads its studies already; the steward
and the privacy office review and never open; viewer and CRO accounts never. A grant for what the account already
reads is refused (`bg.err.needless`), so a grant is always a step outside one's rights. A grant's study must be one
the account sees (SMO and CRO scope holds). The reveal under a grant is signed `breakglass`, never the account's role.

*Every use listed.* Version 2 of the `breakglass` schema adds `uses` (grant, time, what, study, pseudonym, job). Each
use is one row and one `console.breakglass_use` audit event; the steward's review list shows each use under its
grant, the pseudonym cut to 8 characters.

*Matrix rows.* `breakglass.open` (admin, investigator), `breakglass.read` (the page: admin, investigator, steward),
`breakglass.study` (new: a study's grants, its PI). No inline role check (T-102c's grep test).

*Chosen against.* A second person before a non-admin reader's grant (the 2026-11-09 note, URS-STW-10, D-280's
"T-309 keeps"): the card voids the old contract and OD-5 names no second person; one rule is simpler to test and to
explain. Letting the coordinator open grants: it already reads every patient of the studies it sees, and a grant
cannot widen its study scope.

*Not here.* A weekly mail digest of unreviewed grants and a home-page tile for the steward (the steward already starts
on `/breakglass`, where overdue grants are marked).

*Evidence.* `tests/console/test_t309_breakglass_one_rule.py` (the same test for the administrator and an investigator:
60 minutes, every use on the review list; job grants; the needless grant), `tests/console/test_d280_breakglass.py`,
`tests/unit/test_authz_matrix.py`, `tests/console/data/role_route_matrix.md` (regenerated), `tests/unit/test_migrations.py`.
