# D-1222 The console on a phone: what a phone shows first behind one flag; home-screen icons, kept long forms and links from other sites without the flag (J-3)

- **Task:** card J-3 of lane J (the journey review of 2026-11-17, `docs/reviews/2026-11-17-journey-and-simplicity.md`,
  section E, cards R33, R36, R37, R39: E-1, E-4, E-M1 to E-M5 and the table "Which tasks belong on a phone"), with the
  fix round of its independent review · **Date:** 2026-11-17
- **Decision:**
  - **One flag for what a phone shows first.** `layout.phone_first` (`tb_common.flags.DECLARED`, values off/on,
    default off, no seed variable: changed only on `/ops/flags` with a reason, audited as every flag) is read for each
    page request by a small middleware (`console.phone`) into `request.state.phone_first`: in a worker thread, never on
    the event loop; not for `/static`, `/api/`, `/healthz`, `/metrics`, the manifest, the icons or `/link`; its answer,
    a failed read included (then "off"), is kept 5 seconds, so a flag store that is down costs one attempt per 5
    seconds and every page still renders. `base.html` gives `<body>` the class `phone-first`; every new rule of the
    stylesheet is scoped under it. Behind it, at every width unless said:
    - (E-1) On the week page the patient list comes right under the title; the serious-AE banners stay above it (a
      safety alert is never folded away). The procedure, the delegation-log warning, the team's links and a waiting
      criteria approval are written after the list, in one "Study" fold (a checkbox and its label, no script), so the
      order of the page is the order of the screen. The fold's label says, in a whole sentence, how many of its lines
      need the person (a waiting approval, the delegation-log check), marked as a warning. On a desktop too, the fold
      is below the list.
    - (E-4) Under 640 px the worklist's rows are cards (patient and criteria met, then the visit, the status and what
      is still needed, each labelled; the whole card opens the patient); so are the participant's visits and step
      trail (`life_subject.html`: at 390 px the visit window was cut off and the step squeezed to one character a
      line).
    - (E-M4) "More" folds in two levels: the same links, under the same rules, grouped (site, the study's pages,
      registers, administration, lists and requests, settings). Every group is a `details` element that opens by
      click, tap or keyboard in every browser. On a phone the groups are 44 px chips in the menu's own flow, so they no
      longer cover the language and Sign out. On a desktop, where the browser knows `::details-content` (inside
      `@supports`), the groups show open as one list; elsewhere they are folded and open on a click.
    - (E-M5) The investigator reads the criteria before the mark's note, reason and re-check date, on the week page's
      patient sheet and on the full patient page, at every width (the desktop too), in the order of the page.
    - With the flag off every page renders as before: the flag-off HTML of the week page, its sheet, the menu, the
      patient page and the home page was compared byte for byte with master's templates on the same data (identical,
      apart from the head's new links and the inline script), and screenshots of master and of the flag-off branch at
      390 and 1280 px in three languages are pixel-identical but for a blinking caret.
  - **A link from another site (E-M2), without the flag.** The session cookie stays `SameSite=Strict`, so a navigation
    from another site (a mail, a chat) arrives without it. Such a navigation (`Sec-Fetch-Site: cross-site`,
    `Sec-Fetch-Mode: navigate`, a GET) to any page of the console is answered with the console's own page `/link`,
    in the page language: "You followed a link from another site to this page of TrialBox: <path>", why the tap is
    asked, and Continue. **What such a link can do:** open the console's `/link` page, which reads no session and
    shows nothing of the study; after the person's tap on Continue (a tap on this site, so the cookie goes with it),
    open that HTML page of the console: with a live session at once, without one through the sign-in form, which
    leads back to it. **What it cannot do:** download a file or start an action, with or without a live session.
    Continue goes only to an HTML page path (`console.phone.continue_to`): a path `next_page.safe_next` refuses, a
    last segment with a dot (`.xlsx`, `.csv`, `.zip`, `.pdf`, `.xml`, `.json`), an export, a print, a job's files or
    view, `/cmd` and `/api/` go to the home page instead, and the page says so. The sign-in and its steps (`/login`,
    `/logout`, `/enrol` with its code after "#", the identity provider's `/auth/` return), `/api/` (the EDC's sign-in
    included), `/static`, the manifest and the icons arrive as before. A form post from another site is not a
    navigation of this kind and is refused as before (CSRF, Strict cookie). The sign-in page itself is unchanged.
    A browser that sends no `Sec-Fetch-Site` keeps today's behaviour (the sign-in form for a link from elsewhere).
  - **Add to home screen (E-M1), without the flag.** `/manifest.webmanifest` (name, `lang` and `dir`, start page `/`,
    standalone, theme colour `#253a5e`, a 192 and a 512 px icon, the 512 also maskable) and `/favicon.ico`, served by
    the box from `static/icons` (an SVG drawn for the card and PNGs drawn from the same geometry); both are public, like
    `/static` (a browser fetches a manifest without cookies); no offline mode, no service worker.
  - **Long forms (E-M3), without the flag.** The entry form (an AE's, a visit's, any built-in form) carries the set-up
    page's guard (`data-guard`: warn before leaving unsaved edits) and is kept in the tab's session storage while
    typed, keyed by account, study, record, event and form, with its account and time. It is put back **only once**:
    on the way back from the sign-in after a save met an ended session (a one-time marker set at that moment), into
    the fields still empty, each marked, under a notice in the page language ("Fields restored from before your session
    ended: N. Check them, then save." and a Discard button that empties them and drops the entry). Never on a later
    visit. The entry is dropped when a save reaches a live session (also when the same form is shown again, as the
    consent form with its version warnings is), when the person leaves the form without saving, after 12 hours, and on
    any page whose account (`<meta name="tb-user">`) is not the entry's: then every other account's kept forms go, and
    the tab is never sent to another account's form. As the console sends no Referer, no page is kept for that save:
    after the sign-in the home page sends the tab back to the form's own address, made from the form's record, event
    and form (so a refused save shown at the bare entry address returns to the form, not to the chooser). Sign out
    drops every kept form.
- **Phone tasks** (the review's table; each walked by `tests/e2e/phone_walk.js` at 390 x 844 with the flag on, in en,
  zh-TW and ja): the morning list from the mail (2 taps: the link, then Continue; first patient row at 625 px en, 565
  zh-TW and ja, it was 856/774/796), a candidate's evidence (1), Need info (2) and Not suitable (4), each undone, the
  contact outcome after an Approach (2, undone and withdrawn), the coordinator's task list (0), a participant looked up
  (the number, then Go), an SAE form half filled when the session ends (text back after sign-in, with the notice, 0
  taps). Not this card: the SAE acknowledgement (R34), the EDC review (R38, lane E); not walked: marking a visit done
  (saving changes the seeded record; its form is the walked entry form); not for a phone: approving criteria.
- **Switching it on:** as `admin`, `/ops/flags`, flag `layout.phone_first`, value `on`, a reason, confirm. Every
  console process reads it within five seconds; no restart. Off the same way.
- **Left:** the coordinator's home page is still 6,000 to 6,800 px on a phone (the "Today" block is R35); the language
  of a session that ended is not carried to the next sign-in (the new session takes the sign-in page's). Only
  Chromium was driven; Firefox and WebKit are not installed in the container (the menu is safe by construction:
  plain `details`, the open look only inside `@supports`).
- **Held by:** `tests/console/test_phone_first.py` (manifest and icons without a session; the flag declared off and
  described in three languages, its read for pages only and once per 5 s when the store is down; flag off: no class,
  fold, group or label on the week page and the menu; flag on: the list first and the fold after it with its count,
  the labels, the same menu links, groups that open everywhere; the evidence before the mark fields; a link from
  another site: the `/link` page in three languages, Continue only to an HTML page, never a file, an export, `/cmd` or
  `/api/`, the sign-in and its steps untouched; the entry form's guard and key, and the script in Chromium on pages
  of a small local server (`tests/console/form_keep.js`): back once with a notice and marks, Discard, another account,
  a live save, the same form shown again, leaving, 12 hours, the address from the form) and
  `tests/e2e/test_phone_walk.py` (the walk, marked e2e, with a link to a file that downloads nothing; the plan holds
  every row of the review's table). Synthetic data only.
