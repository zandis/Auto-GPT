# Pre-consent lists: who sees patient rows before consent, as matrix rows for lane C2 (10C-3, lane J, 2026-11-19)

**Reader:** the people who build TrialBox. Lane C2 owns the permission matrix, accounts, the acting role and audit,
and decides every row below. The integrator reads it too; the owner reads section 11.2 only. It is written for
builders, so in one language.

Plan 10 row 10C-3 ([plan 10](../plan/47-plan-10-2026-11-18.md), Track C) comes from card JP-2 of
[root review 11](../reviews/2026-11-root/11-japan.md) (section 10). The card says: a pre-consent candidate list is
visible only to the study's PI, its sub-investigators and the coordinators on its delegation log; the trial office
(治験事務局) sees counts. Its exit: a permission-matrix test per role, and a trial-office account sees no patient row.

**It proposes; it changes nothing.** No role may do or read anything on master that it could not before this page.
The matrix file, its loader, every guard and every page are untouched (section 10 has the proof). Read against master
`a44a39da`. Decision D-1238 records that this was put to C2, with status *proposed*.

**Form.** The same as the multicentre proposals of card 10D-14 (pull request #1121): matrix rows written as YAML blocks
in the matrix's own form, so that an adopting pull request can copy them. This card adds one thing 10D-14 did not have:
a table test that is off by default (section 9), because the card's exit is a test per role.

**Words used here.**

- *Pre-consent row*: one line about one patient who has not given consent, for example a candidate on the weekly list,
  a screening-log line for a person not yet consented, or a not-matched patient. It may carry a pseudonym (an
  eight-character code), a screening number, a chart number, criteria answers or evidence.
- *On the log*: the study's delegation log (the box's copy of the signed 書式2-shaped list, `team.entries`) has an
  active entry for this account today, and the PI ticked the task "screen" for it.
- *Counts*: numbers only, never a row; small cells hidden where the page already hides them.

## 1. The proposal in one table

| Who | Sees pre-consent rows | Sees counts | Today |
| --- | --- | --- | --- |
| The PI the study's log names | yes | yes | the same |
| A sub-investigator on the log with "screen" | yes | yes (the study pages' counts) | the same |
| A sub-investigator on the log without "screen" | no | the study's counts | the same |
| An investigator not on the log | no | the study's counts | the same in the matrix; **one leak in code** (4.1) |
| A coordinator on the log with "screen" | yes | yes | the same |
| A coordinator **not** on the log | **no** | yes | **wider: sees every row of every study its account sees** |
| A coordinator, while the log names no PI | **no** | yes | **wider: sees every row** (an investigator sees none here, D-380) |
| The trial office (治験事務局) | no | the research office's counts | **no such role**; an office account is a `viewer` (right) or a `coordinator` (wider) |
| The administrator | no (break-glass only, audited) | the research office's counts | the same |
| A viewer | no | aggregate reports | the same |
| A CRO account | no (enrolled subjects only, under a monitor grant: after consent) | sponsor-form reports | the same |
| The data steward, the privacy office | no list rows; pseudonyms in the audit trail only (4.6) | none of the study's | the same |

So the matrix is already right for investigators, the administrator, viewers, CRO accounts, the steward and the
privacy office. It **has no** trial-office role. It is **wider** for coordinators, and that breadth is **intended**
today: D-147 item 1 (owner decisions of 2026-11-09) says "Coordinators and administrators keep their role's rights",
and the matrix's own comment says "A coordinator has its row in every study"
(`libs/tb_common/authz_matrix.yaml` line 109). So for coordinators this page proposes to narrow a ruled rule; it does
not report a defect. The header search (4.1) is different: no decision allows it.

## 2. The matrix today, in the terms this page uses

- **Seven roles** [R `libs/tb_common/authz_matrix.yaml` line 31]: `admin`, `coordinator`, `investigator`, `viewer`,
  `cro`, `steward`, `privacy`. One function reads the file (`permit`, `libs/tb_common/authz.py` line 157). A role
  that is not in it is refused every action.
- **The two rows that decide pre-consent rows:**
  - `phi.view` [R `authz_matrix.yaml` line 43]: coordinator `true`, investigator `true`, everyone else `false`.
  - `task.screen`, "see the candidate list of a study" [R `authz_matrix.yaml` line 111]: coordinator `true`;
    investigator `[logged_pi, logged_tick]` (the PI the log names, or a sub-investigator the PI ticked for "screen");
    everyone else `false`.
- **How the log is read.** `standing` (`services/console/team.py` line 153) turns the log into the `Standing` that
  `permit` reads. It takes ticks **only from `sub_pi` entries** (line 167). A `crc` entry carries ticks too (the log
  stores them: `services/console/teamstore.py` line 429; the log roles are `pi`, `sub_pi`, `crc`, `other`,
  `monitor`, line 33), but nothing reads them, because the coordinator's cell is plain `true`.
- **How a page applies the log.** `delegated_ok` (`services/console/home.py` line 210) applies the log only to roles
  whose `task.*` cell is a list of conditions (line 214). For the coordinator it returns yes at once.
- **The only fence for a coordinator today** is the account's own study list (`User.sees_study`,
  `services/console/auth.py` line 379, D-380 item 4). An SMO or CRO account must have one. A hospital coordinator
  account with no list sees every study.
- **Counts:** `report.office` [R `authz_matrix.yaml` line 98]: admin, coordinator, viewer. The feasibility report of
  a study is open to every account that sees the study (`route_actions.yaml`: kind `scope`).

## 3. Inventory: every surface that shows pre-consent rows

Read from the code on master. "Guard" is what the route asks (from `tests/console/data/route_actions.yaml`, checked
against the handler). "Today" uses the columns of the role walk (`tests/console/data/role_route_matrix.md`): `crc` a
hospital coordinator with no study list, `pi` an investigator the log does not name, `lpi` the PI the log names, `smo`
an SMO coordinator scoped to the study. Every surface below is open today to `crc`, `lpi` and `smo` and closed to
`admin`, `pi`, `cra`, `viewer`, `steward` and `privacy`, unless the last column says otherwise.

| # | Surface | Route(s) and handler | Guard today | Proposed | Verdict |
| --- | --- | --- | --- | --- | --- |
| S1 | Weekly list | `GET /studies/{rs}/week` (`services/console/home.py` line 741) | `phi.view` + `task.screen` | log only | coordinator wider |
| S2 | Candidate list and candidate page | `GET /studies/{rs}/candidates`, `/{pid}` (`services/console/team.py` lines 448, 465); `GET /api/v1/studies/{rs}/candidates[/{pid}]` (team.py line 1226) | `task.screen` | log only | coordinator wider |
| S3 | Patient view | `GET /studies/{rs}/patients/{pid}` (home.py line 1099) | `phi.view` + `task.screen` | log only | coordinator wider |
| S4 | This week's list, API | `GET /api/v1/studies/{rs}/patients` (home.py line 1575) | `phi.view` + `task.screen` | log only | coordinator wider |
| S5 | Screening log, page, workbook, API | `GET /studies/{rs}/screening-log`, `.xlsx` (`services/console/screening_log.py` lines 345, 384); `GET /api/v1/studies/{rs}/screening-log` (home.py line 1642) | `phi.view` + `task.screen` (`need_rows`) | log only | coordinator wider |
| S6 | Not-matched list | `GET /studies/{rs}/not-matched` (home.py line 977) | `task.screen` | log only | coordinator wider |
| S7 | Not-matched weekly sample | `GET /studies/{rs}/not-matched/sample` (`services/console/notmatched_pages.py` line 216) | `notmatched.sample` (investigator: `pi` or `task:screen`) | unchanged | right (`lpi` only) |
| S8 | Excluded, history, rescreen, conflicts | `GET /studies/{rs}/excluded` (home.py line 969), `/history` (`services/console/entry_pages.py` line 357), `/rescreen` (home.py line 1074), `/conflicts` (`services/console/data_pages.py` line 376) and the API twin (data_pages.py line 498) | `task.screen` | log only | coordinator wider |
| S9 | Referral list and print | `GET /studies/{rs}/referrals` (team.py line 647), `/referrals/{ref_id}/print` (team.py line 625), API (team.py line 1276) | `referral.answer`; print `task.screen` | log only | coordinator wider |
| S10 | Site patients of one study | `GET /site/patients?study=` (`services/console/site_pages.py` line 686) | `task.screen` (`delegated`, line 695) | log only | coordinator wider |
| S11 | Registry and cohort pages | `GET /pilot/registry/{rs}` (`services/console/app.py` line 2302); `GET /studies/{rs}/cohort` (screening_log.py line 483) | `phi.view` + `task.screen` | log only | coordinator wider |
| S12 | Registry workbook (chart numbers) | `GET /pilot/registry/{rs}/export.xlsx` (app.py line 2429) | `id.reveal` + `task.screen` | log only | coordinator wider |
| S13 | Patient twin, API | `GET /api/v1/studies/{rs}/patients/{pid}/twin` (`services/console/twin_api.py` line 51) | `profile.read` + `task.screen` | log only | coordinator wider |
| S14 | CASE sheet; SCREEN job card rows | `GET /pilot/jobs/{id}/view/{file}` (app.py line 1608, `delegated` at 1624); job page card (app.py line 1828, `reads`) | `phi.view` + `task.screen` | log only | coordinator wider; `admin` only under break-glass |
| S15 | Patient-level job file download | `GET /pilot/jobs/{id}/files/{file}` (app.py line 1939; rule `phi_download_ok`, line 1924) | named recipient + `phi.view` + `delegated_ok` | log only | coordinator wider (when named) |
| S16 | Study export | `GET /studies/{rs}/export.{fmt}` (entry_pages.py line 378), API (entry_pages.py line 472) | `task.screen` | log only | coordinator wider |
| S17 | Reveal a chart number | `POST /studies/{rs}/candidates/{pid}/reveal` (team.py line 478), `POST /studies/{rs}/patients/{pid}/reveal` (home.py line 1117) | `id.reveal` + log, in `reveal.identifier` | log only | coordinator wider. The walk shows `Y` for admin, steward and privacy only because the empty test body is refused (400) before the right is asked |
| S18 | Header search ("S28") | `GET /cmd?q=` (`services/console/step4.py` line 131) | `phi.view` only; **no log check** | log only | **wider for every investigator and coordinator**; observed by a test (4.1) |
| S19 | Coordinator's daily mail (N2) | `services/console/notify.py` line 374; log checked for N1 only (line 383) | `request.prepare`; **no log check** | log only | **coordinator wider** (4.2) |
| S20 | Investigator's mail before clinic (N1) | notify.py line 383 | `list.mark` + `delegated_ok` | unchanged | right |
| S21 | Mailed candidate workbook (chart numbers) | `services/orchestrator/scenarios/screen.py` lines 844 and 859 | the study's `routing.list_to` addresses; **no role, no log** | each address must be an account on the log | **outside the matrix** (4.3) |
| S22 | Referral workbook to a department | screen.py (same function, one per routed department) | the study's routing | unchanged; a question (4.4) | outside the matrix |
| S23 | Break-glass | `POST /breakglass` (`services/console/breakglass.py` line 178) | `breakglass.open` (admin, investigator; one patient or one job, 60 minutes, reviewed by the steward) | unchanged | right, as an audited exception (4.5) |
| S24 | Audit trail by patient | `GET /audit/patients[/{pid}]`, `report.csv` (`services/console/audit_page.py` lines 527, 536, 591) | `audit.browse` (steward, privacy) | unchanged; a question (4.6) | pseudonyms, no clinical row |

**Counts only (no row), for the record:**

| Surface | Route | Guard | Who today |
| --- | --- | --- | --- |
| Research office report | `GET /reports/research-office[.xlsx]` (screening_log.py lines 586, 595) | `report.office` | admin, coordinator, viewer |
| Feasibility report | `GET /studies/{rs}/feasibility` (home.py line 648) | every account that sees the study | everyone; the "why the list is longer" box shows exact list counts to `phi.view` holders (line 655), whether or not on the log |
| Weekly picker | `GET /week` (home.py line 630) | not aggregate-only | studies and approvals, no row |
| Opportunity feed, alliance tables | signed files (D-467, D-1226) | no account | counts, rounded |

**Not inventoried in depth:** pages after consent (subjects, enrolment, visits, EDC, SAE, monitor), because the card
is about the time before consent. Host commands (a shell on the box) are outside the matrix by design.

## 4. Gaps the matrix cannot close by a cell

### 4.1 The header search does not ask the log (confirmed by a committed test)

`search` in `services/console/step4.py` (line 131) checks only `can_view_phi` (line 141). It then reads the week list
of every study the account sees (line 147) and the screening numbers, and turns a match into a redirect to the
patient's page.

**Observed today**, with synthetic data, by `tests/console/test_proposal_10c3_header_search.py` (run with
`--runxfail` to see it): an investigator is a sub-investigator on study A's log only (RA-BIO, "screen"); study B
(GZQO) has a log that names another PI and one pre-consent candidate with screening number `GZQO-0001`. The
investigator gets 403 on study B's weekly list and on the candidate's patient page. Yet `/cmd?q=gzqo-0001` answers
`303` to `/studies/GZQO/patients/cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd`. So the search confirms that the patient is on
study B's list and gives the full pseudonym. A 12-character pseudonym prefix did the same in an earlier throwaway run
on the single-study box.

**Intended or a defect?** No decision says the search may pass the log. D-147 item 1 says an investigator not on a log
that names a PI "is refused (403) on the week list, the patient page and the candidates", and D-273 (PV-3) applies
that rule to every page that shows one study's patients. The search is not named in either. Our reading is that it is
a gap against D-147 and D-273, not an intended breadth. It is a guard in code, not a cell: the fix would be to ask
`delegated_ok` per study inside `search`. **Lane J does not fix it** (a change to who may read is C2's). The test is
an expected failure with the reason "proposal 10C-3, awaiting lane C2's decision" (strict under
`TB_PROPOSAL_10C3=1`), so nothing goes red.

### 4.2 The coordinator's daily mail (N2) does not ask the log

`notify.py` line 383 skips a study for N1 when the log does not reach the investigator. N2 has no such check: every
coordinator gets the list rows of every study its account sees. Changing the coordinator's `task.screen` cell alone
does not fix it, because the check is written for N1 only. The adopting change must apply `delegated_ok` to N2 too.
Test: `test_n2_carries_no_row_of_a_study_off_the_coordinators_log`.

### 4.3 The mailed candidate workbook goes to addresses, not to accounts

The SCREEN run mails its workbook, with chart numbers, to the study's `routing.list_to` (screen.py line 844). The
addresses are typed in the study's set-up. Nothing checks that each address belongs to an account on the log. The
console's guarded download (S15) does check the log for the browser. Proposed rule: at criteria approval and at each
send, every `list_to` address must be the mailbox of an account that passes S1's rule; an address that does not is
refused with a sentence naming it. This is orchestrator code and the study set-up, so C2 and the integrator decide who
builds it. Test: `test_a_list_address_off_the_log_is_refused_before_the_mail`.

### 4.4 The referral to the treating doctor (主治医)

A referral workbook goes to a department (one patient, one doctor). In Japan an approach is often made through the
treating doctor, who is not on the study's log. Our reading is that this is the intended route, not a leak. It is
listed so that C2 states it in the record: a referral carries the one patient only, never the list.

### 4.5 Break-glass

The administrator and an investigator off the log may open one patient or one job for 60 minutes, audited and
reviewed by the steward (D-430). It is an exception by design and stays. The proposal asks C2 to state it in the record
as the one way past the log rule.

### 4.6 The audit trail and the opt-out register

The steward and the privacy office read the audit trail by patient (pseudonyms and events, no clinical row), and keep
the opt-out register. Both are oversight duties. The proposal keeps them and asks C2 to confirm that a pseudonym in
the audit trail is not a "pre-consent list" in the card's sense.

## 5. Proposed rows

```yaml
# authz_matrix.yaml: the coordinator's cell of each pre-consent row asks the log, as the investigator's does
  task.screen:
    what: see the candidate list of a study
    admin: false
    coordinator: [logged_tick]          # was: true. The log names a PI and the PI ticked "screen" for this account
    investigator: [logged_pi, logged_tick]
    viewer: false
    cro: false
    steward: false
    privacy: false
# phi.view, id.reveal and profile.read stay role rows (true for coordinator and investigator); every page above asks
# them together with task.screen, so the one cell narrows S1 to S17 at once.

# a new role for the trial office (治験事務局); card 10C-16 names it and its set-up rights
roles: [admin, coordinator, investigator, viewer, cro, steward, privacy, trial_office]
  report.office:
    trial_office: true                  # counts, small cells hidden (ROLE-017)
  # every row that shows a patient: trial_office false (phi.view, id.reveal, task.*, profile.read, list.mark,
  # notmatched.*, audit.browse, breakglass.open). Its set-up and committee rows (study.setup, irb.edit) are
  # 10C-16's to propose; `study.setup` also covers the conflicts, so 10C-16 must check each one shows no row.
```

**What `logged_tick` means for a coordinator.** Today `logged_tick` holds when the log names a PI and the action's task
is in the account's ticks. `standing` fills the ticks from `sub_pi` entries only (team.py line 167). The adopting
change must also read the ticks of `crc` entries (and decide on `other`). Without that, the new cell holds for nobody
and every coordinator loses every list.

**Why not `task:screen` (any tick, PI named or not).** The investigator's rule since D-380 is: while the log names no
PI, nobody has a study task. The proposal keeps one rule for both roles. A study in set-up has no list yet, so no
coordinator loses a list it needs.

**Only narrows.** No role newly reads or does anything, except the new `trial_office` role, which reads counts only.
D-380's account study list stays as a second fence: both must hold.

## 6. What "on this study's delegation log" lacks in the data model today

| Needed | Today | What C2 would add |
| --- | --- | --- |
| A coordinator's entry with ticked tasks | exists: log role `crc`, tasks stored (teamstore.py lines 33, 429) | nothing |
| The entry tied to an account | `Entry.username` exists but is optional (a person without an account may be listed) | nothing for the rule; a coordinator with an account but no `username` on its entry is off the log, so the log must name it |
| The ticks read for a coordinator | read for `sub_pi` only (team.py line 167) | read `crc` ticks; decide whether `other` counts |
| The rule applied to the coordinator on pages | `delegated_ok` skips roles whose cell is `true` (home.py line 214) | nothing once the cell is a condition |
| A trial-office role | none (seven roles) | the role, its rows, its account form and its role guide (10C-16) |
| The CRC's employer (hospital or SMO) and contract date | the account's affiliation only (D-380 item 4) | 10C-16's field; not needed for this rule |

**Adopting it too early locks every coordinator out.** On a box where the logs do not yet list each coordinator with
"screen", every coordinator loses every list the day the cell changes. The adopting change needs a step before it: a
report of each study's coordinators who see rows today and are not on its log, sent to the trial office, which puts
them on the signed log (or not). A box whose studies have a list but no `crc` entry should say so at start, in a
sentence, not quietly empty the pages.

## 7. Data-minimising alternative considered

**No cell change; tie the account's study list to the log.** Keep `coordinator: true` and add a check on the account
page that a coordinator's study list names only studies whose log lists it. Smaller, and close to 10D-14's P-3
alternative. Against it: a hospital coordinator account with no list still sees every study; S18, S19 and S21 are not
fixed; and the 書式2 log, which the trial office signs, would still not be what grants the rows. Recommended only if C2
judges the cell change too wide for 1.0.

## 8. Without it

Nothing is blocked. A coordinator who is not on a study's log reads that study's candidates, screening log and patient
pages, and gets its rows in the daily mail. A trial-office person given a coordinator account (to keep set-up and
committee dates, which are coordinator rows today) reads every pre-consent list.

## 9. The test C2 can switch on

`tests/unit/test_proposal_10c3_pre_consent_matrix.py`: one row per (person × surface), 13 persons × 13 surfaces with
row-level guards, plus the counts surface and the trial office's "no row" check. It asks `permit` only, so it needs no
database.

- **Default (every `make test`):** every row is a non-strict expected failure with the reason "proposal 10C-3, awaiting
  lane C2's decision". A row that holds today shows as XPASS. Nothing goes red, nothing is skipped, no existing test
  changes.
- **Switched on (`TB_PROPOSAL_10C3=1`):** the table is checked. On master: 168 rows pass and 27 are strict expected
  failures, exactly the rows of `WIDER_TODAY` (the coordinator off the log and the coordinator while the log names no
  PI, on each of the 13 row surfaces; the trial office's counts). When C2 changes a cell, its rows turn red as XPASS
  (strict), and C2 deletes them from `WIDER_TODAY`. Adopting is: change the cells, empty `WIDER_TODAY`, remove the
  switch.
- **Not in the table:** S18, S19 and S21, whose guard is code. S18 has its own test,
  `tests/console/test_proposal_10c3_header_search.py` (4.1), switched the same way. Sections 4.2 and 4.3 name the
  tests C2 would need for S19 and S21. The role-by-route table (`tests/console/data/role_route_matrix.md`) would gain a column for a
  coordinator off the log, regenerated with `TB_WRITE_ROLE_MATRIX=1`.

## 10. Proof that nothing changes for any role

- Files changed by this card: this page, the two test files (section 9 and 4.1) and decision D-1238. `libs/tb_common/authz.py`,
  `libs/tb_common/authz_matrix.yaml`, every console and orchestrator file, `tests/console/data/role_route_matrix.md`
  and `tests/console/data/route_actions.yaml` are byte for byte as on master (the pull request's file list).
- The new test file changes no behaviour and, by default, cannot fail.
- The header-search test (4.1) is an expected failure and cannot go red by default.

## 11. Questions

### 11.1 For lane C2

1. The coordinator's `task.screen` cell: `[logged_tick]` (section 5), or the account-page check of section 7?
2. Read the ticks of `crc` entries; and `other` entries too, or not?
3. While the log names no PI, does a coordinator see no list (proposed, the investigator's rule), or does a ticked
   coordinator see it (`task:screen`)?
4. A `trial_office` role (proposed, with 10C-16), or the trial office as a `viewer` account until 10C-16?
5. Who fixes S18 (search) and S19 (N2 mail) and when? S18 is a gap against D-147 and D-273; S19 follows the
   coordinator's ruled breadth today and becomes a gap only if section 5 is adopted.
6. S21: check `routing.list_to` addresses against the log at approval and at send?
7. Confirm 4.4 (referral to the treating doctor), 4.5 (break-glass) and 4.6 (audit trail) as outside the rule.

### 11.2 For the owner

1. Does the first site's trial office need any account on the box, and if so, for set-up only or also for counts?
2. Does the first site's signed 書式2 list name every coordinator who will screen, including SMO staff? (Review 11
   site question 3; plan 10 decision 53.)

## 12. Japanese regulatory grounding (our reading, not legal advice)

Under the GCP ordinance (医薬品の臨床試験の実施の基準に関する省令, 平成9年厚生省令第28号), the investigator shares study
work only with the sub-investigators and study collaborators (治験協力者, which includes CRCs) on a list the investigator
makes and the head of the institution receives; that list is the 書式2 our delegation log copies [S1]. The ethical
guidelines for life science and medical research involving human subjects (人を対象とする生命科学・医学系研究に関する倫理指針)
ask researchers to handle personal information securely and limit it to what the research needs [S2]. The Act on the
Protection of Personal Information (個人情報の保護に関する法律) requires safety-control measures and supervision of the
staff who handle personal data (Articles 23 and 24 in the numbering in force since 2022), and the regulator's guidance
lists access control by role as one technical measure [S3, S4]. Our reading is that a pre-consent list should reach
only the people on the signed list, and that article numbers and the 指針's exact clause are for the regulatory reader
of plan 10 decision 21 to confirm.

- [S1] 医薬品の臨床試験の実施の基準に関する省令, e-Gov: <https://laws.e-gov.go.jp/law/409M50000100028>
- [S2] 人を対象とする生命科学・医学系研究に関する倫理指針, MHLW: <https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/hokabunya/kenkyujigyou/i-kenkyu/index.html>
- [S3] 個人情報の保護に関する法律, e-Gov: <https://laws.e-gov.go.jp/law/415AC0000000057>
- [S4] 個人情報の保護に関する法律についてのガイドライン（通則編）, Personal Information Protection Commission:
  <https://www.ppc.go.jp/personalinfo/legal/>

These pages were cited from the public texts and were not re-opened in this session.

## 13. Not verified

- S19 (N2) and S21 (mailed workbook) are read from the code, not run. S18 is run by a committed test (4.1).
- Whether any site's log lists coordinators with "screen" today (needed before section 5 is adopted).
- The legal readings of section 12: our reading only.
