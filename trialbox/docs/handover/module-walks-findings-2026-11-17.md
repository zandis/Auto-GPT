# The module walks: findings by step (2026-11-17)

**Reader:** the people who build TrialBox: the lanes that own the console (C2) and the box (D), lane V (the findings
register) and the integrator. Findings for builders, so in one language.

Card H-29, decision D-1103: V16 of plan 8, one walk per module that H-10's walk (D-1121, a new study) and H-20's walk
(D-1135, a study's whole life) do not cover. The box is a local steps-mode box (D-1062): `tools/demo.py` with demo
mode off, the stub model, the synthetic hospital and `--day data`. Each step is done by the role that owns it in the
permission matrix (`libs/tb_common/authz_matrix.yaml`), in en, zh-TW and ja, and every role boundary is checked by a
refusal: a real request carrying the page's own form token, answered 403 with the refusal page. The four walks:

1. **Feasibility alone** (D-1066): what a feasibility user does on a box without a GPU. Lane D's D-998 pins the
   embedder on a PRODUCTION box installed with `--mode stub` and RUNBOOK §1 says what such a box does; a steps-mode
   box is not such an install, so the walk is on the box master has (the stub model), on the seeded
   study `AD-MAB`, and stops where the box would have to say what it cannot do.
2. **Safety**: a serious adverse event from the report, through D-415's SAE-type gate and the PI's acknowledgement,
   to the notice the box records. A new study per language, from H-20's steps 1 to 15.
3. **Monitoring**: the monitor's role on the seeded study `GZQO` and the CRO account `cra`: who grants, what the
   monitor may open and may not, and what a refusal says.
4. **Amendment**: a protocol change after approval: who may change, what is approved again and by whom, the
   candidate list, the weekly page and the re-screen list before and after. A new study per language, from H-20's
   steps 1 to 15.

This page reports and does not fix: no product file was changed. Where the product does not do what its documents
say, the walk stops that step with the product's own words; it never asserts the fault as correct.

How it is run: `make walk-modules` (or `make walk-feasibility`, `walk-safety`, `walk-monitoring`, `walk-amendment`).
The browser is H-20's driver, `tests/e2e/life_cycle_walk.js`, required by `tests/e2e/module_walk.js`, which adds the
acts the module forms need through the driver's `extend`. Each run writes a JSON log per module and language outside
the repository. The tables below are written from the four plans (`tests/e2e/module_walk_<module>_plan.py`, through
`tests/e2e/module_walk_common.py`), and a fast test keeps them equal; the same findings are in
`module-walks-findings-2026-11-17.json` beside this page, in the findings register's `--add-from` form.

One box for all four walks meets the coordinator's daily limit of heavy runs (D-146, D-775: 20 FEAS jobs per account
in 24 hours by default): the walks start about 26 FEAS jobs from the one coordinator account, besides the seed's, and
on the first run the 21st, the Japanese amendment's protocol, was refused with "Today's limit is reached". That is
the product as documented, not a finding; the walks' own box is started with `TB_JOBS_PER_SENDER_PER_DAY=60`
(a box given by `TB_WALK_BASE` keeps its own limit). A tester who walks every module on one box in one day meets the
same page.

## Findings

Closed before this page: the first runs' MON-04 (the source-reference sheet's "Consent given" and "Enrolled on" read
the real day while its forms read the box's day, as H-20 F-10) no longer happens since D-1224 (one day for the box) is
on master: the sheet reads the box's day throughout. The term finding that followed it is MON-04 now.

Clicks are counted from the previous step's page; signing in and choosing the language count on a role's first step,
and the sign-ins of a step's refusals (each refused role signs in first) are counted in that step too. Page, clicks
and median seconds are from three runs of `make walk-modules` in a row on fresh boxes (2026-11-17, a 4-core
container, master `7da6edd3` merged; 21 m 46 s, 21 m 30 s, 20 m 54 s), the page and the clicks in en.
Severity is the walk's: blocks the step, slows the tester, cosmetic. The register's scale is in the JSON file
(blocks and slows map to Medium, cosmetic to Low).

<!-- module-walks: findings, written by tests/e2e/module_walk_common.py; do not edit by hand -->

### Feasibility alone (a box without a GPU, D-1066)

Roles: coordinator, investigator, viewer, cro, steward. Study: the seeded study AD-MAB. Sources: D-104 §2, D-280, D-1066.

#### Feasibility: the walk by step

| Step | Role | Matrix row | What the step does | Page reached (en) | Clicks | The clicks (en) | Median s | Refused (403) | Guesses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | coordinator | `–` | Sign in and choose the page language. | `/home` · My work | 3 | Sign in → Change → Change | 3.5 | – | – |
| 2 | coordinator | `command.FEAS` | Open New request (More) and count eligible patients for the approved study. | `/pilot/jobs/{job}` · FEAS AD-MAB v1.0.0 done | 9 | More → New request → Count eligible patients → Sign in → Change → Sign in → Change → Sign in → Change | 6.2 | steward: `POST /pilot/request`; viewer: `POST /pilot/request`; cro: `POST /pilot/request` | – |
| 3 | coordinator | `phi.view` | Open Reports and the study's feasibility report. | `/studies/AD-MAB/feasibility` · AD-MAB · Feasibility report | 2 | Reports → Open report | 0.5 | – | – |
| 4 | investigator | `task.screen` | As the investigator (the study's PI): open Reports and the study's feasibility report. | `/studies/AD-MAB/feasibility` · AD-MAB · Feasibility report | 5 | Sign in → Change → Change → Reports → Open report | 3.4 | – | – |
| 5 | viewer | `report.office` | As the viewer: open Reports and the study's report. | `/studies/AD-MAB/feasibility` · AD-MAB · Feasibility report | 3 | Change → Reports → Open report | 0.6 | viewer: `GET /studies/{rs}/candidates` | – |
| 6 | cro | `report.sponsor_form` | As the CRO account: open Reports and the sponsor copy of its study's report. | `/studies/GZQO/feasibility` · GZQO · Feasibility report | 3 | Change → Reports → Open report | 0.9 | cro: `GET /studies/GZQO/candidates` | – |
| 7 | coordinator | `command.FEAS` | On New request: read what this box does not do without a GPU (note criteria, screening). | `/pilot/request` · New request (stops: FEA-01) | 2 | More → New request | 0.2 | – | – |

#### Feasibility: the findings by step

| Id | Step | Role | Page | Clicks | What a tester would have had to guess | Expected (from) | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FEA-01 | 7 | coordinator | `/pilot/request` | 2 | New request offers "Find candidates for the next visits" (SCREEN) and the plain-words field "goes to the conversation engine"; nothing on the box's pages says that note criteria, screening and the engine need a GPU (RUNBOOK §1 says it, D-998; the pages are unchanged). The steps-mode box runs the stub model, so SCREEN runs here | on a box without a GPU, the pages say what waits for a GPU (note criteria, SCREEN, the engine) and do not offer it as if it ran (D-1066 ruling 1; `deploy/install.sh` --mode stub ("note criteria wait for a GPU"); D-998 (RUNBOOK §1: what a box without a GPU does and does not do)) | blocks the step | D |

#### Feasibility: cannot complete on a steps-mode box

| Step | What | What the product needs that the box does not have |
| --- | --- | --- |
| 7 | what a box without a GPU says it cannot do (D-1066) | a PRODUCTION box installed with `--mode stub` (D-998: the embedder pinned on the CPU from the bundle, no model for the notes). The steps-mode box runs the stub model, so note criteria and SCREEN run on it |

### Safety: a serious adverse event from the report to the notice

Roles: coordinator, investigator, steward, operator. Study: a new study per language (SAFEWALK, SAFEWALKZH, SAFEWALKJA), from H-20's steps 1 to 15. Sources: D-191, D-277, D-415, D-764, FIT-025, UX-028.

#### Safety: the walk by step

| Step | Role | Matrix row | What the step does | Page reached (en) | Clicks | The clicks (en) | Median s | Refused (403) | Guesses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1–15 | (H-10, H-20) | – | H-10's new study and H-20's steps 12 to 15, unchanged: protocol in, PI named, approval, FEAS, SCREEN, candidates; weekly page, Approach, contact outcome, consent and enrolment | – | – | – | – | as H-10 and H-20 | – |
| 16 | coordinator | `task.enter_data` | On the participant's page: Add an adverse event. | `/studies/{rs}/entry` · {rs} · Data entry (stops: SAF-01) | 1 | Add an adverse event | 0.2 | – | – |
| 17 | coordinator | `task.enter_data` | Add the built-in forms on the study's Forms page; back on the participant's page, Add an adverse event, fill the AE form for a serious event (hospital stay) and save. | `/studies/{rs}/subjects/{rs}-0001` · Participant {rs}-0001 | 15 | Forms → Add the built-in forms → My studies → Participants → {rs}-0001 → Add an adverse event → Serious: Yes → Why serious: Hospital stay or a longer stay → Severity: Moderate → Outcome: Recovering → Related to the study treatment or procedure: Unknown → Related in the sponsor's assessment: Not yet assessed → Expected per the reference safety information: Not yet assessed → Treatment unblinded for this event: Open-label study → Save | 4.3 | steward: `POST /studies/{rs}/entry`; operator: `POST /studies/{rs}/entry` | SAF-03 |
| 18 | coordinator | `sae.record` | Open the SAE register (More), then the case of the new SAE. | `/studies/{rs}/sae/{rs}-0001/ae1` · Serious adverse event {rs}-0001 · ae1 (stops: SAF-02) | 3 | More → SAE register → Open | 0.9 | steward: `GET /sae`; operator: `GET /sae` | – |
| 19 | coordinator | `study.state` | Open the study's state: open since the imported steps, which chose its type for SAE reporting before it opened (D-1153). | `/studies/{rs}/state` · {rs} · Study state and identifiers | 5 | More → {rs} · Study set-up → Study state and identifiers → Change state → Change state | 1.1 | steward: `POST /studies/{rs}/state` | – |
| 20 | coordinator | `study.setup` | On the study's set-up: read the SAE rule set chosen when the study opened (Taiwan, trial). | `/studies/{rs}/state` · {rs} · Study state and identifiers | 5 | More → {rs} · Study set-up → Save and confirm → Study state and identifiers → Change state | 1.3 | investigator: `POST /studies/{rs}/setup/sae` | – |
| 21 | investigator | `sae.ack` | As the investigator: open the SAE register, the case, and acknowledge it. | `/studies/{rs}/sae/{rs}-0001/ae1` · Serious adverse event {rs}-0001 · ae1 | 4 | More → SAE register → Open → Acknowledge | 1.3 | coordinator: `POST /studies/{rs}/sae/{record}/ae1/ack` | – |
| 22 | coordinator | `sae.record` | Open the case again and record the first report as sent today. | `/studies/{rs}/sae/{rs}-0001/ae1` · Serious adverse event {rs}-0001 · ae1 | 4 | More → SAE register → Open → Record the report sent | 1.3 | investigator: `POST /studies/{rs}/sae/{record}/ae1/sent` | – |
| 23 | steward | `audit.browse` | As the data steward: open the audit trail and filter on the event "SAE record changed". | `/audit` · Audit trail | 2 | Audit trail → Show | 0.3 | coordinator: `GET /audit` | – |
| 24 | investigator | `–` | As the investigator: open Notices received and find the notice of the new SAE. | `/notices/received` · Notices received (stops: SAF-07) | 2 | More → Notices received | 0.1 | – | – |

#### Safety: the findings by step

| Id | Step | Role | Page | Clicks | What a tester would have had to guess | Expected (from) | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SAF-01 | 16 | coordinator | `/studies/{rs}/entry` | 1 | the participant's page offers "Add an adverse event" in a new study that has no forms; the link opens the data-entry page, which says "This study has no forms yet. Add the built-in forms or import a REDCap data dictionary on the page: Forms" | the AE form opens from the participant's page, or the page says the study's forms are to be added first (D-129 (the built-in forms), D-134; `life.ae.add`) | blocks the step | C2 |
| SAF-03 | 17 | coordinator | `/studies/{rs}/forms` | 15 | after adding the forms, no link leads back to the participant; the walk goes to My studies and the study card's "Participants" (as H-20 F-07) | a way back to the page the coordinator came from (the participant) (D-133 (three ways on), D-134) | slows the tester | C2 |
| SAF-09 | 17 | coordinator | `/studies/{rs}/subjects/{record}` | 15 | the AE line's reporting clock names the regulator "Regulator (PMDA / TFDA)" in en and "規制当局（PMDA）" in ja for a study whose SAE rule set is Taiwan's (TFDA); the case page (step 18) says "Regulator (TFDA)", and zh-TW says TFDA on both | the clock names the regulator of the study's rule set, as the case page does (`life.clock.party.regulator`; D-277) | slows the tester | C2 |
| SAF-08 | 18 | coordinator | `/sae` | 3 | the steps-mode box has no trial office mailbox: the register says "This box has no trial office mailbox (TB_SAE_OFFICE_MAILBOX): a new serious adverse event is mailed to the study's PI only" | the steps-mode box set up as a site is (a test mailbox for the trial office), so the office's copy can be walked (FIT-025, D-764; `tools/demo.py`) | cosmetic | integrator |
| SAF-06 | 23 | steward | `/audit` | 2 | the notice the box recorded reads "page=office_copy to=<the PI's mailbox> event=ae1": the action is labelled "page" and given as a code, in every language | the audit row says in words that the new SAE was notified, and to whom (D-764, FIT-025; `console.sae`) | cosmetic | C2 |
| SAF-07 | 24 | investigator | `/notices/received` | 2 | Notices received lists the morning lists only: the SAE notice the box recorded as mailed to the PI (audit `office_copy`, step 23) is not there | "The notices TrialBox mailed you, newest first": the SAE notice among them (`received.help`, D-764) | blocks the step | C2 |

#### Safety: no longer seen

| Id | Step | What an earlier run saw | What the walk sees now | Changed by |
| --- | --- | --- | --- | --- |
| SAF-02 | 18 | the new SAE had no report and no deadline ("TrialBox tracks no report for this kind of SAE", "The study has not chosen its SAE rule set"): the new study counted as open, so its SAE type was never asked | the case lists its three first reports with their due days (sponsor, IRB, regulator) | D-1153 (WALK-1): a new study starts in start-up and opens only through D-415's SAE-type check |
| SAF-04 | 17 | the AE line said "Reporting clock: no due date yet: enter the onset or the day the site learned of it" though both days were entered (no SAE rule set) | the AE line gives each party's due day | D-1153 (WALK-1): the rule set is chosen before the study opens |
| SAF-05 | 19 | D-415's type check was reached only by pausing the study and opening it again: a study with no state recorded offered no "Open" | the study opens from start-up and the type is asked then (the imported steps); the state page reads open | D-1153 (WALK-1) |

#### Safety: cannot complete on a steps-mode box

| Step | What | What the product needs that the box does not have |
| --- | --- | --- |
| 23 | the notice leaving the box: the mail itself (D-764) | outside mail: the box's mail gateway is in process with no outside mail, so the walk reads the notice the product records (the audit trail), not a mail received |

### Monitoring: the monitor's role

Roles: cro, operator, steward, coordinator, investigator. Study: the seeded study GZQO. Sources: D-380, D-436, D-772, FIT-002.

#### Monitoring: the walk by step

| Step | Role | Matrix row | What the step does | Page reached (en) | Clicks | The clicks (en) | Median s | Refused (403) | Guesses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cro | `monitor.read` | As the CRO account: open the monitoring page of a study it is named for, before any grant. | `/studies/GOUT-COH/monitor` · This page needs another role (stops: MON-01) | 4 | Sign in → Change → Change → (typed) /studies/GOUT-COH/monitor | 1.3 | – | – |
| 2 | operator | `account.create.aggregate` | As the administrator: open Users and find the CRO account and its studies. | `/ops/users` · Users | 6 | Sign in → Change → Change → Users → Sign in → Change | 1.5 | steward: `POST /ops/users` | – |
| 3 | steward | `monitor.grant` | As the data steward: on the study's delegation log, add the CRO account as monitor for one visit (its id, its last day). | `/studies/GZQO/team` · GZQO · Delegation log | 5 | Change → (typed) /studies/GZQO/team → Add and sign → Sign in → Change | 7.6 | coordinator: `POST /studies/{rs}/team`; cro: `POST /studies/{rs}/team`; operator: `POST /studies/{rs}/team` | MON-02 |
| 4 | cro | `monitor.read` | As the CRO account: open Reports (its monitoring line is there now), then Monitoring from the menu. | `/studies/GZQO/monitor` · GZQO · Monitoring | 2 | Reports → Monitoring · GZQO | 1.1 | cro: `GET /studies/{rs}/week`; cro: `GET /studies/{rs}/candidates`; cro: `GET /studies/{rs}/subjects/GZQO-0001`; cro: `GET /studies/{rs}/monitor/GZQO-0002`; cro: `GET /sae` | – |
| 5 | cro | `monitor.read` | Open the enrolled subject's source-reference sheet. | `/studies/GZQO/monitor/GZQO-0001` · GZQO · Source references · GZQO-0001 | 1 | GZQO-0001 | 0.3 | – | – |
| 6 | cro | `monitor.visit` | Record the monitoring visit: its day, the subject verified, the findings. | `/studies/GZQO/monitor` · GZQO · Monitoring | 3 | Monitoring · GZQO → GZQO-0001 → Save the visit record | 0.8 | coordinator: `POST /studies/{rs}/monitor/visits` | – |
| 7 | investigator | `monitor.grant` | As the investigator (the study's PI): read the monitoring visits. | `/studies/GZQO/monitor` · GZQO · Monitoring | 4 | Sign in → Change → Change → (typed) /studies/GZQO/monitor | 2.3 | – | MON-03 |

#### Monitoring: the findings by step

| Id | Step | Role | Page | Clicks | What a tester would have had to guess | Expected (from) | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MON-01 | 1 | cro | `/studies/GOUT-COH/monitor` | 4 | the refusal says "If you need it, ask the TrialBox administrator to change your role"; the monitor grant is given by the PI the log names or the data steward, and the administrator is refused it (step 3) | the refusal of a monitor's page says who grants: the study's PI or the data steward (`monitor.grant`, D-380, FIT-002; `problem.why.forbidden`) | blocks the step | C2 |
| MON-02 | 3 | steward | `/studies/GZQO/team` | 5 | the steward's menu and home page have no link to a study's delegation log once its PI is named; the walk types /studies/GZQO/team | a way from the steward's pages to each study's delegation log, where the steward grants (D-380, FIT-002) | slows the tester | C2 |
| MON-04 | 5 | cro | `/studies/GZQO/monitor/GZQO-0001` | 1 | the state reads "On study (on_study, 2026-11-02)": the code on_study is shown in every page language | the state in words with its day (`life.state.on_study`) | cosmetic | C2 |
| MON-03 | 7 | investigator | `/studies/GZQO/monitor` | 4 | the PI reaches the monitoring visit records only by typing /studies/GZQO/monitor: no link on the study's pages, the weekly page or the delegation log | a link to the monitoring visits from the study's pages for the PI who grants them (D-436) | slows the tester | C2 |

#### Monitoring: cannot complete on a steps-mode box

Nothing: every step of this walk completes on a steps-mode box.

### Amendment: a protocol change after approval

Roles: coordinator, investigator, steward. Study: a new study per language (AMENDWALK, AMENDWALKZH, AMENDWALKJA), from H-20's steps 1 to 15. Sources: D-108, D-364.

#### Amendment: the walk by step

| Step | Role | Matrix row | What the step does | Page reached (en) | Clicks | The clicks (en) | Median s | Refused (403) | Guesses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1–15 | (H-10, H-20) | – | H-10's new study and H-20's steps 12 to 15, unchanged: protocol in, PI named, approval, FEAS, SCREEN, candidates; weekly page, Approach, contact outcome, consent and enrolment | – | – | – | – | as H-10 and H-20 | – |
| 16 | investigator | `task.approach` | As the investigator: open the first patient of the weekly page and mark Approach. | `/studies/{rs}/week` · This week's patients · {rs} | 4 | This week's patients → {rs} → patient {short} → Approach | 6.5 | coordinator: `POST /studies/{rs}/patients/{pid}/mark` | AMD-01 |
| 17 | coordinator | `request.prepare` | Read the candidates; then on the protocol page type the study's own id, paste the amended criteria (age 20 or older) and send them. | `/pilot/jobs/{job}` · FEAS {rs} v1.1.0 waiting for approval | 6 | This week's patients → {rs} → Candidates → More → Protocol → Compile | 3.7 | coordinator: `POST /pilot/jobs/{job}/approve`; steward: `POST /pilot/protocol` | – |
| 18 | investigator | `criteria.approve` | As the investigator: open the criteria waiting for approval (v1.1.0), check each row, give the amendment record (IRB approval number and day) and approve all. | `/pilot/jobs/{job}` · APPROVE {rs} v1.1.0 done | 8 | This week's patients → Criteria waiting for your approval: {rs} v1.1.0 → Open → Open → Open → Open → Approve all → Yes, do it | 7.1 | – | – |
| 19 | coordinator | `command.SCREEN` | Read the weekly page (the list of 1.0.0), then run SCREEN on the study: it runs on version 1.1.0. | `/pilot/jobs/{job}` · SCREEN {rs} v1.1.0 done | 5 | This week's patients → {rs} → More → New request → Find candidates for the next visits | 41.5 | – | – |
| 20 | coordinator | `task.screen` | From the weekly page, open Re-screen after amendment. | `/studies/{rs}/rescreen` · {rs} · Re-screen after amendment | 6 | This week's patients → {rs} → Candidates → This week's patients → {rs} → Re-screen after amendment | 7.2 | steward: `GET /studies/{rs}/rescreen` | – |
| 21 | investigator | `task.screen` | As the investigator: open the weekly page's list of approached patients after the amendment. | `/studies/{rs}/week` · This week's patients · {rs} | 3 | This week's patients → {rs} → Approved and contacted | 3.8 | – | AMD-05 |

#### Amendment: the findings by step

| Id | Step | Role | Page | Clicks | What a tester would have had to guess | Expected (from) | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AMD-01 | 16 | investigator | `/studies/{rs}/week` | 4 | patients are named by an 8-character pseudonym only; the walk takes the worklist's first row (as H-20 F-03) | a patient the tester can be told to take (D-133) | cosmetic | C2 |
| AMD-02 | 17 | coordinator | `/pilot/protocol` | 6 | the field reads "New ruleset id (e.g. GZQO-DEMO)"; an amendment is sent under the study's own id, and nothing on the page says that the same id makes the next version | the protocol page says how an amendment is sent (the study's id, the next version) (D-364; `protocol.ruleset`) | slows the tester | C2 |
| AMD-03 | 18 | investigator | `/pilot/jobs/{job}/approval` | 8 | "Changes since 1.0.0" names one criterion (INC-01, new wording), but approving 1.1.0 asks the PI to open all four amber rows again (1.0.0 asked three) | the changed criteria are the ones to look at again, or the page says why every row is (D-364 rule 1, `s20.changes`) | slows the tester | C2 |
| AMD-04 | 18 | investigator | `/pilot/jobs/{job}/approval` | 8 | the change reads "INC-01 · new wording" with the earlier wording struck through; the new wording is only in the table below | the change shows the old and the new wording side by side (`s20.chg.text`) | cosmetic | C2 |
| AMD-05 | 21 | investigator | `/studies/{rs}/week` | 3 | the list links' names end with their count ("Approved and contacted (n)"); the walk finds the link by the start of its name (as H-20 F-05) | a link named by its list (D-133) | cosmetic | C2 |
| AMD-06 | 21 | investigator | `/studies/{rs}/week` | 3 | the patient approached under 1.0.0 is listed with the mark, but no page says which criteria version the mark was made on | the mark shows its version where the version decides the re-screen list (D-364 rule 4) | cosmetic | C2 |

#### Amendment: cannot complete on a steps-mode box

| Step | What | What the product needs that the box does not have |
| --- | --- | --- |
| 18 | an amendment that takes effect on a later day (D-364 rule 3: the version before screens until then) | a box whose day moves: the walk's box runs on `--day data`, a frozen clock, so the effective date is left empty (in force from the approval) |
| 20 | the re-screen list with patients in it (D-364 rule 5) | a patient set aside, approached or in screening whom the amendment changes: the walk's amendment (age 18 to 20) took 43 unmarked candidates off the list and left the walk's marked patients eligible, so all three groups are empty |

### Counts

| Module | Steps | Refusals | blocks the step | slows the tester | cosmetic | Lanes |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility | 7 | 5 | 1 | 0 | 0 | D 1 |
| safety | 9 | 9 | 2 | 2 | 2 | C2 5, integrator 1 |
| monitoring | 7 | 10 | 1 | 2 | 1 | C2 4 |
| amendment | 6 | 4 | 0 | 2 | 4 | C2 6 |

<!-- module-walks: end of findings -->

## After lane C2's WALK-1 (D-1153)

WALK-1 is on master since train 83 (`a4aa0be1`): a study the box does not know starts in start-up and opens only
through "Study state and identifiers" → Open after its type for SAE reporting is chosen; SCREEN is refused until it
is open; Withdraw, Screen fail and Close ask for confirmation. The first runs of these walks (master `7da6edd3`) were
before it. What changed (card H-29b):

- **Safety and amendment, steps 1 to 15** are H-20's as H-30 made them, imported: the study is opened through the SAE
  type before H-10's SCREEN.
- **Safety, steps 19 and 20** no longer pause the study and open it again to reach D-415's check: step 19 reads the
  open state, step 20 the SAE rule set chosen at opening; step 18 expects the case's reports.
- **SAF-02, SAF-04 and SAF-05 are no longer seen** (the safety walk's "no longer seen" table): the case has its
  reports and due days, the AE line its due days, and the type is asked when the study opens. Their ids are not
  given again. With the clock running, the walk sees a new one, SAF-09 (the regulator the clock names).
- **Feasibility, monitoring and the amendment's own steps** are unchanged.

## The findings register

The rows are in `module-walks-findings-2026-11-17.json` (card `H29`), not in `docs/handover/findings-register.md`:
the register is pinned to its seed rows by `tests/unit/test_findings_register.py` until lane V takes new cards'
rows. `python -m tools.findings_register --add-from docs/handover/module-walks-findings-2026-11-17.json` adds them.
