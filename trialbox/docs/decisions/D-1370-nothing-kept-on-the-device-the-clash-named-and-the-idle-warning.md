# D-1370 Nothing of a clinical page kept on the device; the directory refusal names the two groups; a warning before the idle lock (9f-11, 9f-6, 9g-19)

- **Task:** lane K, plan 10 track F, three small console cards carried from plan 9
  (`docs/plan/45-plan-9-2026-11-17.md`): 9f-11 (root review 02, J-11), 9f-6 (J-6) and 9g-19 (J-25, A11Y-3); the
  review is `docs/reviews/2026-11-root/02-journeys.md`, sections 1.3, 2.2 and 3.3. · **Date:** 2026-11-19
- **Decision:**
  - **9f-11, the rule.** The console leaves nothing of a clinical page on a phone or a PC: no service worker, no
    offline copy of a page, no scan of a signed consent, no web push through Apple's, Google's or any outside push
    service (owner decision 11 of plan 9: an installable web app without a service worker; mail is the notice
    channel). Written in `docs/security/05-data-protection.md` ("Nothing kept on the device").
    - Held in the browser, not only by the code's absence: the console's Content-Security-Policy gains
      `worker-src 'none'`, so a browser registers no service worker (nor any other worker) from a console page,
      whatever a page or a file might ask. The hash-only `script-src` already refused one from a file; the new
      directive says it by name and also covers a worker from `blob:` or `data:`.
    - Every response already carried `Cache-Control: no-store` (the console's headers middleware, D-133); the only
      cached answers are the web manifest and the favicon (`public, max-age=86400`, D-1222), which hold nothing of a
      patient. Checked, not changed.
    - The browser keeps typed text only in the tab's session storage, as before (D-777 a mark's note, D-1222 a long
      form): gone with the tab, dropped on save, on leaving and on sign-out. Never `localStorage`, IndexedDB or the
      Cache API.
    - A consent is recorded as facts (`tb_consent`: dates, versions, initials, ticks); no form field takes a file, no
      page asks for the camera (`capture`), and the consent page's one file input is the study's consent document
      to draft from, documents only.
    - **Held by** `tests/console/test_no_offline_copy.py`: a scan of every console file (templates, script,
      stylesheet, Python, the web manifest) for a service worker, push, a page cache or a lasting browser store; a scan
      of `services`, `libs`, `deploy` and `tools` for the outside push services' hosts; the consent checks; every GET
      route walked as the administrator and as a coordinator, each answer `no-store` with `worker-src 'none'`; and in
      Chromium (`tests/console/no_worker.js`) a console page this console rendered, under its own policy, asked to
      register a service worker: refused, none registered. Each scan and the browser check run beside a planted
      case that breaks the rule (a planted `navigator.serviceWorker.register`, a manifest with `serviceworker`, a
      planted push host; the same page without the policy, where a service worker does register), so a check that
      could never fail is seen. The test fails if a service worker registers.
  - **9f-6, the clash named.** A person whose directory groups map to two roles is still refused (D-192). The refusal
    page now names two of their groups that clash and says what to do: "Ask the hospital's IT to remove you from one
    of these two groups, then sign in again. Nothing was changed in TrialBox", in en, ja and zh-TW.
    - The two names are the site's own configured names (`TB_OIDC_GROUP_ROLES`), in the map's order: the first of the
      person's mapped groups, then the first of theirs with another role. Groups that give no role, or a second group
      of the same role, are not named. They are shown only on this person's own refusal, after the ID token was
      verified and the second factor seen (the same point the refusal was made before), and escaped as any page text.
    - `console.oidc.OidcRoleClash` (an `OidcError`, so every caller that refused one refuses it the same way) carries
      the two names. The audited reason is unchanged ("groups map to more than one role"); the audit gains no group
      name.
    - **Held by** `tests/console/test_identity.py` (the page in three languages, a group name with markup characters
      shown escaped, the audit unchanged; the choice of the two names).
  - **9g-19, the idle warning.** One minute before the idle lock (10 minutes by default, `TB_CONSOLE_IDLE_MINUTES`;
    with a limit under two minutes, half the limit before, and the title then says the seconds, e.g. "in 30 seconds")
    every signed-in page shows a warning with "Stay signed in" (WCAG 2.2.1); at the session's absolute end (8 hours,
    or an hour for a directory session) the same warning says the session cannot be extended and has no button.
    - **Accessible:** an `alertdialog` labelled by its title and described by its sentence; the focus moves to
      "Stay signed in" (Enter or Space presses it) and goes back to the field the person was typing in; after the lock
      to Close. **Escape on the warning is "Stay signed in"** (closing the warning means "I am here"); on the lock or
      the absolute-end warning Escape closes it. At the foot of the screen, existing colour tokens only, 44 px
      buttons. Three languages.
    - **The page's clock.** The page carries the session's real times, read without touching it
      (`UserStore.session_left`: the idle limit, the lead, the seconds to the idle lock and to the absolute end; a page's
      own auto-refresh, which is not activity, shows the time really left). The script counts them from the
      navigation's start on the page's monotonic clock (`performance.now`), not from when it runs: the server counted
      from a moment after the navigation started, so the page errs early by the page's delivery time, never late, and
      a jump of the system clock moves nothing.
    - **No new route, no new right, no longer limit.** "Stay signed in" asks, in the background, a page every
      signed-in person may open anyway (`/help`, or the overview `/` on a console with the workspace off) with
      `keep=1`. The console's `need()` makes every check the page makes (session, password change, scope) and then
      answers `204` with the session's times in two headers (`x-tb-idle-left`, `x-tb-abs-left`): the route's own reads
      do not run, no account notice is taken, and a request that meets an ended session goes to the sign-in without
      being remembered as the page to return to (D-777 remembers real pages as before). That request is activity as
      any page is (D-192); the absolute limit still ends the session however often it is pressed. A press that meets
      an ended session (another tab signed out, the box restarted) shows the lock. The limits, the role table and
      `authz_matrix.yaml` are unchanged.
    - **No false lock from an idle second tab.** Before saying "You have been signed out" the page asks the same page
      with `keep=1&auto=1`, which is not activity (D-192 H3). If the session is alive (another tab in use kept it
      awake) the warning is put away and armed again from the times the answer gives; only an answer that sends it to
      the sign-in (or no answer) shows the lock.
    - **The form's text kept:** the warning and the lock never reload or leave the page, so what was typed stays where
      it is; the lock's message says to press Save, and the sign-in that follows puts back an entry form (an AE's, a
      visit's) and a mark's note as D-1222 and D-777 already do. The warning reads and stores nothing typed: no
      field value, no browser store. Not done: a form that D-1222 does not keep is kept on the screen only; it is
      not put back after a sign-in.
    - Known limits: with a second tab in use, an idle tab may still show the one-minute warning early (it counts from
      its own last request); it no longer shows a false lock, and pressing "Stay signed in" is harmless. An account
      that must change its password is answered by the password page's redirect, which the page reads as the lock;
      such an account reaches only its password page (D-279).
    - **Held by** `tests/console/test_idle_warning.py`: the page's warning, its times, lead and three languages; the
      `keep=1` answer (times only, `auto=1` not activity, no notice taken, the page's own checks, an ended session not
      remembered); the press is activity and never passes the absolute limit; reading the times is not activity; and
      in Chromium (`tests/console/idle_warn.js`, the browser's clock moved forward, pages this console rendered with
      its own policy and stylesheet): no warning at 8:58, the warning at 9:01 with the focus on "Stay signed in",
      Enter extends (one request) and the focus and the typed text come back, Escape extends too, the next warning
      comes 9 minutes after the press, a page delivered 3 s late warns by then, the lock asks once (not activity) and
      keeps the text and the address, a session another tab kept awake gives no lock and a new warning from the
      answer's times, a press that meets an ended session shows the lock, the absolute end shows no button, Japanese
      words. These browser checks need Node Playwright and run on a developer's machine only (see the pull request);
      CI holds the server half and the page's markup.
- **Rights:** none of the three widens what a role may do or read: no new route, no new row in
  `authz_matrix.yaml`, no export, no new read of patient data; 9g-19 lengthens neither limit.
