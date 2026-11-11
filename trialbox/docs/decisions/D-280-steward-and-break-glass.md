**D-280 The administrator sees no patient data; one patient or one job opens only through a 60-minute, audited
break-glass grant that the steward reviews; a data-steward role keeps the opt-out register.** Fix group D-280 (FG-K)
of the critical-issues register (`docs/reviews/2026-11-10-critical-issues-register.md` §4.1 PX-6, §7.3, §7.4):
CR-023 and CR-029 (the register's "CR-027" in §7.3 is a slip for CR-029); deep-review findings FIT-020, FIT-022,
ROLE-010 and DATA-025 (the parts in this group). Owner decision OD-5 (2026-11-10) and owner question Q-20 (plan v6).
Plan TB-PLAN-06 §6.2.1. Branch `agent/FG-D280-privacy`. Date: 2026-11-11.

*The problem.* The administrator (the IT operator) held every patient-level right: the candidate rows and the CASE
sheet (`can_view_phi`), chart numbers (`can_reveal`, the registry workbook), the study task "screen", the SAE register
and the opt-out register (CR-023, ROLE-010). There was no steward role (FIT-022, DATA-025) and no break-glass at all
(CR-029). Break-glass was specified three ways (FIT-020); the owner settled it in Q-20: no second person for the
administrator, 60 minutes, steward and PI told at once, steward review within 7 days.

*The administrator.* `User.can_view_phi` and `User.can_reveal` are now the coordinator's and the investigator's only
(PX-6). In `tb_common.authz` the administrator has no study task and no SAE action. The orchestrator's `ID_ROLES` drops
`admin`, so even a console bug cannot get a chart number signed as `admin`. Pages the administrator loses: the job
page's candidate rows, reveal and CASE sheet; the patient page; the registry page and its export; `/sae`; the
excluded list; the opt-out register; the site pages with patient rows (charts, facts, people, patients) and the
patient parts of the "studies" home. The set-up pages without a patient row stay (`site_pages.ADMIN_SETUP`: readiness,
start, codes, checks, sheets, help, practice and their API), and so do operations, accounts, flags and the staff
directory.

*Break-glass (`console.breakglass`, `/breakglass`).* The administrator opens a grant with a reason from
`BREAK_GLASS_REASONS` (support call, data correction, opt-out request, incident, audit request, other) and a written
note of 10 to 300 characters, for one patient (study and pseudonym) or one job. It lasts `BREAK_GLASS_MINUTES` (60)
and ends by itself; the administrator may end it sooner; a new grant ends the one before (one at a time). Under the
grant the administrator opens that patient's page, or that job's page with its candidate rows and CASE sheet, and
reveals a chart number through the one reveal path (`home.apply_reveal`, D-273). A job grant reveals only while that
job is the study's latest list. The reveal is signed with `BREAK_GLASS_ROLE` (`breakglass`), the only administrator
role in the orchestrator's `ID_ROLES`. Audit events: `console.breakglass_open` (reason, note, target, end time),
`console.breakglass_use` (each page or reveal, with the grant), `console.breakglass_end`, `console.breakglass_notice`,
`console.breakglass_review`; `console.reveal_patient` names the grant. The grants live in the `breakglass` schema of
the trial database (D-126).

*Told at once, reviewed.* When a grant opens, a mail notice of kind `BG` (pseudonym cut to 8 characters, no chart
number; internal addresses only, as N1 and N2) goes to every steward account's mailbox and to the study's PI (the
delegation log's PI today). A failed mail is an audit event; the grant still shows on the lists. The steward's list on
`/breakglass` shows every grant, unreviewed first, marked overdue `BREAK_GLASS_REVIEW_DAYS` (7) after its end. The
steward marks a grant reviewed with a note once it has ended, never their own. An investigator who is a study's PI
reads that study's grants.

*The steward.* `steward` is a console role (`auth.ROLES`, `/ops/users`, `console.cli add-user`, SSO and OIDC maps).
The steward keeps the opt-out register (with the coordinator; the administrator no longer) and the staff directory
(with the coordinator and the administrator), and reviews break-glass. The steward starts on `/breakglass`.

*Chosen against.* A second person before access (TB-PLAN-05 WS-06.6, the 2026-11-09 note): the owner chose review
after (Q-20). A per-request flag on the session instead of a stored grant: a stored grant survives a restart, can be
listed for review and ends at a fixed time. Letting the administrator keep `can_view_phi` and hiding rows in templates:
the property is the one rule every page reads.

*Not in this group (T-102b, T-309).* The steward's own data pages (sources, conflicts, lake and OMOP quality,
exports, every profile and note: URS-STW-02, 04, 08, 09, 11 to 13); a privacy-office role; the opt-out and staff
registers kept *only* by steward or privacy office (the coordinator still keeps them); the monitor grant; CRO and SMO
study scope; the IRB dates and site facts the administrator can still set; the administrator's `can_request` (T-512
owns that line); the audit browser restricted to privacy office and steward (T-211c). T-309 keeps: the break-glass rule
for a non-admin reader outside their own lists (with a second person, URS-STW-10), a home-page tile for the steward,
the matrix rows in `authz_matrix.yaml` when T-102a lands, and a weekly digest of unreviewed grants.

*Evidence.* `tests/console/test_d280_breakglass.py`; the console tests that used the administrator as a patient-level
reader now use a coordinator and assert the administrator's 403 (`test_console_app.py`, `test_d273_privacy_guards.py`,
`test_data_pages.py`, `test_entry_pages.py`, `test_lifecycle_pages.py`, `test_excluded_page.py`,
`test_sae_record.py`); `tests/unit/test_migrations.py` pins the new schema.
