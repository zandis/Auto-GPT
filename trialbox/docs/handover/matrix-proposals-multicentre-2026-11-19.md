# Multicentre permission proposals P-1 to P-5, as matrix rows for lane C2 (10D-14, lane J, 2026-11-19)

**Reader:** the people who build TrialBox: lane C2 (the permission matrix, accounts, the acting role, audit), which
decides every row below, and the integrator; the owner for section 10.2 only. For builders, so in one language.

Plan 10 row 10D-14 ([plan 10](../plan/47-plan-10-2026-11-18.md), Track D; source M14-13 of
[root review 14](../reviews/2026-11-root/14-multicentre-lifecycle.md), section 4.2). Review 14 wrote five permission
proposals, P-1 to P-5, as prose. This page puts each in the form the matrix is written in, so that C2 can adopt,
change or refuse it. **It proposes; it changes nothing.** No role may do or read anything on master that it could
not before this page: the matrix file, its loader, every guard and every page are untouched (section 9 has the
proof). Read against master `a44a39da`.

**Form.** There was no earlier document in which another lane put matrix rows to C2: review 21 section 2.7 and
review 16 propose test columns and mark items "C2 decides", in prose, without a test-only copy of the matrix. So this
card is a document only (the card's rule: "if the precedent was a document only, do the document only"): no disabled
rows in `libs/tb_common/authz_matrix.yaml`, no test-only matrix. Rows below are YAML blocks in the matrix's own form
(an action, its `what`, one cell per role: `true`, `false` or a list of conditions) so that an adopting pull request
can copy them. Where a row needs a scope the matrix cannot say today, the block names a **new condition** and spells
out its rule.

**Decision numbers.** C2 assigns its own decision number from its block when it decides; nothing here reserves one.
This card took no decision of its own and so uses no lane J number.

## 1. The matrix today, in the terms the proposals use

- **Seven roles, 89 actions** [R `libs/tb_common/authz_matrix.yaml:30`; counted: 89 rows]: `admin`, `coordinator`,
  `investigator`, `viewer`, `cro`, `steward`, `privacy`. One function reads it (`permit` in
  `libs/tb_common/authz.py`); a role or action not in it is refused; the file must be total (every row names every
  role) and conditions must be known (`pi`, `logged_pi`, `logged_tick`, `unlogged`, `monitor`, `task:<t>`), else the
  service does not start [R `libs/tb_common/authz.py:108-131`; D-366].
- **The scope words this page uses**, and where each is enforced today:

| Scope word | Meaning | Today |
| --- | --- | --- |
| own site | the box is the site: every row is already "own site" | true by construction (one site per box; review 14 section 1.1) |
| own study | the account sees only some studies | the account's study list (`User.sees_study`, `services/console/auth.py:379`); required for an SMO or CRO account (D-380 item 4); **outside the matrix** |
| delegated | the study's delegation log gives the account a task | conditions `pi`, `logged_pi`, `logged_tick`, `task:<t>`, `monitor` |
| counts only | the reader sees numbers, never a row | `report.aggregate_only` (viewer, cro), the opportunity feed and alliance tables (D-467, D-1226) |
| no pseudonym | the reader never sees a patient's pseudonym or screening number | rows without `phi.view` or `audit.ids`; the provenance search masks pseudonyms for the administrator (D-1155) |

- **What a person outside the site can hold today:** a `cro` account (the sponsor's or CRO's monitor; aggregate
  reports in the sponsor form; one study's enrolled subjects only under a dated monitor grant: `monitor.read`,
  `monitor.visit` with condition `monitor`) and a `viewer` account (aggregate reports). Both are created by the
  administrator under `account.create.aggregate`.
- **Multicentre code on master:** the alliance cohort tables are signed per site and the root verifies them against
  a key register (D-1226, pull request #1092) [R `services/orchestrator/scenarios/cohort.py` lines 11-15 and 341]; the root
  that runs `COHORT MERGE` is an ordinary site box with a root address set [R `cohort.py:487-491`], and the job is
  started under `command.COHORT` (admin, coordinator). The opportunity feed is signed and verified at a hub page that
  has no accounts (D-467) [R `services/opportunity_hub/dashboard.py:1-8`]. There is no coordinating role, no study
  package and no package import (searched `services`, `libs`, `tools`: no "coordinating", "multicent" or
  "study_package").

## 2. P-1 to P-5 at a glance

| # | Need (review 14) | Rows proposed | New reads | Decision asked |
| --- | --- | --- | --- | --- |
| P-1 | No coordinating-centre or central-monitor account inside a site box (finding G-10; review 14 section 4.1) | none: a fixed role list on a site box, held by a test | none | adopt, worded as narrowed in 4.2 |
| P-2 | Coordinating mode with its own small role set; no patient role in it (G-10, M14-12, OD-2) | 4 roles on the coordinating box only; 4 new actions; every existing row `false` for them | the sites' signed counts; package content; no row, no pseudonym | adopt with changes (choose 5.4 option a or b) |
| P-3 | SMO or other-department coordinator sees only delegated studies (G-11, OD-8) | mostly met by D-380 item 4; residual: one new condition `logged` on the coordinator's study rows, or no row | none (narrows only) | adopt the residual or record P-3 as met by D-380 |
| P-4 | Pharmacist read-only account when a pharmacy module exists (review 02 J-D1) | none now; a sketch for later | none now | refuse for 1.0; keep the sketch |
| P-5 | Package import as a right of steward or coordinator; the PI's approval still required (G-3, M14-3) | 1 new action `package.import`; `criteria.approve` unchanged | the package's content; no patient data | adopt |

## 3. Where review 14 is out of date

Review 14 read master `7da6edd38`; this page reads `a44a39da`.

| Review 14 says | Master now | Effect here |
| --- | --- | --- |
| Alliance count tables travel by mail **unsigned**, the sender address binds (section 1.3 D-144 row; the contradiction under 1.3; G-7; card M14-20) | Signed per site with an Ed25519 key, verified at the root against a key register; unsigned tables refused; older ones kept unverified and left out (D-1226, pull request #1092) | P-2's `feed.merge` reuses that check; no new signing right is proposed, because the signature is the box's key, not a person's |
| "Every coordinator sees every study" (P-3, G-11, OD-8) | Not so since D-380 item 4: SMO and CRO accounts must name their studies; an account stored without a list sees none; any account may be given a list | P-3 shrinks to the delegation-log residual (6.2) |
| "No sponsor ... account inside a site box" (P-1) | The sponsor's or CRO's monitor holds a `cro` account with dated monitor grants (D-104, D-380 item 6); review 14's own table 4.1 says so | P-1 narrowed to the coordinating centre and the central monitor (4.2) |
| The site PI's approval is "still required" for an imported package (P-5) | True for a site's own compile; **not** for today's vendor import path, which counts as approved on a site box (D-77, D-640 item 3) | P-5 states "import approves nothing" as a rule for C2's record (8.2) |
| 7 roles, 89 actions; no coordinating role (section 1.1; M 3) | Unchanged: 7 roles, 89 actions; still no coordinating role or package import | none |
| Citation `authz_matrix.yaml:109` | Line 109 is now the comment above `task.screen` (line 111) | none |

## 4. P-1: no coordinating-centre account inside a site box

### 4.1 The need

Review 14 section 4.1 lists four people a multicentre study adds who look across sites: the coordinating
investigator, the coordinating centre's (CC) data manager, a central monitor, the sponsor's staff. Each needs
aggregates only, and aggregates already leave a site as signed files (the opportunity feed, D-467; the alliance
tables, D-1226; the weekly status counts of 10D-10, not built). An account for any of them inside a site box would be
a door into that site's patient rows that the file route does not need. Findings answered: G-10 ("no coordinating
roles"), section 2.3 point 1 ("only aggregates ever leave a site").

### 4.2 Narrowed wording (review 14 is out of date here)

Review 14 writes "No sponsor, CC or central-monitor account inside a site box". Its own table in section 4.1 says the
sponsor's on-site monitor already holds a `cro` account with a monitor grant, and D-104 and D-380 keep that. Proposed
wording: **a site box holds no account for the coordinating centre or a central monitor; the sponsor's or CRO's
on-site monitor keeps today's `cro` account and its monitor grant, unchanged.**

### 4.3 Rows

None added, none changed. The proposal is an invariant on the role list:

```yaml
# on a site box (any box not in coordinating mode, P-2):
roles: [admin, coordinator, investigator, viewer, cro, steward, privacy]   # unchanged; no coordinating-centre role
```

Rows it sits beside (unchanged): `report.aggregate_only` (viewer, cro), `report.sponsor_form` (cro),
`report.office` (admin, coordinator, viewer), `monitor.read` and `monitor.visit` (cro under `monitor`),
`account.create.aggregate` (admin).

### 4.4 New reads

None. A CC person who is also a site's own staff (the coordinating investigator is a PI at the lead site) reads that
site's rows in their site role, as today.

### 4.5 Data-minimising alternative considered

A `viewer` account at each site for the CC's data manager, reading `report.office`. Refused in this proposal: it
puts an outside person's sign-in on every site box, each site's office report shows more than the CC needs (it is
the site's own report), and the signed files already carry the counts with no sign-in at all.

### 4.6 Without it

Nothing is blocked today. The risk is drift: an administrator can create a `viewer` account for a CC person now
(`account.create.aggregate`), and nothing says it should not be done.

### 4.7 The test C2 would need

- `test_a_site_box_has_exactly_the_seven_roles`: the role list of a box not in coordinating mode equals the seven
  (today's `test_the_matrix_roles_are_the_console_roles` in `tests/unit/test_authz_matrix.py` already holds the list;
  the new case pins it per mode once P-2 exists).
- `test_no_coordinating_role_can_be_created_on_a_site_box`: `/ops/users` refuses each P-2 role on a site box.
- The role walk's pseudonym search over every page the `viewer` and `cro` columns reach stays at zero hits
  (`tests/console/test_matrix_role_walk.py`, unchanged).

**Decision for C2:** adopt / adopt with changes / refuse. Recommended: adopt, with the wording of 3.2.

## 5. P-2: a coordinating mode with its own small role set

### 5.1 The need

Under the ruled federation model (plan 10 decision 47) a coordinating centre builds, signs and versions the study
package and reads every site's signed counts; it runs at the lead institution (decision 48, ruled; decision 104
open on where the box that compiles and signs sits). Review 14 asks for a coordinating mode of the same software with
four roles and no patient role (finding G-10; card M14-12, plan 10 row 10D-13). The matrix has no mode and no such
role.

### 5.2 Proposed rows

**Roles.** The coordinating box loads a different role list; a site box keeps the seven (P-1). The loader already
refuses a role it does not list, so the mode is the role list:

```yaml
# coordinating mode only (10D-13 decides how the box knows its mode)
roles: [cc_investigator, cc_data_manager, central_monitor, cc_admin]
```

**Every one of today's 89 rows is `false` for all four roles**, with one exception: `cc_admin` takes the
administrator's operations and account rows (`ops.*`, `account.*`, `job.retry_scheduled`), so the box can be run.
No row with a patient behind it (`phi.view`, `id.reveal`, `task.*`, `edc.*`, `profile.*`, `breakglass.*`,
`audit.ids`, `monitor.*`) is true for any of them. In coordinating mode the box holds no patient data; the rows are
`false` anyway so that a mis-set mode reads nothing.

**New actions** (on a site box every cell of these is `false`):

```yaml
  package.build:
    what: build and version a study package (criteria, value sets, tests, forms, schedule); no patient data (P-2)
    cc_investigator: false
    cc_data_manager: true
    central_monitor: false
    cc_admin: false
  package.sign:
    what: sign a built package version with the coordinating investigator's own key (P-2; who builds is not who signs)
    cc_investigator: true
    cc_data_manager: false
    central_monitor: false
    cc_admin: false
  feed.read:
    what: read the sites' signed counts (feasibility, funnel, reasons, enrolment, package versions); counts only, no pseudonym (P-2)
    cc_investigator: true
    cc_data_manager: true
    central_monitor: true
    cc_admin: false
  feed.merge:
    what: verify and merge the sites' signed count files (as COHORT MERGE, D-73, D-1226); counts only (P-2)
    cc_investigator: false
    cc_data_manager: true
    central_monitor: false
    cc_admin: false
```

Scope rule of all four rows: **own coordinating centre, counts only, no pseudonym**. A count below the published
floor never reaches the reader (the site rounds before signing, D-467; the reader cannot undo it).

### 5.3 New reads

| Role | Newly reads | Never reads |
| --- | --- | --- |
| cc_investigator, cc_data_manager, central_monitor | per site and per study: rounded pre-consent stage counts, exact post-consent counts (decision 49, open), screen-fail reasons by category, package version and import test result, the site's key fingerprint | any row, pseudonym, screening number, chart number, date of a patient |
| cc_data_manager | the package's own content (criteria, value sets, synthetic test patients) | the same |
| cc_admin | the box's health and accounts | any count or package content |

The new read to watch is the **post-consent exact count** (decision 49): at a small site an exact "1 enrolled" by
week can identify a person to someone who knows the clinic. C2 should hear it as a read of this role set.

### 5.4 Data-minimising alternative considered

**(b) No new roles:** the coordinating box keeps the seven role names and the mode switches every patient row off
(the `investigator` signs, the `coordinator` builds, the `viewer` reads feeds, the `admin` runs). Fewer columns, one
matrix. Against it: the same name means different rights on two kinds of box, the role guides and the role walk
would need a mode column anyway, and a mode flag that fails open would give a site's `coordinator` its patient rows
on the coordinating box. **(a)**, the four roles above, fails closed: a site role does not exist there. Recommended:
(a). Either needs the mode itself, which is 10D-13's (lane C2b), not this card's.

### 5.5 Without it

10D-13 (coordinating mode) and 10D-11 (the coordinating view) cannot be built against a decided matrix. Today the
alliance root is a site box (section 1): whoever runs `COHORT MERGE` there is the site's own administrator or
coordinator, who also holds that site's patient rows.

### 5.6 The test C2 would need

- `test_coordinating_mode_refuses_every_patient_level_route` (10D-13's proof): every console route whose row is a
  patient row answers 403 to each of the four roles.
- `test_feed_read_shows_no_pseudonym_and_no_cell_below_the_floor`: three synthetic feeds; the pages `feed.read`
  opens carry no pseudonym (the role walk's search) and no count under the floor.
- `test_who_builds_does_not_sign`: one account cannot hold `package.build` and `package.sign` for the same version.
- `test_a_site_box_refuses_the_four_roles` (with P-1).

**Decision for C2:** adopt / adopt with changes / refuse. Recommended: adopt with changes (choose (a) or (b) in 5.4;
decide whether `feed.merge` is the data manager's or a separate two-person step).

## 6. P-3: a study-scoped coordinator

### 6.1 The need

Japanese sites use SMO staff widely (review 14 OD-8; plan 10 decision 53, open, recommended yes; 10C-16). An SMO
coordinator, or a coordinator from another department, should see only the studies they are delegated to. Review 14
says "today every coordinator sees every study" [its citation: `authz_matrix.yaml:109`] (finding G-11).

### 6.2 Review 14 is out of date: most of this is on master

D-380 item 4 (ROLE-011) already scopes accounts by study: an account with affiliation `smo` or `cro` (or the `cro`
role) **must** name its studies, `/ops/users` and `UserStore.set_scope` refuse an empty list, and an account stored
without one sees no study [R `docs/decisions/D-380-roles.md`, item 4; `services/console/auth.py` lines 56-59, 379-380 and 407-430].
Any hospital coordinator account may be given a list too. IRB dates are refused to SMO accounts (D-380 item 5,
`services/console/team.py:799`). So "every coordinator sees every study" holds only for a hospital coordinator
whose account lists no study.

What is still not there:

1. The scope is a list the administrator types on the account, not the delegation log. A coordinator removed from a
   study's log keeps seeing the study until someone edits the account.
2. The matrix gives the coordinator its study rows in every study it sees, whatever the log says (the comment at
   `libs/tb_common/authz_matrix.yaml:109`: "A coordinator has its row in every study").

### 6.3 Proposed rows (the residual)

One new condition and the coordinator cells of the study-bound rows that read or change one study's patients:

```yaml
# new condition (authz.CONDITIONS): logged — the study's delegation log lists the account with any task, today
  task.screen:
    coordinator: [logged]          # was: true
  task.enter_data:
    coordinator: [logged]          # was: true
  # the same change, coordinator cell only, on: study.state, study.setup, irb.edit, referral.answer,
  # notmatched.send_back, delegation.check, sae.view, sae.record, profile.read; the edc.* rows already ask
  # task:enter_data, and the coordinator's tasks would then come from the log as well
```

Every other cell is unchanged. **This only narrows**: no role newly reads or does anything. D-380's account list
stays as a second fence (both must hold).

### 6.4 Data-minimising alternative considered

**No row change:** keep D-380's list as the only scope, and add a check that an SMO account's list names only studies
whose delegation log lists the account (a check on the account page, not a matrix change). Smaller, and enough if the
site's research office keeps accounts and logs in step. Recommended if C2 judges the matrix change too wide for 1.0.

### 6.5 Without it

Nothing is blocked. A coordinator removed from a study's log keeps reading that study until the account is edited.

### 6.6 The test C2 would need

- `test_a_coordinator_not_in_the_log_sees_no_candidate_list` (403 on `GET /studies/{rs}/week` and its API twin).
- `test_a_coordinator_removed_from_the_log_loses_the_study_the_same_day`.
- `test_d380_an_smo_account_without_studies_sees_none` (exists in substance in the D-380 tests; kept).
- The role-by-route table regenerated (`TB_WRITE_ROLE_MATRI=1`), with an out-of-scope coordinator column.

**Decision for C2:** adopt / adopt with changes / refuse. Recommended: record P-3 as met by D-380 item 4 for SMO
accounts, and adopt either 6.3 or 6.4 for the delegation-log residual.

## 7. P-4: a pharmacist read-only account

### 7.1 The need

Review 02 (J-D1, section 1.2) and review 14 section 4.1: a site pharmacist handles the study drug. There is no
pharmacy module: D-144 keeps drug accountability as an input only, and review 14 marks P-4 "not for 1.0".

### 7.2 Proposed rows

None now. A sketch for when a pharmacy module exists, so the shape is not lost:

```yaml
# not proposed for adoption now
roles: [..., pharmacist]
  pharmacy.read:
    what: read one study's dispensing records by screening number; own study, no chart number
    pharmacist: [task:dispense]     # a new delegation-log task the PI ticks
# every existing row: pharmacist false (no phi.view, no id.reveal, no task.screen)
```

### 7.3 New reads

None now. Under the sketch: a screening number and its dispensing record in one study; never the candidate list,
the chart number or a note.

### 7.4 Data-minimising alternative, without it, test

Alternative: no account at all; the pharmacy keeps its own system and the coordinator types what the EDC needs. That
is today, and nothing is blocked. Test, when a module exists: `test_a_pharmacist_reads_no_patient_page`.

**Decision for C2:** adopt / adopt with changes / refuse. Recommended: refuse for 1.0; keep 7.2 as the sketch.

## 8. P-5: package import as a right, with the PI's approval still required

### 8.1 The need

Under federation by package (decision 47), a site takes a signed study package from the coordinating centre (10D-4,
M14-3; finding G-3, "no import of a study from another box"). Review 14 asks that the import be a right of the
steward or the coordinator, and that importing never approves: the site PI still approves "the package plus these
listed differences" (two people: who imports is not who approves).

### 8.2 What master does today (a gap review 14 did not note)

A rule set reaches a site box today only as a vendor-approved rule set: the host command
`python -m criteria_compiler.import_ruleset ruleset.zip --by update:...` or a signed update bundle applied by the
administrator (`ops.update_apply`) [R `services/criteria_compiler/import_ruleset.py:1-8`]. The rule set arrives
`status: approved`, and an installed update writes "(offline update, <by>)" on its tag, which a site box accepts as
an approval (D-77; D-640 item 3). So on master **an imported rule set needs no site PI approval**. P-5 must not carry
that over: a package import is not an approval.

### 8.3 Proposed rows

```yaml
  package.import:
    what: import a signed study package from a registered coordinating-centre key; the import approves nothing (P-5)
    admin: false
    coordinator: true
    investigator: false
    viewer: false
    cro: false
    steward: true
    privacy: false
```

Rows it sits beside, unchanged: `criteria.approve` (investigator; only the PI the log names approves, D-380 item 3),
`delegation.name_pi` (steward), `site.setup` (admin, coordinator), `study.setup` (coordinator),
`ops.update_apply` (admin). Rule to state in C2's record: **a study from a package runs nothing (no FEAS, no
SCREEN) until the site PI has approved that package version under `criteria.approve`**, whoever imported it.

Two choices for C2: whether an SMO coordinator may import (the matrix cannot say affiliation; the account page can),
and whether `admin` should hold it instead of the coordinator (the update-bundle path is the administrator's).

### 8.4 New reads

The importer reads the package: criteria, value sets, synthetic test patients, the coordinating centre's name and key
fingerprint. No patient data. The import's coverage report (10D-7) is **a count per value-set code in this site's
lake** (how many rows carry each code): an aggregate read of local data, new for a coordinator (the steward already
reads items under `items.view`). Proposed: the coverage report under the steward only.

### 8.5 Data-minimising alternative considered

Keep importing on the host only (the administrator, today's path), with no console row. Smaller, but it leaves the
import outside the matrix and the audit's role, and it is the path that counts as approval today (8.2).

### 8.6 Without it

10D-4 (import with a key register) has no decided right to call; 10D-24's second-site walk cannot be run.

### 8.7 The test C2 would need

- `test_an_imported_package_runs_nothing_before_the_pi_approves` (FEAS and SCREEN refused for the study).
- `test_package_import_refuses_an_unknown_key_and_audits_the_refusal`.
- `test_the_importer_is_not_the_approver`: a steward or coordinator import, then `criteria.approve` refused to them.
- `test_only_the_steward_reads_the_coverage_report`.

**Decision for C2:** adopt / adopt with changes / refuse. Recommended: adopt, with the 8.3 rule in the record.

## 9. Proof that nothing changes for any role

- Files changed by this card: **this page only** (the pull request's file list). `libs/tb_common/authz_matrix.yaml`, `libs/tb_common/authz.py`, every console and orchestrator file, the
  role-by-route table `tests/console/data/role_route_matrix.md` and `tests/console/data/route_actions.yaml` are byte
  for byte as on master.
- The matrix and route tests run on this branch and pass with no regenerated table:
  `tests/unit/test_authz_matrix.py`, `tests/console/test_role_route_matrix.py`,
  `tests/console/test_role_route_matrix_acting.py`, `tests/console/test_matrix_role_walk.py` (results in the pull
  request).
- No disabled or test-only rows were written (no precedent for them; see "Form" at the top), so there is no ignored block for the
  loader to skip.

## 10. Questions

### 10.1 For lane C2

1. P-2: option (a), four roles that exist only on a coordinating box, or (b), the seven names with patient rows off
   by mode? (5.4)
2. P-2: is the merge (`feed.merge`) the data manager's alone, or a two-person step?
3. P-2: is an exact post-consent count by week (decision 49) a read you accept for these roles at a small site?
4. P-3: the matrix condition `logged` on the coordinator's study rows (6.3), or only an account-page check against the
   log (6.4)? Does the delegation log list coordinators today (not verified by this card)?
5. P-5: steward and coordinator, or steward and administrator? May an SMO coordinator import?
6. P-5: should the vendor update path (D-77) keep counting as an approval on a site box once packages exist, or
   should every rule set need its site PI (8.2)?
7. P-5: the coverage report under the steward only?

### 10.2 For the owner

1. Which roles will the coordinating centre of the first multi-site study actually have: one person who builds and
   signs, or the four of P-2? Who is the coordinating investigator, as a role, not a name?
2. Is the first site's first study multi-site at all in 1.0, and is the first site the coordinating centre or a
   member? (It decides whether P-2 is needed for 1.0 or only P-1 and P-5.)
3. Decision 53 (SMO coordinators study-scoped, open): does the first site use SMO staff, and does their contract
   cover pre-consent chart review? (Review 14 section 11 question 6; plan 10 site question 10.)
4. Decision 104 (where the box that compiles and signs sits, open): it decides where P-2's roles live.
5. Decision 49 (counts only each week, open): exact post-consent counts or rounded ones, given P-2's read in 5.3.

## 11. Not verified

- Whether the delegation log records coordinators with tasks today (needed by 6.3); read from the matrix comment
  only.
- That the console refuses `criteria.approve` to an investigator who is not the logged PI on every approval path:
  taken from D-380 item 3, not re-run here.
- The legal readings behind P-2's reads are review 14's opinions (its section 14), not checked here.
