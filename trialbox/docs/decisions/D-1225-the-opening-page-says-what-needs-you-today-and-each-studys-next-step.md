# D-1225 The opening page says what needs you today and each study's next step, behind one flag (J-6)

- **Task:** card J-6 of lane J (the journey review of 2026-11-17, `docs/reviews/2026-11-17-journey-and-simplicity.md`,
  cards R8, R19 and R35: A-1, B-3, B-4, D-4 and section E; root review 09, `docs/reviews/2026-11-root/09-ux.md`, J3
  and DS-13) · **Date:** 2026-11-18
- **Decision:**
  - **One flag.** `layout.home_today` (`tb_common.flags.DECLARED`, values off/on, default off, no seed variable:
    changed only on `/ops/flags` with a reason, audited as every flag). Read together with `layout.phone_first`
    (D-1222) in one background read of both (`Flags.rows`, one statement) by `console.phone`'s middleware: first at
    the console's start, then when the value a page got is older than 5 seconds; a page never waits for the store
    and `/home` takes the value from the request, so the opening page adds no read of its own. Off, `/home` is as
    before for every role, byte for byte: every J-6 part of `home_crc.html` sits between `{#J6#}` and `{#/J6#}` and
    writes nothing with the flag off (a test renders the page with and without those parts).
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
    contact of the candidates marked Approach (someone `to_contact`, or the week page's step bar at "Contact and screen" even when everyone contacted so far screen-failed), consent and enrolment (someone contacted, or
    consented and not yet enrolled), conduct (someone consented, enrolled or on study: the visits), close (someone was
    enrolled, nobody is on study and no candidate is still in progress: on the list, needing information, set aside,
    to contact or contacted; otherwise the consent, contact or review step), paused, closed. A closed study's archive is kept outside TrialBox: the line says so ("its files
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
    a task not due yet is not today's (it stays on the week page's lists). Among the overdue lines, one with no due
    day of its own (a study's overdue visits, each with its window) comes first. "Today" is the site's day. More than five: "N more", linked to
    `/home?today=all`, the whole list. None: "Nothing needs you today." A study's Next whose page is already a line
    of the block keeps its sentence and says so, so a page is linked once.
  - **Only what the role may read, read once.** Each source is read only where the account's own page of that source
    would show it, by that page's own function (no second rule): a study's participants, people and visits by the
    participant pages' `lifecycle_pages.participant_scope` (which their `study_or_404` turns into a 404 or a 403, and
    `reads_participants` into a yes or no: sees the study, not a sponsor copy, `phi.view`, and the log's PI or a
    sub-investigator ticked for screening or data entry); its serious AEs by the SAE pages' `sae_pages.sae_scope`
    (which their `scope` and the `/sae` worklist use: the `sae.*` row and the log's PI or a sub-investigator ticked
    for screening; a sub-investigator ticked for data entry only gets no serious AE, as on those pages). Of those,
    visits are read for the visit lines' row (`task.enter_data`) in a study that is not closed; the card's tasks
    with `request.prepare`. A study's serious AEs are read once, from the SAE pages' own answer
    (`sae_pages.home_saes`), its participants once (the visit rows take their pseudonyms from the participant list
    the page view already read). "Mine" is asked only for the step shown, by the row its page asks. The account's
    standing in a study's log is read once per page view (`Helpers.permit`, through `person_state.per_view`). No
    change to what any page allows.
  - **A closed study** gets no visit, task or site-field line (there is nothing to do), and its visits are not read; its
    serious AEs keep their lines, because their reports are owed after the close too. A safety line opens the SAE
    case, where it is acknowledged and reported.
- **Why:** the opening page's guide stopped at enrolment and pointed back to feasibility; the coordinator's home showed
  the same SAE twice and buried the PI's hand-over under chores; the review asked for "what needs you today" in at most
  five lines and a "Next" for the whole life. A flag because it changes what every clinical role sees first.
- **Not done here:** the eight-phase strip and the study switcher (R15), the start-up checklist (R9), "Remind PI"
  buttons; the line's words for a monitor's queries (they live in the EDC).
- **Kept on purpose:** the coordinator's study cards keep their fixed links (set-up, participants, visits, enrolment
  report, criteria not matched) even where a line above links the same page: they are the study's menu, there whatever
  is due, so the card does not change shape from day to day.
- **Proved by:** `tests/console/test_home_today.py` (the flag; the step table; the order; each role's Next through the
  life of a study on the real pages, with each link; the block's lines and links in three languages; never more than
  five; nothing twice; no data-core or screening-log read for an investigator the participant pages refuse, nor in a
  second study where the PI of the first is on no log; the participant pages' rule for a data-entry sub-investigator;
  the `sae.view` row; the site's day ahead of UTC; the flag-off page byte for byte; a statement budget per study;
  the role walk with the flag on).
