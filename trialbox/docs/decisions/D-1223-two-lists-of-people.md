# D-1223 Two lists of people, Candidates and Participants, in place of seven, behind one flag (J-5, review R16)

- **Task:** card J-5 of lane J (the journey review of 2026-11-17, `docs/reviews/2026-11-17-journey-and-simplicity.md`,
  finding D-2 and row 16 of section 10; built on J-2's one state, D-1221), with the lane coordinator's review of its
  pull request · **Date:** 2026-11-18
- **Decision:**
  - **Two lists, divided at consent.** **Candidates** at `/studies/{rs}/people/candidates` and **Participants** at
    `/studies/{rs}/people/participants`. The **default view** of each divides the study's people by J-2's one state
    (`console.person_state`): Candidates' default shows every person whose state is a candidate's (`CANDIDATE`: on the
    list to screen failure, a record at its first step included), Participants' default every person whose state is
    a participant's (`PARTICIPANT`: consented to withdrawn, a re-consent included, and a participant the screening log
    names before a record exists). The people divided are J-2's: every person the console holds a fact about (a mark,
    a contact outcome, a screening-log row, a participant record), the population every count uses. The patients a
    screening run found that nobody has acted on yet hold no such fact: they are on "This week", and Candidates'
    default says so. Each of J-2's people is in exactly one of the two; nobody opted out or erased is in either (`People.states`); a state that could not be read is in neither, and the page says the facts could
    not be read. A filter on a default (`?state=`) is the one state's, never a record's own step.
  - **Each default is built on an old page's route, guard and reads**: Candidates' on the study registry page
    (`/pilot/registry/{rs}`, which already read every person with the one state, and holds the add by chart number,
    the take-over of a run and the export), Participants' on the participants page (`/studies/{rs}/subjects`, whose
    read of the people already included the screening log). A default only leaves rows out; a participant the log
    names before a record exists is shown with its state and day, without a pseudonym (the participants page shows
    none).
  - **The other views are working views**: the old page as it was, which can show people from both sides of consent,
    and the strip says so on each. Candidates: "This week" (`/week`, its `list=` filters, the contact outcomes),
    "New members" (`/cohort`, a registry study), "Doctors and referrals" (`/candidates`, `show=`), "Screening log".
    Participants: "Every record" (the participants page as it was, with the one state's filter), "Enrolment and
    withdrawals" (`/enrolment`). The old pages' templates and guards are not changed.

    | Old list | Old address | Now |
    | --- | --- | --- |
    | Candidate registry of one study | `/pilot/registry/{rs}` | Candidates' default "Before consent" (the people after consent are under Participants) |
    | This week's patients | `/studies/{rs}/week` | Candidates · This week (working view) |
    | Cohort list | `/studies/{rs}/cohort` | Candidates · New members (working view, a registry study) |
    | Candidates (doctor and referral) | `/studies/{rs}/candidates` | Candidates · Doctors and referrals (working view) |
    | Screening log | `/studies/{rs}/screening-log` | Candidates · Screening log (working view) |
    | Participants | `/studies/{rs}/subjects` | Participants' default "Consented"; the page as it was is the working view "Every record" |
    | Enrolment report | `/studies/{rs}/enrolment` | Participants · Enrolment and withdrawals (working view) |

  - **Redirects.** With the flag on, an old address answers 303 to its view, query kept, **for a reader its route lets
    in**; anyone else (no session, an ended one, a password to change, a role the route refuses) reaches the old route
    and gets its answer and its audit event there, as before. The gate reads the session without counting it as
    activity, makes no sign-in, audits nothing, and asks the strip's questions. Files, actions (every POST), a
    person's own page, `/pilot/registry`, `/site/patients` keep their addresses. The view is in the path, so a page's
    relative filter links stay in their view.
  - **One strip**, on a 200 only, above each view: the two lists and the views of the list shown, each only where the
    role may open it (the questions the routes ask, as a yes or no, with no audit event and no patient read: the
    `phi.view` row and the delegation log, the `screen` task, the registry route's declared row), one line saying what
    the view holds, and from Candidates the weekly page across studies (`/week`: its approvals, safety banners and
    registry lists). The steward and the privacy office, who read the study registry page's counts without patient
    rows, are offered no list: that page answers them at its address as before.
  - **The menu** shows Candidates and Participants where it showed "This week's patients" and "Candidate registry".
    `/people/candidates` and `/people/participants` open the study's list or a choice of study, keeping a view asked
    for (`?view=`). They are plain routes: with the flag off they answer 404, and the route table the role walks read
    is master's. A link from another site to a list (`/link`) continues to it with its filters.
  - **The flag** `layout.people_lists` (`tb_common.flags.DECLARED`, off/on, default off, no seed variable: changed on
    `/ops/flags` with a reason, audited as every flag). Off: every page renders byte for byte as without J-5 (tested by
    rendering pages with the templates and with the templates whose J-5 additions are put back), the new addresses are
    no page (404, with or without a session), and the participants page ignores `?state=`. Read once per request, as
    J-3's flag.
- **Not changed:** the permission matrix and every guard; J-2's one state; the EDC's state where a list shows it
  (lane E); the site set-up's patient check (`/site/patients`, a check of the criteria during set-up) and the registry
  index (`/pilot/registry`, every study's counts) keep their addresses.
- **When the flag becomes the default:** the menu's two old items and More's per-study "Candidates" link go; the old
  addresses stay as redirects for one release; the routes stay (they serve the views).
- **Held by:** `tests/console/test_people_lists.py` (the flag and its words; flag off byte for byte and no new page;
  the division at consent over J-2's people on the real data core and over cases of screen failure, withdrawal,
  re-consent, opt-out and erasure; the filter reads the one state; every redirect; the role walk over every role of the
  role matrix and every view: the same answers and refusals, the same body on a working view and the same forms and no
  new row on a default, the strip on a 200 only and offering exactly the views the role gets, one step each; the menu,
  the picker, the weekly page across studies, the links from another site; three languages); with the flag on, the
  role matrix, the V-2 role walk, the role pages and the wording walk pass.
