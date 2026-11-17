# The whole life of a study, walked: findings by step (2026-11-17)

**Reader:** the people who build TrialBox: the lanes that own the console (C2), erasure (B2) and the box (D), and the
integrator. Findings for builders, so in one language.

Card H-20, decision D-1135. It extends H-10's walk (D-1121) from the new study to the end of a study. The box is a
local steps-mode box (D-1062): `tools/demo.py` with demo mode off, the stub model, the synthetic hospital and
`--day data`. Each step is done by the role that owns it in the permission matrix
(`libs/tb_common/authz_matrix.yaml`), in en, zh-TW and ja, each language under its own new study id. The steps:

1. Steps 1 to 11 are H-10's, unchanged: protocol in, the PI named, approval, FEAS, who to screen, SCREEN and the
   candidates.
2. Step 12: the coordinator opens the weekly page.
3. Step 13: the PI marks Approach on the first patient.
4. Step 14: the coordinator records "reached, visit booked", and the patient gets a screening number.
5. Step 15: the coordinator records consent and enrolment.
6. Step 16: the coordinator records the withdrawal.
7. Step 17: the coordinator closes the study.
8. Step 18: the coordinator shows the chart number for the opt-out.
9. Step 19: the steward records the opt-out.
10. Step 20: the coordinator looks for the patient on the lists.
11. Step 21: the steward reads, in the audit trail, the opt-out worker's run after the opt-out (H-25, D-1124).
12. Step 22: the administrator reads the worker's health check.

Every new role boundary is checked by a refusal: a real request carrying the page's own form token, answered 403.

This page reports and does not fix: no product file was changed. Where the product does not do what its documents
say, the walk stops that branch with the product's own words. It never asserts the fault as correct.

Run time, H-20: three runs in a row on a 4-core container (2026-11-17), each a fresh box: 842, 808 and 795 seconds
(the seed about 7 minutes, then about 2 minutes per language); all three passed in three languages, each with step
21 stopped as F-20. H-10's `make walk-new-study` passed after them (698 seconds).

H-25 (D-1124) settled F-20. A steps-mode box now starts the orchestrator's opt-out worker after its seed, and nothing
else of the start-up (`tools/demo.py`, `START_UP`). Step 21 now asserts that the worker's run after the opt-out names
every clear of the erasure registry's §1, with none failed and nothing left, and step 22 that the health check is
green. The run times of H-25's three runs are in its pull request.

How it is run: `make walk-life-cycle` (or `tests/e2e/test_life_cycle_walk.py -m e2e`). Each run writes a JSON log per
language outside the repository: per step the page and heading reached, the clicks and their texts, the time, the
guesses, the refusals and any stop. The tables below are written from `tests/e2e/life_cycle_walk_plan.py` (its
findings and the summed-up logs of the three runs of 2026-11-17), and a fast test keeps them equal.

## Findings

Clicks are counted from the previous step's page; signing in and choosing the language count on a role's first step
only. "Guess" is anything the walk could not find by a documented label and had to find another way.

<!-- life-cycle-walk: findings, written by tests/e2e/life_cycle_walk_plan.py; do not edit by hand -->

### The walk by step

| Step | Role | Page reached (en) | Clicks | The clicks (en) | Median s | Refused (403) | Guesses |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 12 | coordinator | `/studies/{rs}/week` · This week's patients · {rs} | 2 | This week's patients → {rs} | 2.5 | steward: `GET /studies/{rs}/week` | – |
| 13 | investigator | `/studies/{rs}/week` · This week's patients · {rs} | 4 | This week's patients → {rs} → patient {short} → Approach | 6.4 | coordinator: `POST /studies/{rs}/patients/{pid}/mark` | F-03 |
| 14 | coordinator | `/studies/{rs}/week` · This week's patients · {rs} | 5 | This week's patients → {rs} → Approved and contacted → patient {short} → Reached, visit booked | 8.3 | investigator: `POST /studies/{rs}/patients/{pid}/outcome` | F-05 |
| 15 | coordinator | `/studies/{rs}/subjects/{rs}-0001` · {rs}-0001 · Participants | 5 | My studies → Participants → {rs}-0001 → Consent given → Enrolled | 4.6 | investigator: `POST /studies/{rs}/subjects/{record}/step` | F-07 |
| 16 | coordinator | `/studies/{rs}/subjects/{rs}-0001` · {rs}-0001 · Participants | 2 | Withdraw → Withdraw | 1.1 | investigator: `POST /studies/{rs}/subjects/{record}/undo` | – |
| 17 | coordinator | `/studies/{rs}/state` · {rs} · Study state and identifiers | 4 | More → {rs} · Study set-up → Study state and identifiers → Change state | 1.2 | steward: `POST /studies/{rs}/state`; operator: `POST /studies/{rs}/state` | – |
| 18 | coordinator | `/studies/{rs}/patients/{pid}/reveal` · {rs} · patient {short} | 5 | This week's patients → {rs} → (typed) /studies/{rs}/week?list=all&pid={pid} → Open full chart view → Show chart number (recorded with your name) | 6.0 | – | F-17, F-18 |
| 19 | steward | `/site/opt-outs` · Opt-out register | 2 | Opt-out register → Record the opt-out | 0.3 | coordinator: `POST /site/opt-outs`; operator: `GET /site/opt-outs` | – |
| 20 | coordinator | `/studies/{rs}/candidates` · {rs} · Candidates | 4 | This week's patients → {rs} → (typed) /studies/{rs}/week?list=all&pid={pid} → Candidates | 5.5 | – | F-18 |
| 21 | steward | `/metrics` ·  | 1 | (typed) /metrics | 0.1 | coordinator: `GET /audit` | F-21 |
| 22 | operator | `` ·  |  |  |  | coordinator: `GET /metrics` | – |

### The findings by step

| Id | Step | Role | Page | Clicks | What a tester would have had to guess | Expected (from) | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-01 | 12 | coordinator | `/studies/{rs}/week` | 2 | Help on the weekly page tells the coordinator to "mark Approach, Need info or Not suitable now"; the page gives the coordinator no mark (it says the investigator decides there) | help that matches the role reading it (`help.page.week`, `docs/guides/coordinator.en.md` (This week's patients); the matrix row `task.approach`) | slows the tester | C2 |
| F-02 | 13 | investigator | `/studies/{rs}/week` | 4 | the button reads "Approach" (邀請, 声をかける); after it the page says "Approved. The coordinator has a task…" (已核准, 承認しました) | one word for the mark (`mark.approach`, `wb.done.approach`, `help.page.week`) | cosmetic | C2 |
| F-03 | 13 | investigator | `/studies/{rs}/week` | 4 | patients are named by an 8-character pseudonym only ("patient 1a2b3c4d"); a tester told to take "a patient" must pick one; the walk takes the first row of the list the page opens on | a testers' page that names which patient to take (D-1062 (the testers walk from the first step)) | cosmetic | C2 |
| F-04 | 13 | investigator | `/studies/{rs}/week` | 4 | a warning on a new study: "Check before approaching: marking Approach now is recorded as an override" (no IRB approval date, no consent-form version); no step of the new-study walk asks for the IRB record | the new study's steps lead to the IRB record before the first Approach, or the warning says where (D-147, D-399; `docs/handover/new-study-walk.en.md`) | slows the tester | C2 |
| F-05 | 14 | coordinator | `/studies/{rs}/week` | 5 | the approved patient is on the list "Approved and contacted" before anyone contacted them; the page opens on another list, and the list link's name ends with its count ("Approved and contacted1"), so it is found by the start of its name | a list named for what it holds (`wb.list.approached`; `help.role.coordinator` (record contact outcomes)) | slows the tester | C2 |
| F-06 | 14 | coordinator | `/studies/{rs}/week` | 5 | the five contact outcome buttons are on the page twice for the approved patient (a folded quick form in the row, and the panel) | one form per action on a page (D-178 (two taps, one place)) | cosmetic | C2 |
| F-07 | 15 | coordinator | `/studies/{rs}/week` | 5 | after the outcome the screening number shows on the patient panel, but no link there leads to the participant; the walk goes back to My studies and the study card's "Participants" | a link from the screening number to the participant's page (D-134 (the participant from candidate to the end)) | slows the tester | C2 |
| F-08 | 15 | coordinator | `/studies/{rs}/subjects` | 5 | "Participants" and "Study state and identifiers" are not in the More menu, and Help on both pages says only "Use the command field above, or More, to find any page"; the coordinator's guide lists neither page | each page in the role's guide and Help with its own text (`docs/guides/coordinator.en.md` (Your pages), `help.page.other`, D-104) | slows the tester | C2 |
| F-09 | 15 | coordinator | `/studies/{rs}/subjects/{record}` | 5 | one participant's page is headed "<number> · Participants" (the list's title); "Participant {r}" is only in the browser tab | the heading names one participant (`life.subject.title`) | cosmetic | C2 |
| F-10 | 15 | coordinator | `/studies/{rs}/subjects/{record}` | 5 | on a box started with `--day data` the steps TrialBox makes itself (candidate, approached) are dated the real day (2026-11-17) and the steps a person records are dated the box's day (2026-11-02): the trail shows consent before approach | one day for the box (D-399 (date order), `tools/demo.py` (`--day data` keeps a frozen clock)) | cosmetic | C2 |
| F-11 | 16 | coordinator | `/studies/{rs}/subjects/{record}` | 2 | "Withdraw" with no reason is refused only after the click (the Reason select is not marked required); with a reason one click makes the participant final ("No further step can be recorded") with no confirmation page | a final step named before it is done, and a required field marked (D-178 (an outcome that ends the contact names its consequence first); `life.subject.final`) | slows the tester | C2 |
| F-12 | 16 | coordinator | `/studies/{rs}/subjects/{record}` | 2 | in English "Withdraw" is the participant's withdrawal here and "Withdraw my mark" (taking back a mark) on the patient sheet; zh-TW and ja use two words | two words for two actions (`life.go.withdrawn`, `mark.withdraw`) | cosmetic | C2 |
| F-14 | 17 | coordinator | `/studies/{rs}/state` | 4 | the new study was never opened: "No state has been recorded: the study counts as open"; so its type for SAE reporting was never asked, though a trial "opens only with its type" | a new study starts in start-up and opens through the SAE check (D-386 (start-up, open, paused, closed), D-415) | slows the tester | C2 |
| F-15 | 17 | coordinator | `/studies/{rs}/state` | 4 | "Change state" to Closed is done in one click with no confirmation page; the page says "Closed is final" (only the PI may take it back the same day) | a final step named before it is done (D-763; D-178) | slows the tester | C2 |
| F-16 | 17 | coordinator | `/studies/{rs}/state` | 4 | closed "2026-11-02 07:00" (site time) with 5 years; "kept until 2031-11-01": the period is counted from the close's UTC day, a day before the site's | the close's own day plus the period: 2031-11-02 (D-779; `libs/tb_common/retention.py` (`kept_until`)) | cosmetic | C2 |
| F-13 | 18 | coordinator | `/studies/{rs}/patients/{pid}` | 5 | after the withdrawal and the close the patient sheet still offers the contact outcomes "Not approached (physician)" and "Lost contact" (registry: withdrawn) | no contact step for a finished participant of a closed study (D-763 (nobody goes back on study)) | cosmetic | C2 |
| F-17 | 18 | steward | `/site/opt-outs` | 5 | the opt-out form asks for the chart number ("Type the chart number"); no page of the steward shows one, so on a box the tester must get it elsewhere; the walk has the coordinator show it on the patient sheet (recorded) and carries it over | the testers' page says where the chart number comes from on a box (`team.optout.help`, `help.page.optouts`; D-1062) | slows the tester | C2 |
| F-18 | 18 | coordinator | `/studies/{rs}/week` | 5 | after the withdrawal the patient is on none of the weekly page's lists but "All on the list" (4,000 rows, paged), and the participant's page has no link to the patient sheet; the walk types `?list=all&pid=...` here and in step 20 | a search by pseudonym or screening number, or a link from the participant to the patient sheet (D-133 (the weekly page)) | cosmetic | C2 |
| F-19 | 19 | steward | `/site/opt-outs` | 2 | the opt-out form's note is labelled "Note for the coordinator" (the PI's mark note) on the steward's register | a label of the register's own (`mark.note`, `team.optout.help`) | cosmetic | C2 |
| F-21 | 22 | operator | `/admin?tab=health` |  | the red opt-out worker check is on `/metrics` only (typed in); the administrator's Health tab shows no line for it | the health line turns red on a stale or failed tick, where a person reads it (D-441, T-209a) | slows the tester | C2 |

<!-- life-cycle-walk: end of findings -->

## Steps a steps-mode box cannot complete

| Step | What | What the product needs that the box does not have |
| --- | --- | --- |
| 15 | consent recorded on TrialBox's consent form (D-399) | a study set up to record consent in TrialBox (set-up, Consent); the walk's new study keeps the default, "Not recorded", so "Consent given" is one button and the consent form, its version check and the re-consent list are not walked |
| 15 | on study, visits, completion (D-134) | a visit schedule ("This study has no visit schedule yet"): the walk goes from enrolled to withdrawn |
| 17 | the morning mails of a closed study (D-763) | outside mail: the box's mail gateway is in process with no outside mail |

The opt-out works on the box from end to end:

- step 19: the register takes the chart number;
- step 20: the patient leaves the weekly list and the candidate list at once;
- step 21: within a minute the worker runs every clear of `docs/validation/erasure-registry.md` §1.

`omop` and `vec` report "skipped": this box has no OMOP store and no vector store.

## Counts

| Severity | Findings |
| --- | --- |
| blocks the step | 0 |
| slows the tester | 10 |
| cosmetic | 10 |

## The testers' pages

The testers' pages `docs/handover/new-study-walk.{en,zh-TW,ja}.md` are left as they are. They are H-10's walk of a
new study, written from H-10's plan, and the house's three-language rule binds a testers' page to its two siblings.
It does not bind a findings page for the builders. The life-cycle steps would go onto the testers' pages only once
the findings that slow a tester (F-04, F-05, F-07, F-08, F-17, F-18) are settled. Until then such a page would tell a
tester to type addresses.
