# TrialBox: critical-issues register (2026-11-10)

| Field | Value |
| --- | --- |
| Document ID | TB-REG-01 |
| Date | 2026-11-10 |
| Code read | `origin/master` at `0cc908b` (PRs up to #63 merged). Open draft PRs #59, #61, #64 to #69 were read by their descriptions and file lists only. |
| Method | Seven read-only reviewers, then one assembler. A: the Blockers and Highs of `docs/reviews/2026-11-09-assessment-and-tasks.md`, checked again on master. B: the Blocker, Critical and High findings of the 2026-11-09 reviews, checked again. C: open PRs, branches and the "Open / Not done" blocks of `docs/DECISIONS.md`. D, E, F, G: four new adversarial reviews (patient safety, privacy, security, data integrity). The assembler merged duplicates into one row each and gave new IDs. |
| What was run | Most findings are verified by reading the code (the four adversarial reviewers read each finding twice). A few were also run as throwaway snippets on synthetic data, outside the repository. D (safety): S-1, S-2, S-4, S-5, S-6, S-7, S-8 (b) and the S-10 mechanism by snippet; S-3 by a mutation run (64 single-rule mutants against 244 database-free unit tests). E (privacy): two snippets (the audit-table mask, the log scrubber). G (integrity): two snippets (audit chain truncation, empty lake rebuild). Each row says "confirmed by a run" or "snippet" where that applies; every other row is by reading. |
| What was not run | The test suite, the e2e runs, Docker, the cloud GPU run, a live box. F (security) ran nothing: each exploit is a code-path argument. DI-6 and DI-9 were not run against Postgres. A, B and C ran no tests; "fixed" there means the code is on master and a named test file exists. C read PR bodies and file names, not the PR diffs. The patches in section 4 were not applied or run. |
| Scope | Blocker, Critical and High only. Medium findings of the four new reviews are listed in section 6 so they are not lost. Paths are relative to `trialbox/`. |

How to read the source IDs: P-01 to P-51 and MR-nnn are the assessment and the holistic master register; R-nn is the full-system review (its part ids are not repeated here); "EDC E-nn" is the EDC prefill review; "SA S-nn" is the Study A review; PR-nn is the plan review; "PR #nn" is a pull request; D-nnn is a decision. S-1 to S-17 (safety), PV-1 to PV-18 (privacy), SEC-1 to SEC-17 (security) and DI-1 to DI-14 (integrity) are the four new reviews. P-1 to P-7 and PX-1 to PX-8 are patches in section 4.

## 1. Summary

### 1.1 Counts

Counted from the tables in sections 2 and 3. Reviewer status "partly" is counted as open, with the done part named in the row.

| Severity | open | in progress elsewhere | fixed | Total |
| --- | --- | --- | --- | --- |
| Blocker | 18 | 1 | 5 | 24 |
| Critical | 6 | 0 | 1 | 7 |
| High | 62 | 9 | 12 | 83 |
| Total | 86 | 10 | 18 | 114 |

| Owner | Rows |
| --- | --- |
| this session | 27 |
| another session (named in the row) | 20 |
| the coordinator (task cards) | 32 |
| the owner | 17 |
| none (fixed) | 18 |

### 1.2 Top ten risks

1. **A lab value in another unit can exclude a patient** (CR-001). The comparison never reads the unit, and all five shipped rulesets treat a FALSE inclusion as a hard exclusion. With it: record status, sex unknown, orders with no end date (CR-005, CR-006, CR-007).
2. **The "two-model" check accepts one model twice** (CR-002), and both models read the same cut excerpt (CR-004).
3. **The safety rules of the exclusion path are mostly untested** (CR-003): the stub cannot disagree, and gate G1 with the real pair has never passed (CR-069).
4. **Chart numbers sit in clear in the audit log** and are shown on `/audit` (CR-016). They cannot be removed from the chain without a ruling.
5. **No second factor and no TLS on master; the e-signature is a password the administrator has seen; a signed value is not locked** (CR-033, CR-034, CR-035, CR-036).
6. **The console's "today" is the UTC date** (CR-049, CR-050): a PI in Japan or Taiwan is refused in the morning of the first day, and the Monday digest is never sent.
7. **The administrator sees patient data, and permission checks are scattered** (CR-023, CR-024): eight ways a chart number goes out, and delegation and opt-out are skipped on sibling pages (CR-017, CR-018, CR-019, CR-020, CR-021, CR-022).
8. **A death or a serious event can miss the SAE clock** (CR-008, CR-009, CR-010).
9. **The audit trail and the database do not resist a compromised service** (CR-054, CR-042, CR-037, CR-038).
10. **Data can be lost or replaced without notice** (CR-052, CR-053, CR-056, CR-057, CR-058), and the parity tool can pass on nothing (CR-051).

Also high on the list and outside the code: the hospital-side blockers (CR-088 to CR-092), the image vulnerabilities that nobody owns (CR-045), and the EDC gateway 409 that is said to be fixed on a branch nobody can see (CR-072).

### 1.3 Fix groups of this session

| Fix group | Decision and name | Rows |
| --- | --- | --- |
| FG-A | D-270 site-local "today" | CR-049, CR-050 |
| FG-B | D-271 data pipeline | CR-051, CR-052, CR-053 |
| FG-C | D-272 audit integrity | CR-016, CR-054 |
| FG-D | D-273 console privacy guards | CR-018, CR-019, CR-020, CR-023, CR-055 |
| FG-E | D-274 backup and restore | CR-056, CR-057 |
| FG-F | D-275 structured-criteria safety | CR-001, CR-005, CR-006, CR-007 |
| FG-G | D-276 two-model check | CR-002, CR-003, CR-004 |
| FG-H | D-277 SAE | CR-008, CR-009, CR-010, CR-011 |
| FG-I | D-278 orchestrator authorisation and opt-out | CR-026, CR-038 |

Everything else is owned by another session, a task card, or the owner; see the Owner column.

## 2. The register

Status is one of: open, fixed, in progress elsewhere. "In progress elsewhere" is used only when another session says it is fixing that issue. An issue whose fix needs a file another session owns, and that nobody is fixing, is "open" with that session as owner and a patch in section 4.

One caution on "in progress elsewhere": reviewer C found no remote branch and no pull request named wave0-ci, wave0-goldens or fix-edc-gw on 2026-11-10. Those rows rest on the coordinator's word that the sessions exist.

### 2.1 Patient safety

| ID | Severity | Area | Problem | Evidence | Status | Owner | Fix group / note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-001 | Blocker | safety / engine | A lab threshold is compared with the number only; the row's unit is never read. A value in another unit, or with no unit, is decided as if it matched, and under v1 rules a FALSE inclusion is a hard exclusion. Sources: S-1, MR-002, R-02 (residue R-31), D-149. | `services/criteria_compiler/compile_sql/generator.py:67-77,100-118,218-261`; `services/lake/flatten.py:293`; `docs/DECISIONS.md:3445` | open | this session | FG-F D-275. Reviewers disagree: A rates MR-002 Blocker, partly done; B calls R-02 fixed with a Medium residue (R-31); C rates R-31 Medium; D rates S-1 Critical and confirmed it by a run (creatinine in umol/L excluded). Kept at the highest rating. The fix can move funnel counts: tell wave0-goldens. |
| CR-002 | Critical | safety / two-model rule | The two-model rule does not need two models. A verifier that is the same endpoint and model as the judge is accepted, reported as "both agree", and may exclude. Sources: S-2. | `services/orchestrator/app.py:56-73`; `services/orchestrator/scenarios/evaluate.py:501-520`; `tools/trialbox/doctor.py:227-233`; `services/orchestrator/selftest.py:174-180` | open | this session | FG-G D-276. Confirmed by a run with the gate off, by reading with the gate on. |
| CR-003 | Critical | safety / tests | The test stub answers for any model name and cannot disagree, lose confidence, return a bad quote or fail. Twelve exclusion-path rules have no test that fails when the rule is removed. Sources: S-3, P-34. | `services/llm_stub/app.py:23-25,57`; `services/llm_stub/handlers.py:172-230`; `tests/integration/test_case_inproc.py:148-157`; rules at `services/matching/cascade/engine.py:809-816,927-937,610-615,707-719` | open | this session | FG-G D-276 (stub personas by model name, new test files; no edit to `tests/conftest.py` or goldens). Confirmed by a mutation run: 64 mutants, 244 database-free tests. The goldens and CI halves of P-34 are rows CR-064 and CR-074. |
| CR-004 | High | safety / two-model rule | Both models read the same cut excerpt set. Notes over the 2,500-token budget are skipped without a word, and an agreed `fail` on an inclusion still excludes. Sources: S-10. | `services/matching/cascade/engine.py:73,572-593,811-826` | open | this session | FG-G D-276. Mechanism confirmed by a run; the end result by reading. |
| CR-005 | High | safety / engine | Record status is stored and never used. An entered-in-error or cancelled lab, and a cancelled medication order, count like valid records. Sources: S-4. | `services/lake/flatten.py:275,279-298,316`; `services/criteria_compiler/compile_sql/generator.py:148-161,218-223`; `services/adapter/sources/ssmix2/source.py:75,442` | open | this session | FG-F D-275. Labs confirmed by a run, medication by reading. Applies on the OMOP path too. |
| CR-006 | High | safety / engine | Sex `other` or `unknown` is treated as "not female": a sex criterion is FALSE, eGFR uses the male constants, and the pregnancy-test arm of an exclusion is switched off. Sources: S-5. | `services/lake/flatten.py:216`; `services/criteria_compiler/compile_sql/generator.py:311,434-435` | open | this session | FG-F D-275. Confirmed by a run. |
| CR-007 | High | safety / engine | Missing data becomes FALSE: an order with no end date counts one day, an order with no date is dropped at ingest, and under v1 a FALSE structured inclusion is a hard exclusion with no second check. Sources: S-9. | `services/criteria_compiler/compile_sql/generator.py:399-405,424`; `services/lake/flatten.py:314-315`; `services/adapter/pipeline.py:245-251`; `services/matching/cascade/engine.py:543-544` | open | this session | FG-F D-275. By reading. All five shipped rulesets run v1 (`services/matching/cascade/engine.py:210-213`). |
| CR-008 | High | safety / SAE | A fatal AE, or one with a "why serious" answer, whose Serious radio is "No" is not an SAE: no clock, no case, no alert. Sources: S-6. | `services/datacore/lifecycle.py:125-128`; `services/orchestrator/lifecycle_api.py:283`; `services/console/saerecord.py:278,285-286`; `services/datacore/builtin/forms.csv:28-31` | open | this session | FG-H D-277. Confirmed by a run. |
| CR-009 | High | safety / SAE | The SAE clock falls back to the Taiwan rules (7/15 days) for any zone or rule name it does not know, and ignores a malformed override silently. `site.tz: Japan` gets the Taiwan clock. Sources: S-7. | `services/datacore/lifecycle.py:102-117`; `services/orchestrator/lifecycle_api.py:269-272` | open | this session | FG-H D-277. Confirmed by a run. |
| CR-010 | High | safety / SAE | SAE alerts fail open outside the worklist: no answer from the orchestrator shows "no SAE"; any "reported on" date (even 2099) clears overdue; rule follow-ups never reach a mail. Sources: S-8. | `services/console/lifecycle_pages.py:188-202,216-217,227-232`; `services/datacore/lifecycle.py:134-136`; `services/console/saerecord.py:144-165,168-188,573-576` | open | this session | FG-H D-277. (b) confirmed by a run; (a) and (c) by reading. |
| CR-011 | High | safety / SAE | Left over from the SAE register (PR #60): death does not end the participant; report rows have no unique index; the site zone falls back to UTC silently when `site.tz` is unset. Sources: PR #60 M5, M7, D-143 (line 3101), R-09 residue. | `services/datacore/lifecycle.py:40-50`; `services/console/saerecord.py:71-87`; `services/console/timefmt.py:15-22` | open | this session | FG-H D-277. The register itself is fixed (row CR-104). M5 and M7 are rated Medium in PR #60; the row is High for the death state. |
| CR-012 | High | safety / SAE | SAE register: the sync runs on a page GET as `system:sync`; the write-path hook is not built. Not built either: the copy to the office mailbox, the wrong-clock OQ test, the `/api/v1` route. Sources: PR #60 H3, PR #60 "Open", D-191. | `services/console/saerecord.py` (file only; PR #60 body) | open | the coordinator (task card T-310) | Workstream, not a defect fix; not done in this session. Not in FG-H. |
| CR-013 | High | safety / unknowns | No reason per item for missing data. "Needs information" does not say what to ask or whom. Sources: MR-019. | no code found (B: "no model for outside care / EMR-since") | open | the coordinator (task card T-216) | Workstream, not a defect fix; not done in this session. |
| CR-014 | High | safety / PI checks | No weekly PI sample of ten "not matched" patients. A patient sent back from the excluded list does not re-enter the PI list. Sources: R-07, MR-004, MR-200, J-12. | grep `weekly.*sample` in `services/console/*.py` = 0; `docs/DECISIONS.md:3101` | open | the coordinator (task card T-310) | Workstream, not a defect fix; not done in this session. The "excluded and why" page itself is done (`tests/console/test_excluded_page.py`). |
| CR-015 | High | safety / real data | No vendor SS-MIX2 file and no real MEDIS, JLAC10 or YJ code has ever been read. Notes may be missing from the feed. Sources: MR-110, R-84, PR-18. | `docs/DECISIONS.md:2385-2392` | open | the owner | Needs real site data. |

### 2.2 Privacy

| ID | Severity | Area | Problem | Evidence | Status | Owner | Fix group / note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-016 | Blocker | privacy / audit log | Chart numbers are written in clear into the hash-chained audit log by three writers and shown unmasked on `/audit` and on the job page. The page mask does not match the stored `options` form. No reason, no reveal record, no rate limit. Sources: PV-1 (and PV-9). | `services/orchestrator/core.py:301-309`; `services/console/app.py:680-687`; `services/mail_gateway/gateway.py:190-197`; mask `services/console/app.py:240-245`; `services/console/app.py:838-848` | open | this session | FG-C D-272: orchestrator and mail-gateway writers and the audit-table mask. The console request-line writer is patch PX-3 for PR #67. Mask confirmed by a snippet. Rows already in the chain need the owner's ruling (OD-7). |
| CR-017 | Critical | privacy / reveal | The oldest reveal route `POST /pilot/jobs/{id}/reveal` has no delegation check, an optional reason, no opt-out check, and works on any finished screening job. Sources: PV-2. | `services/console/app.py:1263-1289`; sibling `services/console/home.py:747-783`; `services/orchestrator/app.py:310-345` | open | another session (PR #67, owns `services/console/app.py`) | Patch PX-4. The orchestrator-side opt-out check comes with FG-D (row CR-019). Long term: T-103, one reveal path. |
| CR-018 | High | privacy / delegation | The delegation rule (D-147) is applied on the week, patient, candidate and SAE pages and not on their siblings: excluded list, `/api/v1` patients and screening log, cohort, participants, trial values, exports, job page, registry, N1 mail. Sources: PV-3. | guard `services/console/home.py:329-334`; missing at `services/console/home.py:679-687,1031-1041,1085`; `services/console/screening_log.py:142-146,236-240`; `services/console/lifecycle_pages.py:95-102`; `services/console/entry_pages.py:89-97,164-173`; `services/console/app.py:1105,1221,1612-1621`; `services/console/notify.py:275` | open | this session | FG-D D-273 for the files this session may edit. The three call sites in `services/console/app.py` (PR #67) and `/ask` (PX-8) stay open until those sessions take them. The full answer is T-102. |
| CR-019 | High | privacy / opt-out | The opt-out register is not honoured on five read paths: job page rows, registry page, excluded list, orchestrator reveal, `/ask` fallback. A patient who opted out on Tuesday is still on Monday's job page. Sources: PV-4. | `services/console/app.py:1221-1259,1583-1598`; `services/orchestrator/app.py:310-345,551-556`; `services/console/home.py:651-677`; `services/console/site_pages.py:285-292` | open | this session | FG-D D-273: filter in the shared readers and in the orchestrator, not per page. The `/ask` fallback is PX-8. |
| CR-020 | High | privacy / export | The registry export returns every chart number of a study in one GET: no reason, no delegation check. The orchestrator checks only that a signed user is named, not the role or the study. Sources: PV-5. | `services/console/app.py:1711-1739`; `services/orchestrator/app.py:585-613` | open | this session | FG-D D-273 does the orchestrator half. The console half is patch PX-5 for PR #67. |
| CR-021 | High | privacy / opt-out pages | Chart number to pseudonym oracle with no rate limit: the opt-out endpoints return the pseudonym of any chart number. A study-scoped coordinator can test who is a candidate without a reveal record. Sources: PV-6. | `services/console/team.py:593-628,650,770-774`; `services/console/team.py:551-555`; `services/console/app.py:1623-1656` | open | another session (seven-task session, PRs #64–#68: the `/site/*` part of `services/console/team.py`) | Patch PX-7. |
| CR-022 | High | privacy / assistant | `/ask?pid=` and `/api/v1/ask` return one patient's criterion verdicts to any PHI role with no purpose, no view record, no audit event, no rate limit and no delegation check. Sources: PV-7. | `services/console/site_pages.py:198-258,264-292,675-686,777-780`; compare `services/console/team.py:252-264` | open | another session (seven-task session, PRs #64–#68: `services/console/site_pages.py`) | Patch PX-8. |
| CR-023 | High | privacy / roles | The administrator (IT operator) holds every patient-level right: view, reveal, study task "screen", SAE view, full export, registry export, and the audit trail that would show it. Sources: PV-8, P-30 (part), MR-027 (part). | `services/console/auth.py:150-161`; `libs/tb_common/authz.py:73,140`; `services/console/home.py:757` | open | this session | FG-D D-273 does the `libs/tb_common/authz.py` half. The `services/console/auth.py` half is patch PX-6 for PR #67. Needs the owner's decision first (OD-5): without a steward role nobody else keeps the lists. |
| CR-024 | Blocker | privacy / security / roles | Permission sprawl: no single permission function and no steward role. The privacy review counted 19 groups of permission helpers, six copies of `study_or_404` with three different rules, 28 uses of `can_view_phi`/`can_reveal`/`sees_ids` and 54 inline role comparisons. P-30 names five reveal entry points; the review found eight ways a chart number goes out (the five, plus the CASE job page, the registry export, and `/audit` with the job audit table) and five routes that take a chart number in with no limit. Sources: P-30, MR-027, MR-198, MR-040, MR-041, J-10, PV-8, PV-9. | `services/console/auth.py:28-29,150-166`; reveals at `services/console/app.py:1263`, `services/console/home.py:787,1077`, `services/console/team.py:311`, `services/orchestrator/app.py:310`; also `services/console/app.py:1184,1711,838-848`; `libs/tb_common/authz.py:93,106,146` | open | the coordinator (task card T-102, T-103) | Workstream, not a defect fix; not done in this session. A notes it got worse since the assessment: one more permission table (`sae_allowed`) and ten more inline checks. The defects inside it that this session fixes are rows CR-017 to CR-023. |
| CR-025 | High | privacy / mail | Spreadsheets with chart numbers are mailed as a password zip, and the password goes to the same person on the same channel. `zip` is the default mode; the safer `link` mode cannot deliver patient files. Sources: MR-048, R-12, PV-11 (a), PV-18. | `services/mail_gateway/outbound.py:116,159`; `libs/tb_common/config.py:173`; `services/orchestrator/scenarios/screen.py:601-603,631` | open | the owner | Policy decision first (OD-1); the code change is small after it. |
| CR-026 | High | privacy / opt-out | FEAS counts and the data-core exports (ODM, REDCap CSV) do not read the opt-out register. Sources: MR-035 (part), MR-175 (part), D-147 (line 3285), PV-4 (data-core part), DI-13 (part). | `services/orchestrator/scenarios/feas.py`, `feas_compute.py` (no opt-out use); `services/datacore/export.py:62,92,145`; `services/orchestrator/datacore_api.py:396-417`; `docs/DECISIONS.md:3285` | open | this session | FG-I D-278. Reviewers differ on the export half: C rates it High; E rates it Medium because the intended rule for an enrolled participant is not written down (OD-8). |
| CR-027 | Critical | privacy / opt-out | The opt-out worker is not built. An opt-out removes the patient from lists and scope; facts, chunks, vectors, snapshots and old backups keep the data. Sources: MR-175, MR-035, DF P0-4, D-149 (line 3441), DI-13. | no worker in `libs/tb_common/optout.py`, `services/lake`, `tools/trialbox`; `docs/DECISIONS.md:3441` | open | the coordinator (task card T-206) | Workstream, not a defect fix; not done in this session. C rates it Critical (P0-4); A and B rate the opt-out group High. |
| CR-028 | High | privacy / notes | The PHI pass on note text (FR-DEID-01) is not built: the lake keeps names and phone numbers inside note text. Sources: D-111 (line 1222). | `libs/tb_common/policy/classes.py:83` (class names only); no pass in `services/` or `libs/` | open | the coordinator (no task card named) | Rated High by C's own judgement. Sizeable; not in a fix group. |
| CR-029 | High | privacy / access | No break-glass (reason, second person, time limit). Sources: MR-033. | grep `break.glass` in `services`, `libs`, `tools`, `deploy` = 0 | open | the coordinator (task card T-309) | Workstream, not a defect fix; not done in this session. |
| CR-030 | High | privacy / roles | No restricted clinician view; no clinician role. Sources: MR-039. | `services/console/auth.py:28` | open | the coordinator (task card T-314) | Workstream, not a defect fix; not done in this session. |
| CR-031 | High | privacy / consortium | No shared code-map registry and no de-identified export with k-anonymity, date shift and manifest. Sources: MR-142, MR-143. | `libs/tb_common/smallcell.py` (small-cell rule only) | open | the coordinator (task card T-316) | Workstream, not a defect fix; not done in this session. |
| CR-032 | Blocker | privacy / process | Real patient data could reach build agents before the data-processing agreement is signed. Only a plan rule stops it. Sources: PR-01. | plan rule only (B, not deep-verified) | open | the owner | Contract action. |

### 2.3 Security

| ID | Severity | Area | Problem | Evidence | Status | Owner | Fix group / note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-033 | Blocker | security / identity | Master has no second factor, no AD/LDAP/OIDC and no TLS on the console. Sources: MR-023, R-04, PR #67, SEC-10. | grep `totp, webauthn, pyotp, ldap, oidc, must_change` in `services`, `libs`, `tools`, `deploy` = one i18n string (`services/console/i18n_step4.py:111`); `deploy/docker-compose.yml:223-234` | in progress elsewhere | another session (PR #67, branch claude/tb-identity-tls, D-192/D-193) | Card T-109. PR #67 is a draft: its adversarial review and test re-run are pending and its Caddyfile is not validated. |
| CR-034 | Blocker | security / e-signature | The e-signature's only component is a password the administrator has seen. Admin create and reset show the password, and nothing forces the owner to replace it. Sources: SEC-1, P-12 (part), MR-149 (part), MR-023 (forced change). | `services/console/app.py:899-927`; `services/console/auth.py:326-333`; `services/console/edc_pages.py:263`; `services/edc/store.py:366` | open | another session (PR #67, owns `services/console/auth.py` and `app.py`) | Patches P-1 and P-2. Nobody is fixing it now: PR #67 lists "forced first change" and step-up among its known limits. |
| CR-035 | High | security / e-signature | No record lock. Any account with `enter_data` can change or withdraw a value another person signed, even one already sent. The signature is unlinked quietly and its row is not marked void. No second factor at signing. Sources: SEC-2, P-12, MR-149, EDC E-10, E-11 (open part), D-162 (line 3679). | `services/edc/store.py:281-343` (`:327-335`); `services/orchestrator/edc_api.py:187-191`; `services/console/edc_pages.py:241-266` | open | another session (branch fix-edc-gw, owns `services/edc/*`) | Patch P-3; card T-205. fix-edc-gw is about the gateway 409 (row CR-072), not the lock, so nobody is fixing this now. The second factor depends on PR #67. |
| CR-036 | High | security / e-signature | The signature binding is an unkeyed SHA-256 kept in the row it protects. It does not cover signer, name, meaning or time; send and export never compare with the signature row; the trail tables can be updated and deleted. Sources: SEC-3, EDC E-21, P-12 (trail tables). | `services/edc/store.py:52-62,103-108,362,398,407-408` | open | another session (branch fix-edc-gw, owns `services/edc/*`) | Patch P-4; card T-115. |
| CR-037 | High | security / database | One PostgreSQL role for every service. The mail gateway, model gateway, lake, compiler and adapter can read and write `auth` (sessions, password hashes), `edc` (signatures) and the pseudonym map. Sources: SEC-4. | `deploy/docker/db-init/10-trialbox-wf.sh:6-7`; `deploy/install.sh:198`; `deploy/docker-compose.yml:19`; `deploy/docker-compose.secrets.yml:13,40,44` | open | the coordinator (no task card named) | Not in a fix group and no patch written. `deploy/install.sh` and `deploy/docker-compose.secrets.yml` are also changed by PR #68. |
| CR-038 | High | security / orchestrator | Outside EDC, reveal, export and cancel, the orchestrator takes the acting person from the request body (`by`) and checks no role. The mail gateway's token is accepted on every route. Sources: SEC-5, D-114 (line 1283, the `by` part). | `services/orchestrator/datacore_api.py:217-226,239-255,324-335,379-391`; `services/orchestrator/study_api.py:395-396,416-417,426-442`; `libs/tb_common/service_auth.py:73` | open | this session | FG-I D-278. |
| CR-039 | High | security / SSO | The trusted-header SSO trusts a header by peer address: forgeable behind Docker NAT, signs a local account in without TOTP, and each rejected header writes an fsynced audit event (flood). Sources: MR-024, R-11, PR #67 known limit. | `services/console/app.py:440-466`; `deploy/docker-compose.yml:224`; `services/console/auth.py:293`; `libs/tb_common/audit.py:143,156` | open | another session (PR #67, owns `services/console/app.py` and `auth.py`) | No patch written. A did not trace the exact forgery path. PR #67 lists it as an open limit (WS-13.1). |
| CR-040 | High | security / gateway | The gateway routes on the self-declared `X-TB-Caller`; the verified caller is not read by policy. No per-caller token for the fhir-store and Postgres, no mTLS. Sources: D-138 (line 2498). | `services/gateway/core.py:5,59` | open | the coordinator (no task card named) | Rated High by C's own judgement. Not in a fix group. |
| CR-041 | Blocker | security / data at rest | Windows/WSL2: no BitLocker, swap or hibernation check. `site_hmac.key` and `pid_map.key` are plain files beside the data; PHI spreadsheets and uploads are in clear. Sources: MR-045, R-05, PR-10. | `deploy/windows/preflight.ps1` (grep BitLocker, hibernat, swap = 0); `services/orchestrator/candidates.py:65,71`; `services/orchestrator/scenarios/screen.py:326,603`; `services/orchestrator/scenarios/case.py:202` | open | the coordinator (task card T-210) | Workstream, not a defect fix; not done in this session. |
| CR-042 | High | security / audit | The audit chain is an unkeyed hash chain on a volume six containers mount read-write; the archive is on the same box. Any of them can rewrite history and recompute every hash. Sources: MR-047, R-18, R-91, SEC-8. | `libs/tb_common/audit.py:48-51`; `deploy/docker-compose.yml:148,162,179,192,214,231`; `tools/audit_verify.py:40` | open | the coordinator (task card T-211) | Workstream, not a defect fix; not done in this session. The head anchor is done now as row CR-054; signed heads and one writer stay with T-211. F rates SEC-8 Medium; A and B rate MR-047 High. |
| CR-043 | High | security / egress | The egress table is not persisted: outbound is open after a reboot. Sources: MR-056, R-22. | `deploy/install.sh:285`; `deploy/network.sh:8`; `deploy/egress.py:22` | open | the coordinator (task card T-212) | Workstream, not a defect fix; not done in this session. PR #68 also edits `deploy/egress.py` and `deploy/install.sh`. |
| CR-044 | High | security / supply chain | The Python lock has no hashes, there is no SBOM or audit step, two images are pulled by tag, and `pypdf` 6.19.0 and `pillow` 12.3.0 are still pinned. Sources: MR-072, R-19, SEC-13, PR #61. | `deploy/requirements.lock:108,137` (0 `sha256`); `deploy/docker/python.Dockerfile:7,18`; `deploy/docker-compose.yml:256` | in progress elsewhere | another session (PR #61, branch claude/tb-supply-chain, D-185/D-186) | PR #61 is a draft with unstable CI. Advisory state of the two pins was not checked (no network). |
| CR-045 | Critical | security / supply chain | Container images carry HIGH and CRITICAL vulnerabilities: 32 fixable in each of trialbox-jvm and trialbox-demo (jackson, HL7 core, beanutils, guava, httpcore5, ucum); third-party images mailhog 1,590, vllm 29, postgres 30, hapi 24, greenmail 16. Sources: PR #61 "Open: vulnerabilities", R-19 (part), SC-94. | PR #61 body and file list (C); file `deploy/security/known-image-findings.md` exists only on the PR #61 branch | open | the owner | Said plainly: the list is tracked only in a file on unmerged PR #61, in report mode (the gate does not fail), owner "security owner (to assign)", target 2026-12-10. No GitHub issue, nothing in master. Nobody is fixing it. OD-4. |
| CR-046 | High | security / release | `make_bundle.sh --gates` is optional: a bundle can ship images that passed no gate, and SBOMs are not in the signed bundle. Sources: PR #61 "Not done". | PR #61 body (C); `tools/make_bundle.sh` | open | another session (PR #61 follow-up; `tools/make_bundle.sh` is also in PR #68) | Rated High by C's own judgement. No patch written. |
| CR-047 | High | security / updates | Update bundles have no anti-rollback, key id or expiry: any old, validly signed bundle installs. No crash marker and no free-space check. Sources: MR-064, MR-065, MR-066, R-23, R-24, R-25, SEC-12, D-138 (line 2504). | `tools/verify_update.py:60-116`; `schemas/update_manifest.schema.json:8-18`; `tools/apply_update.sh`; `tools/trialbox/update.py` | open | the coordinator (task card T-111) | Workstream, not a defect fix; not done in this session. PR #68 edits `tools/verify_update.py` (+54 lines): check there first. F rates SEC-12 Medium; A, B and C rate it High. |
| CR-048 | High | security / cloud run | Cloud run (development tool, synthetic data): the driver's door key crosses plain HTTP; the bucket path was never rehearsed. Sources: D-150 (line 3521), M-06, M-07. | `docs/DECISIONS.md:3521`; `deploy/gcp/complete-run-vm.sh` | open | another session (the session that owns `deploy/gcp/*` and `tests/rehearsal/*`) | Rated High by C's own judgement. No patch written. |

### 2.4 Data integrity

| ID | Severity | Area | Problem | Evidence | Status | Owner | Fix group / note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-049 | Critical | integrity / dates | UTC date bug: the console's "today" is the UTC date in 18 listed places (delegation log, standing, E-10, account end date, IRB warnings, worklists, re-check dates). A PI in Japan is refused from 00:00 to 09:00 on the first day; a delegation or account end date runs nine hours long. Sources: DI-1, PR #69 "Not fixed here". | `services/console/home.py:67,236,268,359,441,535,642,645,836,934`; `services/console/edc_pages.py:177,216`; `services/console/team.py:139-140`; `services/console/auth.py:200,237`; `services/console/step4.py:233`; `services/console/teamstore.py:197-199` | open | this session | FG-A D-270 for `home.py`, `notify.py`, `timers.py`, `edc_pages.py`, `team.py:140`. `auth.py:237` and `step4.py:233` are patches PX-1 and PX-2. Count: G's text says 19, G's table and PR #69 list 18. |
| CR-050 | High | integrity / dates | The 07:00 and 07:30 notices (N1, N2) always run for yesterday: the timer fires in site time and passes the UTC date. No Monday digest is ever sent; a digest goes out on Saturday. Sources: DI-2. | `services/console/timers.py:73,76,102`; `services/console/notify.py:115,126,189,277,360,379` | open | this session | FG-A D-270. By reading; arithmetic checked. |
| CR-051 | High | integrity / tools | `tools/omop_parity.py` can pass without comparing anything (two empty lakes, no patients, no rulesets, every set skipped), runs in the caller's database, and its cleanup can drop the caller's schemas. Sources: DI-3. | `tools/omop_parity.py:435,441,451-453,458-463`; `tools/pglocal.py:130-131,146,154-157`; `libs/tb_common/db.py:63` | open | this session | FG-B D-271. |
| CR-052 | High | integrity / lake | Rebuilding a snapshot whose NDJSON folder is missing or empty builds an empty lake and makes it `CURRENT`. With the OMOP source the same call tombstones the hospital's whole feed. Sources: DI-7. | `services/lake/store.py:297-301,309`; `services/lake/source.py:75`; `services/omop/load.py:531-536,757-765,801-807`; `services/lake/app.py:98-100`; `services/sitesetup/service.py:341-343` | open | this session | FG-B D-271, in `services/lake/store.py` and `services/omop/load.py` (not `services/lake/source.py`, which wave0-goldens owns). Legacy path confirmed by a snippet; OMOP path by reading. |
| CR-053 | High | integrity / ingest | A held night (failed validation) is promoted by the next delta: the next run merges over the held folder, validates only its own new records, and moves `CURRENT`. Sources: DI-8, MR-173 (new hole). | `services/adapter/pipeline.py:264-266,273-275,306-308,312-316`; `tools/trialbox/backup.py:516-518` | open | this session | FG-B D-271. By reading, not run. B lists MR-173 as fixed (row CR-108): the hold itself works; this is the next night undoing it. |
| CR-054 | High | integrity / audit | Audit `verify` has no head anchor. Dropping the last events, deleting the newest day file, deleting everything, or rewriting and rehashing all pass. The archive overwrites a closed day that changed. Sources: DI-4, MR-047 (part), SEC-8 (part). | `libs/tb_common/audit.py:50-51,219-249`; `tools/audit_verify.py:26`; `tools/trialbox/logs.py:158-167` | open | this session | FG-C D-272. Confirmed by a snippet. Keyed hash and one writer stay with T-211 (row CR-042). |
| CR-055 | High | integrity / audit | The change is committed before the audit row is written, on another store. A failed append (full volume, I/O error, kill) leaves a mark, a screening number or an opt-out with no audit event. Sources: DI-5, PR #60 M8, SEC-6 (same pattern in EDC). | `services/console/home.py:875-891`; `services/console/team.py:620-629`; `services/sitesetup/service.py:342-345`; `libs/tb_common/audit.py:107-111,183` | open | this session | FG-D D-273. The EDC case (SEC-6, rated Medium) is patch P-5 for fix-edc-gw. |
| CR-056 | High | integrity / restore | Restore over a box that is not empty replaces the databases with no copy kept, checks neither site nor age, and on a real box fails its row check after it has replaced everything. The drill never runs this branch. The update rollback has the same leftover problem. Sources: DI-6. | `tools/trialbox/backup.py:378-388,817-847`; `tools/trialbox/__main__.py:183-186`; `tools/backup_drill.py:97,134-135`; `tools/trialbox/update.py:472-480`; `libs/tb_common/db.py:226-240` | open | this session | FG-E D-274. By reading; not run against Postgres. `tools/trialbox/backup.py` and `update.py` are also changed by PRs #66 and #68: expect merge conflicts. |
| CR-057 | High | integrity / backup | The backup's per-table hash builds one string over the whole table. Postgres cannot build a string over 1 GB, so the nightly backup fails once a table's text passes that (HAPI, OMOP `measurement`). Sources: DI-9. | `tools/trialbox/backup_schedule.py:139-141,171-175,621-622`; `tools/trialbox/backup.py:423-426,444` | open | this session | FG-E D-274. Not run; rests on the known Postgres limit. G's confidence: Medium. Loud failure, not silent. |
| CR-058 | High | integrity / backup | Backups are not wired at install: the cron is not installed, the default target is the same disk, HAPI is dumped only if a variable is set that install never sets, `doctor` has no local-only-target check, and nothing has run in Docker. Sources: MR-061, MR-062, MR-174, MR-184, R-20, R-21, PR #63 M7, D-188 (line 3713). | `deploy/install.sh:275,287-291`; `tools/trialbox/backup.py:305`; `tools/trialbox/doctor.py` (no backup check); `docs/DECISIONS.md:3713` | open | another session (PR #68 holds `deploy/install.sh` and `tools/trialbox/doctor.py`; PR #66 holds the admin tile) | No patch written. Card T-117. The backup code and tests themselves are merged (D-187, D-188). Not in FG-E. |
| CR-059 | High | integrity / database | Migrations are per-store DDL string lists split on `;`, with no checksum and no global order. Sources: P-32, MR-049, R-13 (open part). | `libs/tb_common/db.py:221-241` | open | the coordinator (task card T-104) | Workstream, not a defect fix; not done in this session. The reconnect half of R-13 is fixed (row CR-110). |
| CR-060 | Blocker | integrity / OMOP | OMOP CDM as the store of record: only the first slice is merged and the default source is still `legacy`. Sources: MR-125. | `services/omop/`; `services/lake/source.py:29-32`; `tests/unit/test_omop_core.py:146,437` | open | the coordinator (task card T-106, T-202) | Workstream, not a defect fix; not done in this session. Blocker in the owner's frame (go-live scope), not a defect. |
| CR-061 | High | integrity / OMOP | Provenance, vocabulary, conflicts and all-history back-fill: extension tables only. The screening view does not yet filter on record status or conflict; the legacy adapter holds the batch in memory. Sources: MR-126, MR-127, MR-128, MR-129, MR-144, MR-180, MR-189. | `tests/unit/test_omop_core.py:305,360`; `services/adapter/pipeline.py`; `docs/DECISIONS.md:3600-3610` | open | the coordinator (task card T-105, T-106, T-201) | Workstream, not a defect fix; not done in this session. |
| CR-062 | Blocker | integrity / EDC | EDC prefill lacks its GAMP 5 controls: the switch is two typed numbers and free text; drafts carry no map or dictionary version; `token_ref` can be re-pointed; arms and repeating instruments are refused, not handled; never run on a real REDCap. Sources: MR-147, MR-106, P-13, EDC E-05, E-15, E-16, D-160 (line 3640). | `services/edc/store.py:31-33,45-50,203-207`; `services/edc/prefill.py:49,313`; `services/edc/service.py:260-263`; `services/edc/odm.py:78-85` | open | the coordinator (task card T-115) | Workstream, not a defect fix; not done in this session. Blocker in the owner's frame. Also card T-302. `services/edc/*` is owned by branch fix-edc-gw. |
| CR-063 | High | integrity / lake | Publish rebuilds the current snapshot under the same id during a run; jobs are not pinned to a snapshot. Sources: MR-183, DF P1-12. | grep `snapshot_id, pinned` in `services/lake/store.py` = 0 | open | the coordinator (no task card named) | Not in a fix group. |
| CR-064 | High | integrity / tests | No committed funnel goldens. Sources: MR-083, MR-178, P-34 (part). | `tests/golden/` absent; `tools/omop_parity.py` report only | in progress elsewhere | another session (branch wave0-goldens) | C found no remote branch or PR named wave0-goldens on 2026-11-10: the work is not pushed. |
| CR-065 | High | integrity / process | No feature-flag mechanism; the first flag is an environment variable. Sources: MR-090, P-21. | `services/lake/source.py:29-32` (`TB_LAKE_SOURCE`); grep `feature_flag` = 0 | in progress elsewhere | another session (branch wave0-goldens) | Not pushed (as above). |
| CR-066 | High | integrity / derived values | Derived scores: definitions as data and stored rows with provenance are not on master. On the PR, screening still computes scores in SQL/CQL, rulesets do not pin definition versions, and the adversarial review is still owed. Sources: MR-185, MR-134, MR-155, PR #59. | `docs/DECISIONS.md:3442-3443`; PR #59 body (C) | in progress elsewhere | another session (PR #59, branch claude/tb-derived-scores, D-189/D-190) | Draft. |
| CR-067 | High | integrity / data operations | No data-operations console, no `dataops` schema, catalogue not loaded as data. Sources: MR-154, MR-181, MR-132, MR-173 (rest). | `libs/tb_common/flowledger.py:8` (comment only) | open | the coordinator (task card T-112) | Workstream, not a defect fix; not done in this session. |
| CR-068 | High | integrity / profile | No vector store, profile, annotations, setpoints or "patients like me". Sources: MR-135, MR-136, MR-137, MR-138, MR-139. | no pgvector or halfvec in `services` or `libs` (`deploy/pgbackrest/Dockerfile:5` comment only) | open | the coordinator (task card T-203) | Workstream, not a defect fix; not done in this session. |

### 2.5 Process and operations

| ID | Severity | Area | Problem | Evidence | Status | Owner | Fix group / note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-069 | Blocker | process / safety | Gate G1 has not passed. The real model pair has never completed `e2e_simple` or the scenario matrix through the gateway; real-model exclusions, extraction precision and OCR were never measured. Every gate runs the stub. Sources: P-01, MR-096, MR-021, R-15, D-139, D-141, D-148, PR #64. | `../.github/workflows/trialbox-e2e.yml:61`; `docs/DECISIONS.md:2682-2695,2911-2921`; no run-5 record in the repository | open | the owner | Paid cloud GPU run. A could not check whether a run happened outside the repository. |
| CR-070 | High | operations | GPU quota is 1. Sources: P-06. | `tools/complete_run.py:1289-1295,1328` (the check exists) | open | the owner | Quota request (OD-3). |
| CR-071 | High | operations | The compose stack has never run with the real pair, nothing has run in Docker, and there is no site-acceptance box. Sources: MR-068, MR-094, R-26, PR-15. | `docs/DECISIONS.md:3713` | open | the owner | Hardware. Card T-213 follows it. |
| CR-072 | High | operations / EDC gateway | EDC gateway 409: with strict model stand-ins, EDC note drafting through the gateway is refused with 409, so stage 16 fails on a real box. Sources: PR #69 "Not fixed here". | PR #69 body (C); `services/edc/prefill.py:371`; `services/orchestrator/app.py:538` | in progress elsewhere | another session (branch fix-edc-gw) | NOT landed as of 0cc908b. PR #69 says the fix "is on its own branch"; C found no remote branch and no PR named fix-edc-gw, and nothing in master addresses it. |
| CR-073 | High | operations / e2e | Stage 16 crashes the hospital part at 500 patients (box date behind the console date). Sources: PR #69. | PR #69 body (C); `tools/list_demo.py`; `tools/e2e_simple.py` | in progress elsewhere | another session (PR #69, branch claude/trialbox-plan-v4-oxn56n) | Draft, CI unstable. Rated High by C's own judgement. |
| CR-074 | High | process / CI | One workflow, pull requests only: no pytest, lint, type check, audit or nightly. Sources: MR-070, R-28, P-34 (part). | `../.github/workflows/trialbox-e2e.yml:5-6,61,65` | in progress elsewhere | another session (branch wave0-ci) | C found no remote branch or PR named wave0-ci on 2026-11-10: the work is not pushed. |
| CR-075 | High | process / tests | Test isolation leaks: an autouse Postgres outside pytest's tmp, a shared `/tmp/tb-pglocal-<uid>`, no xdist. Disk at 93 % on the build host. Sources: P-51, P-50, MR-071, R-29. | `tests/conftest.py:34-35`; `tools/pglocal.py:118`; `pyproject.toml:48-49,132` | in progress elsewhere | another session (branch wave0-ci) | Not pushed (as above). A could not reproduce the disk figure: this host is at 24 %. Unmerged branch claude/project-thread-4bwqoc-t5 also touches test order. |
| CR-076 | High | operations / build | On master `make images` fails: `python.Dockerfile` copies a removed folder and the JVM image misses the validator packages. Sources: PR #61 "Fixes to bugs already on master". | PR #61 body (C); `deploy/docker/python.Dockerfile` | in progress elsewhere | another session (PR #61; the same two files are in PR #68) | Rated High by C's own judgement. |
| CR-077 | High | process / decisions | Decision numbers are taken by guess. D-191 is used in nine code files and has no entry in `docs/DECISIONS.md`, which ends at D-188. Task cards start at D-190 while open PRs already took D-189 to D-193. Sources: P-31, PR #60 M9. | `docs/DECISIONS.md` (jumps D-151, D-160..163, D-187, D-188); `libs/tb_common/authz.py:133`; `docs/USER_GUIDE.md:98`; `docs/reviews/2026-11-09-assessment-and-tasks.md:1013` | open | the coordinator (task card T-002) | PR #69 adds the D-191 text. The registry is T-002. OD-6. D-270 to D-289 are free (C). |
| CR-078 | High | process / labelling | Product words: "Criteria not matched" is absent, forbidden words (excluded, 除外, 排除) are present 150 times, there is no forbidden-word check and no intended-use line in the footer. Sources: P-33, MR-038, PR-12. | `services/console/templates/base.html:51`; grep `criteria not matched` in `services/console` = 0 | open | the coordinator (task card T-116) | Workstream, not a defect fix; not done in this session. `templates/base.html` is also changed by PR #67. |
| CR-079 | High | process / models | No `qualify` command and no qualification record; prompts are plain files. Sources: MR-091. | grep `qualify` in `tools`, `services` = 0 | open | the coordinator (task card T-012) | Workstream, not a defect fix; not done in this session. |
| CR-080 | Blocker | process / review | One human merges; the safety core has no second reader. No CODEOWNERS, no CONTRIBUTING. Sources: PR-04, MR-095. | none of `CODEOWNERS`, `.github/CODEOWNERS`, `CONTRIBUTING.md` exists | open | the coordinator (task card T-002) | Workstream, not a defect fix; not done in this session. PR-04 is rated Blocker, MR-095 High. Naming the second reader is the owner's. |
| CR-081 | High | operations / release | Everything is `1.0.0`: no tag, changelog or `release.json`. Sources: MR-069, R-27. | `pyproject.toml:3`; `deploy/docker-compose.yml:15,118,127,137` | open | the coordinator (task card T-110) | Workstream, not a defect fix; not done in this session. |
| CR-082 | High | operations / containers | No container memory, CPU or pids limits. Sources: MR-050, R-17. | `deploy/docker-compose.yml:267,270`; no `mem_limit`, `pids_limit`, `cpus` in any compose file | open | the coordinator (task card T-108) | Workstream, not a defect fix; not done in this session. Compose files are changed by PRs #66, #67, #68. |
| CR-083 | High | operations / database | `postgres:16-alpine` cannot take pgvector. Sources: MR-057. | `deploy/docker-compose.yml:43`; `deploy/pgbackrest/Dockerfile:5` | open | the coordinator (task card T-104) | Workstream, not a defect fix; not done in this session. |
| CR-084 | Blocker | operations / hosting | Shared-host install (CGMH B200): `install.sh` assumes the appliance; no `shared-quota` profile, no `doctor --platform`. Interim hosting is undecided. Sources: MR-213, MR-214. | `deploy/install.sh` (appliance flow only); grep `shared-quota` = 0 | open | the coordinator (task card T-113) | Workstream, not a defect fix; not done in this session. Blocker in the owner's frame. The hosting choice itself is the owner's. |
| CR-085 | High | operations / mail | DNS, timeout and TLS errors leave a send key in `sending`; there is no resolve command and the outbox is not wired. Sources: MR-075, R-16. | `services/mail_gateway/gateway.py:57-65`; `services/mail_gateway/store.py:33,105` | open | the coordinator (task card T-108) | Workstream, not a defect fix; not done in this session. A did not examine it in depth. |
| CR-086 | High | process / PI workflow | The PI list does not prioritise; duplicate pills; checks are not explained. Sources: MR-097, R-30. | not re-verified (B) | open | the coordinator (no task card named) | Not re-verified by any reviewer on this pass. |
| CR-087 | High | process / independence | Study A PI: the owner decided the vendor's owner is the PI, against review SA S-04. It is not in the protocol and has no decision entry. Sources: P-15, MR-169, PR-08, SA S-04, PR #62 follow-up. | `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md:152`; `docs/plan/study-a-protocol.md:10` | open | the owner | OD-2. Card T-010 does the document edits after the ruling. |
| CR-088 | Blocker | process / sites | Neither site's data feed is known; the survey lacks the patient count. Sources: MR-161, PR-16, PR-18. | `docs/plan/sites/` (drafts only) | open | the owner | Not verifiable from the repository. |
| CR-089 | Blocker | process / sites | The Japan box is not ordered; CGMH B200 quota is open; the pair meets the B200 first on IQ day. Sources: MR-162, PR-05. | none in the repository | open | the owner | Not verifiable from the repository. |
| CR-090 | Blocker | process / sites | Hospital IT is not engaged; the zh-TW IT pack calls a re-identifiable store 去識別化. Sources: MR-163, PR-13. | `docs/plan/sites/` | open | the owner | The document fix is possible now. |
| CR-091 | Blocker | process / contracts | Licence, DPA, 責任分界 and insurance are open; sponsors are not told TrialBox is in the source-data chain. Sources: MR-164, PR-14, PR-11. | none in the repository | open | the owner | — |
| CR-092 | Blocker | process / IRB | The CGMH identified export has no owner; IRB amendments are the base case. Sources: MR-165, PR-02, PR-03. | none in the repository | open | the owner | — |
| CR-093 | Blocker | process / schedule | Go-live straddles Lunar New Year. Sources: PR-06, MR-215. | plan only | open | the owner | — |
| CR-094 | High | process / plan | Code changes after the pentest; accuracy never measured on real records before use; platform isolation attested, not verified; baseline overlaps IQ. Sources: PR-07, PR-09, PR-19, PR-20. | plan only | open | the owner | — |
| CR-095 | Blocker | process / Study A | Study A protocol: P1 power sized for half the target; "wrong exclusion" is a false-omission rate; reading rule, weighting, IRB legal basis, tuned charts in the sample; clinician access contradicts the intended use. Sources: SA S-01, S-02, S-03, S-05, S-06, S-07, S-08, S-09. | `docs/DECISIONS.md:3686` (D-163 says revised) | open | the owner | B: the documents were revised in D-163 but not re-read on this pass. Kept open until someone re-reads them. |
| CR-096 | High | process / regulatory | Counsel view, incident plan, QMS-lite, support contact, model and data licences are open. Sources: MR-166, MR-167, MR-168, MR-170, MR-171, MR-133. | none in the repository | open | the owner | — |

## 3. Verified as fixed

"Fixed" means the code is on master `0cc908b` and a named test exists. Reviewers A and B did not run the tests.

| ID | Severity | Area | Problem (sources) | Fixed where | Note |
| --- | --- | --- | --- | --- | --- |
| CR-097 | Blocker | safety / gateway | The installed box refused every PHI prompt; model hashes null. Sources: R-01, MR-001, cloud C-01. | `services/gateway/policy.py:124,187-198`; `tests/unit/test_gateway_box_phi.py` | Left over (Medium): `doctor` has no "gateway would refuse the judge" check; 21 `sha256: null` pinned at install. |
| CR-098 | Blocker | safety / engine | Non-numeric lab value ("75 H", "<0.3", 陰性) silently excluded. Sources: R-02, MR-002 (this half). | `services/criteria_compiler/compile_sql/generator.py:80-117,220`; `tests/unit/test_lab_value_unknown.py` | The unit half is open: row CR-001. CQL ignores the comparator (Medium). |
| CR-099 | Blocker | privacy / console | Chart number on the CASE job page for every role; viewer and CRO reached patient-level pages and `/api/v1`. Sources: R-03, MR-022, MR-193, J-03, J-04, J-05. | `services/console/app.py:243,398,505-532,1188`; `tests/console/test_journey_pages.py` | D-143, D-146. The audit-log leak is separate: row CR-016. |
| CR-100 | Blocker | security / e-signature | Orchestrator EDC routes trusted `by`, `signer`, `role`, `pid` from the body. Sources: EDC E-01. | `services/orchestrator/edc_api.py:17-18,32,39,140,199`; `tests/unit/test_edc.py` | D-162. The same fault outside EDC is open: row CR-038. |
| CR-101 | Blocker | privacy / roles | No delegation log, referral object, staff directory or whole-hospital candidate view. Sources: MR-028, MR-029, MR-030, MR-031, MR-032. | `services/console/team.py`, `teamstore.py`; `libs/tb_common/authz.py:71-72`; `tests/console/test_team_pages.py` | D-147. Checked by decision and test name only. The steward part is open: row CR-024. |
| CR-102 | High | safety / cascade | Patient missing from the snapshot shown as excluded. Sources: R-06, MR-003. | `services/orchestrator/scenarios/evaluate.py:434,617`; `services/orchestrator/scenarios/screen_cascade.py:188,348`; `tests/unit/test_screen_not_at_index.py` | — |
| CR-103 | High | safety / SS-MIX2 | 疑い (suspected) flag ignored. Sources: R-08, MR-005. | `services/adapter/sources/ssmix2/source.py:19,123-129,405`; `tests/unit/test_suspected_diagnosis.py` | Not confirmed on vendor storage (owner). |
| CR-104 | High | safety / SAE | Fatal SAE left the banner; no PI acknowledgement; no 7/15-day clock; no system of record. Sources: R-09, MR-006, J-13, PR-17. | `services/console/saerecord.py:6-26,47,62`; `services/console/sae_pages.py`; `tests/console/test_sae_record.py` | PR #60 (D-191). New holes: rows CR-008 to CR-012. |
| CR-105 | High | integrity / REDCap | Longitudinal sync blanked consent and enrolment dates. Sources: R-10, MR-007. | `services/datacore/sources.py:67,78,110-152`; `tests/unit/test_redcap_longitudinal.py` | — |
| CR-106 | High | safety / scenarios | FHIR scope 0, publish duplicates, undated rows decided. Sources: MR-020. | `tests/unit/test_scenario_findings.py` (decision and test name only) | D-142. |
| CR-107 | High | safety / derived values | CRP assumed mg/L; no JSN eGFR; no same-visit rule. Sources: MR-176, DF P0-5. | `libs/tb_common/derived.py:19-31,95-96,111,129`; `tests/unit/test_derived_scores.py` | Site unit defaults are an install step. |
| CR-108 | High | integrity / data flow | Deletes did not propagate on a delta night; failed validation still moved `CURRENT`; embeddings copied into every snapshot. Sources: MR-172, MR-173, MR-177, DF P0-1, P0-2, P0-6. | `services/adapter/ndjson.py:5-20`; `services/adapter/pipeline.py:269,306-308`; `tests/unit/test_dataflow_lake_p0.py:32,162,216` | D-149. MR-173 has a new hole: row CR-053. |
| CR-109 | High | integrity / EDC | Subject not bound to record key; two decided values per item; events unchecked; duplicate screening number; edited value kept the machine citation; `entered-in-error` drafted "Yes". Sources: EDC E-02, E-03, E-04, E-06, E-08, E-09, PR #56. | `docs/DECISIONS.md:3655-3682`; `tests/unit/test_edc.py` | D-162. Checked by decision and test names. |
| CR-110 | High | operations / database | One connection per store that never reconnects. Sources: R-13 (this half), MR-049 (this half). | `libs/tb_common/db.py:13-17,127,161-188`; `tests/unit/test_db_reconnect.py` | Checksummed migrations are open: row CR-059. |
| CR-111 | High | process / IRB gate | Missing IRB approval or ICF version did not warn; override not logged. Sources: MR-036. | `services/console/home.py:645,873-886,1069`; `services/console/team.py:520` | Monthly override report not seen. |
| CR-112 | High | security / jobs | Job rights by mailbox, not role; one 20-a-day limit across all job types; CJK PDF gave a 500; a new study's SCREEN failed on scope. Sources: MR-191, MR-192, MR-195, MR-209, J-01, J-02, J-07, J-26. | `libs/tb_common/authz.py:55,116`; `tests/unit/test_journey_rules.py` | D-146. |
| CR-113 | Critical | operations / cloud run | Cloud GPU run (development tool): no cap or watchdog, served-name 404, data not on the VM, stale state across boots, health never asserted. Sources: P-02, P-03, P-04, P-05, MR-060, R-14, cloud C-01 to C-03, H-01 to H-05. | `deploy/gcp/complete-run-vm.sh:24,269`; `tests/unit/test_served_names.py`; `tests/unit/test_cloud_run.py`; `tests/rehearsal/check.py:113,162` | PR #57 (D-150). Proven by the local rehearsal only, which is not in CI; nothing has run on the card since. The door-key item is open: row CR-048. |
| CR-114 | High | process | PRs #56, #57 and the OMOP branch conflicted on generated models and DECISIONS. Sources: P-11. | merged: `66f73cc`, `7f52be9`, `6e11e25` | — |

## 4. Patches for files other sessions own

None of these was applied or run. Line numbers are those of master `0cc908b`; the owning branch may have moved them.

| Patch | For | File | Who should take it |
| --- | --- | --- | --- |
| P-1 | CR-034 (SEC-1) | `services/console/auth.py`, `step4.py`, `app.py` | PR #67 (identity); the `step4.py` line goes to the seven-task session |
| P-2 | CR-034 (SEC-1) | `services/console/edc_pages.py` | after PR #67 merges (needs its TOTP verifier); the session that then owns the EDC pages |
| P-3 | CR-035 (SEC-2) | `services/edc/store.py`, `service.py`, `services/orchestrator/edc_api.py` | branch fix-edc-gw (owns `services/edc/*`); card T-205 |
| P-4 | CR-036 (SEC-3) | `services/edc/store.py` | branch fix-edc-gw; card T-115 |
| P-5 | SEC-6 (Medium, section 6); same pattern as CR-055 | `services/edc/store.py`, `service.py` | branch fix-edc-gw |
| P-6 | SEC-7 (Medium, section 6) | `services/edc/service.py` | branch fix-edc-gw |
| P-7 | SEC-9 (Medium, section 6) | `services/console/auth.py` | PR #67 |
| PX-1 | CR-049 (DI-1) | `services/console/auth.py:237`, `app.py:396` | PR #67 |
| PX-2 | CR-049 (DI-1) | `services/console/step4.py:233` | seven-task session (PR #66 changes `step4.py`) |
| PX-3 | CR-016 (PV-1) | `services/console/app.py:686` | PR #67 |
| PX-4 | CR-017 (PV-2) | `services/console/app.py:1278-1289` | PR #67 |
| PX-5 | CR-020 (PV-5) | `services/console/app.py:1717-1718` | PR #67 |
| PX-6 | CR-023 (PV-8) | `services/console/auth.py:154,161` | PR #67, only after the owner's decision OD-5 |
| PX-7 | CR-021 (PV-6) | `services/console/team.py:650,774` | seven-task session (the `/site/*` part of `team.py`) |
| PX-8 | CR-022 (PV-7) | `services/console/site_pages.py:266-267` | seven-task session (`site_pages.py`) |

### 4.1 Patches P-1 to P-7 (copied from the security review, unchanged)

The security reviewer wrote these against master `0cc908b` and did not apply or run them.

#### P-1 — forced password change after an admin-set password (SEC-1) — `services/console/auth.py`

```diff
--- a/services/console/auth.py
+++ b/services/console/auth.py
@@ -68,7 +68,10 @@ CREATE TABLE login_failures (
 );
 CREATE INDEX login_failures_user ON login_failures (username, at)
 """
-MIGRATIONS: tuple[str, ...] = (SCHEMA_V1,)
+# v2 (21 CFR 11.300, 11.100(a)): a password someone else set (account creation, an administrator's reset) must be
+# replaced by its owner before the account does anything else, so only the owner ever knows a password that signs.
+SCHEMA_V2 = "ALTER TABLE users ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0"
+MIGRATIONS: tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2)
 _COLS = "username, role, mailbox, affiliation, studies, expires"
 
 
@@ -281,8 +284,8 @@ class UserStore:
         if mb is not None and ("@" not in mb or " " in mb):
             raise AuthError("mailbox must be an e-mail address")
         n = self.db.execute(
-            "INSERT INTO users (username, role, pw_hash, mailbox, created) VALUES (?,?,?,?,?) "
-            "ON CONFLICT (username) DO NOTHING",
+            "INSERT INTO users (username, role, pw_hash, mailbox, created, must_change) VALUES (?,?,?,?,?,1) "
+            "ON CONFLICT (username) DO NOTHING",
             (u, role, hash_password(password), mb, self.clock().isoformat()),
         )
         if n != 1:
@@ -323,14 +326,22 @@ class UserStore:
         stored = self.db.fetchval("SELECT pw_hash FROM users WHERE username = ?", (username,))
         return bool(stored == SSO_MARK)
 
-    def set_password(self, username: str, password: str) -> None:
+    def must_change(self, username: str) -> bool:
+        """True while the account still has a password its owner did not choose."""
+        return bool(self.db.fetchval("SELECT must_change FROM users WHERE username = ?", (username,)))
+
+    def set_password(self, username: str, password: str, *, by_owner: bool = False) -> None:
+        """``by_owner``: the signed-in owner changed it after typing the current one (``/account/password``). Any
+        other caller (an administrator's reset, the CLI) leaves the account marked ``must_change``."""
         check_password_policy(password)
         pw_hash = hash_password(password)
         with self.db.transaction() as tx:
-            if tx.execute("UPDATE users SET pw_hash = ? WHERE username = ?", (pw_hash, username)) != 1:
+            if tx.execute("UPDATE users SET pw_hash = ?, must_change = ? WHERE username = ?",
+                          (pw_hash, 0 if by_owner else 1, username)) != 1:
                 raise AuthError(f"no user {username}")
             tx.execute("DELETE FROM sessions WHERE username = ?", (username,))  # sign out everywhere
             tx.execute("DELETE FROM login_failures WHERE username = ?", (username,))
```

Callers (same change set):

```diff
--- a/services/console/step4.py
+++ b/services/console/step4.py
@@ -176,7 +176,7 @@ def register(app: FastAPI, h: Helpers) -> None:
         else:
             try:
-                h.users.set_password(u.username, new)
+                h.users.set_password(u.username, new, by_owner=True)
             except AuthError:
                 error = "account.err.policy"
--- a/services/console/app.py
+++ b/services/console/app.py
@@ -499,6 +499,10 @@ def create_app(
             request.state.sso_cookie = token
             au.append("console.login", actor=f"console:{user.username}", detail={"role": user.role, "via": "sso"})
         _scope_check(request, sess)
+        # SEC-1: with a password someone else set, the account reaches only its own password page
+        if request.url.path not in ("/account", "/account/password", "/logout", "/lang") and us.must_change(
+                sess.user.username):
+            raise _Problem(403, "account.must_change")
         bind_session(sess.token_sha[:16])  # S-09: the actor this request names to the orchestrator is signed with it
         return sess
```

`home.api_session` needs the same check (`services/console/home.py:1001`), and the i18n catalogues a
`problem.account.must_change` text with a link to `/account`.

#### P-2 — second factor on the signature (SEC-1) — `services/console/edc_pages.py` (depends on PR #67)

PR #67 owns TOTP. I have not read that branch, so `verify_totp` below is a placeholder name for whatever it exposes;
the point is where the check goes and what is recorded.

```diff
--- a/services/console/edc_pages.py
+++ b/services/console/edc_pages.py
@@ -96,6 +96,7 @@ class ApiSign(BaseModel):
     visit: str = Field(default="", max_length=100)
     password: str = Field(min_length=1, max_length=200)
+    otp: str = Field(default="", max_length=8)  # the signer's one-time code (second signature component)
     meaning_ack: bool = False  # the signer read the meaning of the signature
     seen: dict[int, str] = Field(max_length=2000)  # draft id -> ``sha`` of each value the signer saw (GET drafts)
@@ -260,10 +261,14 @@ def register(app: FastAPI, h: Helpers) -> None:
             raise h.problem(409, "edc.err.edc.sign_sso")
         if not body.meaning_ack:
             raise h.problem(400, "edc.err.edc.meaning_ack")
-        if h.users.authenticate(sess.user.username, body.password) is None:
+        if h.users.must_change(sess.user.username):  # P-1: never sign with a password someone else set
+            raise h.problem(409, "edc.err.edc.must_change")
+        if (h.users.authenticate(sess.user.username, body.password) is None
+                or not h.users.verify_totp(sess.user.username, body.otp)):  # PR #67's verifier; fails closed
             au.append("console.edc_reauth_failed", ruleset=rid, actor=h.actor(sess),
                       detail={"record": body.record.upper()[:64]})  # fmt: skip
             raise h.problem(401, "edc.err.edc.reauth")
```

and in `services/edc/store.py:366` record `"password+totp"` instead of the constant `"password"` (pass `method`
through `EdcService.sign` and `SignBody`).

#### P-3 — record lock: a signed value changes only after re-authentication (SEC-2)

```diff
--- a/services/edc/store.py
+++ b/services/edc/store.py
@@ -279,7 +279,7 @@ class EdcStore:
         )
 
     def decide(self, study: str, draft_id: int, action: str, *, value: str = "", reason: str = "",
-               citation: dict[str, Any] | None = None, by: str, at: str) -> dict[str, Any]:  # fmt: skip
+               citation: dict[str, Any] | None = None, by: str, at: str, unlock: bool = False) -> dict[str, Any]:  # fmt: skip
         """Confirm, edit (with a reason) or reject one draft. The value's check against the field is the caller's
         (it knows the dictionary); the rules on citations, reasons and order are here."""
         if action not in ACTIONS:
@@ -291,6 +291,12 @@ class EdcStore:
             d = self._row(rows[0])
             if d["fate"] == "superseded":
                 raise EdcError("edc.superseded", "a newer draft replaced this one; open the subject again")
+            if d["signature_id"] is not None:
+                # a signed value is locked: it changes only right after the person typed their password again
+                if not unlock:
+                    raise EdcError("edc.locked", "this value is signed; type your password again to amend it", 423)
+                if not reason.strip():
+                    raise EdcError("edc.reason", "say why a signed value is changed", 400)
             old = d["final"] if d["fate"] in DECIDED else None
             cite = d["citation"]
             if action == "confirm":
--- a/services/edc/service.py
+++ b/services/edc/service.py
@@ -177,7 +177,7 @@ class EdcService:
         return self.store.drafts(rs, record, visit or BASE_EVENT)
 
     def decide(self, rs: str, draft_id: int, action: str, *, value: str = "", reason: str = "",
-               citation: dict[str, Any] | None = None, by: str) -> dict[str, Any]:  # fmt: skip
+               citation: dict[str, Any] | None = None, by: str, unlock: bool = False) -> dict[str, Any]:  # fmt: skip
         self.store.require_on(rs)
         d = self.store.draft(rs, draft_id)
         if d is None:
@@ -194,7 +194,7 @@ class EdcService:
                 raise err
         try:
             out = self.store.decide(rs, draft_id, action, value=value, reason=reason, citation=citation, by=by,
-                                    at=self.stamp())  # fmt: skip
+                                    at=self.stamp(), unlock=unlock)  # fmt: skip
         except EdcError as exc:
             self._audit("edc.decide", rs, by, {"draft": draft_id, "action": action, "refused": exc.code})
             raise
--- a/services/orchestrator/edc_api.py
+++ b/services/orchestrator/edc_api.py
@@ -187,8 +187,10 @@ def router(get: Callable[[], EdcService], claim: Claim = claim_of) -> APIRouter:
     @r.post("/studies/{rs}/edc/drafts/{draft_id}/decide")
     def decide(rs: str, draft_id: int, body: DecideBody, request: Request) -> dict[str, Any]:
         a = who(request, "review", body.by)
+        # a signed value is unlocked only by an assertion made right after a password check (as for signing)
+        unlock = (not a.verified) or a.session.startswith(REAUTH)
         return run(lambda: get().decide(_rs(rs), draft_id, body.action, value=body.value, reason=body.reason,
-                                        citation=body.citation, by=a.name))  # fmt: skip
+                                        citation=body.citation, by=a.name, unlock=unlock))  # fmt: skip
```

Console side (`services/console/edc_pages.py` `do_decide`): add an optional `password` to `ApiDecide`; when it is
given, call `h.users.authenticate` (audit a failure as `console.edc_reauth_failed`) and pass
`session="reauth-" + secrets.token_hex(8)` to `act(...)`, as `do_sign` does at line 275; the review page shows the
password field on signed rows. Also record the void on the signature itself: add
`ALTER TABLE signature ADD COLUMN voided TEXT` as a second migration and append the draft id and time there in the
`signature_void` branch (`store.py:327-331`).

#### P-4 — bind the signature to the whole act and verify it before use (SEC-3) — `services/edc/store.py`

```diff
--- a/services/edc/store.py
+++ b/services/edc/store.py
@@ -108,6 +108,17 @@ def draft_sha(d: dict[str, Any]) -> str:
     return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
 
 
+def signature_sha(study: str, record: str, visit: str, signer: str, printed_name: str, role: str, meaning: str,
+                  meaning_text: str, method: str, at: str, shas: dict[int, str]) -> str:
+    """What ``content_sha`` covers: who signed, as what, with which meaning, when, and every value hash."""
+    body = {"study": study, "record": record, "visit": visit, "signer": signer, "printed_name": printed_name,
+            "role": role, "meaning": meaning, "meaning_text": meaning_text, "method": method, "at": at,
+            "values": sorted((int(k), str(v)) for k, v in shas.items())}
+    # TB_EDC_SIGN_KEY_FILE (mounted into the orchestrator only) turns this into an HMAC: see the note below
+    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
+
+
 def _cit(raw: Any) -> dict[str, Any] | None:
     if raw in (None, ""):
         return None
@@ -359,7 +370,8 @@ class EdcStore:
             shas = {int(r["id"]): draft_sha(r) for r in rows}
             if {int(k): str(v) for k, v in seen.items()} != shas:
                 raise EdcError("edc.sign_changed", "the values changed since the page was shown; open it again")
-            content = hashlib.sha256(json.dumps(sorted(shas.items())).encode()).hexdigest()
+            content = signature_sha(study, record, visit, signer, printed_name, role, meaning, meaning_text,
+                                    "password", at, shas)
             sid = int(tx.fetchval(
                 "INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, "
                 "method, at, content_sha, drafts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
@@ -389,14 +401,29 @@ class EdcStore:
             raise EdcError("edc.duplicate", "an item has more than one current draft; nothing is sent or exported")
         return rows
 
+    def _covered(self, d: dict[str, Any], sigs: dict[int, dict[str, Any]]) -> bool:
+        """The value is still exactly what its signature row says was signed, and that row is itself intact."""
+        s = sigs.get(int(d["signature_id"]))
+        if s is None or d["signed_sha"] != draft_sha(d):
+            return False
+        shas = {int(k): str(v) for k, v in json.loads(s["drafts"]).items()}
+        if shas.get(int(d["id"])) != d["signed_sha"]:
+            return False
+        return bool(s["content_sha"] == signature_sha(
+            s["study"], s["record"], s["visit"], s["signer"], s["printed_name"], s["role"], s["meaning"],
+            s["meaning_text"], s["method"], s["at"], shas))
+
     def sendable(self, study: str, record: str | None = None, visit: str | None = None) -> list[dict[str, Any]]:
         """Decided, signed values whose content still matches the signature and that are not sent as they are."""
+        sigs = {int(s["id"]): s for s in self.signatures(study)}
         out = []
         for d in self._current(study, record, visit):
             if d["fate"] not in DECIDED or d["signature_id"] is None or not d["final"]:
                 continue
-            if d["signed_sha"] != draft_sha(d):
+            if not self._covered(d, sigs):
                 continue  # changed after signing (or tampered with): never sent
             if d["sent_at"] and d["sent_value"] == d["final"]:
                 continue
@@ -404,8 +431,9 @@ class EdcStore:
 
     def signed(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
         """Decided, signed values whose content still matches the signature (the ODM export)."""
+        sigs = {int(s["id"]): s for s in self.signatures(study)}
         return [d for d in self._current(study, record) if d["fate"] in DECIDED and d["signature_id"] is not None
-                and d["final"] and d["signed_sha"] == draft_sha(d)]  # fmt: skip
+                and d["final"] and self._covered(d, sigs)]  # fmt: skip
```

Notes for whoever applies it:

* Signatures made before this patch have the old `content_sha`. Either keep a `sig_version` column (old rows verified
  with the old formula) or re-sign; do not silently accept a mismatch.
* The hash is still unkeyed, so it stops accidental and partial tampering only. To resist a database writer, compute
  it as HMAC-SHA256 with a key file mounted into the orchestrator alone and add append-only triggers as a second
  migration (`self._db.migrate([SCHEMA, SCHEMA_V2])`):

```sql
CREATE OR REPLACE FUNCTION edc_append_only() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'edc.% is append-only', TG_TABLE_NAME; END $$ LANGUAGE plpgsql;
CREATE TRIGGER signature_ro BEFORE UPDATE OR DELETE ON signature FOR EACH ROW EXECUTE FUNCTION edc_append_only();
CREATE TRIGGER decision_ro  BEFORE UPDATE OR DELETE ON decision  FOR EACH ROW EXECUTE FUNCTION edc_append_only();
CREATE TRIGGER sent_ro      BEFORE UPDATE OR DELETE ON sent      FOR EACH ROW EXECUTE FUNCTION edc_append_only();
```

  (`Database.migrate` splits a version on `;`, so the function body needs to go in as one statement or through a
  helper; check `libs/tb_common/db.py:221` before using this text as is. Triggers hold only against a role that does
  not own the tables: this needs SEC-4.)

#### P-5 — audit the signature inside its transaction (SEC-6)

```diff
--- a/services/edc/store.py
+++ b/services/edc/store.py
@@ -22,6 +22,7 @@ from __future__ import annotations
 import hashlib
 import json
 import os
+from collections.abc import Callable
 from dataclasses import dataclass
 from datetime import date
 from typing import Any
@@ -344,7 +345,8 @@ class EdcStore:
 
     # ------------------------------------------------------------------ signature
     def sign(self, study: str, record: str, visit: str, *, signer: str, printed_name: str, role: str, meaning: str,
-             meaning_text: str, lang: str, at: str, seen: dict[int, str]) -> dict[str, Any]:  # fmt: skip
+             meaning_text: str, lang: str, at: str, seen: dict[int, str],
+             before_commit: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:  # fmt: skip
         """Sign the decided, unsigned values of one subject and visit. The caller has re-authenticated the signer.
         ``seen`` is what the signer's screen showed (draft id -> hash); the set and every hash must still be what is
         in the database now, or nothing is signed (review E-11)."""
@@ -367,6 +369,9 @@ class EdcStore:
                  content, json.dumps({str(k): v for k, v in sorted(shas.items())}))))  # fmt: skip
             for did, sha in shas.items():
                 tx.execute("UPDATE draft SET signature_id = ?, signed_sha = ? WHERE id = ?", (sid, sha, did))
+            if before_commit is not None:
+                # the audit event is written while the transaction is open: if it fails, nothing is signed
+                before_commit({"id": sid, "visit": visit, "content_sha": content, "values": len(shas)})
         sig = self.signature(sid)
         assert sig is not None
         return sig
--- a/services/edc/service.py
+++ b/services/edc/service.py
@@ -210,17 +210,18 @@ class EdcService:
         self.store.require_on(rs)
         pids = {str(d["pid"]) for d in self.store.drafts(rs, record, visit or BASE_EVENT)}
         self._not_opted_out(rs, signer, "edc.sign", pids, {"record": record})
+
+        def audited(s: dict[str, Any]) -> None:
+            self._audit("edc.sign", rs, signer, {"record": record, "visit": s["visit"], "signature": s["id"],
+                                                 "meaning": meaning, "printed_name": printed_name, "role": role,
+                                                 "values": s["values"], "content_sha": s["content_sha"]})  # fmt: skip
+
         try:
             sig = self.store.sign(rs, record, visit or BASE_EVENT, signer=signer, printed_name=printed_name,
                                   role=role, meaning=meaning, meaning_text=meaning_text, lang=lang,
-                                  at=self.stamp(), seen=seen)  # fmt: skip
+                                  at=self.stamp(), seen=seen, before_commit=audited)  # fmt: skip
         except EdcError as exc:
             self._audit("edc.sign", rs, signer, {"record": record, "visit": visit, "refused": exc.code})
             raise
-        self._audit("edc.sign", rs, signer, {"record": record, "visit": sig["visit"], "signature": sig["id"],
-                                             "meaning": meaning, "printed_name": printed_name, "role": role,
-                                             "values": len(json.loads(sig["drafts"])),
-                                             "content_sha": sig["content_sha"]})  # fmt: skip
         return sig
```

The remaining failure order is "audit line written, commit fails": an `edc.sign` event without a signature row,
which is the safe direction and is visible. `json` stays imported in `service.py` only if still used elsewhere
(check before removing). The same `before_commit` hook fits `store.decide` and `store.set_switch`.

#### P-6 — audit the refusals that are silent today (SEC-7) — `services/edc/service.py`

```diff
--- a/services/edc/service.py
+++ b/services/edc/service.py
@@ -178,10 +178,14 @@ class EdcService:
 
     def decide(self, rs: str, draft_id: int, action: str, *, value: str = "", reason: str = "",
                citation: dict[str, Any] | None = None, by: str) -> dict[str, Any]:  # fmt: skip
-        self.store.require_on(rs)
-        d = self.store.draft(rs, draft_id)
-        if d is None:
-            raise EdcError("edc.no_draft", "no such draft", 404)
+        try:
+            self.store.require_on(rs)
+            d = self.store.draft(rs, draft_id)
+            if d is None:
+                raise EdcError("edc.no_draft", "no such draft", 404)
+        except EdcError as exc:
+            self._audit("edc.decide", rs, by, {"draft": draft_id, "action": action, "refused": exc.code})
+            raise
         self._not_opted_out(rs, by, "edc.decide", {str(d["pid"])}, {"draft": draft_id})
         if action == "edit":
             f = self.dc.fields(rs).get(str(d["item"]))
@@ -207,7 +211,11 @@ class EdcService:
     def sign(self, rs: str, record: str, visit: str, *, signer: str, printed_name: str, role: str, meaning: str,
              meaning_text: str, lang: str, seen: dict[int, str]) -> dict[str, Any]:  # fmt: skip
         """The console re-authenticated ``signer`` just before this call; ``seen`` is what their screen showed."""
-        self.store.require_on(rs)
+        try:
+            self.store.require_on(rs)
+        except EdcError as exc:
+            self._audit("edc.sign", rs, signer, {"record": record, "visit": visit, "refused": exc.code})
+            raise
         pids = {str(d["pid"]) for d in self.store.drafts(rs, record, visit or BASE_EVENT)}
         self._not_opted_out(rs, signer, "edc.sign", pids, {"record": record})
```

In `services/orchestrator/edc_api.py` the router has no audit handle: pass the service's `audit` in (`get().audit`)
and append `edc.refused` with the code before raising at lines 140-141 (`edc.role`) and 196-200
(`edc.reauth_needed`). In `services/console/edc_pages.py:259-271` append `console.edc_refused` with the reason code
before each of the four `raise h.problem(...)`.

#### P-7 — lockout that an outsider cannot use against a named account (SEC-9) — `services/console/auth.py`

Sketch only (a new column, so a third migration after P-1's): `ALTER TABLE login_failures ADD COLUMN source TEXT NOT
NULL DEFAULT ''`; `authenticate(username, password, source="")` stores the caller's address; `locked()` counts
failures for `(username, source)` at the 5-in-15-minutes threshold and, separately, refuses a source with more than
about 30 failures across all names in 15 minutes; a much higher per-name ceiling (for example 50) stays as the
distributed-guessing backstop. `app.py:765`, `home.py:1010`, `step4.py:174` and `edc_pages.py:263` pass
`request.client.host`. Add `console.cli unlock <name>` that deletes the account's `login_failures` rows, audited.


### 4.2 Patches PX-1 to PX-8 (written by the assembler from the fix descriptions and the code on master)

#### PX-1: account end date by the site's day (DI-1), `services/console/auth.py`

```diff
--- a/services/console/auth.py
+++ b/services/console/auth.py
@@ -229,9 +229,12 @@ class UserStore:
     def __init__(self, url: str | None = None, clock: Clock = _utcnow) -> None:
         self.db = open_db(url, "auth", MIGRATIONS)
         self.clock = clock
+        # DI-1: an account's end date is a day at the site. console.app sets this to the site's date;
+        # the CLI and the tests keep the clock's own date.
+        self.today: Callable[[], date] = lambda: self.clock().date()
 
     def close(self) -> None:
         self.db.close()
 
     def _expired(self, user: User) -> bool:
-        return bool(user.expires) and self.clock().date().isoformat() > str(user.expires)
+        return bool(user.expires) and self.today().isoformat() > str(user.expires)
```

And in `services/console/app.py` (also PR #67):

- line 70, old: `from console.timefmt import local_time, site_zone`
- line 70, new: `from console.timefmt import local_time, local_today, site_zone`
- after line 396 (`    site_tz = site_zone(backend)`), add: `    users.today = lambda: local_today(users.clock(), site_tz)  # DI-1: the account end date is a site day`

`Callable` and `date` are already imported in `auth.py` (lines 20 and 22). Test to add: a clock at 2026-11-09T23:30Z with `site.tz=Asia/Tokyo` and `expires=2026-11-09` must be expired.

#### PX-2: "accounts ending soon" by the site's day (DI-1), `services/console/step4.py`

- line 20 area, add the import: `from console.timefmt import local_today, site_zone`
- line 233, old: `        today = h.clock().date()`
- line 233, new: `        today = local_today(h.clock(), site_zone(bk))`

`bk` is the module's backend handle (`step4.py:64`). If FG-A lands first and adds `Helpers.today`, the new line can be `today = h.today()` instead. Lines 236-237 of the same function compare audit times as text (DI-14, Medium); not part of this patch.

#### PX-3: the request line is audited masked (PV-1), `services/console/app.py`

- line 686, old: `            detail={"line": line, "mailbox": mailbox, "role": sess.user.role, "channel": "web"},`
- line 686, new: `            detail={"line": mask_ids(line), "mailbox": mailbox, "role": sess.user.role, "channel": "web"},`

`mask_ids` is defined in the same file (`app.py:243`). Effect: `console.request` rows no longer hold `mrn=…`. The job page builds its first thread row from this audit field (`app.py:1160`), so it will show the masked line; that also closes PV-9 for web requests. FG-C does the other two writers (`services/orchestrator/core.py:301-309`, `services/mail_gateway/gateway.py:190-197`). Test to add: after a CASE request, no audit line contains the chart number.

#### PX-4: the old job reveal goes through the one guarded path (PV-2), `services/console/app.py`

```diff
--- a/services/console/app.py
+++ b/services/console/app.py
@@ -1275,15 +1275,9 @@ def create_app(
         pid = pid.strip()
         if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", pid):
             raise _Problem(400, "request.refused", reason="bad pseudonym")
-        au.append(
-            "console.reveal",
-            job_id=job_id,
-            ruleset=job.ruleset,
-            actor=actor(sess),
-            detail={"pid": pid, "reason": reveal_reason(reason)},
-        )
-        try:
-            mrn = bk.reveal(job_id, pid, actor(sess))
-        except Refused as exc:
-            raise _Problem(409, "request.refused", reason=str(exc)) from exc
-        return _job_page(request, sess, job, revealed={pid: mrn or ""})
+        # PV-2: one reveal path. home.apply_reveal checks the delegation log, requires a reason, refuses a
+        # patient who is not on the study's latest list (so an opted-out patient), and audits before it asks.
+        if helpers.apply_reveal is None or not job.ruleset:
+            raise _Problem(403, "forbidden")
+        _ctx, mrn = helpers.apply_reveal(sess, request.url.path, job.ruleset, pid, reason, via="job")
+        return _job_page(request, sess, job, revealed={pid: mrn})
```

Notes for whoever applies it: `helpers` is the `Helpers` object built at `app.py:977`; `apply_reveal` is set by `console.home` (`home.py:747-786`). The audit event becomes `console.reveal_patient` (as on the patient page) instead of `console.reveal`; tests that look for the old name change. The form in `templates/job.html:83` already sends a reason. An old job's page can then reveal only patients still on the latest list; that is the intended narrowing. Check whether `reveal_reason` and `Refused` are still used in `app.py` before removing imports.

#### PX-5: registry export checks the delegation log and audits first (PV-5, console half), `services/console/app.py`

```diff
--- a/services/console/app.py
+++ b/services/console/app.py
@@ -1717,2 +1717,8 @@ def create_app(
         if not sess.user.sees_ids(rs):  # the export carries chart numbers (phi): identifier authority (D-143)
             raise _Problem(403, "forbidden")
+        # PV-5: the same rule as one reveal. An investigator exports only as the PI or a sub-investigator
+        # ticked "screen"; the request is audited before the file is built.
+        if sess.user.role == "investigator" and helpers.may is not None and not helpers.may(sess.user, rs, "screen"):
+            au.append("console.denied", actor=actor(sess), detail={"action": request.url.path[:80]})
+            raise _Problem(403, "forbidden")
+        au.append("console.registry", actor=actor(sess), ruleset=rs, detail={"action": "export_requested"})
```

This is the smallest guard. The privacy review asks for more, as a follow-up in the same file: make the export a POST with a reason and the CSRF token, and require the log-keeper task. The orchestrator half (role and study check at `services/orchestrator/app.py:585-613`) is FG-D.

#### PX-6: the administrator loses patient-level rights (PV-8), `services/console/auth.py`

- line 154 (`can_view_phi`), old: `        return self.role in ("admin", "coordinator", "investigator")`
- line 154, new: `        return self.role in ("coordinator", "investigator")`
- line 161 (`can_reveal`), old: `        return self.role in ("admin", "coordinator", "investigator")`
- line 161, new: `        return self.role in ("coordinator", "investigator")`

Do not apply before the owner's decision OD-5. Today the administrator also keeps the staff directory and the opt-out list (`team.py:551-555`) and is the only fallback when no coordinator exists; a steward role (T-102) and break-glass (T-309) must exist first, or a site can lock itself out of its own lists. The docstrings of both properties and many console tests change with it. FG-D makes the matching change in `libs/tb_common/authz.py:73,140`.

#### PX-7: the opt-out endpoints stop returning the pseudonym (PV-6), `services/console/team.py`

- line 650, old: `        return RedirectResponse(f"/site/opt-outs?done={done}&p={pid[:8]}", status_code=303)`
- line 650, new: `        return RedirectResponse(f"/site/opt-outs?done={done}", status_code=303)`
- line 774, old: `        return {"pid": pid, "opted_out": not body.lift, "changed": changed}`
- line 774, new: `        return {"opted_out": not body.lift, "changed": changed}`

Also needed in `change_optout` (`team.py:614-629`), described, not written as a diff: an hourly cap per person on chart-number lookups, kept in the team store as `rate()` does for candidate views (`team.py:218-222`), with a `console.rate_limited` audit event; and the lookup audited as its own event even when nothing changed. The page template `site_optouts.html` must not rely on `p=`. The privacy review also asks that only an unscoped hospital account (or the future steward) may use these routes: that is part of OD-5.

#### PX-8: the assistant's "why" answer checks delegation and opt-out and leaves an audit event (PV-7), `services/console/site_pages.py`

```diff
--- a/services/console/site_pages.py
+++ b/services/console/site_pages.py
@@ -266,2 +266,10 @@ def register(app: FastAPI, h: Helpers) -> None:
         if not _PID.match(pid or "") or not rs:
             return None
+        # PV-7: one patient's verdicts are patient-level data. Same delegation rule as the patient page, never an
+        # opted-out patient (the site-check fallback below does not read the register), and one audit event.
+        if sess.user.role == "investigator" and h.may is not None and not h.may(sess.user, rs, "screen"):
+            return None
+        if h.optout is not None and pid in h.optout.active():
+            return None
+        au.append("console.ask_patient", ruleset=rs, actor=h.actor(sess), detail={"pid": pid, "role": sess.user.role})
```

This is the smallest guard: no purpose and no rate limit yet. The privacy review's full fix is to send the "why" branch through `team.view_candidate` (purpose, hourly cap, view record) or to drop `pid` from the assistant, and to make `/ask` a POST so the question is not in the URL. `h.may`, `h.optout` and `h.actor` are fields of `Helpers` (`home.py:62,89-90`); `au` is bound at `site_pages.py:91`.

## 5. Needs the owner's decision

| No. | Decision | Rows | Recommendation |
| --- | --- | --- | --- |
| OD-1 | Default mode for patient files by mail: password zip (PPAP) or not | CR-025 | Stop PPAP for files with chart numbers. Make `link` the default once the guarded download exists; until then S/MIME or no patient file by mail. |
| OD-2 | Study A PI is the vendor's owner (conflict of interest) | CR-087 | Ask CGMH for a written conflict-of-interest ruling, name an independent co-investigator for the reading, and record it in the protocol and as a decision. |
| OD-3 | GPU quota and the paid G1 run | CR-069, CR-070 | Request the quota now and schedule run 5 after the rehearsal passes on current master. Nothing else can show the real pair works. |
| OD-4 | Who owns the image-vulnerability list and its 2026-12-10 target | CR-045 | Name one person today. Merge PR #61 so the list is in master. Fix the 32 own-image jar findings first; replace MailHog. |
| OD-5 | Administrator without patient data; who keeps the lists | CR-023, CR-024, CR-021 | Yes, with a steward role created first (T-102) and break-glass for the operator (T-309). Until then apply only the guards of FG-D. |
| OD-6 | D-191 is missing from `docs/DECISIONS.md`; D-190 to D-193 are claimed twice (task cards and open PRs) | CR-077 | Open PRs keep D-189 to D-193; task cards start at D-200 as the assessment's top note says; this session takes D-270 to D-278. Merge the D-191 text from PR #69 first. |
| OD-7 | Chart numbers already written into the audit chain | CR-016 | Keep the old chain sealed and readable by the steward only; start a new chain after the fix. Do not rewrite hashes in place. |
| OD-8 | Does an opt-out remove an enrolled participant from data-core exports and from counts; what is erased when a patient asks | CR-026, CR-027 | Counts and new exports: yes, honour the register. An enrolled participant's trial data stays (GCP), with the rule written down. Erasure rule to be set with the data steward. |
| OD-9 | A second human reader for the safety core | CR-080 | Name one; without a name CODEOWNERS is an empty file. |
| OD-10 | Hospital-side actions: feeds, box order, IT, contracts, IRB, schedule | CR-088, CR-089, CR-090, CR-091, CR-092, CR-093, CR-032 | Give each an owner and a date this week; they are the longest chains to go-live. |

## 6. Medium findings of the four adversarial reviews (not in scope for the fix phase)

These are listed so they are not lost. They are not fixed in this phase unless a fix group touches the same lines.

Patient safety (D):

- S-11: derived values have no plausibility bounds (height 0, creatinine 0). `services/criteria_compiler/compile_sql/generator.py:316,318-327`; `libs/tb_common/derived.py:119-120,193-199`
- S-12: feasibility sweep hard-excludes a patient with no notes when the index condition is not coded (latent). `services/matching/cascade/engine.py:639-648,686-696`
- S-13: S4 asks the verifier the question it already answered; it can never disagree. `services/orchestrator/scenarios/screen_cascade.py:93-97`; `services/matching/cascade/engine.py:908-947`
- S-14: SCREEN has no snapshot-age check; a stopped feed turns duration atoms FALSE. `services/orchestrator/scenarios/screen.py:438-449,667`
- S-15: the lake takes its zone from `TB_TZ` or Taipei, not `site.tz`. `services/lake/app.py:33`; `services/sitesetup/service.py:73`; `services/lake/store.py:232`
- S-16: an SAE with every clock set to 0 is a quiet row, not an alert. `services/console/saerecord.py:540,585-586`; `services/datacore/lifecycle.py:132-133`
- S-17: an Observation dated only by `effectivePeriod`, `effectiveInstant` or `issued` has no date and is never seen. `services/lake/flatten.py:291`

Privacy (E):

- PV-9: a CASE job page shows the chart number on a GET, with its own in-memory limiter (closed for web requests by PX-3). `services/console/app.py:1184-1197,248-266`
- PV-10: the log scrubber's chart-number rule is never switched on. `libs/tb_common/logging.py:33-37`; `services/orchestrator/core.py:406`
- PV-11 (b) to (e): `phi` mail bodies in clear; attachment names and subjects in audit rows; a refused CASE mails the chart number back. `services/mail_gateway/outbound.py:175,217-226`; `services/mail_gateway/gateway.py:131-144,153-167`; `services/orchestrator/scenarios/case.py:201`
- PV-12: N1 and N2 mail patient-level rows tagged `aggregate`, to every investigator. `services/console/notify.py:65-80,260-303`
- PV-13: the trace store keeps note text after regex redaction only; its read role is a self-written header. `services/gateway/core.py:467-489`; `services/tracestore/store.py:105-128`; `services/tracestore/app.py:27-37`
- PV-14: research-office counts ignore study scope; primary suppression only. `services/console/screening_log.py:294-324`
- PV-15: orchestrator reveal does not check the signed role and accepts NAV jobs; limits in memory. `services/orchestrator/app.py:266-284,310-345`
- PV-16: two workbooks are outside the flow ledger; the data-core export takes its actor from `?by=`. `services/console/screening_log.py:161-232,334-360`; `services/console/entry_pages.py:164-173`; `services/orchestrator/datacore_api.py:396-417`
- PV-17: pseudonyms and free text in URLs. `services/console/home.py:738`; `services/console/team.py:299,650`; `services/console/site_pages.py:675`; `services/console/step4.py:109`
- PV-18: `link` mode cannot deliver patient files (see CR-025). `services/mail_gateway/outbound.py:179-192`; `services/console/app.py:1319`

Security (F):

- SEC-6: the signature's audit line is written after the commit (patch P-5). `services/edc/service.py:213-223`; `services/edc/store.py:353-369`
- SEC-7: several signature and review refusals are not audited (patch P-6). `services/edc/service.py:181-194,210`; `services/console/edc_pages.py:259-271`; `services/orchestrator/edc_api.py:140-141,196-200`
- SEC-8: unkeyed audit chain, six writers (merged into CR-042, rated High there by A and B). `libs/tb_common/audit.py:48-49`
- SEC-9: lockout by user name lets an outsider keep any account locked (patch P-7). `services/console/auth.py:341-344,358-374`; `services/console/home.py:1008-1013`
- SEC-10: plain HTTP, `Secure` off by default, nothing refuses a wide bind without TLS (PR #67; CR-033). `deploy/docker-compose.yml:223-234`; `services/console/app.py:165,437,776`
- SEC-11: mail sender authentication fails open when `TB_MAIL_AUTHSERV_ID` is empty. `services/mail_gateway/app.py:32-37`; `services/mail_gateway/intake.py:63-75,139`
- SEC-12: no downgrade protection for updates (merged into CR-047, rated High there by A, B and C). `tools/verify_update.py:60-116`
- SEC-13: images by tag, lock without hashes (merged into CR-044). `deploy/docker/python.Dockerfile:7,18`
- SEC-14: the REDCap client accepts `http://`. `services/rc_bridge/client.py:60-61`; `services/orchestrator/study_api.py:426-442`
- SEC-15: until the log names a PI, any investigator can enter itself as PI with a free-text printed name. `services/console/team.py:82-87,443-463`; `services/console/edc_pages.py:213-219,267-275`
- SEC-16: with one shared service token every container can forge a `reauth-` assertion. `libs/tb_common/service_auth.py:256-258,330-337`; `services/orchestrator/edc_api.py:195-200`
- SEC-17: the actor assertion is not bound to the request and can be replayed for 120 s. `libs/tb_common/service_auth.py:63,201-203`; `services/console/edc_pages.py:272-275`

Data integrity (G):

- DI-10: restore, PITR and update rollback leave no audit trace; parked backup events are never appended. `tools/trialbox/backup.py:785-853`; `tools/trialbox/__main__.py:183-195`; `tools/trialbox/backup_schedule.py:655-663`
- DI-11: a backup is not one point in time. `tools/trialbox/backup_schedule.py:619-623`; `tools/trialbox/backup.py:568-590,700-715`
- DI-12: settings, `.env`, site pins and the pgBackRest cipher are not in a backup file. `tools/trialbox/backup.py:80-89`; `deploy/docker-compose.yml:24,65-67,213`
- DI-13: a patient deleted at the source is never removed; no erase path (see CR-027, OD-8). `services/adapter/pipeline.py:197-199`; `services/omop/load.py:715-716,767-772,826-829`
- DI-14: other time-zone slips outside the console. `services/omop/dqd.py:128`; `services/omop/load.py:458,974`; `services/orchestrator/scheduler.py:69`; `tools/trialbox/backup_schedule.py:359,649`; `tools/trialbox/update.py:485`; `services/console/home.py:363-364`; `services/console/step4.py:236-237`

Medium items from the PR bodies and decisions that reviewer C listed (PR #60 M3 and M8, PR #61 M1, M3, M6, PR #63 Lows, D-142 CQL censored values, D-143 in-memory rate limits, D-134, D-151 concept-id overflow, D-138 secrets in `deploy/.env`) are in `docs/DECISIONS.md` and the PR bodies and are not repeated here.

## 7. Update 1 (2026-11-10, after PRs #59, #67, #69 and #72 merged)

Master is now at `6506cb2`. The rows above are kept as first written; this section says what changed. Statuses marked "by merge" were taken from the merged PR's own description and checks, not re-verified line by line here.

### 7.1 Status changes

| Row | New status | Why |
| --- | --- | --- |
| CR-033 | partly fixed by merge | PR #67 (D-192, D-193): TOTP for local accounts by default, admin-issued enrolment codes, optional OIDC through Authelia, TLS through Caddy. Still open: a forced first password change, step-up, WebAuthn, removing header SSO. These go to FG-J. |
| CR-039 | fixed by merge | PR #67: header SSO works only in DEV and TEST, never signs in a local or OIDC account, and Caddy strips identity headers. |
| CR-072 | fixed by merge | PR #72 (branch fix-edc-gw): the routing policy did not list the purpose `data_entry`. `make rehearse` passed all 6 cases on its commit. |
| CR-073 | fixed by merge | PR #69 (stage-16 date fix). |
| CR-077 | partly fixed by merge | PR #69 added D-191 to `docs/DECISIONS.md`. The numbering registry is still open. |
| CR-066 | partly fixed by merge | PR #59 (D-189, D-190): score definitions as data and stored derived rows. Screening still computes scores in SQL and CQL; see CR-115. |
| CR-034, CR-035, CR-036 | open, owner this session | `services/edc/*` and the PR #67 files are free now. P-1 to P-6 move into FG-J and FG-L (7.3). |
| CR-016, CR-017, CR-020, CR-021, CR-022 | open, owner this session | The console halves (`app.py`, the site pages) are free now. They move into FG-C (CR-016) and FG-D (CR-017, CR-020, CR-021, CR-022). PX-3, PX-4, PX-5 become those groups' starting points. |
| CR-023 | open, owner this session | The owner decided OD-5 (7.4). It moves into FG-K. |
| CR-049 | open, owner this session | `auth.py` and `step4.py` lines move into FG-A; PX-1 and PX-2 are no longer needed as patches. |

### 7.2 New rows

| ID | Severity | Area | Problem | Evidence | Status | Owner | Fix group / note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-115 | High | safety / derived values | The SQL and CQL screening engines do not apply `derived.DOMAIN`. A joint count over 28, a negative CRP or ESR, or a creatinine of 0 or less gives a number there, while Python gives no value with `derived_unit`. The engines disagree, and garbage input can decide a criterion instead of reading as unknown. Already true for DAS28 on master; PR #59 extended the pattern to CDAI and SDAI. | coordinator message 2026-11-10; `libs/tb_common/derived.py` (DOMAIN); `services/criteria_compiler/compile_sql/generator.py`; `compile_cql` templates | open | this session | FG-F (D-275), added to that group. |
| CR-116 | Medium | security / identity | Lock-out (5 failures in 15 min) can be used to lock out the administrator; there is no per-IP throttle and failure rows are unbounded. Source: PR #67 review M3. | `services/console/identity.py` | open | this session | FG-J (D-279). Listed here because the coordinator asked; rated Medium by PR #67. |
| CR-117 | Medium | security / identity | An OIDC session outlives the directory account by up to 8 hours. Source: PR #67 review M5. | `services/console/oidc.py` | open | this session | FG-J (D-279). |
| CR-118 | Low | security / identity | PR #67 "other Lows": generous AMR set; the first OIDC account gets all studies; `totp.key` sits in the same backup as the database; Caddy's root key is unconstrained; Caddy on `trialbox-net`; HSTS without includeSubDomains; docs drift. | PR #67 body | open | the coordinator | Follow-up list, not in this session's fix phase except the `totp.key` backup point, which FG-E reviews. |
| CR-119 | Medium | integrity / derived values | Stored derived rows of erased or absent patients are never retired. Source: PR #59 review M8. | `libs/tb_common/derived_store.py` | open | the coordinator | Needs the erasure path (DI-13). |
| CR-120 | Low | integrity / derived values | PR #59 "other Lows": engine version not in the fingerprint; sha over the whole YAML; the generator guard can be bypassed; `latest()` edge cases; import-time coupling; prompts not updated; version namespaces; migration nits; fallback anchor key. Also its open Mediums M1, M2, M3, M5, M6. | PR #59 body | open | the coordinator | Follow-up list. |

### 7.3 Fix groups added

| Fix group | Decision and name | Rows |
| --- | --- | --- |
| FG-J | D-279 identity follow-ups | CR-034 (P-1 forced change after an admin sets or resets a password; P-2 second factor at signing), CR-033 rest, CR-116, CR-117 |
| FG-K | D-280 data steward and break-glass | CR-023, CR-027 (break-glass), per the owner's decision in 7.4 |
| FG-L | D-281 EDC signature controls | CR-035, CR-036 (P-3, P-4), SEC-6, SEC-7 (P-5, P-6) |

FG-C now also takes the `app.py` request-line writer of CR-016. FG-D now also takes CR-017 (PV-2), CR-020 (PV-5, both halves), CR-021 (PV-6) and CR-022 (PV-7). FG-F now also takes CR-115.

### 7.4 Owner decision OD-5 (recorded on 2026-11-10)

From `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md` (branch `claude/trialbox-plan-v4-oxn56n`, commit `bf0625a`, coming to master with the coordinator's next PR):

- A separate data-steward role covers sources, conflicts, lake and OMOP quality, opt-outs and exports. The admin role does not.
- An admin sees patient data only through break-glass: a reason (a fixed list plus free text), one patient or one job at a time, 60 minutes and then access ends by itself.
- Every view is audited (who, patient pseudonym, reason, time), and the steward and the PI are told.
- The steward reviews each use; unreviewed uses appear on the steward's worklist.
- Routine admin pages never show patient-level data.

### 7.5 Counts after update 1

Rows CR-001 to CR-114 are counted with the status changes in 7.1 ("partly fixed" counts as open). New rows CR-115 to CR-120 are listed but only CR-115 is counted, because the register counts Blocker, Critical and High only.

| Severity | open | in progress elsewhere | fixed | Total |
| --- | --- | --- | --- | --- |
| Blocker | 18 | 1 | 5 | 24 |
| Critical | 6 | 0 | 1 | 7 |
| High | 62 | 7 | 15 | 84 |
| Total | 86 | 8 | 21 | 115 |

## 8. Update 2: where this session stops (2026-11-10, 16:00 UTC)

The owner asked the sub-sessions to finish what was in hand and hand the rest back. This session started six of the fix groups (FG-A, FG-B, FG-C, FG-D, FG-F, FG-G). FG-A, FG-B, FG-F and FG-G were finished and opened as pull requests. FG-C was stopped after two minutes, with no commit, when the hand-back was asked for. The table below covers every fix group. The build session is now the only integrator (`docs/plan/30-integrator-closing-2026-11-10.md`).

### 8.1 Fix groups

| Fix group | Decision | Rows | Pull request | State | Checks (local, under the shared lock) | Adversarial reviews |
| --- | --- | --- | --- | --- | --- | --- |
| FG-A site-local "today" | D-270 | CR-049, CR-050 | #86 | merged | lint; 2,171 passed, 9 skipped, 0 failed; e2e_simple passed; CI green | 1 review: 0 B, 0 C, 0 H, 1 M, 7 L. The M and 2 L fixed, the rest Open in the PR. |
| FG-B data pipeline | D-271 | CR-051, CR-052, CR-053 | #97 | merged | lint; 2,658 passed, 14 skipped, 0 failed; e2e_simple passed | 1 review: 1 B, 1 C, 2 H, 3 M, 3 L, all fixed with tests |
| FG-C audit integrity | D-272 | CR-016, CR-054 | #104 | merged; built by another session after the hand-back | see #104 | see #104 |
| FG-D console privacy guards | D-273 | CR-017 to CR-023, CR-055 | #108 | open; another session | see #108 | see #108 |
| FG-E backup and restore | D-274 | CR-056, CR-057 | none | not started | | |
| FG-F structured-criteria safety | D-275 | CR-001, CR-005, CR-006, CR-007, CR-115 | #115 | open, draft, head `f514a52` | lint; 2,906 passed, 17 skipped, 2 xfailed, 1 failed (`test_notice.py`, the master break that #111 fixed); e2e_simple passed; decisions check clean | 1 review: 1 C, 2 H, 4 M, 6 L. All fixed except one Low. |
| FG-G two-model check | D-276 | CR-002, CR-003, CR-004, deep review LLM-002 and LLM-003 | #101 | open, head `5497ce9`; the build session merges master into it and merges it | lint; 2,841 passed, 17 skipped, 0 failed; e2e_simple passed | 2 reviews. First: 1 C, 1 H, 3 M, 4 L. Second, on the LLM-002 part: 1 H, 2 L. All C and H fixed. |
| FG-H SAE | D-277 | CR-008 to CR-011 | none | not started | | |
| FG-I orchestrator authorisation and opt-out | D-278 | CR-026, CR-038 | none | not started | | |
| FG-J identity follow-ups | D-279 | CR-034, CR-033 rest, CR-116, CR-117 | #107 | open; another session | see #107 | see #107 |
| FG-K data steward and break-glass | D-280 | CR-023, CR-027 | none | not started (owner decision OD-5 in 7.4) | | |
| FG-L EDC signature controls | D-281 | CR-035, CR-036, SEC-6, SEC-7 | none | not started (patches P-3 to P-6 in section 4) | | |

### 8.2 What the reviews of the fixes found

Every adversarial review of a fix found real defects in work that its author had called finished:

- FG-B's first version still wiped the lake on an empty night, because two Organization rows counted as data. It also let a held night's rows into CURRENT.
- FG-F's first version still counted cancelled SS-MIX2 orders, through the site mapping. Its unit conversion was a new wrong exclusion at the bound.
- FG-G's first version left weekly microbatch screening outside the two-model rule. Its consent explainer could still check its own draft.

All of these were fixed, each with a test, before the pull requests were opened. For the rest of the fix groups, a second review of each diff, by a reviewer that does not see the author's reasoning, is worth its cost.

### 8.3 New rows

| ID | Severity | Area | Problem | Evidence | Status | Owner | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-121 | Critical | safety / two-model check | Weekly microbatch screening worked out the tier without the note-block decision, so on a one-model box one model could exclude. | `services/matching/microbatch.py:115` (before #101) | in PR #101 | the build session | Found by FG-G's review (F-01). |
| CR-122 | Critical | safety / gateway | When the judge's server failed, the gateway answered as the judge from the verifier build, and the verifier then agreed with itself. | `models/routing.yaml:196`; `services/gateway/core.py:307-323` (before #101) | in PR #101 | the build session | Deep review LLM-002, reproduced. |
| CR-123 | High | safety / consent | The consent explainer's second-model check could be done by the drafting model, through the `protocol` route's fallback. | `services/orchestrator/consent.py` (before #101) | in PR #101 | the build session | Found by the second review of #101 (R2-01). |

### 8.4 Needs the owner's decision

| ID | Question | Recommendation |
| --- | --- | --- |
| OD-10 | Under the v1 rulesets, a FALSE structured inclusion is a hard exclusion. FG-F makes missing and unusable data unknown, but a real FALSE still excludes with no person in the loop. | Keep the rule for structured data with a known value, and send every v1 exclusion that rests on a single lab value to the weekly sample (WS-06.7). |
| OD-11 | The shipped rulesets were not recompiled; #115 adds a guard that keeps an answer only where the approved SQL and a fresh rendering agree. | Recompile and re-approve the five shipped rulesets before G2, then remove the guard. |
| OD-12 | FEAS counts a patient as dropped on a known FALSE that the approved SQL used to call TRUE (RA-COH, 332 to 331; #115 F6). | Accept; it is the same-visit rule of D-149. |
| OD-13 | Truncation by retrieval caps (v1 k=5, cascade top-5) is not treated as "evidence left out" (#101 F-05). Treating it so would stop most exclusions from notes. | Measure on G1 how often a capped answer excludes, then decide. |
| OD-14 | #115 moves 17 goldens, all toward unknown, none toward exclusion, no candidate count. | The goldens owner re-blesses after reviewing #115. |

### 8.5 Counts after update 2

Rows CR-001 to CR-123, Blocker, Critical and High only (CR-116 to CR-120 are Medium or Low and not counted). "In PR" counts as open until it is merged.

| Severity | open | in progress elsewhere or in an open PR | fixed (merged) | Total |
| --- | --- | --- | --- | --- |
| Blocker | 15 | 3 | 6 | 24 |
| Critical | 2 | 5 | 2 | 9 |
| High | 45 | 20 | 20 | 85 |
| Total | 62 | 28 | 28 | 118 |

How the rows moved from 7.5:
- **Merged:** CR-049 (Critical) and CR-050 (High) by #86; CR-051, CR-052 and CR-053 (High) by #97; CR-016 (Blocker) and CR-054 (High) by #104.
- **Now in an open PR:** CR-001 (Blocker) and CR-005, CR-006, CR-007 and CR-115 (High) in #115; CR-002 and CR-003 (Critical), CR-004 (High) and the new CR-121, CR-122 (Critical) and CR-123 (High) in #101; CR-017 (Critical) and CR-018 to CR-023 and CR-055 (High) in #108; CR-034 (Blocker) in #107.
- **Unchanged:** the rows that 7.5 counted as in progress elsewhere (the CI, goldens and supply-chain sessions) are still counted that way; this session did not re-check them.

Only #86, #97 and #104 were checked as merged on master `92b02ee`. The open PRs #107 and #108 were not read in this session; their rows follow the integrator's closing note.

## 9. Update 3: the console rows checked against master (2026-11-16, lane C2)

The status column above was last set on 2026-11-10. Lane C2 checked every row in the console, privacy, roles, dates, audit and opt-out area against master `9e6d04cb`, by the decision that closes it and the code that proves it. A row is "fixed" when its decision is merged and the code does what the row asked. The other rows say what is left.

| Row | Now | By | What is left |
|---|---|---|---|
| CR-008 | fixed | D-277 (`datacore/lifecycle.py` `is_serious`) | |
| CR-010 | fixed | D-277 (a)-(c) | D-277 open item 4: N1 and N2 still count partial reads |
| CR-011 | fixed | D-277, D-270 (`timefmt.site_zone` raises) | D-277 open items 5 and 6: deaths before enrolment are held; old duplicate rows block migration 3 |
| CR-012 | partly | D-277, T-602 (the write-path hook, the office mailbox) | no wrong-clock OQ test; `/api/v1` has the acknowledgement route only, no register route |
| CR-014 | fixed | D-446 (T-310a) | |
| CR-016 | owner | D-272 masks the writers and `/audit` from then on | the events already in the chain wait for the owner's OD-7 |
| CR-017 | fixed | D-273 (1), D-438 | |
| CR-018 | fixed | D-273 (`Helpers.delegated`), D-425 | |
| CR-019 | fixed | D-273 (`Helpers.gone`), D-441 | |
| CR-020 | fixed | D-273 (3) | |
| CR-021 | fixed | D-273 (4) | `/site/charts` lists the first 8 characters of a pseudonym |
| CR-022 | fixed | D-273 (5) | |
| CR-023 | fixed | D-280, D-380 | |
| CR-024 | fixed | D-366, D-380, D-425, D-438 | |
| CR-026 | fixed | D-477 (FEAS and COHORT) | the data-core exports are left unfiltered under OD-8 (an enrolled subject's data stays) |
| CR-027 | partly | D-441, D-798, D-860, D-862, D-863, D-866 | the owed list of the erasure registry (`docs/validation/erasure-registry.md`) |
| CR-030 | open | | no clinician role; T-314 waits on the regulatory consultant's opinion |
| CR-033 | fixed | D-192, D-193, D-279, D-320, D-447 | |
| CR-034 | fixed | D-279, D-391 | |
| CR-035 | fixed | D-281, D-391 | |
| CR-039 | fixed | D-192 (H1) | |
| CR-049 | fixed | D-270 (#86) | |
| CR-050 | fixed | D-270 (#86) | |
| CR-055 | fixed | D-273, D-281 | |
| CR-067 | fixed | D-353, D-427, D-443 | |
| CR-078 | fixed | D-351 (T-116) | |
| CR-111 | partly (section 3) | the warning and the logged override are in place | the monthly override report (T-310c) is not built |
| CR-116 | fixed | D-279 | |
| CR-117 | fixed | D-279 | |

CR-099, CR-101 and CR-104 stay as section 3 has them: fixed, re-confirmed by the 11-12 deep review. Rows outside this area are not checked here.
