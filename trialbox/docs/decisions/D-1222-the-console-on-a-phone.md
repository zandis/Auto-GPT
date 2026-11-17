# D-1222 The console on a phone: what a phone shows first behind one flag; home-screen icons, kept long forms and mail links without the flag (J-3)

- **Task:** card J-3 of lane J (the journey review of 2026-11-17, `docs/reviews/2026-11-17-journey-and-simplicity.md`,
  section E, cards R33, R36, R37, R39: E-1, E-4, E-M1 to E-M5 and the table "Which tasks belong on a phone") ·
  **Date:** 2026-11-17
- **Decision:**
  - **One flag for what a phone shows first.** `layout.phone_first` (`tb_common.flags.DECLARED`, values off/on,
    default off, no seed variable: changed only on `/ops/flags` with a reason, audited as every flag) is read once per
    request by a small middleware (`console.phone`) into `request.state.phone_first`; `base.html` then gives `<body>`
    the class `phone-first`, and every new rule of the stylesheet is scoped under it. Behind it: (E-1) on the week
    page under 760 px the patient list comes right under the title; the serious-AE banners stay above it (a safety
    alert is never folded away); the procedure, the delegation-log warning, the team's links and a waiting approval
    fold into one "Study" fold below the list (a checkbox and its label, no script). (E-4) Under 640 px the worklist's
    rows are cards (patient and criteria met, then the visit, the status and what is still needed, each labelled; the
    whole card opens the patient). (E-M4) "More" folds in two levels: the same links, under the same rules, grouped
    (site, the study's pages, registers, administration, lists and requests, settings); on a phone each group is a
    44 px chip in the menu's own flow, so it no longer covers the language and Sign out; on a desktop each group shows
    its links under its name. (E-M5) On the week page's patient sheet and the full patient page the investigator reads
    the criteria before the mark's note, reason and re-check date (the order of the page, not only of the screen). With
    the flag off every page renders as before (the flag-off HTML of the week page, its sheet, the menu, the patient
    page and the home page was compared byte for byte with master's templates on the same data: identical, apart from
    the head's new links and the inline script).
  - **Without the flag** (they change no first view): (E-M1) `/manifest.webmanifest` (name, start page `/`, standalone,
    theme colour `#253a5e`, a 192 and a 512 px icon, the 512 also maskable) and `/favicon.ico`, served by the box from
    `static/icons` (an SVG drawn for the card and PNGs drawn from the same geometry); both are public, like `/static`
    (a browser fetches a manifest without cookies); no offline mode, no service worker. (E-M3) The entry form (an AE's,
    a visit's, any built-in form) carries the set-up page's guard (`data-guard`: warn before leaving unsaved edits) and
    is kept in the tab's session storage while typed, keyed by account, study, record, event and form, as a mark's note
    is (D-777): back on the form after sign-in the kept values fill the fields still empty; a save that reached a live
    session drops them; a save that met the sign-in page keeps them and, as the console sends no Referer (so no page is
    kept for a POST), the first page after sign-in goes back to the form's own address when it is the home page; Sign
    out drops every kept form. (E-M2) A link from another site (a mail) arrives without the `SameSite=Strict` session
    cookie (Strict stays): when `Sec-Fetch-Site` says cross-site, the sign-in page reloads itself once from this site
    (`/login?hop=1`, a meta refresh), which sends the cookie; a live session then goes on to the kept page through
    `next_page.take` (a same-origin path only, `safe_next`), and no session gets the sign-in form, which after sign-in
    leads to the asked page as before. `hop=1` never hops again.
- **Phone tasks** (the review's table; each walked by `tests/e2e/phone_walk.js` at 390 x 844 with the flag on, in en,
  zh-TW and ja): the morning list from the mail (1 tap with a live session; first patient row at 625 px en, 565 zh-TW
  and ja, it was 856/774/796), a candidate's evidence (1), Need info (2) and Not suitable (4), each undone, the contact
  outcome after an Approach (2, undone and withdrawn), the coordinator's task list (0), a participant looked up (the
  number, then Go), an SAE form half filled when the session ends (text back after sign-in, 0 taps). Not this card: the
  SAE acknowledgement (R34), the EDC review (R38, lane E); not walked: marking a visit done (saving changes the seeded
  record; its form is the walked entry form); not for a phone: approving criteria.
- **Switching it on:** as `admin`, `/ops/flags`, flag `layout.phone_first`, value `on`, a reason, confirm. Every
  console process reads it within five seconds; no restart. Off the same way.
- **Left:** the coordinator's home page is still 6,000 to 6,800 px on a phone (the "Today" block is R35); the language
  of a session that ended is not carried to the next sign-in (the new session takes the sign-in page's). The hop needs
  a browser that sends `Sec-Fetch-Site` (current Chromium, Firefox, Safari 16.4+); one that does not keeps today's
  behaviour. On a desktop the menu's groups show open where the browser knows `::details-content` (Chromium 131+,
  Safari 18.4+, Firefox 143+), elsewhere folded.
- **Held by:** `tests/console/test_phone_first.py` (manifest and icons without a session; the flag declared off and
  described in three languages; flag off: no class, fold, group or label on the week page and the menu; flag on: the
  list first, the folds, the labels, the same menu links; the evidence before the mark fields; the hop: once, only
  cross-site, to the kept page and only a same-origin path; the entry form's guard and key, and the script's keep,
  restore, drop and return run in Node) and `tests/e2e/test_phone_walk.py` (the walk, marked e2e; the plan holds every
  row of the review's table). Synthetic data only.
