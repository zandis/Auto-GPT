# The whole life of a study on a phone, 390 px wide: findings by step (2026-11-17)

**Reader:** the people who build TrialBox: the lane that owns the console (C2) and the integrator. Findings for
builders, so in one language.

This is card H-21, decision D-1138. It runs H-20's walk (D-1135) again on a phone: the same 22 steps, roles, refusals
and languages (en, zh-TW, ja), each language under its own new study id. The browser window is 390 x 844 px, touch and
mobile. The box is the same local steps-mode box (D-1062).

On every page the walk reaches, and before every click, the driver measures six things:

- a page that scrolls sideways;
- a control off the screen, or covered where the finger would land;
- a tap target under 24 px, a mark button under 44 px, or any other control under 44 px;
- text cut;
- a table wider than the screen;
- what the desktop page shows and the phone's does not.

Each measure is logged with a screenshot, both outside the repository: no screenshot and no patient-like text is
committed.

The expectations come from the UI spec, `docs/plan/design/09-ui-ux-spec.md` (§10, the phone at 390 px, and its
accessibility table), and from FR-UI-09 in `docs/plan/design/01-SRS.md`:

- no horizontal page scroll at 390 px;
- targets of at least 24 x 24 px, and the PI's mark buttons at least 44 x 44 px;
- on a phone: the role's work list, the PI home, S20 approval, the report, and the PI's card list and marks;
- data entry and reveal are desktop only.

The walk reports and fixes nothing: no product file was changed. It fails when it measures something at a step that no
finding below names, so a new problem gets read and recorded. It does not fail when a problem is gone.

How it is run: `make walk-life-cycle-390` (or `tests/e2e/test_life_cycle_walk_390.py -m e2e`). The measures and
screenshots go to `TB_WALK_LOG_DIR`, in its `phone` folder.

## What fits

No page of the walk scrolls sideways at 390 px, in any of the three languages. No control was off the screen, no text
was cut, and every PI mark button was at least 44 x 44 px. Every step could be done on the phone, including the two the
spec calls desktop only: the participant's steps (data entry, steps 15 and 16) and the chart number (reveal, step 18).
Every refusal was answered 403.

## Findings

A finding names the steps where its measure was seen. The phone adds clicks to each step's path: "☰ Menu" before
the top bar, the language or More, and "← Back to the list" where the patient sheet covers the menu.

<!-- life-cycle-walk-390: findings, written by tests/e2e/life_cycle_walk_390_plan.py; do not edit by hand -->

| Id | Step | Role | Page | Measure | What the phone showed | Expected (from) | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P-01 | 1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21 | coordinator | `/home` | behind the menu | on a phone the top bar's links, the language box and Sign out are behind "☰ Menu"; that visible label is hidden from assistive technology (`aria-hidden`), the accessible control being a hidden check box named "Menu"; the walk finds the button by its data-testid, at every step that opens the top bar, the language or More | one Menu button that is the control a person sees and the one assistive technology names (D-133 ("one Menu button"); WCAG 4.1.2 in `docs/plan/design/09-ui-ux-spec.md` (accessibility table)) | cosmetic | C2 |
| P-02 | 3, 7, 8, 9, 10, 11, 13 | coordinator | `/pilot/jobs/{job}` | table wider than the screen | the job page's thread table is 720 to 915 px wide, the SCREEN job's rows 829 to 937 px and a FEAS job's funnel 417 px (en to ja; train 79 widened them by 30 to 60 px); the table scrolls sideways inside its own frame, the page does not | the job page in one column on a phone (not among the phone's pages) (`docs/plan/design/09-ui-ux-spec.md` §10 (phone's pages)) | cosmetic | C2 |
| P-03 | 4, 5, 7, 8 | coordinator | `/pilot/jobs/{job}/approval` | table wider than the screen | in ja only, the approval table (S20) is 463 to 485 px wide; the table scrolls sideways inside its own frame, the page does not | S20 approval readable on a phone ("allowed on a phone when no row is amber") (`docs/plan/design/09-ui-ux-spec.md` §10 (phone 390–767 px: S20 approval), S20) | cosmetic | C2 |
| P-04 | 6, 19 | steward | `/studies/{rs}/team` | table wider than the screen | the delegation log is 792 to 932 px wide; the table scrolls sideways inside its own frame, the page does not | not among the phone's pages: no expectation for a phone (`docs/plan/design/09-ui-ux-spec.md` §10 (phone's pages)) | cosmetic | C2 |
| P-05 | 9 | coordinator | `/studies/{rs}/feasibility` | table wider than the screen | the feasibility funnel is 488 to 506 px wide, the reports list 448 to 518 px and, in ja, the barriers table 400 px; the table scrolls sideways inside its own frame, the page does not | S3 report readable on a phone (`docs/plan/design/09-ui-ux-spec.md` §10 (phone 390–767 px: S3 report)) | cosmetic | C2 |
| P-06 | 9 | coordinator | `/studies/{rs}/feasibility` | target under 44 px | in zh-TW and ja the report's five step links ("狀態 1" … , "状況 1" …) are 40 and 31 px wide by 44 px; in en they are wider | 44 px controls on a phone (the card's size; the spec asks 24 px except for the PI's marks) (`docs/plan/design/09-ui-ux-spec.md` (2.5.8)) | cosmetic | C2 |
| P-07 | 11 | operator | `/home` | target under 24 px | the administrator's home: the tabs and links "Jobs", "Services and models", "Sources and licences", "Open", "Mail notices" (seven in all) are 20 px high | targets at least 24 x 24 px (`docs/plan/design/09-ui-ux-spec.md` (2.5.8 Target size (minimum))) | slows the tester | C2 |
| P-08 | 11, 12, 13, 14, 15, 18, 20 | coordinator | `/studies/{rs}/week` | table wider than the screen | the weekly page's worklist is a table 437 to 482 px wide; the table scrolls sideways inside its own frame, the page does not | on a phone a card list instead of a table: pseudonym, next visit, state counts, mark buttons (`docs/plan/design/09-ui-ux-spec.md` §10 ("Phone (390 px): card list instead of table"), S5 ("Table (phone: cards)"); FR-UI-09) | slows the tester | C2 |
| P-09 | 11, 12, 20 | coordinator | `/studies/{rs}/candidates` | table wider than the screen | the candidate list is 643 to 724 px wide; the table scrolls sideways inside its own frame, the page does not | not among the phone's pages: no expectation for a phone (`docs/plan/design/09-ui-ux-spec.md` §10 (phone's pages)) | cosmetic | C2 |
| P-10 | 12 | coordinator | `/studies/{rs}/week` | not shown on the phone | the coordinator's line "The investigator decides here; you get a task when they mark Approach…" (its words since train 79, J-4) is only in the patient sheet, which a phone shows after a row is tapped; the desktop shows it beside the list | the list first on a phone, the sheet after a tap (D-133 (the phone's sheet)) | cosmetic | C2 |
| P-11 | 15 | coordinator | `/studies/{rs}/week` | covered | with a patient's sheet open, the sheet's bar ("← Back to the list") covers "☰ Menu": the coordinator taps Back first to reach the menu and My studies | the menu reachable from every page (D-133 (Back, Next and the menu on the phone's sheet)) | slows the tester | C2 |
| P-16 | 15 | coordinator | `/studies/{rs}/subjects` | table wider than the screen | the Participants list is a table 413 to 423 px wide (en, ja), seen since train 79; the table scrolls sideways inside its own frame, the page does not | not among the phone's pages: no expectation for a phone (`docs/plan/design/09-ui-ux-spec.md` §10 (phone's pages)) | cosmetic | C2 |
| P-12 | 17, 18 | coordinator | `/studies/{rs}/state` | table wider than the screen | in en the study's state history is 413 px wide; the table scrolls sideways inside its own frame, the page does not | not among the phone's pages: no expectation for a phone (`docs/plan/design/09-ui-ux-spec.md` §10 (phone's pages)) | cosmetic | C2 |
| P-13 | 19, 21 | steward | `/site/opt-outs` | table wider than the screen | the opt-out register's list is 467 to 565 px wide; the table scrolls sideways inside its own frame, the page does not | not among the phone's pages: no expectation for a phone (`docs/plan/design/09-ui-ux-spec.md` §10 (phone's pages)) | cosmetic | C2 |
| P-14 | 21 | steward | `/audit` | table wider than the screen | the audit trail's table is 1,355 to 1,383 px wide; the worker's run sits in its first row, its time on the left and its detail on the right; the table scrolls sideways inside its own frame, the page does not | not among the phone's pages: no expectation for a phone (`docs/plan/design/09-ui-ux-spec.md` §10 (phone's pages)) | cosmetic | C2 |
| P-15 | 21 | steward | `/audit` | target under 44 px | the audit filter's "Clear" link ("清除", "クリア") is 32 to 40 by 24 px | 44 px controls on a phone (the card's size; the spec asks 24 px except for the PI's marks) (`docs/plan/design/09-ui-ux-spec.md` (2.5.8)) | cosmetic | C2 |

<!-- life-cycle-walk-390: end of findings -->

## Changed with train 79

Train 79 (master `8778394f`: lane J's J-4 #1033 and J-1 #1026) was measured again on a fresh box. Nothing a finding
names went away, and every finding is still seen at its steps. Since then:

- **New P-16:** the Participants list is now a table wider than the screen.
- **Changed words (P-10):** the coordinator's line on the weekly page has new words (J-4's F-01).
- **Wider tables (P-02, P-05, P-14):** the job page's tables are 30 to 60 px wider. The report adds a "barriers"
  table in ja. The audit trail's table is about 50 px wider.
- **P-01 narrowed:** it names the steps and pages where the menu is opened. It used to claim every step, which steps
  3, 4, 16 and 22 never needed.
- **Test tightened:** a measure must now match a finding's page as well as its step and kind.

The console has no `layout.phone_first` flag on this master: J-1 as merged adds none. The walk measured the box as
it starts.

## Steps the phone cannot complete

None. Every step was done on the phone. The erase completes on a steps-mode box since H-25 (D-1124), on the phone as on
a desktop: step 21 sees the worker's run after the opt-out, and step 22 reads its health check at 0.

## Counts

| Severity | Findings |
| --- | --- |
| blocks the step | 0 |
| slows the tester | 3 |
| cosmetic | 13 |
