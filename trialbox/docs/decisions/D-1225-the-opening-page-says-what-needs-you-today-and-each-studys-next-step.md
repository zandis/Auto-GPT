# D-1225 The opening page says what needs you today and each study's next step, behind one flag (J-6)

- **Task:** card J-6 of lane J (the journey review of 2026-11-17, `docs/reviews/2026-11-17-journey-and-simplicity.md`,
  cards R8, R19 and R35: A-1, B-3, B-4, D-4 and section E; root review 09, `docs/reviews/2026-11-root/09-ux.md`, J3
  and DS-13) · **Date:** 2026-11-18
- **Decision:**
  - **One flag.** `layout.home_today` (`tb_common.flags.DECLARED`, values off/on, default off, no seed variable:
    changed only on `/ops/flags` with a reason, audited as every flag). Read as `layout.phone_first` is (D-1222): a
    page gets the value last read and never waits for the store; a value older than 5 seconds starts one background
    read (`console.home_today.flag_now`). Off, `/home` is as before for every role.
  - **Who gets the page.** With the flag on, `/home` gives the coordinator, the investigator, the CRO and the viewer
    one opening page: "Needs you today", then one "Next" line per study the person is on. The investigator, the CRO
    and the viewer are no longer sent on to `/week` or `/reports`; the page links there. The steward, the privacy
    office and the administrator are on no study: their opening pages (their review queues, the health page) are
    unchanged. The coordinator keeps the study cards (the funnel, the feasibility line, the set-up links); the old
    "Next" button, the two SAE cards, the visit block, the task list and the clinic list give way to the new lines.
  - **Next follows the whole life of a study** (`console.home_today.life_step`), one sentence and one link. It does not
    compute a second step: there were two, the home card's own `nxt` (stuck in feasibility, review A-1) and the week
    page's `studies.procedure_step`; the line starts from the week page's (`home.study_step`) and goes on with the
    study's recorded state (`SiteStore.study_state`) and the one state of each person (D-1221). The steps, in order:
    start-up (state `startup`), criteria to approve, feasibility count, first screening, review of the week's list,
    contact of the candidates marked Approach (someone `to_contact`), consent and enrolment (someone contacted),
    conduct (someone consented, enrolled or on study: the visits), close (participants were enrolled and none is on
    study any more), paused, closed. A closed study's archive is kept outside TrialBox: the line says so ("its files
    are kept for N years in the site's archive, outside TrialBox", N from the close or the default five) and has no
    link. The site fields of the feasibility report are a task of "Needs you today", no longer the study's Next
    (review card R8). When the step is another role's the line says whose and that nothing is needed from this
    person, with no link. When the participants cannot be read the line says so (never a guessed step).
  - **A role without patient-level rows** (the viewer, the CRO, an investigator the study's log has not delegated to
    screen) reads no person: its Next is the feasibility report (ready, or not yet and whose count it is) or, for a
    CRO under a monitor grant, the monitoring visit and its last day. A CRO is on a study by the account's scope.
  - **Needs you today** (`console.home_today.ordered`): at most five lines, the same on a desktop and a phone. Order:
    safety clocks first (a serious adverse event), then what is overdue, then what is due today; within one, the oldest
    due day, then the study. One line per serious adverse event, whatever number of reasons it has (root review 09
    found the same event in two cards): the acknowledgement for the investigator, else an overdue report, else "no
    reporting deadline yet" (one cause, review B-4), else the PI's acknowledgement awaited. One line per study for its
    overdue visits and one for today's. The coordinator's study tasks due today or before (site fields, a call after
    Approach, information to find, a clinic visit to prepare, a doctor to ask, the monthly delegation-log comparison);
    a task not due yet is not today's (it stays on the week page's lists). More than five: "N more", linked to
    `/home?today=all`, the whole list. None: "Nothing needs you today." A study's Next whose page is already a line
    of the block keeps its sentence and says so, so a page is linked once.
  - **Only what the role may read.** Each line asks for its source only where the matrix lets the role read it in that
    study: patient-level rows with `phi.view` and the study task `screen` (as the week, participant and visit pages
    ask); serious AEs with `sae.view` (the acknowledgement line with `sae.ack`); visits with `task.enter_data`; the
    coordinator's tasks with `request.prepare`; "mine" for each step by the row its page asks (`criteria.approve`,
    `command.FEAS`, `command.SCREEN`, `list.mark`, `task.enter_data`, `study.state`). No change to any permission.
- **Why:** the opening page's guide stopped at enrolment and pointed back to feasibility; the coordinator's home showed
  the same SAE twice and buried the PI's hand-over under chores; the review asked for "what needs you today" in at most
  five lines and a "Next" for the whole life. A flag because it changes what every clinical role sees first.
- **Not done here:** the eight-phase strip and the study switcher (R15), the start-up checklist (R9), "Remind PI"
  buttons; the line's words for a monitor's queries (they live in the EDC).
- **Proved by:** `tests/console/test_home_today.py` (the flag; the step table; the order; each role's Next through the
  life of a study on the real pages, with each link; the block's lines and links in three languages; never more than
  five; nothing twice; a viewer's page with no patient read; the role walk with the flag on).
